import { describe, expect, it } from 'vitest';

import { cheminHerite, PAGES_VIE, ROUTES_VIE } from './routesVie';

/**
 * Étape 9 du plan de la phase 1b (docs/development/diapason-mobile.md) : les
 * pages passent sous `/vie/*`, et `/succes/*` redirige. Sans la redirection, la
 * réglette de l'app installée ouvrait un module vide dans le mini-panneau.
 */
describe('cheminHerite', () => {
  it('garde la requête et l’ancre', () => {
    expect(cheminHerite('/succes/tasks?x=1#a'), 'le filtre et l’ancre survivent').toBe(
      '/vie/tasks?x=1#a',
    );
  });

  it('redirige chaque page vers la page du même nom', () => {
    for (const page of PAGES_VIE) {
      expect(cheminHerite(`/succes/${page}`), `/succes/${page}`).toBe(`/vie/${page}`);
    }
  });

  it('accepte le préfixe seul, suivi d’une requête ou d’une ancre', () => {
    expect(cheminHerite('/succes')).toBe('/vie');
    expect(cheminHerite('/succes?x=1')).toBe('/vie?x=1');
    expect(cheminHerite('/succes#a')).toBe('/vie#a');
  });

  it('ne touche à rien qui ne soit pas sous /succes', () => {
    expect(cheminHerite('/vie/tasks'), 'déjà sous le nom neuf').toBeNull();
    expect(cheminHerite('/successeur/tasks'), 'un préfixe voisin n’est pas l’ancien').toBeNull();
    expect(cheminHerite('/settings')).toBeNull();
    expect(cheminHerite('')).toBeNull();
  });
});

describe('ROUTES_VIE', () => {
  it('nomme chaque page une seule fois, sous /vie/', () => {
    expect(new Set(ROUTES_VIE).size, 'aucune page en double').toBe(ROUTES_VIE.length);
    for (const route of ROUTES_VIE) {
      expect(route.startsWith('/vie/'), route).toBe(true);
    }
  });
});
