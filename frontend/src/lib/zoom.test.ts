import { describe, expect, it } from 'vitest';

import { ZOOM_DEFAUT, ZOOM_MAX, ZOOM_MIN, normaliserZoom, raccourciZoom, zoomEnPourcent, zoomSuivant } from './zoom';

describe('normaliserZoom', () => {
  it('borne, arrondit, et retombe sur 1 quand la valeur ne veut rien dire', () => {
    expect(normaliserZoom(1.2)).toBe(1.2);
    expect(normaliserZoom('1.3')).toBe(1.3);
    expect(normaliserZoom(40)).toBe(ZOOM_MAX);
    expect(normaliserZoom(0.1)).toBe(ZOOM_MIN);
    expect(normaliserZoom(NaN)).toBe(ZOOM_DEFAUT);
    expect(normaliserZoom(null)).toBe(ZOOM_DEFAUT);
    expect(normaliserZoom('abc')).toBe(ZOOM_DEFAUT);
  });
});

describe('zoomSuivant', () => {
  it('avance par dixième sans dérive flottante, et s’arrête aux bornes', () => {
    expect(zoomSuivant(1, 'plus')).toBe(1.1);
    expect(zoomSuivant(1.1, 'plus')).toBe(1.2);
    expect(zoomSuivant(ZOOM_MAX, 'plus')).toBe(ZOOM_MAX);
    expect(zoomSuivant(ZOOM_MIN, 'moins')).toBe(ZOOM_MIN);
    expect(zoomSuivant(1.6, 'reset')).toBe(ZOOM_DEFAUT);
  });
});

describe('raccourciZoom', () => {
  const touche = (key: string, mod: Partial<{ metaKey: boolean; ctrlKey: boolean; altKey: boolean }> = {}) => ({
    metaKey: false,
    ctrlKey: false,
    altKey: false,
    key,
    ...mod,
  });
  it('reconnaît ⌘ +, ⌘ = (même touche), ⌘ −, ⌘ 0 — et Ctrl ailleurs', () => {
    expect(raccourciZoom(touche('=', { metaKey: true }))).toBe('plus');
    expect(raccourciZoom(touche('+', { metaKey: true }))).toBe('plus');
    expect(raccourciZoom(touche('-', { ctrlKey: true }))).toBe('moins');
    expect(raccourciZoom(touche('0', { metaKey: true }))).toBe('reset');
  });
  it('ignore les touches nues et les combinaisons avec Option', () => {
    expect(raccourciZoom(touche('='))).toBeNull();
    expect(raccourciZoom(touche('=', { metaKey: true, altKey: true }))).toBeNull();
    expect(raccourciZoom(touche('k', { metaKey: true }))).toBeNull();
  });
});

describe('zoomEnPourcent', () => {
  it('affiche un entier', () => {
    expect(zoomEnPourcent(1)).toBe('100 %');
    expect(zoomEnPourcent(1.15)).toBe('115 %');
  });
});
