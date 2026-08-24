// Ce que la page Tâches montre — et ce qu'elle laisse dans Projets.
//
// Demandé le 24 août 2026 : « les tâches des projets remplissent la page
// Tâches ». 148 étapes du parcours OpenClassrooms et 32 d'anglais noyaient
// les 3 vraies tâches libres. Ce ne sont pas des choses à faire aujourd'hui,
// ce sont des JALONS de long terme — ils ont leur carte, dans Projets.
//
// La règle tient en une phrase : un jalon n'entre dans la page Tâches que
// lorsqu'on lui donne une DATE. Dater une étape, c'est décider de la faire ;
// tant qu'elle n'a pas de date, elle attend sur la carte.

import type { SuccesProject, SuccesTask } from './types';

/** Les projets dont les tâches sont des jalons : tout sauf « flat ». */
export function projetsAJalons(projets: ReadonlyArray<SuccesProject>): Set<string> {
  return new Set(
    projets
      .filter((p) => (p.structure || 'flat') !== 'flat')
      .map((p) => p.id),
  );
}

/** Vrai si cette tâche est un jalon SANS date — sa place est sur la carte. */
export function estJalonEnAttente(
  tache: SuccesTask,
  jalons: ReadonlySet<string>,
): boolean {
  if (!tache.projectId || !jalons.has(tache.projectId)) return false;
  return !tache.date;
}

/** Les tâches du jour : le quotidien, plus les jalons qu'on a datés. */
export function tachesDuJour(
  taches: ReadonlyArray<SuccesTask>,
  projets: ReadonlyArray<SuccesProject>,
): SuccesTask[] {
  const jalons = projetsAJalons(projets);
  return taches.filter((t) => !estJalonEnAttente(t, jalons));
}

/** Combien de jalons attendent, par projet — pour le dire sans les montrer. */
export function jalonsEnAttente(
  taches: ReadonlyArray<SuccesTask>,
  projets: ReadonlyArray<SuccesProject>,
): Array<{ projet: SuccesProject; total: number }> {
  const jalons = projetsAJalons(projets);
  const parProjet = new Map<string, number>();
  for (const t of taches) {
    if (t.done) continue;
    if (estJalonEnAttente(t, jalons)) {
      parProjet.set(t.projectId!, (parProjet.get(t.projectId!) ?? 0) + 1);
    }
  }
  return projets
    .filter((p) => parProjet.has(p.id))
    .map((p) => ({ projet: p, total: parProjet.get(p.id)! }))
    .sort((a, b) => b.total - a.total);
}

/**
 * Le jalon SUIVANT dans un projet : la première étape pas encore faite,
 * dans l'ordre de la carte — c'est celle qu'on propose de dater quand la
 * précédente est cochée.
 */
export function jalonSuivant(
  taches: ReadonlyArray<SuccesTask>,
  projectId: string,
  apres?: SuccesTask,
): SuccesTask | null {
  const candidats = taches
    .filter((t) => t.projectId === projectId && !t.done && t.id !== apres?.id)
    .sort((a, b) => (a.order ?? 0) - (b.order ?? 0));
  if (apres) {
    const suivant = candidats.find((t) => (t.order ?? 0) > (apres.order ?? 0));
    if (suivant) return suivant;
  }
  return candidats[0] ?? null;
}
