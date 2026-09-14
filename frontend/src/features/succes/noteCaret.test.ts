// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from 'vitest';

import { ouEstLeCaret, remettreLeCaret } from './noteCaret';

const CALE = 'succes-overflow-gap';
let racine: HTMLElement;

function caretDans(noeud: Node, offset: number) {
  const r = document.createRange();
  r.setStart(noeud, offset);
  r.collapse(true);
  const s = window.getSelection()!;
  s.removeAllRanges();
  s.addRange(r);
}

/** Le HTML avec « | » là où est le caret. */
function lire(): string {
  const r = window.getSelection()!.getRangeAt(0);
  const m = document.createTextNode('|');
  r.insertNode(m);
  const html = racine.innerHTML;
  m.remove();
  racine.normalize();
  return html;
}

beforeEach(() => {
  document.body.innerHTML = '<div id="r"></div>';
  racine = document.getElementById('r')!;
});

describe('le repère du caret', () => {
  it('distingue la fin d’une puce du début de la suivante — le rang seul les confondait', () => {
    racine.innerHTML = '<ol><li>un</li><li><br></li></ol>';
    const nouvelle = racine.querySelectorAll('li')[1];
    caretDans(nouvelle, 0);
    const place = ouEstLeCaret(racine, CALE);
    expect(place).toEqual({ bloc: 0, feuille: 1, rang: 0 });
    // On brouille la sélection, puis on la repose depuis le repère.
    caretDans(racine, 0);
    remettreLeCaret(racine, place, CALE);
    expect(lire()).toBe('<ol><li>un</li><li>|<br></li></ol>');
  });

  it('retrouve la fin de la puce précédente quand c’est là qu’on était', () => {
    racine.innerHTML = '<ol><li>un</li><li><br></li></ol>';
    const texte = racine.querySelector('li')!.firstChild!;
    caretDans(texte, 2);
    const place = ouEstLeCaret(racine, CALE);
    expect(place).toEqual({ bloc: 0, feuille: 0, rang: 2 });
    caretDans(racine, 0);
    remettreLeCaret(racine, place, CALE);
    expect(lire()).toBe('<ol><li>un|</li><li><br></li></ol>');
  });

  it('survit à une cale posée DANS le paragraphe, et ne compte pas son texte', () => {
    racine.innerHTML = '<p>abcdef</p>';
    caretDans(racine.querySelector('p')!.firstChild!, 4);
    const place = ouEstLeCaret(racine, CALE);
    expect(place).toEqual({ bloc: 0, feuille: -1, rang: 4 });
    // La pagination scinde le texte et glisse une cale au milieu — par le
    // DOM, comme l'éditeur (le parseur HTML, lui, refuserait un div dans un p).
    const p = racine.querySelector('p')!;
    const texte = p.firstChild as Text;
    texte.splitText(2);
    const cale = document.createElement('div');
    cale.className = CALE;
    cale.textContent = 'x';
    p.insertBefore(cale, texte.nextSibling);
    remettreLeCaret(racine, place, CALE);
    expect(lire()).toBe(`<p>ab<div class="${CALE}">x</div>cd|ef</p>`);
  });

  it('ignore les cales de premier niveau dans le compte des blocs', () => {
    racine.innerHTML = `<p>a</p><div class="${CALE}"></div><p>b</p>`;
    caretDans(racine.querySelectorAll('p')[1].firstChild!, 1);
    const place = ouEstLeCaret(racine, CALE);
    expect(place).toEqual({ bloc: 1, feuille: -1, rang: 1 });
    racine.innerHTML = '<p>a</p><p>b</p>';
    remettreLeCaret(racine, place, CALE);
    expect(lire()).toBe('<p>a</p><p>b|</p>');
  });

  it('une case de tableau vide est retrouvée', () => {
    racine.innerHTML = '<table><tbody><tr><td>a</td><td><br></td></tr></tbody></table>';
    const td = racine.querySelectorAll('td')[1];
    caretDans(td, 0);
    const place = ouEstLeCaret(racine, CALE)!;
    expect(place.feuille).toBe(1);
    caretDans(racine, 0);
    remettreLeCaret(racine, place, CALE);
    expect(lire()).toBe('<table><tbody><tr><td>a</td><td>|<br></td></tr></tbody></table>');
  });

  it('rend null hors de l’éditeur', () => {
    document.body.insertAdjacentHTML('beforeend', '<p id="dehors">x</p>');
    caretDans(document.getElementById('dehors')!.firstChild!, 0);
    expect(ouEstLeCaret(racine, CALE)).toBeNull();
  });
});

describe('une feuille vide mais stylée', () => {
  it('le caret est reposé DANS le span vide, pas devant', () => {
    racine.innerHTML = '<p>un</p><p><span style="font-size:24pt"><br></span></p>';
    const span = racine.querySelector('span')!;
    caretDans(span, 0);
    const place = ouEstLeCaret(racine, CALE);
    expect(place).toEqual({ bloc: 1, feuille: -1, rang: 0 });
    caretDans(racine, 0);
    remettreLeCaret(racine, place, CALE);
    expect(lire()).toBe('<p>un</p><p><span style="font-size:24pt">|<br></span></p>');
  });
});
