import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

import { contrasteEstompe, lireCouleur, lireHex, opaciteMinimale, rapportDeContraste } from './contraste';
import { OPACITE_LISIBLE_PAR_DEFAUT } from './geometrieRoue';

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

describe('Les noms estompés qui se touchent gardent 4,5:1 dans les sept apparences', () => {
  // 26/09/2026, contre-épreuve : touchables jusqu'à 1,09:1 en Sauge, 1,18:1
  // en Ardéchine — le contraste « voisin » ignorait l'opacité de sa place.
  it('lit les couleurs calculées du navigateur', () => {
    expect(lireCouleur('rgb(8, 145, 178)')).toEqual([8, 145, 178]);
    expect(lireCouleur('rgba(8, 145, 178, 0.5)')).toEqual([8, 145, 178]);
    expect(lireCouleur('#0891b2')).toEqual([8, 145, 178]);
    expect(contrasteEstompe('#000000', '#ffffff', 1)).toBeCloseTo(21, 5);
    expect(contrasteEstompe('#000000', '#ffffff', 0)).toBeCloseTo(1, 5);
  });

  it('l’opacité minimale de chaque apparence tient 4,5:1, et pas un centième de moins', () => {
    for (const [nom, t] of Object.entries(APPARENCES)) {
      const alpha = opaciteMinimale(t['--color-text'], t['--color-bg']);
      expect(contrasteEstompe(t['--color-text'], t['--color-bg'], alpha), `${nom} à ${alpha}`).toBeGreaterThanOrEqual(4.5);
      expect(contrasteEstompe(t['--color-text'], t['--color-bg'], alpha - 0.02), `${nom} : au plus juste`).toBeLessThan(4.5);
      expect(alpha, `${nom} : le repli par défaut doit couvrir cette apparence`).toBeLessThanOrEqual(OPACITE_LISIBLE_PAR_DEFAUT);
    }
  });

  it('un texte qui ne passe pas même opaque n’est jamais estompé', () => {
    expect(opaciteMinimale('#777777', '#888888')).toBe(1);
  });
});
