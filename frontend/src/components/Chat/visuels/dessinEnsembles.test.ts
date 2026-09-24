import { describe, expect, it } from 'vitest';
import { lireEnsembles3D } from './ensembles3D';
import { contourCommun, dessinerEnsembles, positionsEnsembles, RAYON_ENSEMBLES } from './dessinEnsembles';

const f = lireEnsembles3D({ title: 'Ikigai', type: 'venn3d',
  sets: ['Aimer', 'Talent', 'Rémunération', 'Besoins'].map((label, i) => ({ id: `s${i}`, label })),
  intersections: [{ sets: ['s0', 's1'], label: 'Passion' }, { sets: ['s1', 's2'], label: 'Profession' },
    { sets: ['s2', 's3'], label: 'Vocation' }, { sets: ['s3', 's0'], label: 'Mission' }], centerLabel: 'Ikigai' });

describe('La référence Ikigai reste un tracé, pas quatre disques opaques', () => {
  it('remplit seulement l’intersection réelle, sans dépasser aucun cercle', () => {
    for (const n of [2, 3, 4]) {
      const centres = positionsEnsembles(n), contour = contourCommun(n);
      for (const p of contour) {
        const distances = centres.map(c => Math.hypot(p.x - c.x, p.y - c.y));
        expect(Math.max(...distances)).toBeCloseTo(RAYON_ENSEMBLES, 10);
        expect(distances.every(d => d <= RAYON_ENSEMBLES + 1e-12)).toBe(true);
      }
    }
    expect(contourCommun(4)[0].x).toBeCloseTo(.2, 10);
    expect(contourCommun(4)[32].y).toBeCloseTo(.2, 10);
  });
  it('exporte quatre contours, huit textes et le centre rouge sur fond noir', () => {
    const rendu = dessinerEnsembles(f);
    const doc = new DOMParser().parseFromString(rendu.svg, 'image/svg+xml');
    const cercles = [...doc.querySelectorAll('circle')];
    expect(cercles).toHaveLength(4);
    expect(cercles.every(c => c.getAttribute('fill') === 'none')).toBe(true);
    expect(doc.querySelectorAll('rect')).toHaveLength(1);
    expect(doc.querySelector('rect')?.getAttribute('fill')).toBe('#000000');
    expect(doc.querySelectorAll('path')).toHaveLength(1);
    expect(doc.querySelector('path')?.getAttribute('fill')).toBe('#ed161f');
    expect(doc.querySelectorAll('text')).toHaveLength(8);
    expect(doc.querySelector('desc')?.textContent).toContain('Aimer + Talent : Passion');
    expect(doc.querySelector('title')?.textContent).toBe('Ikigai');
    expect(rendu).toMatchObject({ width: 600, height: 640 });
  });
  it('garde les accents et traite les libellés comme du texte, jamais du SVG actif', () => {
    const attaque = '<script>alert(1)</script>';
    const rendu = dessinerEnsembles({ ...f, title: attaque, centerLabel: attaque,
      sets: f.sets.map((s, i) => i ? s : { ...s, label: attaque }) });
    const doc = new DOMParser().parseFromString(rendu.svg, 'image/svg+xml');
    expect(doc.querySelector('script')).toBeNull();
    expect(doc.querySelector('title')?.textContent).toBe(attaque);
    expect(doc.documentElement.textContent).toContain('Rémunération');
  });
});
