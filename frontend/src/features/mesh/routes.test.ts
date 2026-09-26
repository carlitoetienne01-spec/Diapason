import { describe, expect, it } from 'vitest';

import { ROUTES_VIE } from '../vie/routesVie';
import { MESH_ROUTE_TODAY, resolveSuccessRoute } from './routes';

describe('resolveSuccessRoute', () => {
  it('sends today to the day view, not the statistics screen', () => {
    expect(resolveSuccessRoute('success://today')).toEqual({ path: MESH_ROUTE_TODAY });
    expect(MESH_ROUTE_TODAY).toBe('/vie/planner');
  });

  it('opens each Diapason screen the mesh vocabulary names', () => {
    expect(resolveSuccessRoute('success://tasks')).toEqual({ path: '/vie/tasks' });
    expect(resolveSuccessRoute('success://projects')).toEqual({ path: '/vie/projects' });
    expect(resolveSuccessRoute('success://notes')).toEqual({ path: '/vie/notes' });
    expect(resolveSuccessRoute('success://habits')).toEqual({ path: '/vie/habits' });
  });

  it('carries an id only to the screens that can highlight one', () => {
    expect(resolveSuccessRoute('success://projects/p-1')).toEqual({
      path: '/vie/projects',
      selection: { kind: 'project', id: 'p-1' },
    });
    expect(resolveSuccessRoute('success://notes/n-9')).toEqual({
      path: '/vie/notes',
      selection: { kind: 'note', id: 'n-9' },
    });
  });

  it('drops an id no screen could act on rather than pretending', () => {
    // Neither page has per-item selection today. Dropping it here is visible;
    // passing it on would make the command look honoured when nothing happened.
    expect(resolveSuccessRoute('success://tasks/t-42')).toEqual({ path: '/vie/tasks' });
    expect(resolveSuccessRoute('success://habits/h-7')).toEqual({ path: '/vie/habits' });
  });

  it('treats an unreadable id as an unknown route rather than throwing', () => {
    // decodeURIComponent throws URIError on a malformed escape. Left to
    // throw, it escaped the inbox loop — and the inbox drains on read, so
    // every entry after the bad one vanished with no trace.
    expect(() => resolveSuccessRoute('success://notes/%')).not.toThrow();
    expect(resolveSuccessRoute('success://notes/%')).toBeNull();
    expect(resolveSuccessRoute('success://projects/%E0%A4%A')).toBeNull();
    expect(resolveSuccessRoute('success://notes/%zz')).toBeNull();
  });

  it('refuses a route it does not recognise instead of guessing', () => {
    expect(resolveSuccessRoute('success://settings')).toBeNull();
    expect(resolveSuccessRoute('success://tasks/../../etc/passwd')).toBeNull();
    expect(resolveSuccessRoute('diapason://research/42')).toBeNull();
    expect(resolveSuccessRoute('https://example.com')).toBeNull();
    expect(resolveSuccessRoute('')).toBeNull();
    expect(resolveSuccessRoute('n’importe quoi')).toBeNull();
  });

  it('tolerates the shapes a real sender produces', () => {
    expect(resolveSuccessRoute('  success://today  ')).toEqual({ path: MESH_ROUTE_TODAY });
    expect(resolveSuccessRoute('success://today/')).toEqual({ path: MESH_ROUTE_TODAY });
    expect(resolveSuccessRoute('SUCCESS://TODAY')).toEqual({ path: MESH_ROUTE_TODAY });
    expect(resolveSuccessRoute('success://notes/n%20espace')).toEqual({
      path: '/vie/notes',
      selection: { kind: 'note', id: 'n espace' },
    });
  });

  it('never returns a path outside the app', () => {
    for (const route of [
      'success://tasks',
      'success://projects/p1',
      'success://notes/n1',
      'success://habits/h1',
      'success://today',
    ]) {
      const target = resolveSuccessRoute(route);
      expect(target?.path.startsWith('/vie/')).toBe(true);
      // 25/09/2026 : une page que l'application ne sert pas rendait un module
      // vide sur ce bureau, alors que l'émetteur avait lu un SUCCESS.
      expect(ROUTES_VIE, `${route} doit ouvrir une page servie`).toContain(target?.path);
    }
  });
});

describe('les deux schémas du maillage', () => {
  // Plan 1b, étape 12 (25/09/2026) : le schéma devient vie://. Une fenêtre qui
  // ne connaîtrait que success:// laisserait tomber le premier vie:// d'un
  // émetteur renommé, après que Python eut répondu SUCCESS en son nom. Même
  // tableau que test_executor.py et mesh_routes_test.dart.
  const CHEMINS: Array<[string, ReturnType<typeof resolveSuccessRoute>]> = [
    ['today', { path: MESH_ROUTE_TODAY }],
    ['tasks', { path: '/vie/tasks' }],
    ['projects/p-1', { path: '/vie/projects', selection: { kind: 'project', id: 'p-1' } }],
    ['habits/h7', { path: '/vie/habits' }],
    ['notes/n%20espace', { path: '/vie/notes', selection: { kind: 'note', id: 'n espace' } }],
  ];

  for (const schema of ['success', 'vie', 'VIE', 'Success']) {
    for (const [chemin, attendu] of CHEMINS) {
      it(`${schema}://${chemin} ouvre le même écran que success://${chemin}`, () => {
        expect(resolveSuccessRoute(`${schema}://${chemin}`)).toEqual(attendu);
      });
    }
  }

  it("n'ouvre rien de plus sous le nouveau schéma", () => {
    for (const route of [
      'vie://reglages',
      'vie://tasks/../../etc/passwd',
      'vie://notes/%',
      'diapason://today',
      'vies://today',
      'xvie://today',
      'succes://today',
    ]) {
      expect(resolveSuccessRoute(route), `${route} doit rester refusée`).toBeNull();
    }
  });
});
