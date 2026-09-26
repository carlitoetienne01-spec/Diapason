import { describe, expect, it } from 'vitest';

import { TERMINAL_SKINS } from './store';
import { chargeThemeNatif, themeEstClair } from './themeNatif';

describe('La coquille reçoit de quoi rendre sa barre d’état lisible', () => {
  it('Ardéchine est claire : sans ce drapeau, des icônes blanches sur un panneau pâle', () => {
    // Échec évité (26/09/2026) : la barre d'état d'Android illisible en
    // Ardéchine, seule peau du terminal à fond pâle.
    expect(chargeThemeNatif({ theme: 'terminal', skin: 'ardechine', systemeSombre: true }).clair).toBe(true);
  });

  it('les trois autres écrans du terminal sont sombres', () => {
    for (const skin of TERMINAL_SKINS.filter((s) => s !== 'ardechine')) {
      expect(themeEstClair('terminal', skin, false), skin).toBe(false);
    }
  });

  it('clair et sombre ne dépendent pas du système ; « système » en dépend', () => {
    expect(themeEstClair('light', 'phosphor', true)).toBe(true);
    expect(themeEstClair('dark', 'phosphor', false)).toBe(false);
    expect(themeEstClair('system', 'phosphor', true)).toBe(false);
    expect(themeEstClair('system', 'phosphor', false)).toBe(true);
  });

  it('porte les couleurs calculées, sans espaces', () => {
    expect(
      chargeThemeNatif({ theme: 'terminal', skin: 'phosphor', systemeSombre: false, fond: ' #030703', encre: '#b6ff6a ' }),
    ).toEqual({ theme: 'terminal', skin: 'phosphor', fond: '#030703', encre: '#b6ff6a', clair: false });
  });

  it('retombe sur les couleurs de base quand la feuille n’a rien rendu', () => {
    // Un fond vide ferait peindre la coquille en noir par défaut — le flash
    // au démarrage à froid que l'étape 6 doit éviter.
    const charge = chargeThemeNatif({ theme: 'light', skin: 'phosphor', systemeSombre: true, fond: '', encre: '' });
    expect(charge.fond).toBe('#f9f9f9');
    expect(charge.encre).toBe('#09090b');
  });
});
