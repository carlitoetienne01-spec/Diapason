/**
 * Turning a `success://` route from another device into a screen in this one.
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

/** `success://today` is the day view — the planner, not the stats dashboard. */
export const MESH_ROUTE_TODAY = '/succes/planner';

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

const SUCCESS_ROUTE = /^success:\/\/([a-z]+)(?:\/([^/?#]+))?\/?$/i;

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
  tasks: '/succes/tasks',
  projects: '/succes/projects',
  habits: '/succes/habits',
  notes: '/succes/notes',
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
  const id = match[2] ? decodeURIComponent(match[2]) : '';
  const path = PATHS[kind];
  if (!path) return null;

  const selectionKind = SELECTABLE[kind];
  if (selectionKind && id) {
    return { path, selection: { kind: selectionKind, id } };
  }
  return { path };
}
