// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from 'vitest';

import {
  basculerCitation,
  basculerCode,
  basculerListe,
  entreeDansCitation,
  entreeDansCode,
  entreeDansListe,
  entreeDansTitre,
  insererSeparateur,
  insererTableau,
  tabDansTableau,
  toucheDansLaNote,
} from './noteEdition';

let racine: HTMLElement;

/** Pose le contenu et le caret : `|` marque le caret dans un nœud texte. */
const SENTINELLE = '\u2063';
function poser(html: string) {
  racine.innerHTML = html.replace('|', SENTINELLE);
  const marcheur = document.createTreeWalker(racine, NodeFilter.SHOW_TEXT);
  let noeud = marcheur.nextNode();
  while (noeud && !(noeud.textContent ?? '').includes(SENTINELLE)) noeud = marcheur.nextNode();
  const s = window.getSelection()!;
  s.removeAllRanges();
  const r = document.createRange();
  if (noeud) {
    const i = (noeud.textContent ?? '').indexOf(SENTINELLE);
    noeud.textContent = (noeud.textContent ?? '').replace(SENTINELLE, '');
    if (noeud.textContent === '') {
      // Marqueur seul dans un bloc : le caret se pose dans le bloc, vide.
      const parent = noeud.parentElement!;
      parent.removeChild(noeud);
      if (!parent.firstChild) parent.appendChild(document.createElement('br'));
      r.setStart(parent, 0);
    } else {
      r.setStart(noeud, i);
    }
  } else {
    r.selectNodeContents(racine);
    r.collapse(false);
  }
  r.collapse(true);
  s.addRange(r);
}

/** Le HTML, avec `|` là où est le caret. */
function lire(): string {
  const s = window.getSelection()!;
  const r = s.getRangeAt(0);
  const marque = document.createTextNode('|');
  r.insertNode(marque);
  const html = racine.innerHTML;
  marque.remove();
  racine.normalize();
  return html;
}

const ENTREE = { key: 'Enter', shiftKey: false, metaKey: false, ctrlKey: false, altKey: false };
const TAB = { key: 'Tab', shiftKey: false, metaKey: false, ctrlKey: false, altKey: false };

beforeEach(() => {
  document.body.innerHTML = '<div id="r" contenteditable="true"></div>';
  racine = document.getElementById('r')!;
});

describe('le séparateur', () => {
  it('pose un paragraphe sous le trait, caret dedans, quand on est en fin de bloc', () => {
    poser('<p>texte|</p>');
    expect(insererSeparateur(racine)).toBe(true);
    expect(lire()).toBe('<p>texte</p><hr><p>|<br></p>');
  });
  it('descend la suite du bloc sous le trait quand on est au milieu', () => {
    poser('<p>ab|cd</p>');
    insererSeparateur(racine);
    expect(lire()).toBe('<p>ab</p><hr><p>|cd</p>');
  });
  it('pose le trait avant le bloc quand on est à son début', () => {
    poser('<p>|texte</p>');
    insererSeparateur(racine);
    expect(lire()).toBe('<hr><p>|texte</p>');
  });
  it('enveloppe du texte nu dans un paragraphe avant de couper', () => {
    poser('texte|');
    insererSeparateur(racine);
    expect(lire()).toBe('<p>texte</p><hr><p>|<br></p>');
  });
});

describe('les listes', () => {
  it('transforme le paragraphe en liste numérotée — à côté du <p>, jamais dedans', () => {
    poser('<p>un|</p>');
    basculerListe(racine, 'OL');
    expect(lire()).toBe('<ol><li>un|</li></ol>');
  });
  it('Entrée crée l’élément suivant, Entrée sur un élément vide sort de la liste', () => {
    poser('<ol><li>un|</li></ol>');
    expect(entreeDansListe(racine)).toBe(true);
    expect(lire()).toBe('<ol><li>un</li><li>|<br></li></ol>');
    racine.querySelector('li:last-child')!.innerHTML = 'deux';
    poser(racine.innerHTML.replace('deux', 'deux|'));
    entreeDansListe(racine);
    expect(lire()).toBe('<ol><li>un</li><li>deux</li><li>|<br></li></ol>');
    entreeDansListe(racine);
    expect(lire()).toBe('<ol><li>un</li><li>deux</li></ol><p>|<br></p>');
  });
  it('Entrée au milieu d’un élément coupe l’élément en deux', () => {
    poser('<ul><li>ab|cd</li></ul>');
    entreeDansListe(racine);
    expect(lire()).toBe('<ul><li>ab</li><li>|cd</li></ul>');
  });
  it('sortir d’un élément au milieu de la liste la coupe en deux listes', () => {
    poser('<ol><li>un</li><li>|<br></li><li>trois</li></ol>');
    entreeDansListe(racine);
    expect(lire()).toBe('<ol><li>un</li></ol><p>|<br></p><ol><li>trois</li></ol>');
  });
  it('re-cliquer sur le même type retire la liste ; l’autre type la convertit', () => {
    poser('<ol><li>un|</li></ol>');
    basculerListe(racine, 'OL');
    expect(lire()).toBe('<p>un|</p>');
    poser('<ol><li>un|</li></ol>');
    basculerListe(racine, 'UL');
    expect(lire()).toBe('<ul><li>un|</li></ul>');
  });
  it('rejoint une liste voisine du même type au lieu de repartir à 1', () => {
    poser('<ol><li>un</li></ol><p>deux|</p>');
    basculerListe(racine, 'OL');
    expect(lire()).toBe('<ol><li>un</li><li>deux|</li></ol>');
  });
  it('ne s’occupe pas d’une Entrée hors liste', () => {
    poser('<p>texte|</p>');
    expect(entreeDansListe(racine)).toBe(false);
  });
});

describe('les titres', () => {
  it('Entrée en fin de titre ouvre un paragraphe, pas un <div>', () => {
    poser('<h1>Titre|</h1>');
    expect(entreeDansTitre(racine)).toBe(true);
    expect(lire()).toBe('<h1>Titre</h1><p>|<br></p>');
  });
  it('Entrée au milieu d’un titre le coupe en deux titres', () => {
    poser('<h2>ab|cd</h2>');
    entreeDansTitre(racine);
    expect(lire()).toBe('<h2>ab</h2><h2>|cd</h2>');
  });
});

describe('la citation', () => {
  it('bascule le paragraphe en citation, et l’en sort au second clic', () => {
    poser('<p>cité|</p>');
    basculerCitation(racine);
    expect(lire()).toBe('<blockquote><p>cité|</p></blockquote>');
    basculerCitation(racine);
    expect(lire()).toBe('<p>cité|</p>');
  });
  it('Entrée reste DANS la citation ; Entrée sur une ligne vide en sort', () => {
    poser('<blockquote><p>cité|</p></blockquote>');
    entreeDansCitation(racine);
    expect(lire()).toBe('<blockquote><p>cité</p><p>|<br></p></blockquote>');
    entreeDansCitation(racine);
    expect(lire()).toBe('<blockquote><p>cité</p></blockquote><p>|<br></p>');
  });
  it('du texte nu dans la citation (venu d’execCommand) est d’abord mis en paragraphe', () => {
    poser('<blockquote>cité|</blockquote>');
    entreeDansCitation(racine);
    expect(lire()).toBe('<blockquote><p>cité</p><p>|<br></p></blockquote>');
  });
});

describe('le code', () => {
  it('bascule le paragraphe en bloc de code et retour', () => {
    poser('<p>a = 1|</p>');
    basculerCode(racine);
    expect(lire()).toBe('<pre>a = 1|</pre>');
    basculerCode(racine);
    expect(lire()).toBe('<p>a = 1|</p>');
  });
  it('Entrée écrit un retour à la ligne dans le bloc ; deux Entrée en fin sortent', () => {
    poser('<pre>a = 1|</pre>');
    entreeDansCode(racine);
    expect(racine.innerHTML).toBe('<pre>a = 1\n\n</pre>');
    // La seconde ligne, tapée : on simule la frappe qui consomme le \\n de réserve.
    poser('<pre>a = 1\nb = 2|</pre>');
    entreeDansCode(racine);
    expect(racine.innerHTML).toBe('<pre>a = 1\nb = 2\n\n</pre>');
    entreeDansCode(racine);
    expect(lire()).toBe('<pre>a = 1\nb = 2</pre><p>|<br></p>');
  });
  it('un bloc de code de trois lignes redevient trois paragraphes', () => {
    poser('<pre>a\nb\nc|</pre>');
    basculerCode(racine);
    expect(lire()).toBe('<p>a</p><p>b</p><p>c|</p>');
  });
});

describe('le tableau', () => {
  it('s’insère après le bloc, caret dans la première case, un paragraphe après', () => {
    poser('<p>avant|</p>');
    insererTableau(racine, 2, 2);
    expect(lire()).toBe(
      '<p>avant</p><table><tbody><tr><td>|<br></td><td><br></td></tr><tr><td><br></td><td><br></td></tr></tbody></table><p><br></p>',
    );
  });
  it('remplace un paragraphe vide au lieu d’en laisser un au-dessus', () => {
    poser('<p>|</p>');
    insererTableau(racine, 1, 1);
    expect(racine.innerHTML).toBe('<table><tbody><tr><td><br></td></tr></tbody></table><p><br></p>');
  });
  it('Tab passe à la case suivante, Maj+Tab à la précédente, et ajoute une ligne après la dernière', () => {
    poser('<table><tbody><tr><td>a|</td><td>b</td></tr></tbody></table>');
    expect(tabDansTableau(racine, false)).toBe(true);
    expect(window.getSelection()!.toString()).toBe('b');
    expect(tabDansTableau(racine, true)).toBe(true);
    expect(window.getSelection()!.toString()).toBe('a');
    tabDansTableau(racine, false);
    tabDansTableau(racine, false);
    expect(racine.querySelectorAll('tr').length).toBe(2);
    expect(racine.innerHTML).toContain('<tr><td><br></td><td><br></td></tr>');
  });
  it('hors d’un tableau, Tab n’est pas consommé', () => {
    poser('<p>texte|</p>');
    expect(tabDansTableau(racine, false)).toBe(false);
  });
});

describe('le clavier', () => {
  it('Entrée est prise en charge dans une liste, un titre, une citation, un code — et pas ailleurs', () => {
    poser('<ul><li>x|</li></ul>');
    expect(toucheDansLaNote(racine, ENTREE)).toBe(true);
    poser('<p>x|</p>');
    expect(toucheDansLaNote(racine, ENTREE)).toBe(false);
    poser('<p>x|</p>');
    expect(toucheDansLaNote(racine, { ...ENTREE, shiftKey: true })).toBe(false);
    poser('<ul><li>x|</li></ul>');
    expect(toucheDansLaNote(racine, { ...ENTREE, metaKey: true })).toBe(false);
  });
  it('Tab est pris dans un tableau seulement', () => {
    poser('<table><tbody><tr><td>a|</td></tr></tbody></table>');
    expect(toucheDansLaNote(racine, TAB)).toBe(true);
    poser('<p>x|</p>');
    expect(toucheDansLaNote(racine, TAB)).toBe(false);
  });
});

describe('le caret à la racine', () => {
  it('un geste s’accroche au bloc d’avant quand le caret est entre deux blocs', () => {
    racine.innerHTML = '<p>texte</p>';
    const r = document.createRange();
    r.setStart(racine, 1);
    r.collapse(true);
    window.getSelection()!.removeAllRanges();
    window.getSelection()!.addRange(r);
    insererSeparateur(racine);
    expect(lire()).toBe('<p>texte</p><hr><p>|<br></p>');
  });
  it('du texte nu entre deux blocs est enveloppé dans un paragraphe, caret conservé', async () => {
    const { envelopperLeTexteNu } = await import('./noteEdition');
    racine.innerHTML = '<p>a</p>h<hr><p>b</p>';
    const texte = racine.childNodes[1];
    const r = document.createRange();
    r.setStart(texte, 1);
    r.collapse(true);
    window.getSelection()!.removeAllRanges();
    window.getSelection()!.addRange(r);
    expect(envelopperLeTexteNu(racine)).toBe(1);
    expect(lire()).toBe('<p>a</p><p>h|</p><hr><p>b</p>');
    expect(envelopperLeTexteNu(racine)).toBe(0);
  });
});

describe('l’adresse d’un lien', () => {
  it('accepte http(s), complète un domaine nu, refuse le reste', async () => {
    const { adresseDeLien } = await import('./noteEdition');
    expect(adresseDeLien('https://ex.org/a')).toEqual({ url: 'https://ex.org/a' });
    expect(adresseDeLien('  openclassrooms.com/cours ')).toEqual({ url: 'https://openclassrooms.com/cours' });
    expect(adresseDeLien('javascript:alert(1)')).toEqual({ erreur: 'Seules les adresses http:// et https:// sont acceptées.' });
    expect(adresseDeLien('mailto:x@y.z')).toEqual({ erreur: 'Seules les adresses http:// et https:// sont acceptées.' });
    expect(adresseDeLien('')).toEqual({ erreur: 'Indique une adresse.' });
    expect(adresseDeLien('pas une adresse')).toEqual({ erreur: "Cette adresse n'a pas l'air complète." });
  });
});

describe('la mise en forme survit à la ligne', () => {
  it('Entrée dans une puce en fin de <span> de taille : la nouvelle puce naît dans le même span', () => {
    racine.innerHTML = '<ol><li><span style="font-size:24pt">mot</span></li></ol>';
    const t = racine.querySelector('span')!.firstChild!;
    const r = document.createRange();
    r.setStart(t, 3);
    r.collapse(true);
    window.getSelection()!.removeAllRanges();
    window.getSelection()!.addRange(r);
    entreeDansListe(racine);
    expect(lire()).toBe('<ol><li><span style="font-size:24pt">mot</span></li><li><span style="font-size:24pt">|<br></span></li></ol>');
  });
  it('un caret posé juste après une balise de style y rentre avant la frappe', async () => {
    const { entrerDansLeStyleVoisin } = await import('./noteEdition');
    racine.innerHTML = '<p>un <span style="font-size:24pt">mot</span></p>';
    const p = racine.querySelector('p')!;
    const r = document.createRange();
    r.setStart(p, 2);
    r.collapse(true);
    window.getSelection()!.removeAllRanges();
    window.getSelection()!.addRange(r);
    expect(entrerDansLeStyleVoisin(racine)).toBe(true);
    expect(lire()).toBe('<p>un <span style="font-size:24pt">mot|</span></p>');
    // Entre deux textes, il ne bouge pas.
    poser('<p>un| deux</p>');
    expect(entrerDansLeStyleVoisin(racine)).toBe(false);
  });
});
