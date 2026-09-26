import { describe, expect, it } from 'vitest';

import { copierTexte } from './copier';

describe('Copier ne dit « copié » que si c’est copié', () => {
  it('une écriture refusée rend false', async () => {
    const presse = { writeText: () => Promise.reject(new Error('NotAllowedError')) };
    expect(await copierTexte('x', presse)).toBe(false);
  });

  it('sans presse-papiers, false ; une écriture réussie, true', async () => {
    expect(await copierTexte('x', undefined)).toBe(false);
    const copie: string[] = [];
    expect(await copierTexte('x', { writeText: async (t) => void copie.push(t) })).toBe(true);
    expect(copie).toEqual(['x']);
  });
});
