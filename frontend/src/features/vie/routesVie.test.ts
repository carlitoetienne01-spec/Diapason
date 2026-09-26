import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

import { cheminHerite, cibleHeritee, PAGES_VIE, ROUTES_VIE } from './routesVie';

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

/**
 * Étape 10 : la réglette native (`reglette.html`) et les noms de la pastille
 * du mini-panneau (`__diapNoms`, lib.rs) sont écrits hors de React, et
 * compilés dans l'app. Aucun des deux ne passe par `tsc` : une route qui ne
 * suit pas le renommage n'y casse rien de visible au build, elle ouvre un
 * module vide ou fait dire « Diapason » à la pastille au lieu du nom de la
 * page. Ce test les lit comme du texte et les confronte à la liste d'App.tsx.
 */
describe('la réglette et le mini-panneau suivent les routes d’App.tsx', () => {
  // vitest tourne depuis `frontend/`, comme le cliquet d'appelsApi.test.ts.
  const reglette = readFileSync(join(process.cwd(), 'src-tauri/src/reglette.html'), 'utf-8');
  const librs = readFileSync(join(process.cwd(), 'src-tauri/src/lib.rs'), 'utf-8');

  const modules = [...reglette.matchAll(/\{route:'([^']+)'/g)]
    .map((m) => m[1])
    .filter((route) => route !== '/');
  const ligneNoms = librs.split('\n').find((ligne) => ligne.includes('var __diapNoms='));
  const noms = [...(ligneNoms ?? '').matchAll(/'(\/[^']*)':'[^']+'/g)].map((m) => m[1]);

  it('les deux fichiers ont bien été lus', () => {
    expect(modules.length, 'la réglette a huit modules').toBe(8);
    expect(ligneNoms, '__diapNoms est introuvable dans lib.rs').toBeDefined();
  });

  it('chaque module de la réglette ouvre une page qu’App.tsx sert', () => {
    for (const route of modules) {
      expect(ROUTES_VIE, `réglette : ${route}`).toContain(route);
    }
  });

  it('chaque module a son nom pour la pastille du mini-panneau', () => {
    for (const route of modules) {
      expect(noms, `__diapNoms ne nomme pas ${route}`).toContain(route);
    }
  });

  it('chaque nom de __diapNoms désigne une page servie, ou une redirection vers elle', () => {
    for (const route of noms.filter((r) => r !== '/')) {
      const servie = route.startsWith('/succes/') ? cheminHerite(route) : route;
      expect(ROUTES_VIE, `__diapNoms : ${route}`).toContain(servie);
    }
  });
});

/**
 * La redirection elle-même vit dans `App.tsx`, qu'aucun test ne monte (aucun
 * test de composant dans ce dépôt). Contre-épreuve du 25/09/2026 : retirer les
 * deux `<Route path="succes…">`, ou ne passer que `${pathname}`, laissait les
 * 1 274 vitest verts — et la réglette déjà installée, qui ouvre encore
 * `/succes/tasks`, aurait montré un module vide.
 */
describe('App.tsx redirige /succes/* vers /vie/*', () => {
  const app = readFileSync(join(process.cwd(), 'src/App.tsx'), 'utf-8');

  it('les deux routes héritées mènent à la redirection', () => {
    for (const chemin of ['succes', 'succes/*']) {
      expect(app, `<Route path="${chemin}"> manque`).toContain(
        `<Route path="${chemin}" element={<RedirectionHeritee />} />`,
      );
    }
  });

  it('la redirection donne le lieu ENTIER à cibleHeritee', () => {
    const corps = app.match(/function RedirectionHeritee\(\) \{([\s\S]*?)\n\}/)?.[1] ?? '';
    expect(corps, 'RedirectionHeritee est introuvable').not.toBe('');
    expect(corps, 'le lieu doit passer tel quel, requête et ancre comprises').toMatch(
      /cibleHeritee\(useLocation\(\)\)/,
    );
  });

  it('cibleHeritee garde la requête et l’ancre', () => {
    expect(cibleHeritee({ pathname: '/succes/notes', search: '?q=a', hash: '#n1' })).toBe(
      '/vie/notes?q=a#n1',
    );
    expect(cibleHeritee({ pathname: '/successeur', search: '', hash: '' }), 'préfixe voisin').toBe('/');
  });
});
