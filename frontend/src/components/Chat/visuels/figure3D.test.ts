import { describe, expect, it } from 'vitest';
import { lireFigure3D, traces3D } from './figure3D';
const base = { title: 'Positions', type: 'scatter3d', series: [{ name: '<b>A</b>', x: [1, 2], y: [3, 4], z: [5, 6] }], sample: false };
const lire = (v: unknown) => lireFigure3D(JSON.stringify(v));
describe('Les coordonnées 3D restent des données bornées', () => {
  it('conserve exactement les coordonnées et échappe les noms HTML', () => {
    const f = lire(base);
    expect(f.series[0].z).toEqual([5, 6]);
    expect(traces3D(f, { accent: '#123456' } as never)[0]).toMatchObject({ name: '&lt;b&gt;A&lt;/b&gt;', z: [5, 6] });
  });
  it('refuse un Z manquant, une formule, des axes incohérents et une surcharge', () => {
    for (const s of [{ ...base.series[0], z: [1] }, { ...base.series[0], z: ['sin(x)', 2] }, { ...base.series[0], code: 'eval()' }]) expect(() => lire({ ...base, series: [s] })).toThrow();
    expect(() => lire({ ...base, layout: {} })).toThrow();
    expect(() => lire({ ...base, series: Array(6).fill({ name: 'A', x: Array(51).fill(0), y: Array(51).fill(0), z: Array(51).fill(0) }) })).toThrow();
  });
  it('accepte une surface rectangulaire sans inventer ses hauteurs', () => {
    const f = lire({ title: 'Relief', type: 'surface', matrix: [[1, 2], [3, 4]] });
    expect(f.matrix).toEqual([[1, 2], [3, 4]]);
    for (const matrix of [[[1], [2]], [[1, 2], [3]], Array(21).fill([1, 2])]) expect(() => lire({ title: 'X', type: 'surface', matrix })).toThrow();
  });
});
