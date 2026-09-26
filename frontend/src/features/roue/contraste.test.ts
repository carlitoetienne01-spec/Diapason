import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

import { lireHex, rapportDeContraste } from './contraste';

// Lu sur le disque : sous vitest, un import `?raw` de CSS rend une chaîne vide.
const feuille = readFileSync(join(process.cwd(), 'src/index.css'), 'utf-8');
const roue = readFileSync(join(process.cwd(), 'src/features/roue/roue.css'), 'utf-8');

/** Les jetons d'un bloc de index.css, par son sélecteur exact. */
function jetons(selecteur: string): Record<string, string> {
  const debut = feuille.indexOf(`${selecteur} {`);
  if (debut < 0) throw new Error(`bloc introuvable : ${selecteur}`);
  const bloc = feuille.slice(debut, feuille.indexOf('}', debut));
  const sortie: Record<string, string> = {};
  for (const m of bloc.matchAll(/(--color-[a-z-]+):\s*(#[0-9a-fA-F]{3,6})\s*;/g)) sortie[m[1]] = m[2];
  return sortie;
}

/** Les sept apparences : clair et système clair partagent `:root`, sombre et système sombre `.dark`. */
const APPARENCES: Record<string, Record<string, string>> = {
  clair: jetons(':root'),
  sombre: jetons('.dark'),
  phosphore: jetons(':root.terminal'),
  ardechine: jetons(":root.terminal[data-terminal-skin='ardechine']"),
  oxblood: jetons(":root.terminal[data-terminal-skin='oxblood']"),
  sauge: jetons(":root.terminal[data-terminal-skin='sage']"),
};

describe('La capsule allumée de la roue reste lisible dans les sept apparences', () => {
  it('le calcul suit WCAG : noir sur blanc 21:1, une couleur sur elle-même 1:1', () => {
    expect(rapportDeContraste('#000', '#ffffff')).toBeCloseTo(21, 5);
    expect(rapportDeContraste('#0891b2', '#0891b2')).toBeCloseTo(1, 5);
    expect(lireHex('#abc')).toEqual([170, 187, 204]);
    expect(() => lireHex('#zzzzzz'), 'une couleur illisible doit se dire').toThrow();
  });

  it('en clair, l’accent seul ne suffit pas : roue.css prend sa teinte appuyée', () => {
    // Échec évité (26/09/2026, lot 3) : 3,68:1 pour un nom de 16 px en gras.
    const { '--color-accent': accent, '--color-accent-hover': appuye, '--color-on-accent': encre } = APPARENCES.clair;
    expect(rapportDeContraste(encre, accent), 'le défaut que la règle corrige').toBeLessThan(4.5);
    expect(rapportDeContraste(encre, appuye), 'la teinte appuyée doit passer 4,5:1').toBeGreaterThanOrEqual(4.5);
    expect(roue, 'roue.css doit poser la teinte appuyée en clair').toMatch(
      /:root:not\(\.dark\):not\(\.terminal\) \[data-roue\] \{\s*--roue-allume: var\(--color-accent-hover\);/,
    );
  });

  it('en sombre et dans les quatre écrans du terminal, l’encre sur l’accent passe 4,5:1', () => {
    for (const nom of ['sombre', 'phosphore', 'ardechine', 'oxblood', 'sauge']) {
      const t = APPARENCES[nom];
      expect(t['--color-accent'], `${nom} : accent lu`).toBeTruthy();
      expect(
        rapportDeContraste(t['--color-on-accent'], t['--color-accent']),
        `${nom} : encre « on-accent » sur l’accent`,
      ).toBeGreaterThanOrEqual(4.5);
    }
  });

  it('le nom des autres éléments, dans la couleur du texte sur le fond, passe 4,5:1 partout', () => {
    for (const [nom, t] of Object.entries(APPARENCES)) {
      expect(rapportDeContraste(t['--color-text'], t['--color-bg']), `${nom} : texte sur fond`).toBeGreaterThanOrEqual(4.5);
    }
  });
});
