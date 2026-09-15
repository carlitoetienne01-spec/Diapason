import { describe, expect, it } from 'vitest';

import { deplacerCategorie, grouperEnSections } from './notesSections';
import type { SuccesNote } from './types';

let compteur = 0;
function note(category: string): SuccesNote {
  compteur += 1;
  return { id: `n${compteur}`, title: `Note ${compteur}`, category } as SuccesNote;
}

describe('les sections de notes', () => {
  it('sans aucune catégorie, la page reste à plat — pas d’en-tête pour rien', () => {
    const notes = [note(''), note('')];
    expect(grouperEnSections(notes, [])).toEqual([{ nom: '', notes }]);
  });

  it('suit l’ordre choisi, range l’inconnu à la fin, le sans-catégorie ferme', () => {
    const ecole = note('École');
    const jeux = note('Jeux');
    const zebre = note('Zèbre');
    const alpha = note('Alpha');
    const vrac = note('');
    const sections = grouperEnSections([vrac, jeux, ecole, zebre, alpha], ['Jeux', 'École']);
    expect(sections.map((s) => s.nom)).toEqual(['Jeux', 'École', 'Alpha', 'Zèbre', '']);
    expect(sections[0].notes).toEqual([jeux]);
    expect(sections[4].notes).toEqual([vrac]);
  });

  it('l’ordre des notes DANS une section est celui reçu — le tri de la page', () => {
    const b = note('Cat');
    const a = note('Cat');
    expect(grouperEnSections([b, a], ['Cat'])[0].notes).toEqual([b, a]);
  });

  it('une catégorie de l’ordre sans note vivante n’apparaît pas', () => {
    const sections = grouperEnSections([note('Vivante')], ['Morte', 'Vivante']);
    expect(sections.map((s) => s.nom)).toEqual(['Vivante']);
  });
});

describe('déplacer une catégorie', () => {
  it('se place avant la cible, ou à la fin', () => {
    expect(deplacerCategorie(['A', 'B', 'C'], 'C', 'A')).toEqual(['C', 'A', 'B']);
    expect(deplacerCategorie(['A', 'B', 'C'], 'A', '')).toEqual(['B', 'C', 'A']);
    expect(deplacerCategorie(['A', 'B'], 'A', 'A')).toEqual(['A', 'B']);
  });
});
