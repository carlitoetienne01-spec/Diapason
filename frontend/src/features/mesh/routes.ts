/**
 * Turning a `success://` or `vie://` route from another device into a screen
 * in this one.
 *
 * The mesh speaks a stable, platform-independent vocabulary (§25) precisely so
 * that a phone and a laptop can name the same thing without knowing each
 * other's navigation. That translation lives here, in one table, and nowhere
 * else — a second copy would drift and the two devices would disagree about
 * what "mes tâches" means.
 *
 * Deliberately free of React so it can be tested on its own.
 *
 * Parsed with a regex rather than `new URL()`: host parsing for non-special
 * schemes differs between WebKit and Chromium, and this app ships on both.
 */

/** `vie://today` (like `success://today`) is the day view, not the dashboard. */
export const MESH_ROUTE_TODAY = '/vie/planner';

export type MeshSelectionKind = 'project' | 'note';

export interface MeshSelection {
  kind: MeshSelectionKind;
  id: string;
}

export interface MeshNavTarget {
  path: string;
  /**
   * Present only where the destination screen can actually act on it. A
   * selection the page would ignore is worse than none: it makes the command
   * look honoured when nothing was highlighted.
   */
  selection?: MeshSelection;
}

/**
 * Two schemes, one vocabulary. 25/09/2026: the domain was renamed `vie` and the
 * scheme follows, but a window that knew only `success://` would drop the first
 * `vie://` a renamed sender emits — after the Python receiver had answered
 * SUCCESS on its behalf. Every receiver accepts both before any sender
 * switches; `tests/contract/test_routes_du_maillage.py` holds this pattern,
 * `mesh/executor.py` and `mesh_routes.dart` to the same set. `diapason://`
 * stays out: it is the OS deep-link namespace, not a mesh route.
 */
const SUCCESS_ROUTE = /^(?:success|vie):\/\/([a-z]+)(?:\/([^/?#]+))?\/?$/i;

/**
 * Screens that can highlight one item. Tasks and habits are absent on
 * purpose: neither page has per-item selection today, so an id would be
 * silently dropped either way — better to drop it here, visibly, than to
 * pretend downstream.
 */
const SELECTABLE: Record<string, MeshSelectionKind> = {
  projects: 'project',
  notes: 'note',
};

const PATHS: Record<string, string> = {
  today: MESH_ROUTE_TODAY,
  tasks: '/vie/tasks',
  projects: '/vie/projects',
  habits: '/vie/habits',
  notes: '/vie/notes',
};

/**
 * @returns the screen to open, or `null` for a route this app does not
 * recognise. Null is the honest answer for an unknown route: navigating
 * somewhere approximate would be worse than doing nothing and saying so.
 */
export function resolveSuccessRoute(route: string): MeshNavTarget | null {
  const match = SUCCESS_ROUTE.exec(String(route ?? '').trim());
  if (!match) return null;

  const kind = match[1].toLowerCase();
  // decodeURIComponent throws URIError on a malformed escape — `%` on its own
  // is enough, and the id group admits it. Left to throw, it escaped all the
  // way out of the inbox loop, and since the inbox drains on read, every
  // entry after the bad one was lost silently. An unreadable id is just an
  // unknown route.
  let id = '';
  if (match[2]) {
    try {
      id = decodeURIComponent(match[2]);
    } catch {
      return null;
    }
  }
  const path = PATHS[kind];
  if (!path) return null;

  const selectionKind = SELECTABLE[kind];
  if (selectionKind && id) {
    return { path, selection: { kind: selectionKind, id } };
  }
  return { path };
}

/**
 * Every screen a mesh route can open, once each. The phone shell may ask the
 * bundle to show one of these and nothing else.
 */
export const MESH_PATHS: readonly string[] = [...new Set(Object.values(PATHS))];

const SELECTION_OF_PATH: Record<string, MeshSelectionKind> = Object.fromEntries(
  Object.entries(SELECTABLE).map(([kind, selection]) => [PATHS[kind], selection]),
);

/**
 * A `naviguer` request from the phone shell, checked against this table.
 *
 * 26/09/2026 (phase 3, step 9): on the phone the mesh command reaches the
 * Flutter shell, not the Python inbox, and the shell translates the route
 * itself (`mesh_routes.dart`, held to `vecteurs_routes.json`). The bundle
 * still refuses a path it would never have produced — any page could post on
 * the channel before the shell's origin check existed, and a path outside the
 * table would open a screen the sender never named.
 */
export function readShellNavigation(donnees: unknown): MeshNavTarget | null {
  if (!donnees || typeof donnees !== 'object') return null;
  const { path, selection } = donnees as { path?: unknown; selection?: unknown };
  if (typeof path !== 'string' || !MESH_PATHS.includes(path)) return null;
  if (selection === undefined || selection === null) return { path };
  if (typeof selection !== 'object') return null;
  const { kind, id } = selection as { kind?: unknown; id?: unknown };
  const expected = SELECTION_OF_PATH[path];
  if (!expected || kind !== expected || typeof id !== 'string' || !id) return null;
  return { path, selection: { kind: expected, id } };
}
