import { describe, expect, it } from 'vitest';

import { dateCourte, domaineDe, lignesDeSources } from './sourcesDeReponse';

describe('les sources sous une réponse', () => {
  it('range les sources par numéro, une fois chacune, avec domaine et date courte', () => {
    expect(
      lignesDeSources([
        { ref: 2, url: 'https://www.france24.com/b', title: 'Canada–UE', date: '2026-09-18' },
        { ref: 1, url: 'https://ledevoir.com/a', title: 'Carney assermenté', sender: 'Le Devoir', date: '2026-09-16T10:00:00' },
        { ref: 1, url: 'https://ledevoir.com/a', title: 'doublon' },
        { ref: 3, url: '', title: 'sans adresse' },
      ]),
    ).toEqual([
      { ref: 1, url: 'https://ledevoir.com/a', domaine: 'Le Devoir', titre: 'Carney assermenté', date: '16 sept. 2026' },
      { ref: 2, url: 'https://www.france24.com/b', domaine: 'france24.com', titre: 'Canada–UE', date: '18 sept. 2026' },
    ]);
  });

  it('ne fabrique ni date ni domaine', () => {
    expect(dateCourte(undefined)).toBe('');
    expect(dateCourte('hier')).toBe('hier');
    expect(domaineDe('pas une url')).toBe('');
    expect(lignesDeSources(undefined)).toEqual([]);
  });
});
