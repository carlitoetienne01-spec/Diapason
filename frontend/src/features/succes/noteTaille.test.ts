import { describe, expect, it } from 'vitest';

import { NOTE_FONT_SIZES, pointsDepuisPx, tailleAffichee } from './noteFormats';

describe('La barre doit dire la taille du texte sous le curseur', () => {
  it('rend les points d’une longueur lue en pixels', () => {
    // getComputedStyle ne rend jamais l'unité écrite : toujours des pixels.
    expect(pointsDepuisPx(16)).toBe(12);
    expect(pointsDepuisPx(12)).toBe(9);
    expect(pointsDepuisPx(96)).toBe(72);
  });

  it('arrondit le retour flottant de 11 pt au lieu d’annoncer 11,000025', () => {
    // 11 pt = 14,6667 px, et 14,6667 × 0,75 = 11,000025.
    expect(pointsDepuisPx(14.6667)).toBe(11);
  });

  it('garde la demi-taille plutôt que de mentir d’un point entier', () => {
    // 10,5 pt = 14 px. Arrondir à l'entier ferait afficher 11 sur du 10,5.
    expect(pointsDepuisPx(14)).toBe(10.5);
  });

  it('retrouve chaque taille de la liste après l’aller-retour pt → px → pt', () => {
    for (const points of NOTE_FONT_SIZES) {
      expect(pointsDepuisPx((points * 96) / 72)).toBe(points);
    }
  });

  it('ne rend rien pour une longueur absente ou absurde', () => {
    expect(pointsDepuisPx(0)).toBeNull();
    expect(pointsDepuisPx(Number.NaN)).toBeNull();
    expect(pointsDepuisPx(-12)).toBeNull();
  });

  it('affiche la taille quand toute la sélection s’accorde', () => {
    expect(tailleAffichee([12, 12, 12])).toBe(12);
    expect(tailleAffichee([14])).toBe(14);
  });

  it('se tait quand la sélection mélange deux tailles', () => {
    // Word laisse la case vide. Annoncer 12 sur une sélection 12+18 serait
    // décrire un texte qui n'existe pas.
    expect(tailleAffichee([12, 18])).toBeNull();
  });

  it('se tait dès qu’une taille est inconnue', () => {
    expect(tailleAffichee([12, null])).toBeNull();
  });

  it('se tait sur une sélection vide', () => {
    expect(tailleAffichee([])).toBeNull();
  });
});
