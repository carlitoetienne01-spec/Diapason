/**
 * Reporter en langage naturel — la logique pure de la boîte « Reporter » de
 * la carte de tâche, hors React pour être vérifiée sous vitest.
 *
 * Expertise de la page Tâches, 17 sept. 2026 (défauts 4 et 6) : le résolveur
 * de dates du serveur (« lundi », « vendredi prochain », « dans 3 jours »,
 * « 21/09/2026 » — `succes/dates.py`, qui ne connaît PAS « 21 sept » : un
 * placeholder le promettait et rendait 422 à coup sûr, revue du 17 sept.
 * 2026, défaut 7) n'était atteint que par la voix ; au clic, il fallait
 * ouvrir un calendrier. Et quand le serveur répondait « cette date peut
 * désigner deux jours », les deux `options` qu'il joignait se perdaient dans
 * un toast rouge — une question sans bouton pour y répondre (§34).
 */

import { DateAmbigueError, DateInconnueError } from './api';
import { dateAvecJour, ecartJours, libelleEcheance } from './echeances';

/**
 * Les exemples du champ libre : seulement ce que `resolve_date_expression`
 * comprend. La vérité d'un placeholder se vérifie côté serveur, pas ici.
 */
export const EXEMPLES_EXPRESSION = 'lundi, vendredi prochain, dans 3 jours, 21/09/2026…';

/** La longueur que la route accepte (`RescheduleBody.date`, max_length=80). */
export const EXPRESSION_MAX = 80;

/**
 * L'expression telle qu'on l'envoie : ébarbée, jamais vide, bornée à ce que
 * la route accepte — au-delà, le serveur répondait un 422 de validation en
 * anglais (« String should have at most 80 characters ») que le champ aurait
 * pris pour une date inconnue.
 */
export function expressionDeReport(saisie: string): string | null {
  const propre = saisie.trim().slice(0, EXPRESSION_MAX);
  return propre ? propre : null;
}

export type RefusDeReport =
  | { type: 'ambigue'; message: string; options: string[] }
  | { type: 'inconnue'; message: string };

/**
 * Ce qu'un refus du serveur donne à répondre dans la carte, ou `null` quand
 * ce n'est pas à elle de répondre (réseau, 404, 409 métier) — la page a déjà
 * dit ce cas dans un toast.
 */
export function lireRefusDeReport(error: unknown): RefusDeReport | null {
  if (error instanceof DateAmbigueError) {
    return { type: 'ambigue', message: error.message, options: error.options };
  }
  if (error instanceof DateInconnueError) {
    return { type: 'inconnue', message: error.message };
  }
  return null;
}

/**
 * Les deux jours possibles, en chips datées lisibles — TOUJOURS avec le jour
 * de semaine (« lun. 21 sept. », « lun. 28 sept. ») : la seconde option est
 * par construction à 8-14 jours, au-delà de l'horizon où `libelleEcheance`
 * le dit, et les deux chips ne parlaient pas la même langue (revue du
 * 17 sept. 2026, défaut 22).
 */
export function chipsAmbiguite(
  options: string[],
  aujourdHui: string,
): { date: string; label: string }[] {
  return options.map((date) => ({ date, label: dateAvecJour(date, aujourdHui) }));
}

/**
 * Le toast d'un report, sur la date que le SERVEUR a rendue (§100), dans la
 * langue de la carte : « Reportée à demain », « Reportée au lun. 21 sept. »,
 * « Reportée au 3 oct. ». Le toast disait « Reportée au 2026-09-21 » sur la
 * page même qui venait de bannir l'ISO des cartes (défaut 12), et le
 * Planificateur répétait l'expression ENVOYÉE — « Reportée au dans 3 jours »
 * (défaut 6). Une date passée (« hier ») reste une date, jamais « En retard ».
 */
export function phraseReportee(dateServeur: string, aujourdHui: string): string {
  if (!dateServeur) return 'Reportée';
  const ecart = ecartJours(aujourdHui, dateServeur);
  if (ecart === 0) return 'Reportée à aujourd’hui';
  if (ecart === 1) return 'Reportée à demain';
  return `Reportée au ${libelleEcheance(dateServeur, aujourdHui, { terminee: true })}`;
}

/**
 * Le seuil où la carte pose la question du découpage : le serveur joint
 * son `warning` à partir du quatrième report, et c'est alors que la mention
 * « Reportée N× » se teinte et devient un bouton vers « Nouvelle sous-tâche ».
 */
export const REPORTS_AVANT_DECOUPAGE = 4;

export function proposeDecoupage(postponedCount: number): boolean {
  return postponedCount >= REPORTS_AVANT_DECOUPAGE;
}
