import { describe, expect, it } from 'vitest';

import { orbeFigee } from './orbeFigee';

describe("L'orbe de la voix ne tourne pas au repos sur le téléphone", () => {
  it('au téléphone, au repos : figée', () => {
    // Échec évité (26/09/2026, lot 3) : une scène WebGL redessinée à chaque
    // image pour un orbe immobile au regard.
    expect(orbeFigee('idle', false, true), "l'orbe au repos doit être figée au téléphone").toBe(true);
  });

  it('au téléphone, dès que la voix écoute ou parle : elle reprend', () => {
    for (const etat of ['listening', 'speaking', 'connecting'] as const) {
      expect(orbeFigee(etat, false, true), `${etat} doit animer l'orbe`).toBe(false);
    }
  });

  it('sur le Mac, seul le mouvement réduit la fige', () => {
    expect(orbeFigee('idle', false, false), 'le Mac garde son orbe animée au repos').toBe(false);
    expect(orbeFigee('speaking', true, false), 'le mouvement réduit fige partout').toBe(true);
  });
});
