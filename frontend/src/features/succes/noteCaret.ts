// Où est le caret, dans un repère qui survit à la pose des cales de
// pagination — et qui distingue « fin d'une puce » de « début de la suivante ».
//
// Ni le nœud ni le décalage ne survivent : poser une cale insère un élément
// DANS un paragraphe et scinde ses nœuds texte. L'ancien repère (index du
// bloc de premier niveau + rang du caractère dans ce bloc) avait un trou :
// dans une liste, la fin de « un » et le début de la puce vide qui suit ont
// le MÊME rang, et le caret revenait toujours dans la puce précédente —
// « il crée le numéro suivant mais le curseur ne suit pas » (13 septembre
// 2026). Le repère porte désormais aussi la FEUILLE : le bloc le plus
// profond (li, p, td, titre…) qui contient le caret, compté dans l'ordre du
// document à l'intérieur du bloc de premier niveau.

export interface PlaceDuCaret {
  /** Index du bloc de premier niveau (les cales ne comptent pas). */
  bloc: number;
  /** Index de la feuille dans ce bloc (ordre du document) ; -1 : le bloc lui-même. */
  feuille: number;
  /** Rang du caractère dans la feuille. */
  rang: number;
}

const FEUILLES = 'p, li, td, th, h1, h2, h3, h4, h5, h6, pre, div';

function feuillesDe(bloc: Element, classeCale: string): Element[] {
  return Array.from(bloc.querySelectorAll(FEUILLES)).filter(
    (e) => !e.classList.contains(classeCale) && !e.closest(`.${classeCale}`),
  );
}

/** La feuille (le bloc le plus profond) qui contient `noeud`, sans dépasser `bloc`. */
function feuilleDe(noeud: Node, bloc: Element, feuilles: Element[]): Element | null {
  let courant: Node | null = noeud;
  while (courant && courant !== bloc) {
    if (courant instanceof Element && feuilles.includes(courant)) return courant;
    courant = courant.parentNode;
  }
  return null;
}

export function ouEstLeCaret(editor: HTMLElement, classeCale: string): PlaceDuCaret | null {
  const doc = editor.ownerDocument;
  const selection = doc.getSelection();
  if (!selection || selection.rangeCount === 0) return null;
  const plage = selection.getRangeAt(0);
  if (!editor.contains(plage.startContainer)) return null;
  const blocs = Array.from(editor.children).filter((e) => !e.classList.contains(classeCale));
  for (let i = 0; i < blocs.length; i += 1) {
    if (!blocs[i].contains(plage.startContainer)) continue;
    const feuilles = feuillesDe(blocs[i], classeCale);
    const feuille = feuilleDe(plage.startContainer, blocs[i], feuilles);
    const repere = feuille ?? blocs[i];
    const avant = doc.createRange();
    avant.selectNodeContents(repere);
    avant.setEnd(plage.startContainer, plage.startOffset);
    return { bloc: i, feuille: feuille ? feuilles.indexOf(feuille) : -1, rang: avant.toString().length };
  }
  return null;
}

export function remettreLeCaret(editor: HTMLElement, place: PlaceDuCaret | null, classeCale: string): void {
  if (!place) return;
  const doc = editor.ownerDocument;
  const blocs = Array.from(editor.children).filter((e) => !e.classList.contains(classeCale));
  const bloc = blocs[place.bloc];
  if (!bloc) return;
  const repere = place.feuille >= 0 ? (feuillesDe(bloc, classeCale)[place.feuille] ?? bloc) : bloc;
  const poser = (noeud: Node, offset: number) => {
    const plage = doc.createRange();
    plage.setStart(noeud, offset);
    plage.collapse(true);
    const selection = doc.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(plage);
  };
  const marcheur = doc.createTreeWalker(repere, NodeFilter.SHOW_TEXT);
  let reste = place.rang;
  let noeud = marcheur.nextNode() as Text | null;
  let dernier: Text | null = null;
  while (noeud) {
    // Le texte d'une cale ne compte pas : elle est vide, mais un futur
    // contenu décalerait le rang sans que personne ne s'en aperçoive.
    const dansUneCale = (noeud.parentElement as HTMLElement | null)?.closest(`.${classeCale}`);
    if (!dansUneCale) {
      if (reste <= noeud.data.length) {
        poser(noeud, reste);
        return;
      }
      reste -= noeud.data.length;
      dernier = noeud;
    }
    noeud = marcheur.nextNode() as Text | null;
  }
  // Pas de texte (une puce vide, « <li><br></li> ») ou rang au-delà : au
  // début de la feuille, ou après son dernier texte.
  if (dernier) poser(dernier, dernier.data.length);
  else poser(repere, 0);
}
