import { textePlotly } from './figureScientifique';
import { positionsEnsembles, contourCommun, etiquettesEnsembles, lignesLibelle, PALETTE_ENSEMBLES } from './dessinEnsembles';
import type { PaletteVisuel } from './svgSur';

export interface FigureEnsembles3D {
  title: string; type: 'venn3d';
  sets: { id: string; label: string }[];
  intersections: { sets: string[]; label: string }[];
  centerLabel: string; source?: string;
  sample: false; xLabel: ''; yLabel: ''; zLabel: ''; series: []; matrix?: never;
}

const erreur = (): never => { throw new Error('ensembles3d'); };
function objet(v: unknown, cles: string[]): Record<string, unknown> {
  if (!v || typeof v !== 'object' || Array.isArray(v) || Object.keys(v).some(k => !cles.includes(k))) return erreur();
  return v as Record<string, unknown>;
}
function libelle(v: unknown, max = 80): string {
  if (typeof v !== 'string' || !v.trim() || v.length > max) return erreur();
  return v.trim();
}
export function lireEnsembles3D(brut: unknown): FigureEnsembles3D {
  const d = objet(brut, ['title', 'type', 'sets', 'intersections', 'centerLabel', 'source']);
  if (d.type !== 'venn3d' || !Array.isArray(d.sets) || d.sets.length < 2 || d.sets.length > 4) return erreur();
  const sets = d.sets.map(v => {
    const s = objet(v, ['id', 'label']);
    const id = libelle(s.id, 32);
    if (!/^[a-zA-Z][a-zA-Z0-9_-]*$/.test(id)) return erreur();
    return { id, label: libelle(s.label) };
  });
  const ids = new Set(sets.map(s => s.id));
  if (ids.size !== sets.length) return erreur();
  const entrees = d.intersections ?? [];
  if (!Array.isArray(entrees) || entrees.length > 6) return erreur();
  const deja = new Set<string>();
  const intersections = entrees.map(v => {
    const s = objet(v, ['sets', 'label']);
    // 23/09/2026 : un point « Centre » passait pour quatre ensembles.
    // Les relations sont désormais explicites, jamais déduites de nombres
    // inventés. Le centre nomme l'ensemble commun ; les paires sont voisines.
    if (!Array.isArray(s.sets) || s.sets.length !== 2 || sets.length === 2
      || s.sets.some(id => typeof id !== 'string' || !ids.has(id)) || s.sets[0] === s.sets[1]) return erreur();
    const paire = s.sets as string[];
    const distance = Math.abs(sets.findIndex(s => s.id === paire[0]) - sets.findIndex(s => s.id === paire[1]));
    if (sets.length === 4 && distance === 2) return erreur();
    const cle = [...paire].sort().join('/');
    if (deja.has(cle)) return erreur();
    deja.add(cle);
    return { sets: [...paire], label: libelle(s.label, 40) };
  });
  return { title: libelle(d.title, 180), type: 'venn3d', sets, intersections,
    centerLabel: libelle(d.centerLabel, 40),
    ...(d.source === undefined ? {} : { source: libelle(d.source, 500) }),
    sample: false, xLabel: '', yLabel: '', zLabel: '', series: [] };
}

export function tracesEnsembles3D(f: FigureEnsembles3D, _p: PaletteVisuel): unknown[] {
  const contour = contourCommun(f.sets.length);
  const traces: unknown[] = [{ type: 'mesh3d', name: textePlotly(f.centerLabel),
    x: [0, ...contour.map(p => p.x)], y: [0, ...contour.map(p => p.y)], z: [0, ...contour.map(() => 0)],
    i: contour.map(() => 0), j: contour.map((_, n) => n + 1), k: contour.map((_, n) => (n + 1) % contour.length + 1),
    color: PALETTE_ENSEMBLES.accent, opacity: 1, lighting: { ambient: 1, diffuse: 0, specular: 0 },
    hoverinfo: 'skip', showlegend: false }];
  for (const [i, c] of positionsEnsembles(f.sets.length).entries()) {
    const angles = Array.from({ length: 129 }, (_, n) => n * Math.PI * 2 / 128);
    traces.push({ type: 'scatter3d', mode: 'lines', name: textePlotly(f.sets[i].label),
      x: angles.map(a => c.x + Math.cos(a)), y: angles.map(a => c.y + Math.sin(a)), z: angles.map(() => .005),
      line: { width: 2, color: PALETTE_ENSEMBLES.bord }, hoverinfo: 'skip', showlegend: false });
  }
  return traces;
}

export function sceneEnsembles3D(f: FigureEnsembles3D, _p: PaletteVisuel, largeur: number) {
  const p = PALETTE_ENSEMBLES, petit = largeur < 420;
  return {
    bgcolor: p.fond,
    camera: { eye: petit ? { x: .052, y: -.52, z: 1.625 } : { x: .04, y: -.4, z: 1.25 }, up: { x: 0, y: 1, z: 0 } },
    aspectmode: 'manual', aspectratio: { x: 1, y: 1, z: .12 },
    xaxis: { visible: false, range: [-1.85, 1.85], fixedrange: true },
    yaxis: { visible: false, range: [-1.85, 1.85], fixedrange: true },
    zaxis: { visible: false, range: [-.22, .22], fixedrange: true },
    annotations: etiquettesEnsembles(f).map(t => ({
      x: t.x, y: t.y, z: .01, text: lignesLibelle(t.texte, t.relation ? 13 : Math.abs(t.x) > .8 ? 11 : 12).map(textePlotly).join('<br>'),
      showarrow: false, xanchor: 'center', yanchor: 'middle', align: 'center',
      font: { family: p.police, size: petit ? (t.relation ? 9 : 10) : 13, color: p.texte },
      bgcolor: 'rgba(0,0,0,0)', borderwidth: 0, borderpad: 0,
    })),
  };
}
