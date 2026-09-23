import { SOURCE_MAX } from './limitesVisuels';
import type { PaletteVisuel } from './svgSur';

export interface SerieScientifique { name: string; x: number[]; y?: number[]; errorY?: number[] }
export interface FigureScientifique {
  title: string; type: 'line' | 'scatter' | 'histogram' | 'heatmap';
  xLabel: string; yLabel: string; series: SerieScientifique[]; bins: number;
  matrix?: number[][]; xLabels?: string[]; yLabels?: string[]; source?: string; sample: boolean;
}
const erreur = () => { throw new Error('figure'); };
const objet = (v: unknown, cles: string[]): Record<string, any> => {
  if (!v || typeof v !== 'object' || Array.isArray(v) || Object.keys(v).some(c => !cles.includes(c))) return erreur();
  return v;
};
const texte = (v: unknown, max = 120): string => typeof v === 'string' && v.length <= max ? v : erreur();
const vecteur = (v: unknown, max = 300): number[] => {
  if (!Array.isArray(v) || !v.length || v.length > max || v.some(n => typeof n !== 'number' || !Number.isFinite(n) || Math.abs(n) > 1e12)) return erreur();
  return [...v];
};
export function lireFigureScientifique(source: string, plotly = false): FigureScientifique {
  if (source.length > SOURCE_MAX) return erreur();
  const d = objet(JSON.parse(source), ['title', 'type', 'xLabel', 'yLabel', 'series', 'bins', 'matrix', 'xLabels', 'yLabels', 'source', 'sample']);
  const title = texte(d.title, 180);
  if (!title.trim() || !['line', 'scatter', 'histogram', 'heatmap'].includes(d.type) || (plotly && d.type === 'heatmap')) return erreur();
  if (d.sample !== undefined && typeof d.sample !== 'boolean') return erreur();
  const bins = d.bins ?? 12;
  if (!Number.isInteger(bins) || bins < 2 || bins > 60) return erreur();
  if (d.series !== undefined && (!Array.isArray(d.series) || d.series.length > 6)) return erreur();
  const series = (d.series ?? []).map((v: unknown) => {
    const s = objet(v, ['name', 'x', 'y', 'errorY']);
    const x = vecteur(s.x), y = s.y === undefined ? undefined : vecteur(s.y);
    const errorY = s.errorY === undefined ? undefined : vecteur(s.errorY);
    if (d.type === 'histogram' ? y !== undefined || errorY !== undefined : !y || y.length !== x.length) return erreur();
    if (errorY && (errorY.length !== x.length || errorY.some(n => n < 0))) return erreur();
    return { name: texte(s.name), x, ...(y ? { y } : {}), ...(errorY ? { errorY } : {}) };
  });
  let matrix: number[][] | undefined, xLabels: string[] | undefined, yLabels: string[] | undefined;
  if (d.type === 'heatmap') {
    if (series.length || !Array.isArray(d.matrix) || !d.matrix.length || d.matrix.length > 20) return erreur();
    matrix = d.matrix.map((l: unknown) => vecteur(l, 20));
    if (matrix!.some(l => l.length !== matrix![0].length)) return erreur();
    const labels = (v: unknown, n: number) => {
      if (v === undefined) return undefined;
      if (!Array.isArray(v) || v.length !== n) return erreur();
      return v.map(t => texte(t));
    };
    xLabels = labels(d.xLabels, matrix![0].length); yLabels = labels(d.yLabels, matrix!.length);
  } else if (!series.length || series.reduce((n: number, s: SerieScientifique) => n + s.x.length, 0) > 300
    || d.matrix !== undefined || d.xLabels !== undefined || d.yLabels !== undefined) return erreur();
  return { title, type: d.type, xLabel: texte(d.xLabel ?? ''), yLabel: texte(d.yLabel ?? ''), series, bins,
    ...(matrix ? { matrix } : {}), ...(xLabels ? { xLabels } : {}), ...(yLabels ? { yLabels } : {}),
    ...(d.source === undefined ? {} : { source: texte(d.source, 500) }), sample: d.sample ?? false };
}

/** Plotly accepte HTML dans les libellés ; seules des chaînes échappées y entrent. */
export const textePlotly = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
export function tracesPlotly(f: FigureScientifique, p: PaletteVisuel) {
  const couleurs = [p.accent, '#4287ab', '#ac7449', '#8470a6', '#58956b', '#b56576'];
  const observations = f.series.flatMap(s => s.x);
  let debut = Math.min(...observations), fin = Math.max(...observations);
  if (debut === fin) { debut -= .5; fin += .5; }
  return f.series.map((s, i) => ({
    name: textePlotly(s.name), x: [...s.x], ...(s.y ? { y: [...s.y] } : {}),
    type: f.type === 'histogram' ? 'histogram' : 'scatter',
    // nbinsx n'est qu'une indication pour Plotly : des bornes explicites
    // gardent le même découpage que Matplotlib et entre les séries.
    ...(f.type === 'histogram' ? { xbins: { start: debut, end: fin, size: (fin - debut) / f.bins }, opacity: .65 }
      : { mode: f.type === 'line' ? 'lines+markers' : 'markers' }),
    marker: { color: couleurs[i], size: 6 }, line: { color: couleurs[i] },
    ...(s.errorY ? { error_y: { type: 'data', array: [...s.errorY], visible: true } } : {}),
  }));
}
