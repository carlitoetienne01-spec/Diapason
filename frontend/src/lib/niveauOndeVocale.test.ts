import { expect, it } from 'vitest';
import { niveauOndeVocale } from './niveauOndeVocale';
it('reste au repos dans le silence et rend une voix douce visible', () => {
  expect(niveauOndeVocale(new Uint8Array(512).fill(128), 0, 16)).toBe(0);
  const son = Uint8Array.from({ length: 512 }, (_, i) => i % 2 ? 130 : 126);
  expect(niveauOndeVocale(son, 0, 35)).toBeGreaterThan(0.2);
});
it('redescend doucement et ne dépasse jamais le cadre', () => {
  const silence = new Uint8Array(512).fill(128);
  expect(niveauOndeVocale(silence, 1, 16)).toBeGreaterThan(0.85);
  expect(niveauOndeVocale(silence, 1, 1000)).toBeLessThan(0.01);
  expect(niveauOndeVocale(new Uint8Array(512).fill(255), 0.9, 100)).toBeLessThanOrEqual(1);
});
