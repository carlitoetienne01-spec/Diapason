import { describe, expect, it } from 'vitest';
import { overflowGapPlan, overflowGapHeight } from './notePages';

const A4 = 930.52, GUT = 28, MAR = 96, LIGNE = 24.75;

/** Rejoue le plan et rend la hauteur de contenu posée sur chaque feuille. */
function contenuParFeuille(blocs: any[], plan: any[]) {
  const items = blocs.map((b) => ({ ...b }));
  const decale = (i: number, d: number) => {
    for (let j = i; j < items.length; j++) items[j].top += d;
  };
  const coupures: number[] = [];
  const extents: number[] = [];
  for (const g of plan) {
    // `items[...].top` porte déjà les décalages des cales précédentes.
    coupures.push(items[g.beforeIndex].top);
    const ext = overflowGapHeight(g, GUT, MAR);
    extents.push(ext);
    decale(g.beforeIndex, ext);
  }
  const pages: number[] = [];
  let debut = 0;
  for (let k = 0; k < coupures.length; k++) {
    pages.push(coupures[k] - debut);
    debut = coupures[k] + extents[k];
  }
  const dernier = items[items.length - 1];
  pages.push(dernier.top + dernier.height - debut);
  return pages;
}

describe('propriété : aucune feuille ne dépasse sa hauteur utile', () => {
  for (const n of [40, 120, 400]) {
    it(`sur ${n} paragraphes d'une ligne`, () => {
      const blocs = Array.from({ length: n }, (_, i) => ({
        top: i * LIGNE, height: LIGNE, kind: 'block' as const, lines: [i * LIGNE],
      }));
      const plan = overflowGapPlan(blocs, A4, GUT, MAR);
      const pages = contenuParFeuille(blocs, plan);
      console.log(`n=${n} feuilles=${pages.length} max=${Math.round(Math.max(...pages))} trop=${pages.filter(h => h > A4 + 1).length}`);
      expect(pages.filter((h) => h > A4 + 1)).toHaveLength(0);
    });
  }
});
