import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

import { contrasteEstompe, lireCouleur, lireHex, luminance, opaciteMinimale, rapportDeContraste } from './contraste';
import { ECART_ALLUME, estompeSelonEcart, OPACITE_LISIBLE_PAR_DEFAUT, PORTEE_LISIBLE } from './geometrieRoue';

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
      // Sur la capsule (--color-surface) depuis la surimpression du 27/09/2026 :
      // l'écran « Aller à » et son --color-bg ont disparu.
      const alpha = opaciteMinimale(t['--color-text'], t['--color-surface']);
      expect(contrasteEstompe(t['--color-text'], t['--color-surface'], alpha), `${nom} à ${alpha}`).toBeGreaterThanOrEqual(4.5);
      expect(contrasteEstompe(t['--color-text'], t['--color-surface'], alpha - 0.02), `${nom} : au plus juste`).toBeLessThan(4.5);
      expect(alpha, `${nom} : le repli par défaut doit couvrir cette apparence`).toBeLessThanOrEqual(OPACITE_LISIBLE_PAR_DEFAUT);
    }
  });

  it('un texte qui ne passe pas même opaque n’est jamais estompé', () => {
    expect(opaciteMinimale('#777777', '#888888')).toBe(1);
  });
});

/** L'accent de la capsule allumée tel que roue.css le résout : la teinte
 *  appuyée en clair, l'accent partout ailleurs. */
function accentAllume(nom: string, t: Record<string, string>): string {
  return nom === 'clair' ? t['--color-accent-hover'] : t['--color-accent'];
}

describe('En surimpression, chaque nom touchable se lit sur sa capsule opaque, quelle que soit la page', () => {
  // 27/09/2026, la roue en surimpression : les noms ne se posent plus sur
  // l'écran « Aller à » mais sur la page vivante — blanc d'une carte, texte
  // d'une tâche, tout est possible dessous. La capsule de chaque nom est
  // opaque tant qu'il se touche (geometrieRoue.ts, `presenceSelonEcart`) :
  // le contraste ne dépend plus que du nom et de SA capsule.
  it('texte sur capsule de surface : 4,5:1 opaque dans les sept apparences, et les actions sur leur fond plein', () => {
    for (const [nom, t] of Object.entries(APPARENCES)) {
      expect(t['--color-surface'], `${nom} : surface lue`).toBeTruthy();
      expect(rapportDeContraste(t['--color-text'], t['--color-surface']), `${nom} : texte sur sa capsule`).toBeGreaterThanOrEqual(4.5);
      expect(
        rapportDeContraste(t['--color-text'], t['--color-bg-secondary']),
        `${nom} : les actions (Liste, Parler) sur leur fond plein`,
      ).toBeGreaterThanOrEqual(4.5);
    }
  });

  it('le nom estompé au bout de la portée garde 4,5:1 sur sa capsule, et le repli couvre les sept', () => {
    for (const [nom, t] of Object.entries(APPARENCES)) {
      const lisible = opaciteMinimale(t['--color-text'], t['--color-surface']);
      const auBout = estompeSelonEcart(PORTEE_LISIBLE, lisible);
      expect(contrasteEstompe(t['--color-text'], t['--color-surface'], auBout), `${nom} à ${auBout}`).toBeGreaterThanOrEqual(4.5);
      expect(lisible, `${nom} : le repli par défaut doit couvrir cette apparence`).toBeLessThanOrEqual(OPACITE_LISIBLE_PAR_DEFAUT);
    }
    expect(opaciteMinimale(APPARENCES.sauge['--color-text'], APPARENCES.sauge['--color-surface']), 'Sauge fixe le repli').toBe(
      OPACITE_LISIBLE_PAR_DEFAUT,
    );
  });

  it('la capsule accent tient parce que son nom ne s’estompe jamais : en Oxblood, un centième de moins la perdait', () => {
    // L'élément [data-allume] glisse jusqu'à ECART_ALLUME pendant la
    // rotation ; là, estompeSelonEcart le garde plein. La contre-preuve
    // d'Oxblood : à 0,99, l'encre sur l'accent tombe à 4,49:1.
    for (const [nom, t] of Object.entries(APPARENCES)) {
      expect(estompeSelonEcart(ECART_ALLUME, 0.5), `${nom} : plein au demi-écart`).toBe(1);
      expect(rapportDeContraste(t['--color-on-accent'], accentAllume(nom, t)), `${nom} : encre sur accent`).toBeGreaterThanOrEqual(4.5);
    }
    expect(
      contrasteEstompe(APPARENCES.oxblood['--color-on-accent'], APPARENCES.oxblood['--color-accent'], 0.99),
      'Oxblood estompé d’un centième : la preuve que le plateau n’est pas du luxe',
    ).toBeLessThan(4.5);
  });
});

describe('Le voile de la surimpression : mesuré, pas choisi au pif', () => {
  const VOILE = 0.2;
  const CANDIDATS = [0.15, 0.2, 0.25, 0.3];
  const sousVoile = (hex: string) => lireCouleur(hex).map((v) => v * (1 - VOILE)) as [number, number, number];
  const ratio = (a: [number, number, number], b: [number, number, number]) => {
    const [clair, sombre] = [luminance(a), luminance(b)].sort((x, y) => y - x);
    return (clair + 0.05) / (sombre + 0.05);
  };

  it('roue.css porte la valeur mesurée', () => {
    expect(roue).toContain('--roue-voile: rgba(0, 0, 0, 0.2);');
  });

  it('0,20 est le plus léger des candidats qui sépare la capsule du pire cas — page blanche, thème clair', () => {
    // La capsule (surface #ffffff) posée sur une carte blanche de la page :
    // sans voile, aucune frontière. 1,5:1 est la séparation visible retenue.
    const surface = lireCouleur(APPARENCES.clair['--color-surface']);
    const separation = (v: number) => ratio(surface, surface.map((c) => c * (1 - v)) as [number, number, number]);
    expect(separation(VOILE), 'la séparation du pire cas').toBeGreaterThanOrEqual(1.5);
    for (const v of CANDIDATS.filter((c) => c < VOILE)) {
      expect(separation(v), `un voile de ${v} ne sépare plus`).toBeLessThan(1.5);
    }
  });

  it('la page reste bien visible : son texte garde 4,5:1 sous le voile dans les sept apparences', () => {
    for (const [nom, t] of Object.entries(APPARENCES)) {
      expect(
        ratio(sousVoile(t['--color-text']), sousVoile(t['--color-bg'])),
        `${nom} : texte de la page sous le voile`,
      ).toBeGreaterThanOrEqual(4.5);
    }
  });
});
