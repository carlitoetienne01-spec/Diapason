import { describe, expect, it } from 'vitest';
import { styleCadreVitre } from './styleCadreVitre';

describe('§5 — le verre ne doit pas effacer les états des cartes', () => {
  it.each(['var(--color-surface)', 'var(--color-bg-secondary)'])('retire seulement l’aplat neutre %s', (background) => {
    const original = { background, border: '1px solid var(--color-border)', height: 220, opacity: 0.55 };
    expect(styleCadreVitre(original)).toEqual({ height: 220, opacity: 0.55 });
    expect(original.background).toBe(background);
    expect(original.border).toBe('1px solid var(--color-border)');
  });
  it('préserve le dépôt actif, le retard, les couleurs et la taille de la case', () => {
    const style = {
      background: 'color-mix(in srgb, var(--color-accent) 10%, var(--color-bg-secondary))',
      border: '1px solid var(--color-error)', color: 'var(--color-text)', height: 220,
    };
    expect(styleCadreVitre(style)).toEqual(style);
  });
  it('préserve la bordure accentuée du formulaire et ses styles explicites', () => {
    expect(styleCadreVitre({ background: 'var(--color-surface)', borderColor: 'var(--color-accent)', boxShadow: 'none' }))
      .toEqual({ borderColor: 'var(--color-accent)', boxShadow: 'none' });
  });
  it('laisse le biseau du matériau remplacer une bordure transparente', () => {
    expect(styleCadreVitre({ border: '1px solid transparent' })).toEqual({});
    expect(styleCadreVitre()).toEqual({});
  });
});
