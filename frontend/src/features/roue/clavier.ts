// Le clavier du téléphone est-il ouvert ? — en fonctions pures.
//
// 26/09/2026, contre-épreuve de la fluidité : clavier ouvert (482 px de
// haut au banc), la Discussion gardait 97 px sous le compositeur pour le
// bouton « Aller à… », 14 % de ce qui reste d'écran. Clavier ouvert, le
// bouton se retire (index.css, `data-clavier-ouvert`) ; il revient dès que
// le clavier se ferme, même si le champ garde le focus (le retour d'Android
// ferme le clavier sans rendre le focus).

/** Sous 75 % de la plus grande hauteur vue à cette largeur : un clavier
 *  Android en prend 40 à 45 %, une barre d'adresse ou de navigation qui
 *  apparaît, moins de 10 %. */
export const PART_CLAVIER = 0.75;

export function clavierOuvert(e: { hauteur: number; hauteurMax: number; saisie: boolean }): boolean {
  return e.saisie && e.hauteur < e.hauteurMax * PART_CLAVIER;
}

const SANS_CLAVIER = new Set(['button', 'checkbox', 'radio', 'range', 'color', 'file', 'submit', 'reset', 'image', 'hidden']);

/** Un élément qui ouvre le clavier quand il a le focus. */
export function estUneSaisie(el: Element | null): boolean {
  if (el instanceof HTMLTextAreaElement) return !el.readOnly && !el.disabled;
  if (el instanceof HTMLInputElement) return !SANS_CLAVIER.has(el.type) && !el.readOnly && !el.disabled;
  return el instanceof HTMLElement && (el.isContentEditable || el.getAttribute('contenteditable') === 'true');
}

/** La plus grande hauteur vue, par largeur : tourner l'écran en change. */
export function suivreHauteurMax(memo: Map<number, number>, largeur: number, hauteur: number): number {
  const max = Math.max(memo.get(largeur) ?? 0, hauteur);
  memo.set(largeur, max);
  return max;
}
