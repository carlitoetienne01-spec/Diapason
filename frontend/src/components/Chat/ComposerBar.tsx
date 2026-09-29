import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Check, ChevronDown, Cloud, Cpu, Loader2, Plus, Paperclip, Brain, BookOpen } from 'lucide-react';
import { OUVRIR_ETUDES } from '../../features/etudes/etudes';
import { useAppStore } from '../../lib/store';
import { fetchServerConfig, preloadModel, setServerConfigKey } from '../../lib/api';
import { isCloudModel } from '../../lib/cloud-models';
import { useTranslation } from '../../i18n/useTranslation';
import { useSurfaceVitree } from './useSurfaceVitree';
import { demanderLeFocusDuCompositeur } from '../../lib/panneau';
import { conversationVocaleEnCours } from '../../lib/conversationVocale';

/* 27/09/2026 : le menu + regroupe les pièces et les permissions réelles.
 * Le pourcentage de contexte a été retiré du compositeur à la demande de
 * Carlito ; le choix du modèle garde le préchauffage de la palette. */

// ---------------------------------------------------------------------------
// Shared upward-opening portal menu
// ---------------------------------------------------------------------------

interface Anchor {
  rect: DOMRect;
  el: HTMLElement;
}

interface MenuProps {
  anchor: Anchor;
  width?: number;
  role?: string;
  onClose: () => void;
  children: React.ReactNode;
}

function ChipMenu({ anchor, width = 280, role = 'menu', onClose, children }: MenuProps) {
  const ref = useSurfaceVitree();
  // Latest-ref: the parent re-renders on every keystroke, and a raw
  // [onClose] dep would tear the document listeners down each time.
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    const onPointerDown = (e: MouseEvent) => {
      const target = e.target as Node;
      // The anchor button is NOT outside: closing here would race the
      // button's own onClick, which would then see a closed menu and
      // reopen it — an unclosable, flickering menu.
      if (anchor.el.contains(target)) return;
      // Null ref must close too — see the zombie-menu lesson in
      // ConversationList: `ref.current && !contains` kept state alive.
      if (!ref.current || !ref.current.contains(target)) onCloseRef.current();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      // 17 sept. 2026 : Échap sur un menu ouvert fermait le menu ET le
      // mini-panneau entier — le script natif (lib.rs) écoute la même
      // touche. `preventDefault` est le signal convenu : « la couche du
      // dessus a consommé Échap » ; le panneau ne se ferme qu'au second.
      e.preventDefault();
      onCloseRef.current();
    };
    // 16 sept. 2026, audit du mini-panneau : `anchor.rect` est un DOMRect
    // figé au clic, et le panneau de la réglette se redimensionne en
    // continu — un menu ouvert pendant l'étirement flottait détaché de sa
    // puce, parfois sur le bord. Fermer suffit (modèle EmojiPicker).
    const onResize = () => onCloseRef.current();
    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKey);
    window.addEventListener('resize', onResize);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onKey);
      window.removeEventListener('resize', onResize);
    };
  }, [anchor]);

  // Quel que soit le chemin de sortie (choix, Échap, clic dehors, resize), le
  // curseur retourne au compositeur : avant, il n'était plus nulle part et
  // il fallait cliquer dans le champ pour reprendre la phrase (17 sept. 2026).
  // Différé d'un tour : le nettoyage d'effet d'un mousedown est flushé en
  // microtâche, donc AVANT l'action par défaut du clic, qui reprenait le
  // focus au compositeur (contre-revue du 17 sept. 2026 : « Autorisations
  // des outils » ouvert, clic dans le fil → activeElement = BODY).
  useEffect(() => () => {
    window.setTimeout(() => {
      // 27/09/2026 : lancer la voix depuis + rendait aussitôt le focus au
      // texte, ce qui mettait le micro en pause dès son ouverture.
      if (!conversationVocaleEnCours()) demanderLeFocusDuCompositeur();
    }, 0);
  }, []);

  // The composer sits at the bottom of the screen: menus open UPWARD,
  // anchored to the chip, and never off the horizontal edges.
  const menuWidth = Math.min(width, Math.max(0, window.innerWidth - 16));
  const left = Math.min(Math.max(8, anchor.rect.left), window.innerWidth - menuWidth - 8);
  const auDessus = anchor.rect.top >= window.innerHeight - anchor.rect.bottom;
  const espace = auDessus ? anchor.rect.top - 14 : window.innerHeight - anchor.rect.bottom - 14;

  return createPortal(
    <div
      ref={ref}
      role={role}
      className="composer-glass-menu fixed z-50 py-1.5 px-1.5 overflow-y-auto"
      style={{
        left,
        ...(auDessus ? { bottom: window.innerHeight - anchor.rect.top + 6 } : { top: anchor.rect.bottom + 6 }),
        width: menuWidth,
        maxHeight: Math.max(0, espace),
      }}
    >
      {children}
    </div>,
    document.body,
  );
}

const chipClass =
  'composer-glass-chip inline-flex items-center gap-1.5 px-2.5 py-1 text-xs cursor-pointer disabled:cursor-default disabled:opacity-50';

// ---------------------------------------------------------------------------
// Mode chip — Auto / Ask, backed by agent.tool_approval
// ---------------------------------------------------------------------------

export function ComposerPlus({ disabled, onJoindre, recherche, onRecherche, onConversationSeule }: {
  disabled: boolean; onJoindre: () => void; recherche: boolean; onRecherche: () => void;
  onConversationSeule?: () => void;
}) {
  const { t } = useTranslation();
  const [mode, setMode] = useState<'auto' | 'ask' | null>(null);
  const [anchor, setAnchor] = useState<Anchor | null>(null);

  useEffect(() => {
    let alive = true;
    fetchServerConfig()
      .then((c) => {
        if (alive) setMode(c.agent?.tool_approval === 'ask' ? 'ask' : 'auto');
      })
      .catch(() => {
        // Fail closed, like the backend: when the mode is unreadable the
        // server treats it as "ask" — the chip must not claim "auto".
        if (alive) setMode('ask');
      });
    return () => {
      alive = false;
    };
  }, []);

  const [writeFailed, setWriteFailed] = useState(false);

  const choose = (next: 'auto' | 'ask') => {
    const previous = mode;
    setMode(next);
    setAnchor(null);
    setServerConfigKey('agent.tool_approval', next).catch(() => {
      // A silent revert would let the user BELIEVE sensitive actions now
      // wait for approval while tools keep running in auto.
      setMode(previous);
      setWriteFailed(true);
      window.setTimeout(() => setWriteFailed(false), 5000);
    });
  };


  const item = (value: 'auto' | 'ask', title: string, desc: string) => (
    <button
      role="menuitem"
      className="composer-glass-menu-item flex w-full items-start gap-2.5 px-3 py-2 text-left cursor-pointer"
      onClick={() => choose(value)}
    >
      <div className="flex-1 min-w-0">
        <div className="text-[13px]" style={{ color: 'var(--color-text)' }}>
          {title}
        </div>
        <div className="text-[11px] mt-0.5" style={{ color: 'var(--color-text-tertiary)' }}>
          {desc}
        </div>
      </div>
      {mode === value && (
        <Check size={14} className="mt-0.5 shrink-0" style={{ color: 'var(--color-accent)' }} />
      )}
    </button>
  );

  return (
    <>
      <button
        type="button"
        disabled={disabled || mode === null}
        className="composer-glass-chip composer-plus inline-flex items-center justify-center cursor-pointer disabled:opacity-40"
        data-active={mode === 'ask' && !writeFailed}
        style={
          writeFailed
            ? { borderColor: 'var(--color-error)', color: 'var(--color-error)' }
            : undefined
        }
        onClick={(e) =>
          setAnchor(
            anchor
              ? null
              : { rect: e.currentTarget.getBoundingClientRect(), el: e.currentTarget },
          )
        }
        title={writeFailed ? t('composer.modeWriteFailed') : t('composer.plus')}
        aria-label={t('composer.plus')}
        aria-haspopup="menu"
        aria-expanded={anchor !== null}
      >
        <Plus size={20} aria-hidden="true" />
      </button>
      {anchor && (
        <ChipMenu anchor={anchor} onClose={() => setAnchor(null)}>
          <button type="button" role="menuitem" className="composer-glass-menu-item flex w-full items-center gap-3 px-3 py-2.5 text-sm text-left"
            onClick={() => { setAnchor(null); window.dispatchEvent(new Event(OUVRIR_ETUDES)); }}><BookOpen size={17} />Étudier un cours · Tests et examens</button>
          <button type="button" role="menuitem" className="composer-glass-menu-item flex w-full items-center gap-3 px-3 py-2.5 text-sm text-left"
            onClick={() => { setAnchor(null); onJoindre(); }}><Paperclip size={17} />{t('composer.attach')}</button>
          <button type="button" role="menuitemcheckbox" aria-checked={recherche}
            className="composer-glass-menu-item flex w-full items-center gap-3 px-3 py-2.5 text-sm text-left"
            onClick={() => { onRecherche(); setAnchor(null); }}><Brain size={17} />{t('common.deepResearch')}{recherche && <Check size={14} className="ml-auto" />}</button>
          {onConversationSeule && <button type="button" role="menuitem" className="composer-glass-menu-item w-full px-3 py-2.5 text-sm text-left"
            onClick={() => { setAnchor(null); onConversationSeule(); }}>{t('talk.conversation.start')}</button>}
          {writeFailed && <p role="alert" className="px-3 text-xs" style={{ color: 'var(--color-error)' }}>{t('composer.modeWriteFailed')}</p>}
          <div
            className="px-3 pt-1.5 pb-1 text-[10px] font-medium uppercase tracking-wider"
            style={{ color: 'var(--color-text-tertiary)' }}
          >
            {t('composer.modeTitle')}
          </div>
          {item('auto', t('composer.modeAuto'), t('composer.modeAutoDesc'))}
          {item('ask', t('composer.modeAsk'), t('composer.modeAskDesc'))}
        </ChipMenu>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Model chip — active model, quick switch, gateway to the full palette
// ---------------------------------------------------------------------------

export function ModelChip({ disabled }: { disabled: boolean }) {
  const { t } = useTranslation();
  const models = useAppStore((s) => s.models);
  const selectedModel = useAppStore((s) => s.selectedModel);
  const chooseModel = useAppStore((s) => s.chooseModel);
  const modelLoading = useAppStore((s) => s.modelLoading);
  const setModelLoading = useAppStore((s) => s.setModelLoading);
  const setCommandPaletteOpen = useAppStore((s) => s.setCommandPaletteOpen);
  const [anchor, setAnchor] = useState<Anchor | null>(null);

  const isCloud = isCloudModel(selectedModel);
  const Icon = modelLoading ? Loader2 : isCloud ? Cloud : Cpu;

  const pick = (id: string) => {
    setAnchor(null);
    if (id === selectedModel) return;
    chooseModel(id);
    // Same path as the ⌘K palette: warm the model so the first message
    // does not pay the load.
    setModelLoading(true);
    preloadModel(id)
      .catch(() => undefined)
      .finally(() => setModelLoading(false));
  };

  return (
    <>
      <button
        type="button"
        disabled={disabled}
        className={`${chipClass} composer-model-selector`}
        onClick={(e) =>
          setAnchor(
            anchor
              ? null
              : { rect: e.currentTarget.getBoundingClientRect(), el: e.currentTarget },
          )
        }
        title={`${t('composer.model')} : ${selectedModel || t('sidebar.selectModel')}`}
        aria-haspopup="menu"
        aria-expanded={anchor !== null}
      >
        <Icon size={14} className={`composer-model-icon shrink-0 ${modelLoading ? 'animate-spin' : ''}`} />
        <span className="truncate" style={{ color: 'var(--color-text-secondary)' }}>
          {selectedModel || t('sidebar.selectModel')}
        </span>
        <ChevronDown size={14} className="shrink-0" />
      </button>
      {anchor && (
        <ChipMenu anchor={anchor} width={260} onClose={() => setAnchor(null)}>
          {models.map((m) => (
            <button
              key={m.id}
              role="menuitem"
              className="composer-glass-menu-item flex w-full items-center gap-2.5 px-3 py-1.5 text-left text-[13px] cursor-pointer"
              style={{ color: 'var(--color-text)' }}
              onClick={() => pick(m.id)}
            >
              <span className="flex-1 truncate">{m.id}</span>
              {m.id === selectedModel && (
                <Check size={14} className="shrink-0" style={{ color: 'var(--color-accent)' }} />
              )}
            </button>
          ))}
          <div className="my-1 mx-2" style={{ borderTop: '1px solid var(--color-border)' }} />
          <button
            role="menuitem"
            className="composer-glass-menu-item flex w-full items-center gap-2.5 px-3 py-1.5 text-left text-[13px] cursor-pointer"
            style={{ color: 'var(--color-text-secondary)' }}
            onClick={() => {
              setAnchor(null);
              setCommandPaletteOpen(true);
            }}
          >
            <span className="flex-1">{t('composer.manageModels')}</span>
            <kbd
              className="text-[10px] px-1.5 py-0.5 rounded font-mono"
              style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-text-tertiary)' }}
            >
              ⌘K
            </kbd>
          </button>
        </ChipMenu>
      )}
    </>
  );
}
