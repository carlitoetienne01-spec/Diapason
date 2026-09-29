import { describe, expect, it } from 'vitest';
import { appliquerClassementNotes, rangerNoteMobile } from './classementNotesMobile';

const notes = [
  { id: 'a', category: 'Travail', content: 'Texte intact' },
  { id: 'b', category: 'Travail', content: 'Deuxième' },
  { id: 'c', category: 'Personnel', content: 'Troisième' },
];
describe('§82 — les notes se rangent comme les projets', () => {
  it('déplace dans les deux directions et conserve le contenu', () => {
    const ids = rangerNoteMobile(notes, ['a', 'b', 'c'], 'a', 'b', 'Travail');
    expect(ids).toEqual(['b', 'a', 'c']);
    expect(rangerNoteMobile(notes, ids, 'a', 'b', 'Travail')).toEqual(['a', 'b', 'c']);
    const suivant = appliquerClassementNotes(notes, ids, { id: 'a', zone: 'Travail' });
    expect(suivant.find(n => n.id === 'a')?.content).toBe('Texte intact');
    expect(notes[0].category).toBe('Travail');
  });
  it('dépose dans une autre catégorie sans déplacer les autres notes de catégorie', () => {
    const ids = rangerNoteMobile(notes, ['a', 'b', 'c'], 'a', null, 'Personnel');
    const suivant = appliquerClassementNotes(notes, ids, { id: 'a', zone: 'Personnel' });
    expect(suivant.map(n => [n.id, n.category])).toEqual([['b', 'Travail'], ['c', 'Personnel'], ['a', 'Personnel']]);
    expect(notes[0].category).toBe('Travail');
  });
  it('accepte une catégorie vide et une sortie de catégorie', () => {
    const ids = rangerNoteMobile(notes, ['a', 'b', 'c'], 'a', null, '');
    expect(appliquerClassementNotes(notes, ids, { id: 'a', zone: '' }).slice(-1)[0]?.category).toBe('');
  });
  it('garde une note reçue pendant le geste et ne duplique aucun cartable', () => {
    expect(appliquerClassementNotes(notes, ['b', 'a', 'a'], { id: 'a' }).map(n => n.id)).toEqual(['b', 'a', 'c']);
  });
});
