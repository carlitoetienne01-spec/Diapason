import { describe, expect, it } from 'vitest';
import { lireFigureScientifique, tracesPlotly } from './figureScientifique';
import { genreVisuel } from './formatVisuel';

const base = { title: 'Mesures', type: 'scatter', series: [{ name: 'Essai', x: [1, 2], y: [3, 4], errorY: [.1, .2] }], sample: true };
const lire = (v: unknown, plotly = false) => lireFigureScientifique(JSON.stringify(v), plotly);
describe('Les figures scientifiques gardent les mesures et refusent le code', () => {
  it('reconnaît les deux formats dans les conversations enregistrées', () => {
    expect(genreVisuel('diapason-plotly')).toBe('diapason-plotly');
    expect(genreVisuel('diapason-matplotlib')).toBe('diapason-matplotlib');
    expect(genreVisuel('python')).toBeNull();
  });
  it('conserve les coordonnées et incertitudes sans coercition', () => {
    expect(lire(base).series).toEqual(base.series);
    const p = tracesPlotly(lire({ ...base, series: [{ ...base.series[0], name: '<a href="x">X</a>' }] }),
      { accent: '#abcdef', fond: '#ffffff', texte: '#000000', bord: '#444444', secondaire: '#333333', police: 'monospace' });
    expect(p[0].x).toEqual([1, 2]); expect(p[0].error_y?.array).toEqual([.1, .2]);
    expect(p[0].name).not.toContain('<a');
  });
  it.each([
    { series: [{ name: 'X', x: [1, 2], y: [1] }] },
    { series: [{ name: 'X', x: ['1'], y: [1] }] },
    { series: [{ name: 'X', x: [true], y: [1] }] },
    { series: [{ name: 'X', x: [1], y: [1], errorY: [-1] }] },
    { series: [{ name: 'X', x: Array(151).fill(1), y: Array(151).fill(1) }, { name: 'Y', x: Array(151).fill(1), y: Array(151).fill(1) }] },
    { bins: 100000 }, { code: 'eval(1)' }, { layout: { images: ['https://x'] } }, { title: ' ' }, { sample: 'false' },
  ])('rejette les paramètres incohérents %j', modif => { expect(() => lire({ ...base, ...modif })).toThrow(); });
  it('calcule un histogramme depuis les observations, sans fausses ordonnées', () => {
    expect(lire({ title: 'Répartition', type: 'histogram', bins: 8, series: [{ name: 'A', x: [1, 2, 1] }] }).bins).toBe(8);
    expect(() => lire({ ...base, type: 'histogram' })).toThrow();
  });
  it('borne la matrice et réserve son rendu vectoriel à Matplotlib', () => {
    const m = { title: 'Matrice', type: 'heatmap', matrix: [[1, 2], [3, 4]], xLabels: ['A', 'B'] };
    expect(lire(m).matrix).toEqual(m.matrix);
    expect(() => lire({ ...m, matrix: [[1, 2], [3]] })).toThrow();
    expect(() => lire({ ...m, xLabels: ['A'] })).toThrow();
    expect(() => lire(m, true)).toThrow();
  });
});
