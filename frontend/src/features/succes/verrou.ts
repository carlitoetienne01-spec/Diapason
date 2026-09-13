// Le verrou séquentiel — les aides pures de la progression pas à pas.
//
// Demandé le 6 septembre 2026 : « si je n'ai pas accédé à la tâche avant, je
// ne peux pas accéder aux autres ». Le calcul est répété ici parce que
// l'interface doit griser AVANT le clic ; le magasin, lui, refuse au moment
// de cocher (`store._verrou_sequentiel`). Les deux disent la même chose, et
// c'est le magasin qui fait foi — une restriction que seul le client applique
// se lève en rejouant la requête.
//
// Trois règles, identiques des deux côtés :
//   1. les RACINES ne se verrouillent jamais — les grandes branches avancent
//      en parallèle, sinon une tâche administrative en attente gèlerait tout ;
//   2. dans une fratrie, une tâche attend TOUTES celles de rang inférieur ;
//   3. le verrou se propage vers le bas — les stations d'un cours fermé
//      restent fermées, sans quoi on l'atteindrait par un détour.

import type { SuccesTask } from './types';

/** Ce qui barre la route à une tâche : le titre de celle qu'il faut finir. */
export type Verrous = Map<string, string>;

const parRang = (a: SuccesTask, b: SuccesTask) =>
  (a.order ?? 0) - (b.order ?? 0) || a.id.localeCompare(b.id);

/**
 * Les tâches verrouillées d'un projet, chacune avec ce qui la débloque.
 *
 * Une tâche déjà cochée n'est jamais verrouillée : rouvrir la précédente ne
 * doit pas effacer sous les yeux le travail qu'on a fait.
 */
export function tachesVerrouillees(
  taches: SuccesTask[],
  actif: boolean,
): Verrous {
  const verrous: Verrous = new Map();
  if (!actif) return verrous;

  const parId = new Map<string, SuccesTask>();
  const fratries = new Map<string, SuccesTask[]>();
  for (const tache of taches) {
    parId.set(tache.id, tache);
    const parent = tache.parentTaskId || '';
    const fratrie = fratries.get(parent);
    if (fratrie) fratrie.push(tache);
    else fratries.set(parent, [tache]);
  }
  for (const fratrie of fratries.values()) fratrie.sort(parRang);

  /** La première sœur non cochée de rang inférieur, s'il y en a une. */
  const barrage = (tache: SuccesTask): SuccesTask | null => {
    const fratrie = fratries.get(tache.parentTaskId || '') ?? [];
    for (const soeur of fratrie) {
      if (soeur.id === tache.id) return null;
      if (!soeur.done) return soeur;
    }
    return null;
  };

  for (const tache of taches) {
    if (tache.done) continue;
    let noeud: SuccesTask | undefined = tache;
    const vus = new Set<string>();
    while (noeud && noeud.parentTaskId && !vus.has(noeud.id)) {
      vus.add(noeud.id);
      const bloquante = barrage(noeud);
      if (bloquante) {
        verrous.set(tache.id, bloquante.title);
        break;
      }
      noeud = parId.get(noeud.parentTaskId);
    }
  }
  return verrous;
}

/** Vrai si ce projet fait avancer ses tâches une par une. */
export function progressionSequentielle(
  structure: string | undefined,
  config: { sequential?: boolean } | undefined,
): boolean {
  if (structure !== 'tree' && structure !== 'mindmap') return false;
  return config?.sequential === true;
}
