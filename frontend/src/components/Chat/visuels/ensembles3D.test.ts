import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { lireFigure3D, estFigure3D, traces3D } from './figure3D';
import { lireEnsembles3D, sceneEnsembles3D } from './ensembles3D';
import { reconnaitreVisuel } from './formatVisuel';
import type { PaletteVisuel } from './svgSur';

// Le contrat envoyé au modèle et le parseur doivent rester compatibles.
const consigne = readFileSync(resolve(__dirname, '../../../../../src/diapason/server/visuels_chat.py'), 'utf8');
const source = consigne.match(/```diapason-plotly3d\n(\{"title":"Ikigai[\s\S]*?)\n```/)![1];
const donnees = JSON.parse(source);
const palette: PaletteVisuel = { fond: '#101810', texte: '#d2ead2', accent: '#88cc88', bord: '#435043', secondaire: '#a0b0a0', police: 'monospace' };

describe('Les ensembles conceptuels ne deviennent plus un point chiffré', () => {
  it('rend les quatre dimensions et les cinq intersections nommées du contrat Ikigai', () => {
    const f = lireFigure3D(source);
    expect(f.type).toBe('venn3d');
    expect(estFigure3D(f)).toBe(true);
    expect(reconnaitreVisuel('json', source)?.genre).toBe('diapason-plotly3d');
    if (f.type !== 'venn3d') throw new Error('contrat');
    expect(f.sets).toHaveLength(4);
    expect(f.intersections.map(r => r.label)).toEqual(['Passion', 'Profession', 'Vocation', 'Mission']);
    expect(f.centerLabel).toBe('Ikigai');
    expect(f.sample).toBe(false);
    const traces = traces3D(f, palette) as Record<string, any>[];
    const volumes = traces.filter(t => t.type === 'mesh3d');
    expect(volumes).toHaveLength(4);
    for (const volume of volumes) {
      expect(volume.i.length).toBeGreaterThan(100);
      expect(volume.x.every(Number.isFinite)).toBe(true);
      expect(volume.i.concat(volume.j, volume.k).every((i: number) => i >= 0 && i < volume.x.length)).toBe(true);
      expect(Math.max(...volume.z) - Math.min(...volume.z)).toBeGreaterThan(0);
      expect(volume.hoverinfo).toBe('skip');
    }
    const scene = sceneEnsembles3D(f, palette, 340);
    expect(scene.annotations).toHaveLength(9);
    for (const axe of [scene.xaxis, scene.yaxis, scene.zaxis]) expect(axe.visible).toBe(false);
    expect(scene.annotations.every(a => a.font.color === palette.texte)).toBe(true);
  });
  it('refuse un ensemble incomplet, les identifiants ambigus et les relations impossibles', () => {
    const invalides = [
      { ...donnees, sets: donnees.sets.slice(0, 1) },
      { ...donnees, sets: Array(5).fill(donnees.sets[0]) },
      { ...donnees, sets: [donnees.sets[0], donnees.sets[0]] },
      { ...donnees, centerLabel: ' ' },
      { ...donnees, sets: donnees.sets.map((s: object) => ({ ...s, label: '' })) },
      ...[['aimer', 'inconnu'], ['aimer', 'aimer'], ['aimer', 'revenu'], ['aimer', 'talent', 'besoin']].map(sets => ({ ...donnees, intersections: [{ sets, label: 'Faux' }] })),
      { ...donnees, intersections: [donnees.intersections[0], { sets: ['talent', 'aimer'], label: 'Doublon' }] },
      { ...donnees, sample: true }, { ...donnees, series: [{ x: [0], y: [0], z: [0] }] },
      { ...donnees, xLabel: 'Valeur' }, { ...donnees, code: 'eval()' },
    ];
    for (const invalide of invalides) expect(() => lireFigure3D(JSON.stringify(invalide))).toThrow();
  });
  it('accepte aussi deux et trois ensembles, sans imposer Ikigai à tous les schémas', () => {
    for (const n of [2, 3]) {
      const f = lireEnsembles3D({ title: 'Concepts', type: 'venn3d', sets: donnees.sets.slice(0, n), centerLabel: 'En commun' });
      expect(f.sets).toHaveLength(n);
      expect(sceneEnsembles3D(f, palette, 600).annotations).toHaveLength(n + 1);
    }
    const mesure = lireFigure3D(JSON.stringify({ title: 'Mesure unique', type: 'scatter3d', series: [{ name: 'Capteur', x: [2], y: [4], z: [8] }] }));
    expect(mesure.series[0].z).toEqual([8]);
  });
  it('échappe les libellés HTML et adapte la typographie sans modifier le sens', () => {
    const f = lireEnsembles3D({ ...donnees, centerLabel: '<b>Centre</b>' });
    const petit = sceneEnsembles3D(f, palette, 320), grand = sceneEnsembles3D(f, palette, 800);
    expect(petit.annotations[petit.annotations.length - 1].text).toBe('&lt;b&gt;Centre&lt;/b&gt;');
    expect(petit.annotations.map(a => a.text.replace(/<br>/g, ' '))).toEqual(grand.annotations.map(a => a.text.replace(/<br>/g, ' ')));
    expect(petit.annotations[0].font.size).toBeLessThan(grand.annotations[0].font.size);
    expect(donnees.sets[0].label).toBe('Ce que tu aimes');
  });
});
