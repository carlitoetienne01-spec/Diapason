import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useNavigate } from 'react-router';
import {
  ChevronDown,
  Copy,
  MoreHorizontal,
  PanelRightClose,
  PanelRightOpen,
  Pencil,
  Pin,
  PinOff,
  Plus,
  Search,
  Trash2,
} from 'lucide-react';
import { useAppStore } from '../../lib/store';
import { titreDiscussion, titreProvisoire } from '../../lib/discussions';
import { demanderLeFocusDuCompositeur } from '../../lib/panneau';
import { useConfirm } from '../ConfirmDialog';
import { useTranslation } from '../../i18n/useTranslation';
import { useSurfaceVitree } from './useSurfaceVitree';

/**
 * L'en-tête du fil : le nom de la discussion active, et de quoi en changer.
 *
 * 17 sept. 2026, chantier « discussions dans le mini-panneau ». La rangée du
 * haut de ChatArea ne portait que l'icône du panneau système : dans le
 * mini-panneau (pas de barre latérale), Carlito écrivait dans un fil dont il
 * ignorait le nom et ne pouvait ni le renommer ni en ouvrir un autre sans
 * fermer le panneau. Ajouter une rangée aurait volé 40 px à un fil de 184 px
 * à la hauteur minimale : l'en-tête tient dans les 40 px (h-10) que la rangée
 * occupait déjà.
 *
 * Hors compact, la barre latérale fait déjà tout cela : seuls le titre (utile
 * quand la barre est repliée) et l'icône du panneau système restent visibles ;
 * ⌕ ＋ ⋯ n'apparaissent qu'en compact (`hidden compact:inline-flex`), et y
 * sont PERMANENTS — le NSPanel ne livre pas le survol (convention, règle 5).
 */

/** Horizontal room the window's floating top-right cluster needs: its measured
 * width, its 12px offset from the edge, and a little air. A class rather than
 * an inline style, so that `compact:` can override it (an inline style beats
 * every class). The underscores are Tailwind's spelling of spaces. */
const CLUSTER_CLEARANCE_CLASS = 'pr-[calc(var(--top-right-cluster,33px)_+_20px)]';

// Sans classe d'affichage : `hidden compact:inline-flex` la porte pour les
// glyphes réservés au compact, et un `inline-flex` ici la neutraliserait
// (même spécificité, ordre du CSS) — constaté au premier essai, les trois
// boutons s'affichaient dans la fenêtre.
const BOUTON =
  'items-center justify-center w-7 h-7 rounded-md cursor-pointer transition-colors shrink-0';

interface Props {
  /** Le sauteur (⌘J) est-il ouvert ? Tenu par ChatArea, rempli par le lot suivant. */
  sauteurOuvert: boolean;
  /** Ouvre le sauteur — depuis le titre ou ⌕. */
  onOuvrirSauteur: () => void;
}

export function EnteteDiscussion({ sauteurOuvert, onOuvrirSauteur }: Props) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const confirm = useConfirm();
  const conversations = useAppStore((s) => s.conversations);
  const activeId = useAppStore((s) => s.activeId);
  const selectedModel = useAppStore((s) => s.selectedModel);
  const nouvelleDiscussion = useAppStore((s) => s.nouvelleDiscussion);
  const renameConversation = useAppStore((s) => s.renameConversation);
  const togglePinConversation = useAppStore((s) => s.togglePinConversation);
  const duplicateConversation = useAppStore((s) => s.duplicateConversation);
  const deleteConversation = useAppStore((s) => s.deleteConversation);
  const systemPanelOpen = useAppStore((s) => s.systemPanelOpen);
  const toggleSystemPanel = useAppStore((s) => s.toggleSystemPanel);

  const active = activeId ? conversations.find((c) => c.id === activeId) : undefined;
  const titre = titreDiscussion(conversations, activeId, t);
  const provisoire = titreProvisoire(conversations, activeId);

  const [menuAncre, setMenuAncre] = useState<DOMRect | null>(null);
  const boutonMenuRef = useRef<HTMLButtonElement>(null);
  const [renommage, setRenommage] = useState<string | null>(null);

  const fermerMenu = (rendreLeFocus = true) => {
    setMenuAncre(null);
    // Quel que soit le chemin de sortie, le curseur retourne au compositeur —
    // sauf quand un renommage commence : son champ prend le focus, et une
    // demande différée le lui reprendrait (le nettoyage passif court APRÈS
    // l'autoFocus du champ monté dans le même commit).
    if (rendreLeFocus) demanderLeFocusDuCompositeur();
  };

  const commencerRenommage = () => {
    if (!active) return;
    // Le titre BRUT, jamais le libellé de repli : valider sans rien toucher
    // figerait « Nouvelle discussion » comme vrai titre et couperait le
    // nommage automatique du premier message.
    setRenommage(active.title);
    fermerMenu(false);
  };

  const validerRenommage = () => {
    if (renommage !== null && active) {
      const suivant = renommage.trim();
      if (suivant && suivant !== active.title) renameConversation(active.id, suivant);
    }
    setRenommage(null);
    demanderLeFocusDuCompositeur();
  };

  const nouvelle = () => {
    // Même règle que la barre latérale et ⌘N (store.nouvelleDiscussion) :
    // une vierge existante est réutilisée, jamais deux « Nouvelle
    // discussion » empilées.
    nouvelleDiscussion(selectedModel);
    navigate('/');
    demanderLeFocusDuCompositeur();
  };

  const dupliquer = () => {
    if (!active) return;
    const nom = active.title || t('sidebar.untitled');
    duplicateConversation(active.id, t('sidebar.duplicateTitle', { title: nom }));
    fermerMenu();
    navigate('/');
  };

  const supprimer = () => {
    if (!active) return;
    const id = active.id;
    fermerMenu(false);
    void (async () => {
      const confirme = await confirm({
        title: t('sidebar.deleteConversation'),
        description: t('sidebar.confirmDelete'),
        confirmLabel: t('common.delete'),
        keepLabel: 'Garder',
        tone: 'danger',
      });
      if (confirme) deleteConversation(id);
      demanderLeFocusDuCompositeur();
    })();
  };

  const PanelIcon = systemPanelOpen ? PanelRightClose : PanelRightOpen;
  const raccourci = (touche: string) =>
    `${navigator.platform.includes('Mac') ? '⌘' : 'Ctrl'}+${touche}`;
  const raccourciPanneau = raccourci('I');

  return (
    <div
      className={`flex items-center gap-1 h-10 pl-3 shrink-0 ${
        // Talk and the approval bell are pinned to the window's top-right
        // corner. With the system panel open the panel sits beneath them;
        // closed, this bar reaches that same edge, so it has to yield their
        // footprint or the controls land on top of one another.
        // 16 sept. 2026 : en compact, Layout ne rend pas ce groupe — la
        // barre réservait 53 px à un cluster absent. `compact:` est le
        // variant de chrome prévu pour cela (convention, règle 3).
        systemPanelOpen ? 'pr-3' : `${CLUSTER_CLEARANCE_CLASS} compact:pr-3`
      }`}
    >
      {renommage !== null ? (
        <input
          autoFocus
          value={renommage}
          placeholder={t('sidebar.untitled')}
          aria-label={t('sidebar.rename')}
          onFocus={(e) => e.currentTarget.select()}
          onChange={(e) => setRenommage(e.target.value)}
          onKeyDown={(e) => {
            if (e.nativeEvent.isComposing) return;
            if (e.key === 'Enter') validerRenommage();
            if (e.key === 'Escape') {
              // Consommé : le script natif du mini-panneau ne doit pas fermer
              // le panneau sur l'Échap qui annule un renommage.
              e.preventDefault();
              setRenommage(null);
              demanderLeFocusDuCompositeur();
            }
          }}
          onBlur={validerRenommage}
          className="flex-1 min-w-0 h-7 px-2 text-[13px] font-semibold rounded-md outline-none"
          style={{
            background: 'var(--color-bg-secondary)',
            color: 'var(--color-text)',
            border: '1px solid var(--color-accent)',
          }}
        />
      ) : (
        <button
          type="button"
          onClick={onOuvrirSauteur}
          className="flex items-center gap-2 flex-1 min-w-0 h-7 px-1.5 -ml-1.5 rounded-md text-left cursor-pointer"
          title={t('chat.header.jump')}
          aria-haspopup="menu"
          aria-expanded={sauteurOuvert}
        >
          <span
            aria-hidden="true"
            className="w-1.5 h-1.5 rounded-full shrink-0"
            style={{ background: provisoire ? 'var(--color-border)' : 'var(--color-accent)' }}
          />
          <span
            className="min-w-0 truncate text-[13px] font-semibold"
            style={{ color: provisoire ? 'var(--color-text-tertiary)' : 'var(--color-text)' }}
          >
            {titre}
          </span>
          <ChevronDown size={12} className="shrink-0" style={{ color: 'var(--color-text-tertiary)' }} />
        </button>
      )}

      <div className="flex items-center gap-0.5 shrink-0 ml-auto">
        <button
          type="button"
          onClick={onOuvrirSauteur}
          className={`hidden compact:inline-flex ${BOUTON}`}
          style={{ color: 'var(--color-text-tertiary)' }}
          title={t('chat.header.jump')}
          aria-label={t('chat.header.jump')}
          aria-haspopup="menu"
          aria-expanded={sauteurOuvert}
        >
          <Search size={15} />
        </button>
        <button
          type="button"
          onClick={nouvelle}
          className={`hidden compact:inline-flex ${BOUTON}`}
          style={{ color: 'var(--color-text-tertiary)' }}
          title={t('chat.header.newChat', { shortcut: raccourci('N') })}
          aria-label={t('chat.header.newChat', { shortcut: raccourci('N') })}
        >
          <Plus size={16} />
        </button>
        <button
          ref={boutonMenuRef}
          type="button"
          disabled={!active}
          onClick={() => {
            if (menuAncre) {
              fermerMenu();
              return;
            }
            const rect = boutonMenuRef.current?.getBoundingClientRect();
            if (rect) setMenuAncre(rect);
          }}
          className={`hidden compact:inline-flex ${BOUTON} disabled:opacity-40 disabled:cursor-default`}
          style={{ color: 'var(--color-text-tertiary)' }}
          title={t('sidebar.conversationOptions')}
          aria-label={t('sidebar.conversationOptions')}
          aria-haspopup="menu"
          aria-expanded={menuAncre !== null}
        >
          <MoreHorizontal size={16} />
        </button>
        <button
          type="button"
          onClick={toggleSystemPanel}
          className={`inline-flex ${BOUTON}`}
          style={{ color: 'var(--color-text-tertiary)' }}
          title={
            systemPanelOpen
              ? t('chat.system.hidePanel', { shortcut: raccourciPanneau })
              : t('chat.system.showPanel', { shortcut: raccourciPanneau })
          }
        >
          <PanelIcon size={16} />
        </button>
      </div>

      {menuAncre && active && (
        <MenuEntete ancre={menuAncre} boutonRef={boutonMenuRef} onClose={() => fermerMenu()}>
          <EntreeMenu icone={<Pencil size={14} />} onClick={commencerRenommage}>
            {t('sidebar.rename')}
          </EntreeMenu>
          <EntreeMenu
            icone={active.pinned ? <PinOff size={14} /> : <Pin size={14} />}
            onClick={() => {
              togglePinConversation(active.id);
              fermerMenu();
            }}
          >
            {active.pinned ? t('sidebar.unpin') : t('sidebar.pin')}
          </EntreeMenu>
          <EntreeMenu icone={<Copy size={14} />} onClick={dupliquer}>
            {t('sidebar.duplicate')}
          </EntreeMenu>
          <div className="my-1 mx-2" style={{ borderTop: '1px solid var(--color-border)' }} />
          <EntreeMenu icone={<Trash2 size={14} />} couleur="var(--color-error)" onClick={supprimer}>
            {t('sidebar.deleteConversation')}
          </EntreeMenu>
        </MenuEntete>
      )}
    </div>
  );
}

function EntreeMenu({
  icone,
  couleur,
  onClick,
  children,
}: {
  icone: React.ReactNode;
  couleur?: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      className="composer-glass-menu-item flex w-full items-center gap-2.5 px-3 py-1.5 text-left text-[13px] cursor-pointer"
      style={{ color: couleur ?? 'var(--color-text)' }}
      onClick={onClick}
    >
      <span className="shrink-0" style={{ color: couleur ?? 'var(--color-text-secondary)' }}>
        {icone}
      </span>
      {children}
    </button>
  );
}

/**
 * Le menu ⋯ : un portail `fixed` sur body, ancré SOUS son bouton et borné au
 * panneau (convention, règle 4). Même matière que les menus de puce du
 * compositeur (composer-glass-menu), mais ouvert vers le bas : l'en-tête est
 * en haut, le compositeur en bas.
 */
function MenuEntete({
  ancre,
  boutonRef,
  onClose,
  children,
}: {
  ancre: DOMRect;
  boutonRef: React.RefObject<HTMLButtonElement | null>;
  onClose: () => void;
  children: React.ReactNode;
}) {
  const ref = useSurfaceVitree();
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    const onPointerDown = (e: MouseEvent) => {
      const cible = e.target as Node;
      // Le bouton n'est pas « dehors » : fermer ici ferait la course avec
      // son propre onClick, qui rouvrirait un menu déjà fermé.
      if (boutonRef.current?.contains(cible)) return;
      if (!ref.current || !ref.current.contains(cible)) onCloseRef.current();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      // Consommé : le panneau ne se ferme qu'au second Échap (contrat du
      // 17 sept. 2026 avec le script natif, qui lit `defaultPrevented`).
      e.preventDefault();
      onCloseRef.current();
    };
    // Le panneau se redimensionne en continu : une ancre figée devient
    // fausse, fermer suffit (modèle ChipMenu).
    const onResize = () => onCloseRef.current();
    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKey);
    window.addEventListener('resize', onResize);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onKey);
      window.removeEventListener('resize', onResize);
    };
  }, [boutonRef, ref]);

  const largeur = Math.min(220, Math.max(0, window.innerWidth - 16));
  // Aligné à droite sur le bouton, jamais hors du bord gauche.
  const left = Math.min(Math.max(8, ancre.right - largeur), window.innerWidth - largeur - 8);
  const top = ancre.bottom + 4;

  return createPortal(
    <div
      ref={ref}
      role="menu"
      className="composer-glass-menu fixed z-50 py-1.5 px-1.5 overflow-y-auto"
      style={{
        left,
        top,
        width: largeur,
        maxHeight: `min(50vh, ${Math.max(0, window.innerHeight - top - 8)}px)`,
      }}
    >
      {children}
    </div>,
    document.body,
  );
}
