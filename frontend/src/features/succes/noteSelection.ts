// La sélection d'une note en deux nombres — début et fin, en caractères —
// pour la retrouver après avoir remplacé le HTML de l'éditeur.
//
// L'aperçu des tailles (13 septembre 2026 : « quand je passe le curseur sur
// une taille, le texte sélectionné doit me donner un aperçu ») applique la
// taille pour de vrai, puis remet le HTML d'avant ; les nœuds d'origine
// n'existent plus, seuls des rangs de caractères survivent. Le HTML remis
// est EXACTEMENT celui mesuré, cales comprises : les rangs y valent.

export interface Etendue {
  debut: number;
  fin: number;
}

function rangDe(racine: HTMLElement, noeud: Node, offset: number): number {
  const plage = racine.ownerDocument.createRange();
  plage.selectNodeContents(racine);
  plage.setEnd(noeud, offset);
  return plage.toString().length;
}

/** L'étendue sélectionnée dans `racine`, ou null si la sélection est ailleurs. */
export function etendueDeLaSelection(racine: HTMLElement): Etendue | null {
  const selection = racine.ownerDocument.getSelection();
  if (!selection || selection.rangeCount === 0) return null;
  const plage = selection.getRangeAt(0);
  if (!racine.contains(plage.startContainer) || !racine.contains(plage.endContainer)) return null;
  return {
    debut: rangDe(racine, plage.startContainer, plage.startOffset),
    fin: rangDe(racine, plage.endContainer, plage.endOffset),
  };
}

function pointAuRang(racine: HTMLElement, rang: number): [Node, number] {
  const marcheur = racine.ownerDocument.createTreeWalker(racine, NodeFilter.SHOW_TEXT);
  let reste = rang;
  let dernier: Text | null = null;
  let noeud = marcheur.nextNode() as Text | null;
  while (noeud) {
    if (reste <= noeud.data.length) return [noeud, reste];
    reste -= noeud.data.length;
    dernier = noeud;
    noeud = marcheur.nextNode() as Text | null;
  }
  return dernier ? [dernier, dernier.data.length] : [racine, 0];
}

/** Resélectionne `etendue` dans `racine` (après un remplacement du HTML). */
export function selectionnerEtendue(racine: HTMLElement, etendue: Etendue): void {
  const doc = racine.ownerDocument;
  const [n1, o1] = pointAuRang(racine, etendue.debut);
  const [n2, o2] = pointAuRang(racine, etendue.fin);
  const plage = doc.createRange();
  plage.setStart(n1, o1);
  plage.setEnd(n2, o2);
  const selection = doc.getSelection();
  selection?.removeAllRanges();
  selection?.addRange(plage);
}
