import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * L'aspect plat du téléphone s'étend aux pop-ups ouverts (26/09/2026,
 * contre-épreuve de la fluidité) : les menus du compositeur portaient 32 px
 * d'ombre et chaque confirmation 60 px, en style en ligne. On lit la feuille
 * et le composant, faute de tests de composants dans ce dépôt.
 */
const lire = (chemin: string) => readFileSync(join(__dirname, chemin), 'utf8');

/** Le plus grand flou (3e longueur) des ombres d'une déclaration box-shadow. */
function flouMax(declaration: string): number {
  let max = 0;
  for (const ombre of declaration.split(/,(?![^(]*\))/)) {
    const longueurs = ombre
      .replace(/[a-z-]+\([^)]*\)/g, ' ')
      .trim()
      .split(/\s+/)
      .filter((jeton) => /^-?\d*\.?\d+(px)?$/.test(jeton))
      .map((jeton) => Number.parseFloat(jeton));
    if (longueurs.length >= 3) max = Math.max(max, longueurs[2]);
  }
  return max;
}

describe('telephonePlat.css', () => {
  const css = lire('telephonePlat.css').replace(/\/\*[\s\S]*?\*\//g, '');

  it('ramène sous 12 px l’ombre des menus et des confirmations', () => {
    const regle = css.match(/:is\(\.composer-glass-menu, \.confirmation-panneau\)\s*\{([^}]*)\}/);
    expect(regle, 'la règle des menus et des confirmations').not.toBeNull();
    const ombre = regle![1].match(/box-shadow:\s*([^;]+?)\s*!important/);
    expect(ombre, 'une ombre qui bat le style en ligne').not.toBeNull();
    expect(flouMax(ombre![1]), 'une ombre courte, pas une grande').toBeLessThan(12);
    expect(css).toContain("html[data-diapason-mobile='1'] :is(.composer-glass-menu, .confirmation-panneau)");
  });

  it('flouMax lit le flou, pas le décalage', () => {
    expect(flouMax('0 24px 60px rgba(0,0,0,0.45)')).toBe(60);
    expect(flouMax('0 18px 32px -12px rgb(0 0 0 / 0.4), 0 1px 2px 0 red')).toBe(32);
  });
});

describe('ConfirmDialog.tsx', () => {
  it('le panneau porte la classe que le téléphone aplatit', () => {
    const dialogue = lire('components/ConfirmDialog.tsx');
    const panneau = dialogue.slice(dialogue.indexOf('onClick={(event) => event.stopPropagation()}'));
    expect(panneau.slice(0, 600)).toMatch(/className="confirmation-panneau /);
  });
});
