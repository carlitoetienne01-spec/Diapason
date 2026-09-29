import { describe, expect, it } from 'vitest';
import { doigtDeplace, rangerProjet, pasDefilementProjet } from './gesteProjet';

describe('§82 — ranger les projets au doigt sans voler le défilement', () => {
  it('tolère le tremblement du doigt, mais laisse défiler avant la prise', () => {
    expect(doigtDeplace({ x: 0, y: 0 }, { x: 4, y: 4 })).toBe(false);
    expect(doigtDeplace({ x: 0, y: 0 }, { x: 0, y: 9 })).toBe(true);
  });
  it('déplace dans les deux sens sans perdre ni dupliquer un projet', () => {
    const ids = ['a', 'b', 'c', 'd'];
    expect(rangerProjet(ids, 'a', 'c')).toEqual(['b', 'c', 'a', 'd']);
    expect(rangerProjet(ids, 'd', 'b')).toEqual(['a', 'd', 'b', 'c']);
    expect(rangerProjet(ids, 'absent', 'a')).toEqual(ids);
    expect(ids).toEqual(['a', 'b', 'c', 'd']);
  });
  it('ne défile qu’aux bords, avec une vitesse bornée', () => {
    expect(pasDefilementProjet(300, 100, 600)).toBe(0);
    expect(pasDefilementProjet(110, 100, 600)).toBeLessThan(0);
    expect(pasDefilementProjet(590, 100, 600)).toBeGreaterThan(0);
    expect(pasDefilementProjet(1000, 100, 600)).toBe(10);
  });
});
