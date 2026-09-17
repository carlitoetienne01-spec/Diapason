/**
 * L'échéance d'une tâche, dite comme on la pense.
 *
 * Expertise de la page Tâches, 17 sept. 2026 (défaut 1) : la carte affichait
 * « 2026-09-17 » — une soustraction mentale pour savoir si c'est aujourd'hui,
 * demain ou déjà passé — et la Liste ne disait JAMAIS qu'une tâche était en
 * retard ; seule la Semaine recalculait ses jours de retard, à part. Ici UNE
 * définition sert aux deux vues : « Aujourd'hui », « Demain », le jour de la
 * semaine tant qu'on est dans la semaine qui vient, la date courte au-delà,
 * l'année seulement si elle diffère, et « En retard de N j » pour ce qui est
 * passé sans être fait.
 */

import { analyserIso, dateIsoLocale } from './planificateur';

/** L'horizon où le jour de la semaine suffit : sept jours, aujourd'hui compris. */
const HORIZON_SEMAINE_J = 6;

const MS_PAR_JOUR = 86_400_000;

/**
 * Jours entre deux ISO locaux, midi à midi — le changement d'heure ne fait
 * donc jamais pencher l'arrondi vers 0 ou 2 pour une seule journée.
 */
export function ecartJours(depuisIso: string, versIso: string): number {
  return Math.round((analyserIso(versIso).getTime() - analyserIso(depuisIso).getTime()) / MS_PAR_JOUR);
}

/** Les jours de retard d'une échéance ; 0 si elle n'est pas passée. */
export function joursDeRetard(iso: string, aujourdHui: string = dateIsoLocale()): number {
  if (!iso) return 0;
  return Math.max(0, ecartJours(iso, aujourdHui));
}

function dateCourte(iso: string, aujourdHui: string, avecJourSemaine: boolean, locale: string): string {
  const date = analyserIso(iso);
  const anneeDifferente = date.getFullYear() !== analyserIso(aujourdHui).getFullYear();
  return new Intl.DateTimeFormat(locale, {
    ...(avecJourSemaine ? { weekday: 'short' as const } : {}),
    day: 'numeric',
    month: 'short',
    ...(anneeDifferente ? { year: 'numeric' as const } : {}),
  }).format(date);
}

/**
 * Le libellé de l'échéance.
 *
 * - le jour même : « Aujourd'hui » ; la veille : « Demain » ;
 * - dans les six jours qui suivent : « sam. 19 sept. » — le jour de la
 *   semaine est ce qu'on se dit ;
 * - au-delà : « 3 oct. », et « 3 janv. 2027 » seulement si l'année change ;
 * - passé et non fait : « En retard de 3 j ». Une tâche terminée n'est
 *   jamais en retard : sa date passée redevient une date.
 */
export function libelleEcheance(
  iso: string,
  aujourdHui: string = dateIsoLocale(),
  options: { terminee?: boolean; locale?: string } = {},
): string {
  const locale = options.locale ?? 'fr-CA';
  if (!iso) return '';
  const ecart = ecartJours(aujourdHui, iso);
  if (ecart === 0) return 'Aujourd’hui';
  if (ecart === 1) return 'Demain';
  if (ecart < 0) {
    if (!options.terminee) return `En retard de ${-ecart} j`;
    return dateCourte(iso, aujourdHui, false, locale);
  }
  return dateCourte(iso, aujourdHui, ecart <= HORIZON_SEMAINE_J, locale);
}

/**
 * La date AVEC son jour de semaine, quelle que soit la distance : « lun.
 * 21 sept. », « lun. 28 sept. », « ven. 3 janv. 2027 ». Jamais « Demain »
 * ni « En retard » : c'est le libellé d'un CHOIX, pas d'une échéance. Les
 * deux chips d'une date ambiguë (« lundi prochain » : 21 ou 28 ?) passaient
 * par `libelleEcheance`, dont le jour de semaine s'arrête à six jours — la
 * seconde option tombait toujours au-delà, et deux chips sœurs se lisaient
 * « lun. 21 sept. » et « 28 sept. » (revue du 17 sept. 2026, défaut 22).
 */
export function dateAvecJour(iso: string, aujourdHui: string = dateIsoLocale(), locale = 'fr-CA'): string {
  if (!iso) return '';
  return dateCourte(iso, aujourdHui, true, locale);
}
