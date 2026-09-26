import { describe, expect, it } from 'vitest';

import { CHEMINS_DES_REGLAGES } from '../../lib/barre';
import { ROUTES_VIE } from '../vie/routesVie';
import { translate } from '../../i18n/translate';
import { PAGES_ROUE, indexDeLaPage } from './pagesRoue';

describe('La roue dessert toutes les pages de la barre latérale (§82)', () => {
  it('chaque page de la vie, chaque onglet des Réglages et la Discussion y sont', () => {
    // Échec évité (26/09/2026) : au téléphone, la roue REMPLACE la barre ;
    // une page ajoutée à la barre et oubliée ici n'aurait plus eu de chemin
    // au toucher.
    const chemins = PAGES_ROUE.map((p) => p.chemin);
    for (const attendu of ['/', ...ROUTES_VIE, ...CHEMINS_DES_REGLAGES]) {
      expect(chemins, `${attendu} doit être dans la roue`).toContain(attendu);
    }
  });

  it('aucune page n’y figure deux fois', () => {
    const chemins = PAGES_ROUE.map((p) => p.chemin);
    expect(new Set(chemins).size, 'une page en double fausserait la rotation').toBe(chemins.length);
  });

  it('l’ordre commence comme Carlito l’a décidé', () => {
    expect(PAGES_ROUE.slice(0, 11).map((p) => p.chemin)).toEqual([
      '/',
      '/vie/dashboard',
      '/vie/planner',
      '/vie/tasks',
      '/vie/projects',
      '/vie/finances',
      '/vie/habits',
      '/vie/notes',
      '/vie/year-review',
      '/settings',
      '/devices',
    ]);
  });

  it('chaque nom est traduit en français et en anglais', () => {
    for (const p of PAGES_ROUE) {
      for (const langue of ['fr', 'en'] as const) {
        const nom = translate(langue, p.cle);
        expect(nom, `${p.cle} doit être traduit (${langue})`).not.toBe(p.cle);
      }
    }
  });
});

describe('La page courante est l’élément allumé à l’ouverture', () => {
  it('un chemin connu allume sa page', () => {
    expect(PAGES_ROUE[indexDeLaPage('/vie/tasks')].chemin).toBe('/vie/tasks');
    expect(PAGES_ROUE[indexDeLaPage('/logs')].chemin).toBe('/logs');
  });

  it('un sous-chemin allume sa page, un inconnu la Discussion', () => {
    expect(PAGES_ROUE[indexDeLaPage('/vie/notes/abc')].chemin).toBe('/vie/notes');
    expect(indexDeLaPage('/nulle-part'), 'jamais aucun élément allumé').toBe(0);
  });
});
