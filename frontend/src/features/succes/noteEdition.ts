// L'édition des blocs d'une note — listes, séparateur, titres, citation,
// code, tableau — par manipulation directe du DOM, et non par `execCommand`.
//
// Le 13 septembre 2026, un banc WebKit (le moteur de l'app) piloté par de
// vraies touches a montré ce que `execCommand` fait vraiment :
//   - `insertOrderedList` sur « <p>un</p> » produit « <p><ol><li>un… » — la
//     liste À L'INTÉRIEUR du paragraphe, HTML invalide — et Entrée dans cette
//     liste ne crée plus d'élément : « deux » et « para » finissent collés
//     dans le même <li> ;
//   - `insertHorizontalRule` pose le <hr> sans bloc après lui : ce qu'on tape
//     ensuite est du texte nu, et aucune flèche ne permet de « passer
//     dessous » ;
//   - `formatBlock blockquote` / `pre` : chaque Entrée ouvre un NOUVEAU
//     <blockquote> ou <pre>, et rien ne permet d'en sortir ;
//   - `insertHTML <table>` laisse le curseur APRÈS le tableau, et Tab fait
//     sortir le focus de l'éditeur.
// Le même banc reproduit tout cela dans un contenteditable nu : ce sont des
// comportements de WebKit, pas de l'app. Ici, chaque geste est écrit, et
// vérifiable sous jsdom.

const BLOCS = new Set([
  'P',
  'DIV',
  'H1',
  'H2',
  'H3',
  'H4',
  'H5',
  'H6',
  'LI',
  'PRE',
  'BLOCKQUOTE',
  'TD',
  'TH',
]);

/** Le bloc le plus proche qui contient `noeud`, sans remonter jusqu'à la racine. */
export function blocDe(noeud: Node | null, racine: HTMLElement): HTMLElement | null {
  let courant: Node | null = noeud;
  while (courant && courant !== racine) {
    if (courant instanceof HTMLElement && BLOCS.has(courant.tagName)) return courant;
    courant = courant.parentNode;
  }
  return null;
}

/** Le bloc de PREMIER niveau (enfant direct de la racine) qui contient `noeud`. */
function blocDePremierNiveau(noeud: Node | null, racine: HTMLElement): HTMLElement | null {
  let courant: Node | null = noeud;
  while (courant && courant.parentNode !== racine) courant = courant.parentNode;
  return courant instanceof HTMLElement ? courant : null;
}

function selectionDans(racine: HTMLElement): Range | null {
  const s = racine.ownerDocument.getSelection();
  if (!s || s.rangeCount === 0) return null;
  const r = s.getRangeAt(0);
  return racine.contains(r.startContainer) ? r : null;
}

/** Pose le caret au début (ou à la fin) d'un nœud. */
export function placerCaret(noeud: Node, fin = false): void {
  const doc = noeud.ownerDocument ?? document;
  const r = doc.createRange();
  if (noeud.nodeType === Node.TEXT_NODE) {
    r.setStart(noeud, fin ? (noeud.textContent ?? '').length : 0);
  } else if (noeud.firstChild && noeud.firstChild.nodeName === 'BR' && !fin) {
    r.setStart(noeud, 0);
  } else {
    r.selectNodeContents(noeud);
    r.collapse(!fin);
  }
  r.collapse(true);
  const s = doc.getSelection();
  if (!s) return;
  s.removeAllRanges();
  s.addRange(r);
}

function paragrapheVide(doc: Document): HTMLElement {
  const p = doc.createElement('p');
  p.appendChild(doc.createElement('br'));
  return p;
}

function estVide(bloc: HTMLElement): boolean {
  return (bloc.textContent ?? '').replace(/\u200B/g, '').trim() === '' && !bloc.querySelector('img, table, hr');
}

/**
 * Coupe `bloc` au caret : ce qui suit part dans un nouveau bloc de même
 * balise, inséré juste après. Rend ce nouveau bloc (vide : un <br>).
 */
export function couperLeBloc(bloc: HTMLElement, caret: Range): HTMLElement {
  const doc = bloc.ownerDocument;
  const apres = doc.createRange();
  apres.setStart(caret.startContainer, caret.startOffset);
  apres.setEnd(bloc, bloc.childNodes.length);
  const reste = apres.extractContents();
  const nouveau = doc.createElement(bloc.tagName);
  nouveau.appendChild(reste);
  // Un <br> de fin de ligne laissé derrière par le navigateur ne compte pas
  // comme contenu ; un bloc sans rien dedans n'a pas de hauteur, d'où le <br>.
  if (estVide(nouveau) && !nouveau.querySelector('br')) nouveau.appendChild(doc.createElement('br'));
  if (estVide(bloc) && !bloc.querySelector('br')) bloc.appendChild(doc.createElement('br'));
  bloc.after(nouveau);
  return nouveau;
}

/** Le caret est-il à la toute fin de `bloc` (rien de visible après lui) ? */
export function caretEnFin(bloc: HTMLElement, caret: Range): boolean {
  const apres = bloc.ownerDocument.createRange();
  apres.setStart(caret.startContainer, caret.startOffset);
  apres.setEnd(bloc, bloc.childNodes.length);
  const contenu = apres.cloneContents();
  return (contenu.textContent ?? '').length === 0 && !contenu.querySelector('img, table, hr');
}

/** Le caret est-il au tout début de `bloc` ? */
export function caretAuDebut(bloc: HTMLElement, caret: Range): boolean {
  const avant = bloc.ownerDocument.createRange();
  avant.setStart(bloc, 0);
  avant.setEnd(caret.startContainer, caret.startOffset);
  const contenu = avant.cloneContents();
  return (contenu.textContent ?? '').length === 0 && !contenu.querySelector('img, table, hr, br');
}

/**
 * Le bloc qui porte le caret. À la racine, entre deux blocs (c'est là que
 * WebKit pose le caret après une flèche autour d'un <hr>), on s'accroche au
 * bloc d'avant — ou d'après — et le caret y descend. Du texte nu à la
 * racine est enveloppé dans un <p>.
 */
function blocCourant(racine: HTMLElement, caret: Range): HTMLElement {
  const bloc = blocDe(caret.startContainer, racine);
  if (bloc) return bloc;
  const doc = racine.ownerDocument;
  if (caret.startContainer === racine) {
    const avant = racine.childNodes[caret.startOffset - 1] ?? null;
    const apres = racine.childNodes[caret.startOffset] ?? null;
    const estBloc = (n: Node | null): n is HTMLElement => n instanceof HTMLElement && BLOCS.has(n.tagName);
    if (estBloc(avant)) {
      placerCaret(avant, true);
      return avant;
    }
    if (estBloc(apres)) {
      placerCaret(apres);
      return apres;
    }
    const noeud = apres ?? avant;
    const p = doc.createElement('p');
    if (noeud && noeud.nodeType === Node.TEXT_NODE) {
      racine.insertBefore(p, noeud);
      p.appendChild(noeud);
      placerCaret(noeud, noeud === avant);
    } else {
      p.appendChild(doc.createElement('br'));
      if (apres) racine.insertBefore(p, apres);
      else racine.appendChild(p);
      placerCaret(p);
    }
    return p;
  }
  // Un nœud texte (ou inline) directement sous la racine.
  let haut: Node = caret.startContainer;
  while (haut.parentNode && haut.parentNode !== racine) haut = haut.parentNode;
  const p = doc.createElement('p');
  racine.insertBefore(p, haut);
  p.appendChild(haut);
  return p;
}

/**
 * Enveloppe dans un <p> tout texte (ou inline) posé directement sous la
 * racine — ce que laisse une frappe quand WebKit a mis le caret entre deux
 * blocs. Les plages de sélection suivent le nœud déplacé : le caret ne bouge
 * pas. Rend le nombre de blocs créés.
 */
export function envelopperLeTexteNu(racine: HTMLElement): number {
  const doc = racine.ownerDocument;
  // Déplacer un nœud rejette hors de lui toute plage qui y était (c'est la
  // règle du DOM) : on note le caret, on le reposera au même endroit.
  const selection = doc.getSelection();
  const memo =
    selection && selection.rangeCount > 0
      ? { noeud: selection.getRangeAt(0).startContainer, offset: selection.getRangeAt(0).startOffset }
      : null;
  let crees = 0;
  let p: HTMLElement | null = null;
  for (const enfant of Array.from(racine.childNodes)) {
    const bloc =
      enfant instanceof HTMLElement && (BLOCS.has(enfant.tagName) || ['HR', 'TABLE', 'UL', 'OL', 'IMG'].includes(enfant.tagName));
    const vide = enfant.nodeType === Node.TEXT_NODE && (enfant.textContent ?? '') === '';
    if (bloc || (enfant instanceof HTMLElement && enfant.contentEditable === 'false')) {
      p = null;
      continue;
    }
    if (vide) continue;
    if (enfant.nodeName === 'BR' && p) {
      enfant.remove();
      p = null;
      continue;
    }
    if (!p) {
      p = doc.createElement('p');
      racine.insertBefore(p, enfant);
      crees += 1;
    }
    p.appendChild(enfant);
  }
  if (crees > 0 && memo && racine.contains(memo.noeud)) {
    const r = doc.createRange();
    r.setStart(memo.noeud, Math.min(memo.offset, memo.noeud.nodeType === Node.TEXT_NODE ? (memo.noeud.textContent ?? '').length : memo.noeud.childNodes.length));
    r.collapse(true);
    selection?.removeAllRanges();
    selection?.addRange(r);
  }
  return crees;
}

// ---------------------------------------------------------------------------
// Séparateur
// ---------------------------------------------------------------------------

/**
 * Un trait, et TOUJOURS un paragraphe après lui, où le caret atterrit. Au
 * milieu d'un bloc, ce qui suit le caret descend sous le trait.
 */
export function insererSeparateur(racine: HTMLElement): boolean {
  const caret = selectionDans(racine);
  if (!caret) return false;
  const doc = racine.ownerDocument;
  const bloc = blocCourant(racine, caret);
  const haut = blocDePremierNiveau(bloc, racine) ?? bloc;
  const hr = doc.createElement('hr');
  let suivant: HTMLElement;
  if (caretEnFin(bloc, caret)) {
    suivant = paragrapheVide(doc);
    haut.after(hr, suivant);
  } else if (caretAuDebut(bloc, caret)) {
    haut.before(hr);
    suivant = bloc;
  } else {
    suivant = couperLeBloc(bloc, caret);
    // Coupé dans un bloc imbriqué (li, td) : on ne déplace pas hors de son
    // conteneur ; le trait se pose entre les deux moitiés.
    suivant.before(hr);
  }
  placerCaret(suivant);
  return true;
}

// ---------------------------------------------------------------------------
// Listes
// ---------------------------------------------------------------------------

/** Le <li> qui contient le caret, s'il y en a un. */
function elementDeListe(noeud: Node | null, racine: HTMLElement): HTMLLIElement | null {
  let courant: Node | null = noeud;
  while (courant && courant !== racine) {
    if (courant instanceof HTMLLIElement) return courant;
    courant = courant.parentNode;
  }
  return null;
}

/** Sort `li` de sa liste : il devient un <p> après la liste (coupée s'il faut). */
function sortirDeLaListe(li: HTMLLIElement, racine: HTMLElement): HTMLElement {
  const doc = racine.ownerDocument;
  const liste = li.parentElement as HTMLElement;
  const p = doc.createElement('p');
  while (li.firstChild) p.appendChild(li.firstChild);
  if (estVide(p) && !p.querySelector('br')) p.appendChild(doc.createElement('br'));
  // Ce qui suit dans la liste part dans une seconde liste, après le paragraphe.
  const suite = doc.createElement(liste.tagName);
  let frere = li.nextSibling;
  while (frere) {
    const prochain = frere.nextSibling;
    suite.appendChild(frere);
    frere = prochain;
  }
  li.remove();
  liste.after(p);
  if (suite.childNodes.length > 0) p.after(suite);
  if (liste.childNodes.length === 0) liste.remove();
  return p;
}

/**
 * Bascule le bloc du caret en élément d'une liste (`OL` ou `UL`) — ou l'en
 * sort s'il y est déjà dans une liste du même type. Une liste d'un autre type
 * change de type.
 */
export function basculerListe(racine: HTMLElement, type: 'OL' | 'UL'): boolean {
  const caret = selectionDans(racine);
  if (!caret) return false;
  const doc = racine.ownerDocument;
  const li = elementDeListe(caret.startContainer, racine);
  if (li) {
    const liste = li.parentElement as HTMLElement;
    if (liste.tagName === type) {
      const p = sortirDeLaListe(li, racine);
      placerCaret(p, true);
    } else {
      const autre = doc.createElement(type);
      while (liste.firstChild) autre.appendChild(liste.firstChild);
      liste.replaceWith(autre);
      placerCaret(li, true);
    }
    return true;
  }
  const bloc = blocCourant(racine, caret);
  const haut = blocDePremierNiveau(bloc, racine) ?? bloc;
  const nouveau = doc.createElement('li');
  while (bloc.firstChild) nouveau.appendChild(bloc.firstChild);
  if (estVide(nouveau) && !nouveau.querySelector('br')) nouveau.appendChild(doc.createElement('br'));
  // Collé à une liste voisine du même type : on la rejoint plutôt que d'en
  // ouvrir une seconde, sinon la numérotation repart à 1.
  const precedent = haut.previousElementSibling;
  const suivant = haut.nextElementSibling;
  if (precedent && precedent.tagName === type) {
    precedent.appendChild(nouveau);
    haut.remove();
  } else if (suivant && suivant.tagName === type) {
    suivant.insertBefore(nouveau, suivant.firstChild);
    haut.remove();
  } else {
    const liste = doc.createElement(type);
    liste.appendChild(nouveau);
    haut.replaceWith(liste);
  }
  placerCaret(nouveau, true);
  return true;
}

/**
 * Entrée dans une liste : un <li> vide → on sort de la liste ; sinon, ce qui
 * suit le caret devient le <li> suivant. Rend `false` si le caret n'est pas
 * dans une liste (le navigateur fait alors son travail).
 */
export function entreeDansListe(racine: HTMLElement): boolean {
  const caret = selectionDans(racine);
  if (!caret) return false;
  const li = elementDeListe(caret.startContainer, racine);
  if (!li) return false;
  if (!caret.collapsed) caret.deleteContents();
  if (estVide(li)) {
    const p = sortirDeLaListe(li, racine);
    placerCaret(p);
    return true;
  }
  const nouveau = couperLeBloc(li, caret);
  placerCaret(nouveau);
  return true;
}

// ---------------------------------------------------------------------------
// Titres
// ---------------------------------------------------------------------------

/**
 * Entrée à la fin d'un titre : la ligne suivante est un paragraphe. Le
 * navigateur, lui, ouvre un <div> — ni titre ni paragraphe, et le bouton
 * « Paragraphe » n'y change rien puisqu'il croit y être déjà.
 */
export function entreeDansTitre(racine: HTMLElement): boolean {
  const caret = selectionDans(racine);
  if (!caret || !caret.collapsed) return false;
  const bloc = blocDe(caret.startContainer, racine);
  if (!bloc || !/^H[1-6]$/.test(bloc.tagName)) return false;
  if (caretEnFin(bloc, caret)) {
    const p = paragrapheVide(racine.ownerDocument);
    bloc.after(p);
    placerCaret(p);
    return true;
  }
  if (caretAuDebut(bloc, caret)) {
    bloc.before(paragrapheVide(racine.ownerDocument));
    return true;
  }
  const suite = couperLeBloc(bloc, caret);
  placerCaret(suite);
  return true;
}

// ---------------------------------------------------------------------------
// Citation
// ---------------------------------------------------------------------------

function citationDe(noeud: Node | null, racine: HTMLElement): HTMLQuoteElement | null {
  let courant: Node | null = noeud;
  while (courant && courant !== racine) {
    if (courant instanceof HTMLElement && courant.tagName === 'BLOCKQUOTE') return courant as HTMLQuoteElement;
    courant = courant.parentNode;
  }
  return null;
}

/** Les paragraphes d'une citation : du texte nu dedans est enveloppé d'abord. */
function normaliserCitation(citation: HTMLElement): void {
  const doc = citation.ownerDocument;
  let p: HTMLElement | null = null;
  for (const enfant of Array.from(citation.childNodes)) {
    const bloc = enfant instanceof HTMLElement && BLOCS.has(enfant.tagName);
    if (bloc) {
      p = null;
      continue;
    }
    if (enfant.nodeName === 'BR' && p) {
      enfant.remove();
      p = null;
      continue;
    }
    if (!p) {
      p = doc.createElement('p');
      citation.insertBefore(p, enfant);
    }
    p.appendChild(enfant);
  }
}

/** Bascule le bloc du caret en citation, ou sort de la citation où il est. */
export function basculerCitation(racine: HTMLElement): boolean {
  const caret = selectionDans(racine);
  if (!caret) return false;
  const doc = racine.ownerDocument;
  const citation = citationDe(caret.startContainer, racine);
  if (citation) {
    normaliserCitation(citation);
    const bloc = blocDe(caret.startContainer, racine);
    const cible = bloc && citation.contains(bloc) && bloc !== citation ? bloc : (citation.firstElementChild as HTMLElement | null);
    if (!cible) return false;
    // On sort SEULEMENT le bloc du caret ; ce qui le suit reste cité, dans une
    // seconde citation.
    const suite = doc.createElement('blockquote');
    let frere = cible.nextSibling;
    while (frere) {
      const prochain = frere.nextSibling;
      suite.appendChild(frere);
      frere = prochain;
    }
    citation.after(cible);
    if (suite.childNodes.length > 0) cible.after(suite);
    if (citation.childNodes.length === 0) citation.remove();
    placerCaret(cible, true);
    return true;
  }
  const bloc = blocCourant(racine, caret);
  const haut = blocDePremierNiveau(bloc, racine) ?? bloc;
  const nouvelle = doc.createElement('blockquote');
  haut.replaceWith(nouvelle);
  nouvelle.appendChild(haut);
  placerCaret(bloc, true);
  return true;
}

/**
 * Entrée dans une citation : un paragraphe vide → on sort ; sinon un nouveau
 * paragraphe DANS la citation (le navigateur ouvrait une seconde citation).
 */
export function entreeDansCitation(racine: HTMLElement): boolean {
  const caret = selectionDans(racine);
  if (!caret) return false;
  const citation = citationDe(caret.startContainer, racine);
  if (!citation) return false;
  if (elementDeListe(caret.startContainer, citation)) return false;
  normaliserCitation(citation);
  if (!caret.collapsed) caret.deleteContents();
  const bloc = blocDe(caret.startContainer, citation) ?? (citation.firstElementChild as HTMLElement | null);
  if (!bloc || bloc === citation) return false;
  if (estVide(bloc)) {
    const suite = racine.ownerDocument.createElement('blockquote');
    let frere = bloc.nextSibling;
    while (frere) {
      const prochain = frere.nextSibling;
      suite.appendChild(frere);
      frere = prochain;
    }
    const p = paragrapheVide(racine.ownerDocument);
    bloc.remove();
    citation.after(p);
    if (suite.childNodes.length > 0) p.after(suite);
    if (citation.childNodes.length === 0) citation.remove();
    placerCaret(p);
    return true;
  }
  const nouveau = couperLeBloc(bloc, caret);
  placerCaret(nouveau);
  return true;
}

// ---------------------------------------------------------------------------
// Code
// ---------------------------------------------------------------------------

function codeDe(noeud: Node | null, racine: HTMLElement): HTMLPreElement | null {
  let courant: Node | null = noeud;
  while (courant && courant !== racine) {
    if (courant instanceof HTMLPreElement) return courant;
    courant = courant.parentNode;
  }
  return null;
}

/** Bascule le bloc du caret en bloc de code, ou le bloc de code en paragraphe. */
export function basculerCode(racine: HTMLElement): boolean {
  const caret = selectionDans(racine);
  if (!caret) return false;
  const doc = racine.ownerDocument;
  const pre = codeDe(caret.startContainer, racine);
  if (pre) {
    // Chaque ligne du code redevient un paragraphe.
    const lignes = (pre.textContent ?? '').replace(/\n$/, '').split('\n');
    const paragraphes = lignes.map((l) => {
      const p = doc.createElement('p');
      if (l === '') p.appendChild(doc.createElement('br'));
      else p.textContent = l;
      return p;
    });
    pre.replaceWith(...paragraphes);
    placerCaret(paragraphes[paragraphes.length - 1], true);
    return true;
  }
  const bloc = blocCourant(racine, caret);
  const haut = blocDePremierNiveau(bloc, racine) ?? bloc;
  const nouveau = doc.createElement('pre');
  nouveau.textContent = (haut.textContent ?? '').replace(/ /g, ' ');
  if (nouveau.textContent === '') nouveau.appendChild(doc.createElement('br'));
  haut.replaceWith(nouveau);
  placerCaret(nouveau, true);
  return true;
}

/**
 * Entrée dans un bloc de code : un retour à la ligne DANS le bloc. Deux
 * Entrée de suite en fin de bloc (une ligne vide) : on sort.
 */
export function entreeDansCode(racine: HTMLElement): boolean {
  const caret = selectionDans(racine);
  if (!caret) return false;
  const pre = codeDe(caret.startContainer, racine);
  if (!pre) return false;
  if (!caret.collapsed) caret.deleteContents();
  const doc = racine.ownerDocument;
  const avant = doc.createRange();
  avant.setStart(pre, 0);
  avant.setEnd(caret.startContainer, caret.startOffset);
  const apres = doc.createRange();
  apres.setStart(caret.startContainer, caret.startOffset);
  apres.setEnd(pre, pre.childNodes.length);
  const texteAvant = avant.cloneContents().textContent ?? '';
  const texteApres = apres.cloneContents().textContent ?? '';
  // Sur une ligne vide en fin de bloc (la précédente Entrée l'a ouverte) :
  // on retire cette ligne et on sort dans un paragraphe.
  if (/\n$/.test(texteAvant) && texteApres.replace(/\n/g, '') === '') {
    apres.deleteContents();
    const dernier = pre.lastChild;
    if (dernier && dernier.nodeType === Node.TEXT_NODE) {
      dernier.textContent = (dernier.textContent ?? '').replace(/\n$/, '');
      if (dernier.textContent === '') dernier.remove();
    }
    if (!pre.firstChild) pre.appendChild(doc.createElement('br'));
    const p = paragrapheVide(doc);
    pre.after(p);
    placerCaret(p);
    return true;
  }
  // Un <br> laissé par le navigateur ne se comporte pas comme un « \\n » dans
  // un <pre> ; on n'écrit que du texte. En toute fin de bloc, un « \\n » seul
  // n'a pas de hauteur : on en ajoute un second, invisible, que la frappe
  // suivante consommera — ou que la prochaine Entrée lira comme « sortir ».
  const enFin = texteApres === '';
  const texte = doc.createTextNode(enFin ? '\n\n' : '\n');
  caret.insertNode(texte);
  const c = doc.createRange();
  c.setStart(texte, 1);
  c.collapse(true);
  const s = doc.getSelection();
  s?.removeAllRanges();
  s?.addRange(c);
  return true;
}

// ---------------------------------------------------------------------------
// Tableau
// ---------------------------------------------------------------------------

/** Insère un tableau après le bloc du caret et pose le caret dans sa première case. */
export function insererTableau(racine: HTMLElement, lignes: number, colonnes: number): boolean {
  const caret = selectionDans(racine);
  if (!caret) return false;
  const doc = racine.ownerDocument;
  const table = doc.createElement('table');
  const corps = doc.createElement('tbody');
  for (let i = 0; i < lignes; i += 1) {
    const tr = doc.createElement('tr');
    for (let j = 0; j < colonnes; j += 1) {
      const td = doc.createElement('td');
      td.appendChild(doc.createElement('br'));
      tr.appendChild(td);
    }
    corps.appendChild(tr);
  }
  table.appendChild(corps);
  const bloc = blocCourant(racine, caret);
  const haut = blocDePremierNiveau(bloc, racine) ?? bloc;
  const apres = paragrapheVide(doc);
  if (estVide(haut) && haut.tagName === 'P') {
    haut.replaceWith(table, apres);
  } else {
    haut.after(table, apres);
  }
  placerCaret(table.querySelector('td') as HTMLElement);
  return true;
}

function celluleDe(noeud: Node | null, racine: HTMLElement): HTMLTableCellElement | null {
  let courant: Node | null = noeud;
  while (courant && courant !== racine) {
    if (courant instanceof HTMLTableCellElement) return courant;
    courant = courant.parentNode;
  }
  return null;
}

/**
 * Tab dans un tableau : la case suivante (Maj : la précédente). Sur la
 * dernière case, Tab ajoute une ligne — comme dans Word. Rend `false` hors
 * d'un tableau ; le navigateur, lui, faisait sortir le focus de la note.
 */
export function tabDansTableau(racine: HTMLElement, arriere: boolean): boolean {
  const caret = selectionDans(racine);
  if (!caret) return false;
  const cellule = celluleDe(caret.startContainer, racine);
  if (!cellule) return false;
  const table = cellule.closest('table');
  if (!table) return false;
  const cellules = Array.from(table.querySelectorAll<HTMLTableCellElement>('td, th'));
  const index = cellules.indexOf(cellule);
  let cible: HTMLTableCellElement | null = null;
  if (arriere) {
    cible = cellules[index - 1] ?? null;
  } else if (index + 1 < cellules.length) {
    cible = cellules[index + 1];
  } else {
    const ligne = cellule.closest('tr');
    if (!ligne) return false;
    const nouvelle = ligne.cloneNode(false) as HTMLTableRowElement;
    for (let i = 0; i < ligne.cells.length; i += 1) {
      const td = racine.ownerDocument.createElement(ligne.cells[i].tagName === 'TH' ? 'td' : ligne.cells[i].tagName);
      td.appendChild(racine.ownerDocument.createElement('br'));
      nouvelle.appendChild(td);
    }
    ligne.after(nouvelle);
    cible = nouvelle.cells[0];
  }
  if (!cible) return true;
  const r = racine.ownerDocument.createRange();
  r.selectNodeContents(cible);
  const s = racine.ownerDocument.getSelection();
  s?.removeAllRanges();
  s?.addRange(r);
  return true;
}

// ---------------------------------------------------------------------------
// Le clavier
// ---------------------------------------------------------------------------

/**
 * Ce que l'éditeur fait lui-même sur une touche. Rend `true` quand la touche
 * a été consommée (l'appelant fait `preventDefault`), `false` pour laisser le
 * navigateur agir.
 */
export function toucheDansLaNote(
  racine: HTMLElement,
  touche: { key: string; shiftKey: boolean; metaKey: boolean; ctrlKey: boolean; altKey: boolean },
): boolean {
  if (touche.metaKey || touche.ctrlKey || touche.altKey) return false;
  if (touche.key === 'Tab') return tabDansTableau(racine, touche.shiftKey);
  if (touche.key === 'Enter' && !touche.shiftKey) {
    return entreeDansCode(racine) || entreeDansListe(racine) || entreeDansCitation(racine) || entreeDansTitre(racine);
  }
  return false;
}
