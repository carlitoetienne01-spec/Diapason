import type { Root, Code } from 'mdast';
import type { VFile } from 'vfile';
import { lireFigure3D } from './figure3D';
import { lireFigureScientifique } from './figureScientifique';
import { SOURCE_MAX } from './limitesVisuels';
export { SOURCE_MAX } from './limitesVisuels';

export type GenreVisuel = 'svg' | 'mermaid' | 'diapason-chart' | 'diapason-matplotlib' | 'diapason-plotly' | 'diapason-plotly3d';
export function genreVisuel(langue: string): GenreVisuel | null {
  const nom = langue.toLowerCase();
  const alias: Record<string, GenreVisuel> = { plotly: 'diapason-plotly', matplotlib: 'diapason-matplotlib', chart: 'diapason-chart' };
  return alias[nom] || (['svg', 'mermaid', 'diapason-chart', 'diapason-matplotlib', 'diapason-plotly', 'diapason-plotly3d'].includes(nom) ? nom as GenreVisuel : null);
}

/** Réparation uniquement syntaxique : aucune valeur/colonne ajoutée ou devinée. */
export function nettoyerJsonVisuel(source: string): string {
  if (source.length > SOURCE_MAX) return source;
  let chaine = false, echappe = false, resultat = '';
  const texte = source.replace(/^\uFEFF/, '');
  for (let i = 0; i < texte.length; i++) {
    const c = texte[i];
    if (chaine) {
      resultat += c;
      if (echappe) echappe = false;
      else if (c === '\\') echappe = true;
      else if (c === '"') chaine = false;
      continue;
    }
    if (c === '"') chaine = true;
    if (c === ',') {
      let j = i + 1; while (/\s/.test(texte[j] ?? '') && j < texte.length) j++;
      if (texte[j] === ']' || texte[j] === '}') continue;
    }
    resultat += c;
  }
  try { JSON.parse(resultat); return resultat; } catch { return source; }
}

export function reconnaitreVisuel(langue: string, source: string): { genre: GenreVisuel; source: string } | null {
  const direct = genreVisuel(langue);
  if (direct) return { genre: direct, source: direct.startsWith('diapason-') ? nettoyerJsonVisuel(source) : source };
  if (source.length > SOURCE_MAX) return null;
  if (['xml', 'html', ''].includes(langue.toLowerCase()) && /^\s*<svg\b/.test(source)) return { genre: 'svg', source };
  if (!['json', ''].includes(langue.toLowerCase())) return null;
  const normalisee = nettoyerJsonVisuel(source);
  try { lireGraphique(normalisee); return { genre: 'diapason-chart', source: normalisee }; } catch { /* autre schéma */ }
  try {
    const figure = lireFigureScientifique(normalisee);
    return { genre: figure.type === 'heatmap' ? 'diapason-matplotlib' : 'diapason-plotly', source: normalisee };
  } catch { /* autre schéma */ }
  try { lireFigure3D(normalisee); return { genre: 'diapason-plotly3d', source: normalisee }; } catch { return null; }
}

export function blocFerme(extrait: string): boolean {
  const lignes = extrait.trimEnd().split('\n');
  const debut = /^\s*(`{3,}|~{3,})/.exec(lignes[0] ?? '');
  if (!debut || lignes.length < 2) return false;
  return new RegExp(`^\\s*${debut[1][0]}{${debut[1].length},}\\s*$`).test(lignes[lignes.length - 1]);
}

/** Un bloc incomplet ne doit ni faire clignoter Mermaid, ni afficher ses
 * erreurs à chaque jeton (23/09/2026). La clôture vient du Markdown réel. */
export function remarkVisuels() {
  return (arbre: Root, fichier: VFile) => {
    let nombre = 0;
    const parcourir = (noeud: { type: string; children?: unknown[] }) => {
      if (noeud.type === 'code') {
        const code = noeud as Code;
        const extrait = String(fichier.value).slice(code.position?.start.offset, code.position?.end.offset);
        const ferme = blocFerme(extrait);
        const reconnu = ferme ? reconnaitreVisuel(code.lang ?? '', code.value) : null;
        const genre = reconnu?.genre || genreVisuel(code.lang ?? '');
        if (genre && ++nombre <= 8) {
          if (reconnu) code.value = reconnu.source;
          code.lang = genre;
          code.data = { ...code.data, hProperties: {
            className: [`language-${genre}`, 'no-highlight'],
            'data-visual-complete': ferme ? 'yes' : 'no',
          } };
        }
      }
      for (const enfant of noeud.children ?? []) parcourir(enfant as typeof noeud);
    };
    parcourir(arbre);
  };
}

export interface Graphique {
  title: string;
  type: 'bar' | 'line' | 'area' | 'pie';
  xKey: string;
  series: Array<{ key: string; label: string }>;
  data: Array<Record<string, string | number>>;
  source?: string;
  sample: boolean;
}
const cleSure = (v: unknown): v is string => typeof v === 'string' && /^[a-zA-Z][a-zA-Z0-9_]{0,39}$/.test(v) && !['constructor', 'prototype', '__proto__'].includes(v);
export function lireGraphique(source: string): Graphique {
  if (source.length > SOURCE_MAX) throw new Error('size');
  const g = JSON.parse(source);
  if (!g || typeof g.title !== 'string' || !g.title.trim() || g.title.length > 180
    || !['bar', 'line', 'area', 'pie'].includes(g.type) || !cleSure(g.xKey)
    || !Array.isArray(g.series) || !g.series.length || g.series.length > 8
    || !Array.isArray(g.data) || !g.data.length || g.data.length > 300) throw new Error('chart');
  const cles = new Set<string>([g.xKey]);
  const series = g.series.map((s: Record<string, unknown>) => {
    if (!s || !cleSure(s.key) || cles.has(s.key) || typeof s.label !== 'string' || s.label.length > 120) throw new Error('chart');
    cles.add(s.key);
    return { key: s.key, label: s.label };
  });
  if (g.type === 'pie' && series.length !== 1) throw new Error('chart');
  const data = g.data.map((ligne: Record<string, unknown>) => {
    if (!ligne || typeof ligne[g.xKey] !== 'string' || (ligne[g.xKey] as string).length > 120) throw new Error('chart');
    const valeur: Record<string, string | number> = { [g.xKey]: ligne[g.xKey] as string };
    for (const s of series) {
      const n = ligne[s.key];
      if (typeof n !== 'number' || !Number.isFinite(n) || Math.abs(n) > 1e15 || (g.type === 'pie' && n < 0)) throw new Error('chart');
      valeur[s.key] = n;
    }
    return valeur;
  });
  if (g.type === 'pie' && !data.some((d: Record<string, string | number>) => Number(d[series[0].key]) > 0)) throw new Error('chart');
  return { title: g.title, type: g.type, xKey: g.xKey, series, data, sample: g.sample === true,
    source: typeof g.source === 'string' ? g.source.slice(0, 500) : undefined };
}
