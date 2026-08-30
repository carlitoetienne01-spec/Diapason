/**
 * Mettre la feuille à l'échelle plutôt que la comprimer.
 *
 * 30 août 2026. La feuille portait `width: var(--note-page-width)` ET
 * `max-width: 100%`. Quand la fenêtre est plus étroite que le papier, la
 * SEULE dimension qui cède est la largeur : la hauteur reste à 297 mm.
 * Mesuré dans le navigateur sur une A4 : 398 px de large au lieu de 794.
 *
 * Ce n'est pas qu'un défaut d'allure. Le texte reflue alors sur beaucoup plus
 * de lignes que la page n'en contient, pendant que la pagination continue de
 * lire `--note-page-height`, une constante — les feuilles peintes ne
 * correspondent plus à rien, et l'impression donne un troisième découpage.
 * C'est la moitié restante de « les pages se découpent n'importe où ».
 *
 * Word ne reflue jamais : son zoom « Largeur de page » met la page à
 * l'échelle. Une A4 reste une A4, elle est seulement affichée plus petite.
 */

/** Marge du bureau autour de la feuille, des deux côtés. */
const RESPIRATION_PX = 32;

/**
 * Le zoom qui fait tenir `largeurPapierPx` dans `largeurDisponible`.
 *
 * Jamais au-dessus de 100 % : un grand écran ne doit pas gonfler le papier —
 * Word ne le fait pas non plus en « Largeur de page », et une A4 affichée à
 * 150 % sur un 4K ne serait plus une A4 pour l'œil.
 *
 * Jamais en dessous de 25 % : en deçà, le texte n'est plus lisible et mieux
 * vaut laisser le bureau défiler horizontalement que promettre une page
 * qu'on ne peut pas lire.
 *
 * Arrondi au pour cent, parce qu'un `ResizeObserver` qui écrirait
 * `0.6613756613756614` à chaque pixel de redimensionnement relancerait une
 * pagination complète à chaque image.
 */
export function fitZoom(largeurDisponible: number, largeurPapierPx: number): number {
  if (!(largeurPapierPx > 0) || !(largeurDisponible > 0)) return 1;
  const brut = Math.min(1, (largeurDisponible - RESPIRATION_PX) / largeurPapierPx);
  return Math.max(0.25, Math.round(brut * 100) / 100);
}

/** Les crans du menu de zoom, comme celui de Word. */
export const NOTE_ZOOMS: Array<{ id: string; label: string; valeur: number | null }> = [
  { id: 'ajuste', label: 'Largeur de page', valeur: null },
  { id: '50', label: '50 %', valeur: 0.5 },
  { id: '75', label: '75 %', valeur: 0.75 },
  { id: '100', label: '100 %', valeur: 1 },
];
