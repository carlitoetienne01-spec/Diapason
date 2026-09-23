import { textePlotly } from './figureScientifique';
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

function centres(f: FigureEnsembles3D) {
  return f.sets.map((_, i) => {
    const a = Math.PI / 2 + i * 2 * Math.PI / f.sets.length;
    return { x: .72 * Math.cos(a), y: .72 * Math.sin(a) };
  });
}

// 48 segments × 2 faces : un disque arrondi en relief reste fluide dans
// le mini-panneau ; aucune coordonnée de cette géométrie n'est une mesure.
export function tracesEnsembles3D(f: FigureEnsembles3D, p: PaletteVisuel): unknown[] {
  const couleurs = [p.accent, '#568eab', '#a87d53', '#7e9a73'];
  return centres(f).flatMap((c, indice) => {
    const x: number[] = [], y: number[] = [], z: number[] = [];
    const i: number[] = [], j: number[] = [], k: number[] = [];
    const segments = 48, rayon = 1.04, epaisseur = .08;
    for (let face = 0; face < 2; face++) {
      for (let n = 0; n < segments; n++) {
        const a = n * Math.PI * 2 / segments;
        x.push(c.x + rayon * Math.cos(a)); y.push(c.y + rayon * Math.sin(a)); z.push(face ? epaisseur : -epaisseur);
      }
      x.push(c.x); y.push(c.y); z.push(face ? epaisseur : -epaisseur);
    }
    for (let n = 0; n < segments; n++) {
      const suivant = (n + 1) % segments, haut = segments + 1;
      i.push(segments, haut + segments, n, n);
      j.push(suivant, haut + n, suivant, haut + suivant);
      k.push(n, haut + suivant, haut + suivant, haut + n);
    }
    const nom = textePlotly(f.sets[indice].label), couleur = couleurs[indice];
    const contour = Array.from({ length: segments + 1 }, (_, n) => n % segments);
    return [
      { type: 'mesh3d', name: nom, x, y, z, i, j, k, color: couleur, opacity: .19,
        flatshading: false, lighting: { ambient: .9, diffuse: .3, specular: .1 },
        hoverinfo: 'skip', showlegend: false },
      { type: 'scatter3d', mode: 'lines', name: nom,
        x: contour.map(n => x[n]), y: contour.map(n => y[n]), z: contour.map(() => epaisseur),
        line: { width: 3, color: couleur }, hoverinfo: 'skip', showlegend: false },
    ];
  });
}

function lignes(texte: string, limite: number) {
  const mots = texte.split(/\s+/), lignes: string[] = [''];
  for (const mot of mots) {
    const n = lignes.length - 1;
    if (lignes[n] && lignes[n].length + mot.length + 1 > limite) lignes.push(mot);
    else lignes[n] += (lignes[n] ? ' ' : '') + mot;
  }
  return lignes.map(textePlotly).join('<br>');
}

export function sceneEnsembles3D(f: FigureEnsembles3D, p: PaletteVisuel, largeur: number) {
  const positions = centres(f), petit = largeur < 420;
  const annotation = (x: number, y: number, texte: string, centre = false) => ({
    x, y, z: .12, text: lignes(texte, centre ? 18 : petit ? 14 : 17), showarrow: false,
    xanchor: 'center', yanchor: 'middle', align: 'center',
    font: { family: p.police, size: petit ? (centre ? 13 : 11) : (centre ? 16 : 13), color: p.texte },
    bgcolor: p.fond, borderpad: centre ? 6 : 3,
    ...(centre ? { bordercolor: p.accent, borderwidth: 1 } : {}),
  });
  return {
    bgcolor: p.fond,
    camera: { eye: petit ? { x: .052, y: -.52, z: 1.625 } : { x: .04, y: -.4, z: 1.25 }, up: { x: 0, y: 1, z: 0 } },
    aspectmode: 'manual', aspectratio: { x: 1, y: 1, z: .12 },
    xaxis: { visible: false, range: [-1.85, 1.85], fixedrange: true },
    yaxis: { visible: false, range: [-1.85, 1.85], fixedrange: true },
    zaxis: { visible: false, range: [-.22, .22], fixedrange: true },
    annotations: [
      ...f.sets.map((s, i) => annotation(positions[i].x * (petit ? 1.9 : 1.72), positions[i].y * (petit ? 1.9 : 1.72), s.label)),
      ...f.intersections.map(r => {
        const a = positions[f.sets.findIndex(s => s.id === r.sets[0])];
        const b = positions[f.sets.findIndex(s => s.id === r.sets[1])];
        return annotation((a.x + b.x) * .87, (a.y + b.y) * .87, r.label);
      }),
      annotation(0, 0, f.centerLabel, true),
    ],
  };
}
