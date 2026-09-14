// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from 'vitest';

import { etendueDeLaSelection, selectionnerEtendue } from './noteSelection';

let racine: HTMLElement;
beforeEach(() => {
  document.body.innerHTML = '<div id="r"></div>';
  racine = document.getElementById('r')!;
});

describe('l’étendue de la sélection', () => {
  it('se mesure en caractères à travers les balises, et se retrouve après un remplacement du HTML', () => {
    racine.innerHTML = '<p>un <b>mot</b> ici</p><p>deux</p>';
    const b = racine.querySelector('b')!.firstChild!;
    const p2 = racine.querySelectorAll('p')[1].firstChild!;
    const r = document.createRange();
    r.setStart(b, 1);
    r.setEnd(p2, 2);
    window.getSelection()!.removeAllRanges();
    window.getSelection()!.addRange(r);
    const etendue = etendueDeLaSelection(racine);
    expect(etendue).toEqual({ debut: 4, fin: 12 });
    expect(window.getSelection()!.toString()).toBe('ot icide');
    // Le HTML est remplacé (par exemple après un aperçu de taille remis).
    racine.innerHTML = '<p>un <span style="font-size:20pt">mot</span> ici</p><p>deux</p>';
    selectionnerEtendue(racine, etendue!);
    expect(window.getSelection()!.toString()).toBe('ot icide');
  });
  it('rend null quand la sélection est ailleurs', () => {
    document.body.insertAdjacentHTML('beforeend', '<p id="x">x</p>');
    const r = document.createRange();
    r.selectNodeContents(document.getElementById('x')!);
    window.getSelection()!.removeAllRanges();
    window.getSelection()!.addRange(r);
    expect(etendueDeLaSelection(racine)).toBeNull();
  });
});
