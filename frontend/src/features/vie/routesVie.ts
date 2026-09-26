/**
 * Les pages du domaine « vie », et le chemin qu'elles avaient avant.
 *
 * 25/09/2026 : les pages quittent `/succes/*` pour `/vie/*`. Mais la réglette
 * compilée dans l'app déjà installée ouvre encore `127.0.0.1:8000/succes/tasks`
 * dans le mini-panneau, et un signet ou un lien collé dans une note garde
 * l'ancien chemin. Sans redirection, ces ouvertures montraient un module vide,
 * sans un mot : aucune route ne correspondait plus.
 *
 * La liste vit ici, et non dans `App.tsx`, pour qu'un test puisse la lire sans
 * monter React : c'est à elle que la réglette et `__diapNoms` (lib.rs) sont
 * confrontés.
 */

/** Chaque page, sous `/vie/`. `App.tsx` en tire ses routes, une par une. */
export const PAGES_VIE = [
  'planner',
  'dashboard',
  'tasks',
  'projects',
  'finances',
  'habits',
  'notes',
  'year-review',
  'sync',
] as const;

export type PageVie = (typeof PAGES_VIE)[number];

export const PREFIXE_VIE = '/vie';
export const PREFIXE_HERITE = '/succes';

/** Les chemins complets que l'application sert, `/vie/tasks` compris. */
export const ROUTES_VIE: readonly string[] = PAGES_VIE.map((page) => `${PREFIXE_VIE}/${page}`);

/**
 * `/succes/tasks?x=1#a` → `/vie/tasks?x=1#a`. La requête et l'ancre sont
 * gardées : une note ouverte par `#` ou un filtre posé en `?` survivent au
 * changement de nom.
 *
 * @returns `null` pour un chemin qui n'est pas sous `/succes` — rien à
 * rediriger, et deviner une destination serait pire que ne rien faire.
 */
export function cheminHerite(chemin: string): string | null {
  const texte = String(chemin ?? '');
  if (texte !== PREFIXE_HERITE && !/^\/succes(?=[/?#])/.test(texte)) return null;
  return PREFIXE_VIE + texte.slice(PREFIXE_HERITE.length);
}

/**
 * Où envoyer une ouverture de `/succes/*`, à partir du lieu que donne
 * `useLocation()`. Tirée d'`App.tsx` le 25/09/2026 : la contre-épreuve y avait
 * réduit l'appel à `${pathname}` seul — requête et ancre perdues — et les
 * 1 274 vitest restaient verts, faute de pouvoir monter le composant.
 */
export function cibleHeritee(lieu: { pathname: string; search: string; hash: string }): string {
  return cheminHerite(`${lieu.pathname}${lieu.search}${lieu.hash}`) ?? '/';
}
