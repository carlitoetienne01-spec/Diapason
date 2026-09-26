import { describe, expect, it } from 'vitest';

import { REQUETE_PANNEAU_SYSTEME_EN_COLONNE, panneauSystemeOuvertAuDemarrage } from './panneauSysteme';

const largeur = (px: number) => (requete: string) => {
  const min = /min-width:\s*(\d+(?:\.\d+)?)rem/.exec(requete);
  return { matches: min ? px >= Number(min[1]) * 16 : false };
};

describe('Le panneau Système au premier lancement', () => {
  it('reste fermé sur un téléphone, où il couvrirait la Discussion', () => {
    // Échec évité (26/09/2026) : à 375 px, 280 px de jetons et de watts
    // posés sur la Discussion, le compositeur derrière le voile.
    expect(panneauSystemeOuvertAuDemarrage(null, largeur(375))).toBe(false);
    expect(panneauSystemeOuvertAuDemarrage(null, largeur(340))).toBe(false);
  });

  it('s’ouvre comme avant là où il est une colonne', () => {
    expect(panneauSystemeOuvertAuDemarrage(null, largeur(640))).toBe(true);
    expect(panneauSystemeOuvertAuDemarrage(null, largeur(1280))).toBe(true);
    expect(panneauSystemeOuvertAuDemarrage(null, undefined)).toBe(true);
  });

  it('obéit au choix mémorisé, quelle que soit la largeur', () => {
    expect(panneauSystemeOuvertAuDemarrage('true', largeur(375))).toBe(true);
    expect(panneauSystemeOuvertAuDemarrage('false', largeur(1280))).toBe(false);
  });

  it('interroge une requête que les vieux WebKit comprennent', () => {
    expect(REQUETE_PANNEAU_SYSTEME_EN_COLONNE).toBe('(min-width: 40rem)');
  });
});
