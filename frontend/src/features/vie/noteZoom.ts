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
/**
 * L'AJUSTEMENT automatique, plafonné à 100 %.
 *
 * Ce plafond ne concerne que l'ajustement : « Largeur de page » ne doit pas
 * gonfler le papier sur un grand écran, Word ne le fait pas non plus. Le
 * curseur manuel, lui, monte jusqu'à `ZOOM_MAX` — ce sont deux gestes
 * différents, et les confondre bridait un agrandissement voulu.
 */
export function fitZoom(largeurDisponible: number, largeurPapierPx: number): number {
  if (!(largeurPapierPx > 0) || !(largeurDisponible > 0)) return 1;
  const brut = Math.min(1, (largeurDisponible - RESPIRATION_PX) / largeurPapierPx);
  return Math.max(0.25, Math.round(brut * 100) / 100);
}

/**
 * Les bornes du curseur de zoom, comme la réglette de Word en bas à droite.
 *
 * Word descend à 10 % et monte à 500 % ; Carlito a demandé 200 %, et c'est un
 * plafond plus honnête pour une note : au-delà, on ne lit plus une page, on
 * inspecte des pixels.
 *
 * Le plancher reste 25 % — celui de `fitZoom` — pour qu'ajuster et régler à la
 * main ne puissent pas donner deux minimums différents.
 */
export const ZOOM_MIN = 0.25;
export const ZOOM_MAX = 2;
export const ZOOM_PAS = 0.05;

/** Ramener une valeur dans les bornes, arrondie au pour cent. */
export function bornerZoom(valeur: number): number {
  if (!Number.isFinite(valeur)) return 1;
  const borne = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, valeur));
  return Math.round(borne * 100) / 100;
}
