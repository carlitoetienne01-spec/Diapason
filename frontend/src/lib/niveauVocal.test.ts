import { describe, expect, it } from 'vitest';
import { NiveauVocal, rmsVocal } from './niveauVocal';

function onde(amplitude: number) {
  return Float32Array.from({ length: 1024 }, (_, i) => amplitude * Math.sin(2 * Math.PI * i / 32));
}

describe('§100 — la forme suit l’énergie du son et non des bandes FFT vides', () => {
  it('calcule un vrai RMS et reste finie sur une entrée invalide', () => {
    expect(rmsVocal(onde(0.1))).toBeCloseTo(0.1 / Math.sqrt(2), 6);
    expect(rmsVocal(new Float32Array())).toBe(0);
    expect(rmsVocal(new Float32Array([NaN]))).toBe(0);
  });
  it('réagit dès la première lecture à une voix faible, sans bruit amplifié au repos', () => {
    const niveau = new NiveauVocal();
    for (let i = 0; i < 1000; i++) expect(niveau.lire(onde(0.001), i * 16)).toBe(0);
    expect(niveau.lire(onde(0.025), 16001)).toBeGreaterThan(0.5);
    expect(niveau.lire(onde(0), 16017)).toBe(0);
  });
  it('reste bornée sur une voix forte et récupère après un cri', () => {
    const niveau = new NiveauVocal();
    expect(niveau.lire(onde(1), 0)).toBe(1);
    expect(niveau.lire(onde(0.025), 30_000)).toBeGreaterThan(0.5);
    expect(niveau.lire(onde(Infinity), 30_016)).toBe(0);
  });
  it('adapte le pic de la même manière à 30 et à 60 images par seconde', () => {
    const lent = new NiveauVocal(); const rapide = new NiveauVocal();
    lent.lire(onde(0.5), 0); rapide.lire(onde(0.5), 0);
    for (let i = 1; i <= 30; i++) lent.lire(onde(0), i * 1000 / 30);
    for (let i = 1; i <= 60; i++) rapide.lire(onde(0), i * 1000 / 60);
    expect(lent.lire(onde(0.025), 1100)).toBeCloseTo(rapide.lire(onde(0.025), 1100), 6);
  });
});
