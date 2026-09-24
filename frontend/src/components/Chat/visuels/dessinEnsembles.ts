import type { FigureEnsembles3D } from './ensembles3D';
import { nettoyerSvg, type PaletteVisuel, type SvgPret } from './svgSur';

// Référence de Carlito du 24/09/2026 : une seule couleur porte du sens,
// le rouge de la zone commune. Le cadre du chat conserve son propre thème.
export const PALETTE_ENSEMBLES: PaletteVisuel = {
  fond: '#000000', texte: '#e7e9e8', accent: '#ed161f',
  bord: '#d1d6d3', secondaire: '#bec4c0', police: 'monospace',
};
export const RAYON_ENSEMBLES = 1;
export function positionsEnsembles(nombre: number) {
  return Array.from({ length: nombre }, (_, i) => {
    const a = Math.PI / 2 + i * 2 * Math.PI / nombre;
    // Distance/rayon = 0,8 : petite intersection centrale comme sur la
    // référence, au lieu des larges lentilles de la première version.
    return { x: .8 * Math.cos(a), y: .8 * Math.sin(a) };
  });
}

export function contourCommun(nombre: number) {
  const centres = positionsEnsembles(nombre);
  // 128 segments : l'écart maximal au cercle reste inférieur à 0,05 px
  // dans le dessin de 600 px, sans dépendre d'un moteur booléen externe.
  return Array.from({ length: 128 }, (_, i) => {
    const angle = i * 2 * Math.PI / 128, x = Math.cos(angle), y = Math.sin(angle);
    const distance = Math.min(...centres.map(c => {
      const projection = x * c.x + y * c.y;
      return projection + Math.sqrt(projection ** 2 + RAYON_ENSEMBLES ** 2 - c.x ** 2 - c.y ** 2);
    }));
    return { x: x * distance, y: y * distance };
  });
}

export function lignesLibelle(texte: string, limite: number): string[] {
  const mots = texte.split(/\s+/).flatMap(m => m.match(new RegExp(`.{1,${limite}}`, 'gu')) ?? []);
  const lignes: string[] = [''];
  for (const mot of mots) {
    const n = lignes.length - 1;
    if (lignes[n] && lignes[n].length + mot.length + 1 > limite) lignes.push(mot);
    else lignes[n] += (lignes[n] ? ' ' : '') + mot;
  }
  return lignes;
}

export function etiquettesEnsembles(f: FigureEnsembles3D) {
  const centres = positionsEnsembles(f.sets.length);
  return [
    ...f.sets.map((s, i) => ({ x: centres[i].x * 1.52, y: centres[i].y * 1.67, texte: s.label, relation: false })),
    ...f.intersections.map(r => {
      const a = centres[f.sets.findIndex(s => s.id === r.sets[0])];
      const b = centres[f.sets.findIndex(s => s.id === r.sets[1])];
      return { x: (a.x + b.x) * .6, y: (a.y + b.y) * .6, texte: r.label, relation: true };
    }),
  ];
}

export function dessinerEnsembles(f: FigureEnsembles3D): SvgPret {
  const xml = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  const x = (v: number) => 300 + v * 140, y = (v: number) => 350 - v * 140;
  const contour = contourCommun(f.sets.length).map((p, i) => `${i ? 'L' : 'M'}${x(p.x).toFixed(3)},${y(p.y).toFixed(3)}`).join(' ') + ' Z';
  const cercles = positionsEnsembles(f.sets.length).map(c => `<circle cx="${x(c.x)}" cy="${y(c.y)}" r="140" fill="none" stroke="${PALETTE_ENSEMBLES.bord}" stroke-width="2"/>`).join('');
  const textes = etiquettesEnsembles(f).map(t => {
    const lignes = lignesLibelle(t.texte, t.relation ? 13 : Math.abs(t.x) > .8 ? 11 : 12), taille = t.relation ? 14 : 16;
    const debut = y(t.y) - (lignes.length - 1) * (taille + 4) / 2;
    // Le 24/09/2026, svg2pdf décalait les tspan centrés par rapport au PNG.
    // Une position par ligne garde le même ancrage dans les deux exports.
    return lignes.map((l, i) => `<text x="${x(t.x)}" y="${debut + i * (taille + 4) + taille * .32}" text-anchor="middle" font-size="${taille}" fill="${PALETTE_ENSEMBLES.texte}">${xml(l)}</text>`).join('');
  }).join('');
  const description = `${f.sets.map(s => s.label).join(' ; ')}. ${f.intersections.map(r => `${r.sets.map(id => f.sets.find(s => s.id === id)!.label).join(' + ')} : ${r.label}`).join('. ')}. ${f.centerLabel}${f.source ? '. ' + f.source : ''}`;
  return nettoyerSvg(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 640"><title>${xml(f.title)}</title><desc>${xml(description)}</desc><rect width="600" height="640" fill="${PALETTE_ENSEMBLES.fond}"/><path d="${contour}" fill="${PALETTE_ENSEMBLES.accent}"/>${cercles}${textes}</svg>`, PALETTE_ENSEMBLES);
}
