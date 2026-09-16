import { describe, expect, it } from 'vitest';

import { LEGEND_MAX, compactAxisTick, legendSlices } from './FinanceCharts';
import type { FinanceCategoryBreakdown } from './types';

function categorie(name: string, amount: number): FinanceCategoryBreakdown {
  return { categoryId: name, name, icon: '·', color: `#${name}`, amount };
}

describe('la graduation compacte de l’axe vertical', () => {
  it('laisse les petits montants entiers, sans suffixe', () => {
    expect(compactAxisTick(0)).toBe('0');
    expect(compactAxisTick(999.6)).toBe('1000');
    expect(compactAxisTick(-42)).toBe('-42');
  });

  it('abrège les milliers avec une virgule française et sans « ,0 »', () => {
    expect(compactAxisTick(1234)).toBe('1,2k');
    expect(compactAxisTick(25000)).toBe('25k');
    expect(compactAxisTick(-1500)).toBe('-1,5k');
  });

  it('passe au million au-delà de 999 999', () => {
    expect(compactAxisTick(1_250_000)).toBe('1,3M');
    expect(compactAxisTick(2_000_000)).toBe('2M');
  });
});

describe('la légende du camembert', () => {
  it('rend toutes les catégories tant qu’elles tiennent dans la boîte', () => {
    const data = [categorie('a', 3), categorie('b', 2), categorie('c', 1)];
    expect(legendSlices(data)).toEqual([
      { key: 'a', name: 'a', color: '#a' },
      { key: 'b', name: 'b', color: '#b' },
      { key: 'c', name: 'c', color: '#c' },
    ]);
  });

  it('distingue deux catégories du même nom par leur id — rien n’impose l’unicité côté serveur', () => {
    const doublons = [
      { categoryId: 'c1', name: 'Autres', icon: '·', color: '#1', amount: 3 },
      { categoryId: 'c2', name: 'Autres', icon: '·', color: '#2', amount: 1 },
    ];
    const cles = legendSlices(doublons).map((item) => item.key);
    expect(new Set(cles).size, 'deux entrées, deux clés').toBe(2);
  });

  it('garde les plus lourdes et agrège le reste — la légende de 36 px ne déborde plus', () => {
    const data = [
      categorie('petit', 1),
      categorie('gros', 50),
      categorie('moyen', 10),
      categorie('minuscule', 0.5),
      categorie('énorme', 100),
      categorie('autre', 2),
    ];
    const legende = legendSlices(data);
    expect(legende).toHaveLength(LEGEND_MAX);
    expect(legende.slice(0, 3).map((item) => item.name)).toEqual(['énorme', 'gros', 'moyen']);
    expect(legende[3].name).toBe('Autres (3)');
    expect(legende[3].key, 'l’entrée synthétique a sa propre clé').toBe('__autres');
  });

  it('ne rend rien pour une répartition vide', () => {
    expect(legendSlices([])).toEqual([]);
  });
});
