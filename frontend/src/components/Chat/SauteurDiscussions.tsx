import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { CornerDownLeft, Plus, Search } from 'lucide-react';
import type { Conversation } from '../../types';
import { useAppStore } from '../../lib/store';
import { classerDiscussions } from '../../lib/discussions';
import {
  demanderLeFocusDuCompositeur,
  deposerLeTexteDansLeCompositeur,
} from '../../lib/panneau';
import { formatRelativeTime, sectionsOf } from '../Sidebar/ConversationList';
import { useTranslation } from '../../i18n/useTranslation';
import { useSurfaceVitree } from './useSurfaceVitree';

/**
 * Le sauteur de discussions (⌘J) : un menu de verre ancré SOUS le titre du
 * fil, épinglées puis récentes, fermé dès qu'on a choisi.
 *
 * 17 sept. 2026, chantier « discussions dans le mini-panneau ». Changer de
 * fil exigeait de fermer le mini, ouvrir la fenêtre, cliquer la barre
 * latérale, revenir. Un tiroir aurait caché 85 % du fil à 340 px et une
 * feuille aurait recouvert le compositeur : le menu s'ouvre sous le titre
 * qu'on vient de toucher — la seule forme qui ne s'ouvre « nulle part
 * ailleurs » et ne cache pas la vue (Slack ⌘K, Raycast AI ⌘P, Figma et
 * Notion sous le nom du fichier).
 *
 * Portail `fixed` sur body (un menu ouvert dans une carte vitrée est peint
 * sous la suivante : convention, règle 5), borné au panneau, fermé sur clic
 * dehors, Échap (consommé : le panneau ne se ferme qu'au second) et
 * `resize` — le panneau se redimensionne en continu, une ancre figée devient
 * fausse (modèle ChipMenu). Le focus est dans le champ « Aller à… » tant
 * qu'il est ouvert, et retourne au compositeur quel que soit le chemin de
 * sortie.
 *
 * Les actions sur un AUTRE fil ne sont pas ici : on le choisit, puis ⋯ agit
 * sur le courant — épuré. L'état d'ouverture est celui de ChatArea, jamais
 * une route (le rail réécrit l'URL).
 */

/** Posé sur les boutons qui ouvrent ET ferment le sauteur (titre, ⌕) : un
 * `mousedown` dessus n'est pas « dehors », sinon il fermerait le menu et le
 * clic qui suit le rouvrirait — un menu qui clignote et ne se ferme jamais. */
export const ATTRIBUT_BASCULE_SAUTEUR = 'data-sauteur-bascule';

// 320 px : la largeur du panneau minimal (340) moins les deux gouttières de
// 8 ; au-delà, un titre de 13 px ne gagne plus rien à s'étaler. 360 px de
// haut : 50 vh vaut 190 px à la hauteur minimale (380) et 310 à 620, la
// hauteur par défaut ; 360 ne mord que sur un panneau étiré au-delà.
const LARGEUR_MAX = 320;
const HAUTEUR_MAX = 360;
const HAUTEUR_RANGEE = 32;

interface Props {
  /** Le bouton-titre : le menu s'ancre sous lui. */
  ancre: HTMLElement | null;
  /** La rangée de l'en-tête, quand le titre est remplacé par le champ de renommage. */
  repli: HTMLElement | null;
  onClose: () => void;
}

function positionner(element: HTMLElement | null) {
  const rect = element?.getBoundingClientRect() ?? null;
  const largeur = Math.min(LARGEUR_MAX, Math.max(0, window.innerWidth - 16));
  const gauche = Math.max(8, window.innerWidth - largeur - 8);
  const left = Math.min(Math.max(8, rect?.left ?? 8), gauche);
  const top = (rect?.bottom ?? 0) + 6;
  return { left, top, largeur };
}

export function SauteurDiscussions({ ancre, repli, onClose }: Props) {
  const { t } = useTranslation();
  const conversations = useAppStore((s) => s.conversations);
  const activeId = useAppStore((s) => s.activeId);
  const selectedModel = useAppStore((s) => s.selectedModel);
  const selectConversation = useAppStore((s) => s.selectConversation);
  const loadMessages = useAppStore((s) => s.loadMessages);
  const nouvelleDiscussion = useAppStore((s) => s.nouvelleDiscussion);

  const ref = useSurfaceVitree();
  const listeRef = useRef<HTMLDivElement>(null);
  // Quel que soit le chemin de sortie (choix, Échap, clic dehors, resize), le
  // curseur retourne au compositeur : on choisit un fil et on continue à
  // taper sans cliquer. Explicite à chaque sortie, PAS dans le nettoyage
  // d'un effet (modèle ChipMenu) : en StrictMode, React simule un démontage
  // au premier montage et ce nettoyage volait le focus au champ « Aller
  // à… » — les lettres tapées partaient dans le compositeur (constaté dans
  // le banc ?compact, 17 sept. 2026). Et différé d'un tour : demandé DANS
  // le `mousedown` d'un clic dehors, le focus était repris aussitôt par
  // l'action par défaut du clic, qui court après les écouteurs — le curseur
  // n'était de nouveau nulle part.
  const fermer = () => {
    onClose();
    window.setTimeout(demanderLeFocusDuCompositeur, 0);
  };
  const fermerRef = useRef(fermer);
  fermerRef.current = fermer;

  // Mesuré UNE fois à l'ouverture : `resize` ferme (voir plus bas), il n'y a
  // donc jamais d'ancre périmée à recalculer.
  const [position] = useState(() => positionner(ancre ?? repli));

  const [requete, setRequete] = useState('');
  const [idx, setIdx] = useState(0);
  const enRecherche = requete.trim() !== '';

  const classees = useMemo(
    () => classerDiscussions(requete, conversations, Date.now()),
    [requete, conversations],
  );
  // Sans requête, les sections de la barre latérale ; avec, une liste plate
  // dans l'ordre du classement (épinglées, début de mot, sous-chaîne,
  // récence). Les sections ne réordonnent pas : leur concaténation est
  // exactement `classees`, et l'index clavier s'y lit directement.
  const sections = useMemo<{ label: string | null; items: Conversation[] }[]>(
    () => (enRecherche ? [{ label: null, items: classees }] : sectionsOf(classees, t)),
    [enRecherche, classees, t],
  );
  const indexDe = useMemo(() => new Map(classees.map((c, i) => [c.id, i])), [classees]);
  const proposerCreation = enRecherche && classees.length === 0;
  const nombre = proposerCreation ? 1 : classees.length;

  useEffect(() => {
    const onPointerDown = (e: MouseEvent) => {
      const cible = e.target as Node;
      if (cible instanceof Element && cible.closest(`[${ATTRIBUT_BASCULE_SAUTEUR}]`)) return;
      // Une ref nulle ferme aussi (leçon du menu-zombie de ConversationList).
      if (!ref.current || !ref.current.contains(cible)) fermerRef.current();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      // Consommé : le script natif du mini-panneau lit `defaultPrevented`
      // après le tour et ne ferme le panneau qu'au second Échap.
      e.preventDefault();
      fermerRef.current();
    };
    const onResize = () => fermerRef.current();
    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKey);
    window.addEventListener('resize', onResize);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onKey);
      window.removeEventListener('resize', onResize);
    };
  }, [ref]);

  useEffect(() => {
    listeRef.current
      ?.querySelector(`[data-index="${idx}"]`)
      ?.scrollIntoView({ block: 'nearest' });
  }, [idx]);

  const choisir = (id: string) => {
    if (id !== activeId) {
      selectConversation(id);
      loadMessages(id);
    }
    fermer();
  };

  const creer = () => {
    const texte = requete.trim();
    // Même règle que ＋ et ⌘N : une vierge existante est réutilisée. Le texte
    // tapé est DÉPOSÉ dans le compositeur, jamais envoyé (§100) : on le relit
    // et on appuie sur ↩ soi-même.
    nouvelleDiscussion(selectedModel);
    if (texte) deposerLeTexteDansLeCompositeur(texte);
    fermer();
  };

  const valider = () => {
    if (proposerCreation) {
      creer();
      return;
    }
    const cible = classees[idx];
    if (cible) choisir(cible.id);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.nativeEvent.isComposing) return;
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'j') {
      // ⌘J sur un sauteur ouvert le referme (Slack ⌘K) : le champ n'a pas
      // `data-raccourcis-globaux`, App.tsx ne voit donc pas la touche.
      e.preventDefault();
      fermer();
      return;
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setIdx((i) => Math.min(i + 1, Math.max(0, nombre - 1)));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      valider();
    }
  };

  const idOption = (i: number) => `sauteur-option-${i}`;

  return createPortal(
    <div
      ref={ref}
      role="dialog"
      aria-label={t('chat.header.jump')}
      className="composer-glass-menu sauteur-entree fixed z-50 flex flex-col p-1.5"
      style={{
        left: position.left,
        top: position.top,
        width: position.largeur,
        maxHeight: `min(50vh, ${HAUTEUR_MAX}px)`,
      }}
    >
      <div
        className="flex items-center gap-2 h-8 px-2.5 shrink-0 rounded-[11px]"
        style={{ color: 'var(--color-text-tertiary)' }}
      >
        <Search size={14} className="shrink-0" />
        <input
          autoFocus
          type="text"
          role="combobox"
          aria-expanded="true"
          aria-controls="sauteur-liste"
          aria-autocomplete="list"
          aria-activedescendant={nombre > 0 ? idOption(idx) : undefined}
          value={requete}
          placeholder={t('chat.jump.placeholder')}
          onChange={(e) => {
            setRequete(e.target.value);
            setIdx(0);
          }}
          onKeyDown={onKeyDown}
          className="flex-1 min-w-0 bg-transparent outline-none text-[13px]"
          style={{ color: 'var(--color-text)' }}
        />
      </div>
      <div className="mx-1 my-1 shrink-0" style={{ borderTop: '1px solid var(--color-border)' }} />
      <div
        id="sauteur-liste"
        ref={listeRef}
        role="listbox"
        aria-label={t('chat.header.jump')}
        className="min-h-0 overflow-y-auto"
      >
        {proposerCreation && (
          <div
            role="option"
            id={idOption(0)}
            data-index={0}
            aria-selected="true"
            onClick={creer}
            onMouseEnter={() => setIdx(0)}
            className="composer-glass-menu-item flex items-center gap-2 px-2.5 text-[13px] cursor-pointer"
            style={{
              height: HAUTEUR_RANGEE,
              background: 'var(--color-accent-subtle)',
              color: 'var(--color-text)',
            }}
          >
            <Plus size={14} className="shrink-0" style={{ color: 'var(--color-accent)' }} />
            <span className="flex-1 min-w-0 truncate">
              {t('chat.jump.create', { text: requete.trim() })}
            </span>
            <CornerDownLeft
              size={12}
              className="shrink-0"
              aria-hidden="true"
              style={{ color: 'var(--color-text-tertiary)' }}
            />
          </div>
        )}
        {!proposerCreation && classees.length === 0 && (
          <div
            className="px-2.5 py-3 text-center text-xs"
            style={{ color: 'var(--color-text-tertiary)' }}
          >
            {t('sidebar.noConversations')}
          </div>
        )}
        {sections.map((section, s) => (
          <div key={section.label ?? s}>
            {section.label && (
              <div
                className="px-2.5 pt-2 pb-1 text-[10px] font-medium uppercase tracking-wider select-none"
                style={{ color: 'var(--color-text-tertiary)' }}
              >
                {section.label}
              </div>
            )}
            {section.items.map((c) => {
              const i = indexDe.get(c.id) ?? 0;
              const choisie = i === idx;
              const active = c.id === activeId;
              return (
                <div
                  key={c.id}
                  role="option"
                  id={idOption(i)}
                  data-index={i}
                  aria-selected={choisie}
                  onClick={() => choisir(c.id)}
                  onMouseEnter={() => setIdx(i)}
                  className="composer-glass-menu-item flex items-center gap-2 px-2.5 text-[13px] cursor-pointer"
                  style={{
                    height: HAUTEUR_RANGEE,
                    background: choisie ? 'var(--color-accent-subtle)' : undefined,
                    color: 'var(--color-text)',
                  }}
                >
                  <span
                    aria-hidden="true"
                    className="w-1.5 h-1.5 rounded-full shrink-0"
                    style={{ background: active ? 'var(--color-accent)' : 'transparent' }}
                  />
                  <span
                    className="flex-1 min-w-0 truncate"
                    style={{
                      color: c.title.trim() ? 'var(--color-text)' : 'var(--color-text-tertiary)',
                      fontWeight: active ? 500 : 400,
                    }}
                  >
                    {c.title.trim() || t('sidebar.untitled')}
                  </span>
                  <span
                    className="shrink-0 text-[11px] tabular-nums"
                    style={{ color: 'var(--color-text-tertiary)' }}
                  >
                    {formatRelativeTime(c.updatedAt, t)}
                  </span>
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>,
    document.body,
  );
}
