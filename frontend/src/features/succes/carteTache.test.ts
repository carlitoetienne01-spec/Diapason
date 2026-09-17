import { describe, expect, it } from 'vitest';

import { SIGNES_PRIORITE, monogrammeProjet } from './carteTache';

describe('le signe de priorité devant le titre', () => {
  it('se tait pour la priorité par défaut — un signal sur 90 % des cartes n’en est pas un', () => {
    expect(SIGNES_PRIORITE.medium.signe).toBe('');
    expect(SIGNES_PRIORITE.low.signe).toBe('');
    expect(SIGNES_PRIORITE.medium.couleur).toBeUndefined();
  });

  it('gradue urgent au-dessus de haute, en signes et en jetons', () => {
    expect(SIGNES_PRIORITE.urgent.signe.length).toBeGreaterThan(SIGNES_PRIORITE.high.signe.length);
    expect(SIGNES_PRIORITE.urgent.couleur).toBe('var(--color-error)');
    expect(SIGNES_PRIORITE.high.couleur).toContain('var(--color-warning)');
  });

  it('assombrit le « !! » d’encre : le jeton d’avertissement seul fait 2,94:1 sur blanc', () => {
    // Seul porteur visuel du niveau haute ; 35 % d'encre en OKLab donne
    // 6,28:1 sur #ffffff (revue du 17 sept. 2026, défaut 18). Toujours par
    // jetons : les quatre peaux gardent la main sur la teinte.
    expect(SIGNES_PRIORITE.high.couleur).toBe(
      'color-mix(in oklab, var(--color-warning), var(--color-text) 35%)',
    );
    expect(SIGNES_PRIORITE.high.couleur).not.toMatch(/#[0-9a-f]{3,6}/i);
  });

  it('garde un libellé lisible par un lecteur d’écran, même sans signe', () => {
    for (const signe of Object.values(SIGNES_PRIORITE)) {
      expect(signe.libelle).toMatch(/^Priorité /);
    }
  });
});

describe('le monogramme de projet — la forme qui remplace la teinte en Ardéchine', () => {
  it('prend l’initiale du premier mot et celle du dernier', () => {
    expect(monogrammeProjet('La Cité')).toBe('LC');
    expect(monogrammeProjet('Zéro à Héro')).toBe('ZH');
    expect(monogrammeProjet('English Mastery')).toBe('EM');
  });

  it('prend deux lettres quand le nom n’a qu’un mot', () => {
    expect(monogrammeProjet('Diapason')).toBe('DI');
    expect(monogrammeProjet('X')).toBe('X·');
  });

  it('ne rend jamais rien — une boîte vide ne distinguerait plus deux projets', () => {
    expect(monogrammeProjet('')).toBe('··');
    expect(monogrammeProjet('  -  ')).toBe('··');
  });
});
