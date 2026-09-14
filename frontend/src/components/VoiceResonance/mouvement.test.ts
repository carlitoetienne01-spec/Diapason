import { describe, expect, it } from 'vitest';
import type { VoiceLiveState } from '../../hooks/useVoiceLive';
import { approcher, DENSITES, energieVocale, pointsDesVoiles, PROFILS } from './mouvement';
import type { AIQuality } from '../AIEntity/types';

describe('Résonance — §5, le mouvement ne prétend pas entendre un son absent', () => {
  it.each<VoiceLiveState>(['idle', 'connecting', 'error'])('ignore le son en état %s', (etat) => {
    expect(energieVocale(1, etat, false)).toBe(0);
  });
  it.each<VoiceLiveState>(['listening', 'speaking'])('suit le niveau réel en état %s', (etat) => {
    expect(energieVocale(0, etat, false)).toBe(0);
    expect(energieVocale(0.03, etat, false)).toBe(0);
    expect(energieVocale(0.8, etat, false)).toBeGreaterThan(energieVocale(0.2, etat, false));
    expect(energieVocale(1, etat, false)).toBe(1);
    expect(energieVocale(1, etat, true)).toBe(0);
  });
  it('ne transforme pas un niveau invalide en saut du volume', () => {
    for (const niveau of [NaN, Infinity, -1]) expect(energieVocale(niveau, 'speaking', false)).toBe(0);
    expect(energieVocale(4, 'speaking', false)).toBe(1);
  });
  it('se resserre pour écouter et s’ouvre pour répondre', () => {
    expect(PROFILS.listening.taille).toBeLessThan(PROFILS.idle.taille);
    expect(PROFILS.speaking.taille).toBeGreaterThan(PROFILS.idle.taille);
    expect(PROFILS.error.vitesse).toBe(0);
  });
  it('lisse de la même façon à 30 et 60 images par seconde', () => {
    let trente = 0, soixante = 0;
    for (let i = 0; i < 30; i++) trente = approcher(trente, 1, 1/30, 0.18);
    for (let i = 0; i < 60; i++) soixante = approcher(soixante, 1, 1/60, 0.18);
    expect(trente).toBeCloseTo(soixante, 8);
    expect(trente).toBeLessThanOrEqual(1);
  });
  it.each<AIQuality>(['low', 'medium', 'high', 'ultra'])('ferme les trois voiles sans amas aux pôles : %s', (qualite) => {
    const points = pointsDesVoiles(qualite);
    const [x, y] = DENSITES[qualite];
    expect(points.length).toBe(x*y*3*3);
    for (let i = 0; i < points.length; i += 3) {
      if (!(points[i] >= 0 && points[i] < Math.PI*2 && points[i+1] > 0 && points[i+1] < Math.PI && points[i+2] <= 2)) {
        throw new Error(`Point hors du voile à l’index ${i}`);
      }
    }
    expect(pointsDesVoiles(qualite)).toEqual(points);
  });
});
