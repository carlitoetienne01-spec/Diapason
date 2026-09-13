// Le zoom de l'interface — la logique, sans écran.
//
// Demandé le 13 septembre 2026 : « tout doit suivre la taille des caractères
// que j'ai choisie ». macOS n'offre aucune taille de texte système qu'une
// fenêtre WebKit puisse lire, et le réglage « Taille du texte » de l'app ne
// touche que ce qui est en unités relatives — une bonne part de l'interface
// est figée en pixels (146 classes `text-[Npx]`, ~300 `fontSize: N`). Le zoom
// du webview, lui, agrandit TOUT, pixels compris, comme ⌘+ dans un
// navigateur. Il se règle au clavier, se souvient, et se voit dans Réglages.

export const ZOOM_MIN = 0.8;
export const ZOOM_MAX = 1.8;
export const ZOOM_DEFAUT = 1;
const PAS = 0.1;

/** Arrondi au centième : sinon 1,1 + 0,1 s'écrit 1,2000000000000002. */
const centieme = (v: number) => Math.round(v * 100) / 100;

/** Un zoom utilisable, quoi qu'on ait lu dans localStorage. */
export function normaliserZoom(valeur: unknown): number {
  const n = typeof valeur === 'string' ? Number(valeur) : valeur;
  if (typeof n !== 'number' || !Number.isFinite(n)) return ZOOM_DEFAUT;
  return centieme(Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, n)));
}

export function zoomSuivant(zoom: number, sens: 'plus' | 'moins' | 'reset'): number {
  if (sens === 'reset') return ZOOM_DEFAUT;
  return normaliserZoom(zoom + (sens === 'plus' ? PAS : -PAS));
}

/** « 120 % » — ce que Réglages affiche. */
export function zoomEnPourcent(zoom: number): string {
  return `${Math.round(zoom * 100)} %`;
}

/**
 * Le geste clavier, s'il y en a un : ⌘ + (ou ⌘ =, la même touche sans
 * majuscule), ⌘ −, ⌘ 0. Ctrl sur les autres systèmes. Contrairement aux
 * autres raccourcis de l'app, celui-ci vaut AUSSI dans une zone de saisie :
 * c'est là qu'on a besoin de mieux voir, et aucun éditeur ne s'en sert.
 */
export function raccourciZoom(e: {
  metaKey: boolean;
  ctrlKey: boolean;
  altKey: boolean;
  key: string;
}): 'plus' | 'moins' | 'reset' | null {
  if (!(e.metaKey || e.ctrlKey) || e.altKey) return null;
  if (e.key === '+' || e.key === '=') return 'plus';
  if (e.key === '-' || e.key === '_') return 'moins';
  if (e.key === '0') return 'reset';
  return null;
}
