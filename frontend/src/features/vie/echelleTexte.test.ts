import { describe, expect, it } from 'vitest';

import {
  ECHELLE_DEFAUT,
  ECHELLE_MAX,
  ECHELLE_MIN,
  TAILLES_BASE,
  echelleSuivante,
  libelleEchelle,
  normaliserEchelle,
  taillesDe,
} from './echelleTexte';

describe('normaliserEchelle', () => {
  it('retombe sur le défaut quand rien n’a jamais été réglé', () => {
    expect(normaliserEchelle(undefined)).toBe(ECHELLE_DEFAUT);
    expect(normaliserEchelle(null)).toBe(ECHELLE_DEFAUT);
  });

  it('refuse ce qui ferait disparaître le texte au lieu de l’agrandir', () => {
    expect(normaliserEchelle(NaN)).toBe(ECHELLE_DEFAUT);
    expect(normaliserEchelle('grand')).toBe(ECHELLE_DEFAUT);
    expect(normaliserEchelle({})).toBe(ECHELLE_DEFAUT);
  });

  it('accepte une valeur relue en chaîne — localStorage ne rend que du texte', () => {
    expect(normaliserEchelle('1.3')).toBe(1.3);
  });

  it('borne une valeur posée à la main hors des limites', () => {
    expect(normaliserEchelle(40)).toBe(ECHELLE_MAX);
    expect(normaliserEchelle(0.1)).toBe(ECHELLE_MIN);
  });
});

describe('echelleSuivante', () => {
  it('agrandit et réduit d’un cran, sans traîne de virgule', () => {
    expect(echelleSuivante(1.15, 1)).toBe(1.3);
    expect(echelleSuivante(1.3, -1)).toBe(1.15);
  });

  it('s’arrête aux bornes plutôt que de les dépasser', () => {
    expect(echelleSuivante(ECHELLE_MAX, 1)).toBe(ECHELLE_MAX);
    expect(echelleSuivante(ECHELLE_MIN, -1)).toBe(ECHELLE_MIN);
  });
});

describe('taillesDe', () => {
  it('rend les tailles d’avant le réglage à l’échelle 1', () => {
    expect(taillesDe(1)).toEqual(TAILLES_BASE);
  });

  it('agrandit tout ensemble — un titre ne doit pas grossir seul', () => {
    const t = taillesDe(2);
    expect(t.titre).toBe(28);
    expect(t.note).toBe(26);
    expect(t.mention).toBe(24);
    expect(t.badge).toBe(22);
  });

  it('ne rend jamais NaN, même nourrie n’importe comment', () => {
    for (const valeur of [undefined, null, NaN, 'x', -5]) {
      const t = taillesDe(valeur as unknown as number);
      expect(Object.values(t).every((n) => Number.isFinite(n) && n > 0)).toBe(true);
    }
  });
});

describe('libelleEchelle', () => {
  it('s’affiche en pour cent entier', () => {
    expect(libelleEchelle(1)).toBe('100 %');
    expect(libelleEchelle(1.15)).toBe('115 %');
    expect(libelleEchelle(2)).toBe('200 %');
  });
});
