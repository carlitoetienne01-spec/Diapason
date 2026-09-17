/**
 * Réconcilier une ligne de tâche avec ce que le serveur renvoie — pur, donc
 * vérifiable sous vitest.
 *
 * Expertise de la page Tâches, 17 sept. 2026 (défaut 6) : chaque coche
 * relançait `load()` sur les 702 tâches — la case restait figée quelques
 * centaines de ms, et cinq sous-tâches cochées faisaient cinq rechargements.
 * Sous 100 ms (Nielsen), l'interface semble répondre au doigt.
 *
 * Le contrat, §100 : l'état peint au clic n'est qu'un intérim. La ligne que
 * rend le serveur (`{ task }` de /done, PATCH, /reschedule, /subtasks)
 * l'écrase toujours ; en erreur, l'ancienne ligne revient. Rien de ce qui
 * reste affiché ne vient de ce qu'on a envoyé.
 */

import type { SuccesSubtask, SuccesTask } from './types';

/**
 * Le temps qu'une tâche cochée reste barrée, à sa place, avant de glisser
 * hors d'une liste qui cache les terminées. 1 s : assez pour voir la coche
 * se poser et se raviser ; à 300 ms la ligne disparaissait sous le doigt et
 * l'on ne savait plus laquelle on venait de cocher.
 */
export const GLISSEMENT_MS = 1000;

/** La liste, avec `ligne` à la place de la tâche du même id — telle quelle si absente. */
export function remplacerLigne(tasks: SuccesTask[], ligne: SuccesTask): SuccesTask[] {
  let trouvee = false;
  const suivante = tasks.map((task) => {
    if (task.id !== ligne.id) return task;
    trouvee = true;
    return ligne;
  });
  return trouvee ? suivante : tasks;
}

function parcourir(
  subtasks: SuccesSubtask[],
  transformer: (subtask: SuccesSubtask) => SuccesSubtask | null,
): SuccesSubtask[] {
  const resultat: SuccesSubtask[] = [];
  for (const subtask of subtasks) {
    const transformee = transformer(subtask);
    if (transformee === null) continue;
    resultat.push({ ...transformee, children: parcourir(transformee.children, transformer) });
  }
  return resultat;
}

/** La tâche avec la sous-tâche `subtaskId` (à toute profondeur) cochée ou non. */
export function basculerSousTache(task: SuccesTask, subtaskId: string, done: boolean): SuccesTask {
  return {
    ...task,
    subtasks: parcourir(task.subtasks, (subtask) =>
      subtask.id === subtaskId ? { ...subtask, done } : subtask,
    ),
  };
}

/** La tâche sans la sous-tâche `subtaskId` ni ses enfants. */
export function retirerSousTache(task: SuccesTask, subtaskId: string): SuccesTask {
  return {
    ...task,
    subtasks: parcourir(task.subtasks, (subtask) => (subtask.id === subtaskId ? null : subtask)),
  };
}

/**
 * La liste sans la tâche `taskId` — seulement si elle est encore terminée :
 * une tâche rouverte pendant le délai reste à sa place.
 */
export function glisserSiTerminee(tasks: SuccesTask[], taskId: string): SuccesTask[] {
  return tasks.filter((task) => task.id !== taskId || !task.done);
}

/** Une date ISO `AAAA-MM-JJ` — la seule qu'on ose peindre avant la réponse. */
export function estDateIso(valeur: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(valeur);
}

interface SuiviDeLigne {
  /** Combien de requêtes ont été émises pour cette tâche — le prochain numéro. */
  emises: number;
  /** Les numéros encore sans réponse. */
  enVol: Set<number>;
  /** Le plus grand numéro dont la réponse est arrivée. */
  repondue: number;
  /** La dernière ligne que le SERVEUR a rendue — avant toute requête, la ligne d'origine. */
  serveur: SuccesTask;
}

/**
 * Le suivi des requêtes en vol, tâche par tâche (revue des gains rapides,
 * 17 sept. 2026, défaut 3).
 *
 * Deux coches en rafale sur un serveur injoignable (chaque requête réessaie
 * ≥ 1,5 s) : la première échouait et rétablissait la ligne d'origine ; la
 * seconde échouait et rétablissait son « avant » — la ligne OPTIMISTE de la
 * première. Résultat : une sous-tâche cochée à l'écran, jamais enregistrée,
 * à côté de deux toasts rouges disant l'inverse (faux SUCCESS, §100). Sur un
 * serveur lent, la première réponse écrasait la ligne entière et les coches
 * suivantes se décochaient sous les yeux, pour se recocher une à une.
 *
 * Deux règles : une réponse ne se peint que si aucune requête plus récente
 * n'est en vol pour cette tâche (elle peindra la sienne) ; un échec ne
 * rétablit jamais un intérim, seulement la dernière ligne que le serveur a
 * rendue. L'entrée d'une tâche disparaît dès que plus rien n'est en vol :
 * la ligne affichée est alors la ligne serveur, et c'est elle que la
 * prochaine requête reçoit en `avant`.
 */
export class SuiviDesRequetes {
  private readonly suivis = new Map<string, SuiviDeLigne>();

  /** Une requête part pour `avant` (la ligne telle qu'affichée). Rend son numéro. */
  partir(avant: SuccesTask): number {
    const suivi = this.suivis.get(avant.id);
    if (!suivi) {
      this.suivis.set(avant.id, { emises: 1, enVol: new Set([1]), repondue: 0, serveur: avant });
      return 1;
    }
    suivi.emises += 1;
    suivi.enVol.add(suivi.emises);
    return suivi.emises;
  }

  /**
   * La requête `numero` a réussi et `serveur` est la ligne rendue. Rend la
   * ligne à peindre, ou `null` si une requête plus récente est encore en vol.
   */
  reussir(taskId: string, numero: number, serveur: SuccesTask): SuccesTask | null {
    const suivi = this.suivis.get(taskId);
    if (!suivi) return serveur;
    if (numero > suivi.repondue) {
      suivi.repondue = numero;
      suivi.serveur = serveur;
    }
    return this.conclure(taskId, suivi, numero);
  }

  /** La requête `numero` a échoué. Rend la ligne à rétablir, ou `null` si une plus récente est encore en vol. */
  echouer(taskId: string, numero: number): SuccesTask | null {
    const suivi = this.suivis.get(taskId);
    if (!suivi) return null;
    return this.conclure(taskId, suivi, numero);
  }

  /**
   * Un GET complet vient de repeindre `lignes` : pour les tâches encore en
   * vol, la « dernière ligne serveur » devient celle-ci. Sans quoi un échec
   * qui suit rétablissait un cliché d'AVANT le GET — un titre changé sur le
   * téléphone repassait à l'ancien (contre-revue du 17 sept. 2026).
   */
  rafraichir(lignes: readonly SuccesTask[]): void {
    for (const ligne of lignes) {
      const suivi = this.suivis.get(ligne.id);
      if (suivi) suivi.serveur = ligne;
    }
  }

  /** Combien de requêtes attendent encore une réponse pour cette tâche. */
  enVol(taskId: string): number {
    return this.suivis.get(taskId)?.enVol.size ?? 0;
  }

  private conclure(taskId: string, suivi: SuiviDeLigne, numero: number): SuccesTask | null {
    suivi.enVol.delete(numero);
    for (const autre of suivi.enVol) if (autre > numero) return null;
    if (suivi.enVol.size === 0) this.suivis.delete(taskId);
    return suivi.serveur;
  }
}
