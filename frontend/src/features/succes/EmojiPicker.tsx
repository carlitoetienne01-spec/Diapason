import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Ban, SmilePlus } from 'lucide-react';

export const HABIT_EMOJIS = [
  '✨', '🔥', '💪', '🏃', '🧘', '🙏', '❤️', '🧠',
  '📚', '✍️', '💻', '🎯', '✅', '⭐', '🌟', '💡',
  '🌅', '🌙', '💧', '🥗', '🍎', '🥤', '😴', '🛏️',
  '🧹', '🧼', '🪴', '🌳', '🚴', '🏋️', '⚽', '🎵',
  '🎸', '🎹', '🎨', '📷', '📱', '💰', '📈', '🗓️',
  '⏰', '☕', '🍵', '🦷', '🧴', '🚶', '🗣️', '📝',
] as const;

/** L'entrée « Aucun » : elle émet une chaîne vide. */
export const AUCUN_EMOJI = '';

/**
 * Ce que la liste propose, dans l'ordre : la valeur courante si elle n'est
 * pas des 48 (un 📞 posé à la voix ou par l'API restait affiché mais ne se
 * retrouvait plus une fois changé), puis les 48, puis « Aucun » quand la
 * valeur est facultative. Ce sélecteur venait d'Habitudes, où l'icône est
 * obligatoire ; branché sur l'emoji de tâche, facultatif côté serveur, il ne
 * laissait plus aucun chemin au clic ni au clavier pour l'effacer — §82
 * (revue du 17 sept. 2026, défaut 20). Pur, pour vitest.
 */
export function choixEmoji(value: string, optionnel: boolean): { emoji: string; libelle: string }[] {
  const courant = value && !(HABIT_EMOJIS as readonly string[]).includes(value)
    ? [{ emoji: value, libelle: `Emoji ${value} (actuel)` }]
    : [];
  const liste = HABIT_EMOJIS.map((emoji) => ({ emoji, libelle: `Emoji ${emoji}` }));
  const aucun = optionnel ? [{ emoji: AUCUN_EMOJI, libelle: 'Aucun emoji' }] : [];
  return [...courant, ...liste, ...aucun];
}

/** Largeur du panneau, hauteur au plus : 8 colonnes de 28 px + écarts + marge. */
export const PANNEAU_EMOJI_LARGEUR = 248;
export const PANNEAU_EMOJI_HAUTEUR_MAX = 240;
const PANNEAU_EMOJI_ECART = 6;
const PANNEAU_EMOJI_MARGE = 8;

export type PlacementPanneauEmoji = {
  left: number;
  width: number;
  /** Ancré sous le bouton (`top`) ou au-dessus (`bottom`, mesuré depuis le bas de la fenêtre). */
  top?: number;
  bottom?: number;
  maxHeight: number;
};

/**
 * Où poser le panneau, en coordonnées `fixed`, depuis le rectangle du bouton.
 * Retourné vers le haut quand la place manque dessous ET qu'elle existe
 * dessus ; borné aux bords de la fenêtre ; jamais plus large que la fenêtre.
 * Pur, pour vitest.
 */
export function placerPanneauEmoji(
  ancre: { top: number; bottom: number; left: number },
  fenetre: { largeur: number; hauteur: number },
): PlacementPanneauEmoji {
  const width = Math.min(PANNEAU_EMOJI_LARGEUR, Math.max(0, fenetre.largeur - 2 * PANNEAU_EMOJI_MARGE));
  const left = Math.min(Math.max(PANNEAU_EMOJI_MARGE, ancre.left), fenetre.largeur - width - PANNEAU_EMOJI_MARGE);
  const maxHeight = Math.min(PANNEAU_EMOJI_HAUTEUR_MAX, Math.floor(fenetre.hauteur * 0.4));
  const encombrement = maxHeight + PANNEAU_EMOJI_ECART;
  const versLeHaut = ancre.bottom + encombrement > fenetre.hauteur && ancre.top > encombrement;
  return versLeHaut
    ? { left, width, maxHeight, bottom: fenetre.hauteur - ancre.top + PANNEAU_EMOJI_ECART }
    : { left, width, maxHeight, top: ancre.bottom + PANNEAU_EMOJI_ECART };
}

type Props = {
  value: string;
  onChange: (emoji: string) => void;
  'aria-label'?: string;
  /** La valeur peut être vide : la liste propose « Aucun ». Habitudes et
      Finances exigent une icône et ne le passent pas. */
  optionnel?: boolean;
};

export function EmojiPicker({
  value,
  onChange,
  'aria-label': ariaLabel = 'Choisir un emoji',
  optionnel = false,
}: Props) {
  /**
   * Le panneau est un PORTAIL `fixed` sur body, jamais un `absolute` dans le
   * bouton : le formulaire de création de tâche est une carte vitrée, et
   * `.composer-glass > * { position: relative; z-index: 1 }` fait de chaque
   * rangée son propre contexte d'empilement — le panneau `z-50` restait
   * enfermé dans la rangée de l'emoji et les rangées suivantes (date,
   * catégorie, notes), peintes après, le recouvraient : 32 des 48 emojis
   * incliquables en création, 40 en édition, visibles à travers les champs
   * transparents mais le clic tombait sur l'input (revue du 17 sept. 2026,
   * défaut 13). Modèle MenuActions : position calculée depuis le rectangle
   * du bouton à l'ouverture — retourné vers le haut quand la place manque
   * (« s'ouvre en bas, caché » dans le mini-panneau, 15 sept. 2026), borné
   * aux bords — et refermé au `resize` et au défilement, une ancre mesurée
   * devenant fausse. Le même composant sert Habitudes et Finances : corrigé
   * ici, corrigé partout.
   */
  const [placement, setPlacement] = useState<PlacementPanneauEmoji | null>(null);
  const boutonRef = useRef<HTMLButtonElement>(null);
  const panneauRef = useRef<HTMLDivElement>(null);
  const open = placement !== null;

  useEffect(() => {
    if (!open) return;
    const fermer = () => setPlacement(null);
    const onPointer = (event: MouseEvent) => {
      const cible = event.target as Node;
      // Le bouton n'est pas « dehors » : fermer ici ferait la course avec
      // son propre onClick, qui rouvrirait un panneau déjà fermé.
      if (boutonRef.current?.contains(cible)) return;
      if (!panneauRef.current?.contains(cible)) fermer();
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      // Consommé : le mini-panneau ne se ferme qu'au second Échap (contrat du 17 sept. 2026, lib.rs lit `defaultPrevented`).
      event.preventDefault();
      fermer();
      boutonRef.current?.focus();
    };
    // En portail, le panneau vit en fin de body : Tab depuis le bouton
    // passerait au champ suivant sans jamais l'atteindre (§82). Le focus
    // entre donc dans le panneau à l'ouverture, sur l'emoji courant — s'il
    // y en a un : sans emoji, « Aucun » est le DERNIER bouton et y entrer
    // mettait les 48 emojis derrière soi (contre-revue du 17 sept. 2026).
    const courant = value
      ? panneauRef.current?.querySelector<HTMLButtonElement>('button[aria-pressed="true"]')
      : null;
    (courant ?? panneauRef.current?.querySelector<HTMLButtonElement>('button'))?.focus();
    // Capture : le défilement se produit dans le conteneur de la page, pas
    // sur window ; un panneau `fixed` resterait planté pendant que son
    // formulaire s'en va. Le panneau lui-même défile (7 rangées sous
    // 40 vh dans le mini-panneau) : son propre défilement ne le ferme pas.
    const onScroll = (event: Event) => {
      if (panneauRef.current?.contains(event.target as Node)) return;
      fermer();
    };
    document.addEventListener('mousedown', onPointer);
    document.addEventListener('keydown', onKey);
    window.addEventListener('resize', fermer);
    document.addEventListener('scroll', onScroll, true);
    return () => {
      document.removeEventListener('mousedown', onPointer);
      document.removeEventListener('keydown', onKey);
      window.removeEventListener('resize', fermer);
      document.removeEventListener('scroll', onScroll, true);
    };
  }, [open]);

  const basculer = () => {
    if (placement) {
      setPlacement(null);
      return;
    }
    const rect = boutonRef.current?.getBoundingClientRect();
    if (rect) {
      setPlacement(placerPanneauEmoji(rect, { largeur: window.innerWidth, hauteur: window.innerHeight }));
    }
  };

  return (
    <div>
      {/* Vide, le bouton montre une ICÔNE de bouton, pas ✨ en guise de
          valeur : en création de tâche on pouvait croire un emoji choisi
          alors que la tâche partait sans (défaut 20). Le libellé le dit. */}
      <button
        ref={boutonRef}
        type="button"
        onClick={basculer}
        aria-label={value ? `${ariaLabel} — ${value}` : `${ariaLabel} — aucun`}
        aria-expanded={open}
        aria-haspopup="dialog"
        className="size-full min-h-[46px] rounded-xl text-lg cursor-pointer flex items-center justify-center"
        style={{
          border: '1px solid var(--color-border)',
          color: value ? 'var(--color-text)' : 'var(--color-text-tertiary)',
          background: open
            ? 'color-mix(in srgb, var(--color-accent) 12%, transparent)'
            : 'transparent',
        }}
      >
        {value ? <span aria-hidden>{value}</span> : <SmilePlus size={18} aria-hidden />}
      </button>

      {placement && createPortal(
        <div
          ref={panneauRef}
          role="dialog"
          aria-label="Liste d’emojis"
          className="fixed z-50 overflow-y-auto rounded-xl p-2 shadow-lg"
          style={{
            left: placement.left,
            width: placement.width,
            top: placement.top,
            bottom: placement.bottom,
            maxHeight: placement.maxHeight,
            background: 'var(--color-surface)',
            border: '1px solid var(--color-border)',
            backdropFilter: 'blur(12px)',
          }}
        >
          <div className="grid grid-cols-8 gap-0.5">
            {choixEmoji(value, optionnel).map((choix) => {
              const selected = value === choix.emoji;
              return (
                <button
                  key={choix.emoji || '__aucun__'}
                  type="button"
                  onClick={() => {
                    onChange(choix.emoji);
                    setPlacement(null);
                    // Le bouton focalisé disparaît avec le portail : sans
                    // retour au déclencheur, Tab repartait de la fin du
                    // body au lieu du champ suivant du formulaire.
                    boutonRef.current?.focus();
                  }}
                  aria-label={choix.libelle}
                  title={choix.emoji ? undefined : 'Aucun'}
                  aria-pressed={selected}
                  className="size-7 rounded-md text-base cursor-pointer flex items-center justify-center hover:opacity-100"
                  style={{
                    background: selected
                      ? 'color-mix(in srgb, var(--color-accent) 22%, transparent)'
                      : 'transparent',
                    outline: selected ? '1px solid var(--color-accent)' : undefined,
                    color: choix.emoji ? undefined : 'var(--color-text-tertiary)',
                  }}
                >
                  {choix.emoji || <Ban size={15} aria-hidden />}
                </button>
              );
            })}
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
}
