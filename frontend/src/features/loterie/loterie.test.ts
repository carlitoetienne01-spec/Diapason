import { describe, expect, it } from 'vitest';

import { lireGrille, lireLaValeurP, tiragesPourAnnees, unSur } from './loterie';

describe('Lire une grille tapée à la main', () => {
  it('accepte les séparateurs qu’on utilise vraiment', () => {
    for (const saisie of ['6 23 28 34 37 4', '6,23,28,34,37,4', '6-23-28-34-37-4']) {
      expect(lireGrille(saisie).grille).toEqual({
        numeros: [6, 23, 28, 34, 37],
        grandNumero: 4,
      });
    }
  });

  it('trie les numéros', () => {
    expect(lireGrille('37 6 28 23 34 4').grille?.numeros).toEqual([6, 23, 28, 34, 37]);
  });

  it('refuse une grille incomplète au lieu de la compléter', () => {
    // Compléter jouerait une grille que personne n'a choisie.
    const { grille, erreur } = lireGrille('6 23 28 34');
    expect(grille).toBeNull();
    expect(erreur).toContain('Grand Numéro');
  });

  it('refuse un doublon', () => {
    expect(lireGrille('6 6 28 34 37 4').erreur).toBe('Un numéro revient deux fois.');
  });

  it('refuse un numéro hors de 1 à 49', () => {
    expect(lireGrille('6 23 28 34 50 4').erreur).toContain('50');
  });

  it('refuse un Grand Numéro hors de 1 à 7', () => {
    expect(lireGrille('6 23 28 34 37 8').erreur).toContain('Grand Numéro');
  });

  it('ne se plaint pas d’une saisie encore vide', () => {
    // Une erreur affichée avant qu'on ait tapé quoi que ce soit est du bruit.
    expect(lireGrille('')).toEqual({ grille: null, erreur: '' });
    expect(lireGrille('   ')).toEqual({ grille: null, erreur: '' });
  });
});

describe('Dire une cote et une valeur p en français', () => {
  it('écrit la cote du gros lot', () => {
    // Le séparateur de milliers rendu par `fr-CA` est une espace fine
    // INSÉCABLE (U+202F), pas une espace ordinaire. Comparer la chaîne entière
    // ferait échouer ce test sur une différence invisible à l'œil ; on compare
    // donc les chiffres et le mot, pas les blancs.
    const rendu = unSur(13348188);
    expect(rendu.replace(/[\s\u202f\u00a0]/g, '')).toBe('1sur13348188');
  });

  it('rend un tiret plutôt qu’une cote absurde', () => {
    for (const mauvais of [0, -1, Number.NaN, Number.POSITIVE_INFINITY]) {
      expect(unSur(mauvais)).toBe('—');
    }
  });

  it('traduit un p élevé en « rien à signaler »', () => {
    expect(lireLaValeurP(0.79)).toContain('équitable');
  });

  it('nuance un p bas au lieu de crier à la fraude', () => {
    // Avec 49 numéros, un tirage parfait passe sous 5 % une fois sur vingt.
    expect(lireLaValeurP(0.03)).toContain('une fois sur vingt');
  });

  it('reste prudent même sur un p très bas', () => {
    expect(lireLaValeurP(0.0001)).toContain('avant d’en conclure');
  });
});

describe('Traduire des années de jeu en tirages', () => {
  it('compte deux tirages par semaine', () => {
    expect(tiragesPourAnnees(1)).toBe(104);
    expect(tiragesPourAnnees(50)).toBe(5200);
  });

  it('ne descend jamais à zéro tirage', () => {
    expect(tiragesPourAnnees(0)).toBe(1);
  });
});
