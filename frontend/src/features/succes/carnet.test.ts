import { describe, expect, it } from 'vitest';

import { carnetRempli, lignesDuCarnet } from './CarnetDeTache';

describe('Le repère « j’ai écrit ici » doit dire la vérité', () => {
  it('reconnaît un carnet qui porte quelque chose', () => {
    expect(carnetRempli('séance 1 : DNS résolu')).toBe(true);
  });

  it('ne s’allume pas pour du vide', () => {
    for (const rien of ['', '   ', '\n\n', '\t \n', undefined, null]) {
      expect(carnetRempli(rien)).toBe(false);
    }
  });

  it('ne s’allume pas pour un carnet ouvert puis effacé', () => {
    // Sans ce filtre, l'icône resterait allumée sur une tâche vide et le
    // repère cesserait de vouloir dire quoi que ce soit.
    expect(carnetRempli('   \n  \n ')).toBe(false);
  });

  it('compte les lignes qui portent du texte', () => {
    expect(lignesDuCarnet('a\n\nb\n   \nc')).toBe(3);
    expect(lignesDuCarnet('')).toBe(0);
    expect(lignesDuCarnet(undefined)).toBe(0);
  });
});
