/**
 * Les clés `localStorage` du domaine changent de nom : `diapason-succes-*`
 * devient `diapason-vie-*` (25/09/2026, étape 8 du plan de la phase 1b,
 * docs/development/diapason-mobile.md).
 *
 * Deux défauts guettaient ce renommage, chacun silencieux :
 *
 * - sans copie, les préférences des pages (mode de vue, filtres, pages,
 *   arbres dépliés) repartaient à zéro, et les rappels d'habitude déjà
 *   envoyés aujourd'hui se renvoyaient ;
 * - sans suppression, les 1 692 006 octets d'anciens caches (mesurés le
 *   25/09/2026) restaient à côté du budget de 4,2 Mo du cache renommé, au-delà
 *   des 5 Mo que WebKit accorde à l'origine. `saveSettings`, qui écrit sans
 *   `try`, aurait alors perdu les réglages d'apparence.
 *
 * Le stockage est cloisonné par origine (`tauri://localhost` pour la fenêtre,
 * `http://127.0.0.1:8000` pour le mini-panneau) : la migration s'exécute à
 * l'amorçage de chaque bundle, donc une fois par origine. Idempotente, elle
 * ne lève jamais — un stockage absent ou qui refuse vaut « rien à migrer ».
 */

import type { Stockage } from './cacheVie';

/** [ancien nom, nouveau nom] — recopiés si le nouveau est absent. */
export const CLES_RENOMMEES: ReadonlyArray<readonly [string, string]> = [
  ['diapason-succes-ui-prefs', 'diapason-vie-ui-prefs'],
  ['diapason-succes-habit-reminder-fired', 'diapason-vie-habit-reminder-fired'],
];

/**
 * Les caches d'avant le renommage : supprimés, pas recopiés. Leur empreinte
 * de build est celle de l'ancien bundle, que le nouveau rejetterait de toute
 * façon à la lecture.
 */
export const PREFIXE_CACHE_HERITE = 'diapason-succes-cache:';

export interface BilanMigration {
  /** Clés recopiées vers leur nouveau nom. */
  recopiees: number;
  /** Anciennes clés retirées (recopiées, ou déjà présentes sous le nouveau nom). */
  retirees: number;
  /** Entrées d'ancien cache supprimées. */
  cachesSupprimes: number;
}

function ancienCache(store: Stockage): string[] {
  const noms: string[] = [];
  if (typeof store.length !== 'number' || typeof store.key !== 'function') return noms;
  // Relevés d'abord, retirés ensuite : retirer pendant le parcours décale
  // les index de `key(i)` et en saute une sur deux.
  for (let i = 0; i < store.length; i += 1) {
    const nom = store.key(i);
    if (nom && nom.startsWith(PREFIXE_CACHE_HERITE)) noms.push(nom);
  }
  return noms;
}

export function migrerStockage(store: Stockage | null): BilanMigration {
  const bilan: BilanMigration = { recopiees: 0, retirees: 0, cachesSupprimes: 0 };
  if (!store) return bilan;
  // Les caches d'abord : ils libèrent la place que la copie des préférences
  // pourrait demander sur un stockage plein.
  try {
    for (const nom of ancienCache(store)) {
      store.removeItem(nom);
      bilan.cachesSupprimes += 1;
    }
  } catch {
    // Un stockage qui refuse de se laisser lire : le cache neuf vivra en
    // mémoire, comme il le fait déjà sur un quota plein.
  }
  for (const [ancien, neuf] of CLES_RENOMMEES) {
    try {
      const valeur = store.getItem(ancien);
      if (valeur === null) continue;
      if (store.getItem(neuf) === null) {
        store.setItem(neuf, valeur);
        bilan.recopiees += 1;
      }
      // Retirée seulement une fois le nouveau nom garni : une copie qui a
      // échoué (quota) laisse l'ancienne pour le prochain lancement.
      store.removeItem(ancien);
      bilan.retirees += 1;
    } catch {
      // Rien de perdu : l'ancienne clé reste, la migration réessaiera.
    }
  }
  return bilan;
}

/** Le `localStorage` de cette origine, ou `null` (navigation privée, Node). */
export function stockageDeLOrigine(): Stockage | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage;
  } catch {
    return null;
  }
}
