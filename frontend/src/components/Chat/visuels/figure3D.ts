import { SOURCE_MAX } from './limitesVisuels';
import { textePlotly } from './figureScientifique';
import type { PaletteVisuel } from './svgSur';

export interface Figure3D {
  title: string; type: 'scatter3d' | 'surface'; xLabel: string; yLabel: string; zLabel: string;
  series: { name: string; x: number[]; y: number[]; z: number[] }[];
  matrix?: number[][]; source?: string; sample: boolean;
}
const erreur = (): never => { throw new Error('figure3d'); };
function objet(v: unknown, cles: string[]): Record<string, unknown> {
  if (!v || typeof v !== 'object' || Array.isArray(v) || Object.keys(v).some(k => !cles.includes(k))) return erreur();
  return v as Record<string, unknown>;
}
const texte = (v: unknown, max = 120): string => typeof v === 'string' && v.length <= max ? v : erreur();
function vecteur(v: unknown, max = 300): number[] {
  if (!Array.isArray(v) || !v.length || v.length > max || v.some(n => typeof n !== 'number' || !Number.isFinite(n) || Math.abs(n) > 1e12)) return erreur();
  return [...v];
}
export function lireFigure3D(source: string): Figure3D {
  if (source.length > SOURCE_MAX) return erreur();
  const d = objet(JSON.parse(source), ['title', 'type', 'xLabel', 'yLabel', 'zLabel', 'series', 'matrix', 'source', 'sample']);
  const title = texte(d.title, 180);
  if (!title.trim() || (d.type !== 'scatter3d' && d.type !== 'surface') || (d.sample !== undefined && typeof d.sample !== 'boolean')) return erreur();
  const series: Figure3D['series'] = [];
  let matrix: number[][] | undefined;
  if (d.type === 'scatter3d') {
    if (d.matrix !== undefined || !Array.isArray(d.series) || !d.series.length || d.series.length > 6) return erreur();
    for (const v of d.series) {
      const s = objet(v, ['name', 'x', 'y', 'z']);
      const x = vecteur(s.x), y = vecteur(s.y), z = vecteur(s.z);
      if (x.length !== y.length || y.length !== z.length) return erreur();
      series.push({ name: texte(s.name), x, y, z });
    }
    if (series.reduce((n, s) => n + s.x.length, 0) > 300) return erreur();
  } else {
    if (d.series !== undefined || !Array.isArray(d.matrix) || d.matrix.length < 2 || d.matrix.length > 20) return erreur();
    matrix = d.matrix.map(v => vecteur(v, 20));
    if (matrix[0].length < 2 || matrix.some(v => v.length !== matrix![0].length)) return erreur();
  }
  return { title, type: d.type, series, ...(matrix ? { matrix } : {}),
    xLabel: texte(d.xLabel ?? ''), yLabel: texte(d.yLabel ?? ''), zLabel: texte(d.zLabel ?? ''),
    ...(d.source === undefined ? {} : { source: texte(d.source, 500) }), sample: d.sample === true };
}
export function traces3D(f: Figure3D, p: PaletteVisuel): unknown[] {
  if (f.type === 'surface') return [{ type: 'surface', z: f.matrix!.map(l => [...l]), colorscale: [[0, p.fond], [1, p.accent]], showscale: false }];
  const couleurs = [p.accent, '#4287ab', '#ac7449', '#8470a6', '#58956b', '#b56576'];
  return f.series.map((s, i) => ({ type: 'scatter3d', mode: 'markers', name: textePlotly(s.name),
    x: [...s.x], y: [...s.y], z: [...s.z], marker: { size: 5, color: couleurs[i] } }));
}
export const estFigure3D = (f: { type: string }): f is Figure3D => f.type === 'scatter3d' || f.type === 'surface';
