/**
 * L'onglet Terminées — ce qui se décide sans écran, pur, vérifiable sous
 * vitest.
 *
 * Demande de Carlito, 17 sept. 2026 : « Pourquoi les tâches terminées sont
 * dans la même page en bas ? Je veux une autre façon de les gérer. » Les 36
 * terminées traînaient sous les 690 ouvertes, barrées, sans date de
 * complétion visible, et une sélection multiple n'existait pas : vider un
 * mois de tâches faites, c'était 36 confirmations.
 *
 * Ici : l'ordre (les plus récentes d'abord), le regroupement par jour de
 * complétion, le libellé du jour, la sélection par plage et le bilan d'une
 * suppression en masse tel que le SERVEUR l'a rendu (§100).
 */

import { dateAvecJour, ecartJours } from './echeances';
import type { SuccesTask } from './types';

/** Clé de groupe d'une terminée sans `completedDate` — d'anciennes lignes n'en ont pas. */
export const JOUR_INCONNU = '';

/**
 * Les terminées, les plus récentes d'abord : par jour de complétion, puis
 * par dernière modification, puis par titre pour que deux relectures
 * rendent le même ordre. Les lignes sans jour de complétion ferment la
 * marche — leur place n'est pas devinable (§34).
 */
export function trierTerminees(taches: readonly SuccesTask[]): SuccesTask[] {
  return [...taches].sort((a, b) => {
    const ja = a.completedDate || JOUR_INCONNU;
    const jb = b.completedDate || JOUR_INCONNU;
    if (ja !== jb) {
      if (ja === JOUR_INCONNU) return 1;
      if (jb === JOUR_INCONNU) return -1;
      return jb.localeCompare(ja);
    }
    if (a.updatedAtMs !== b.updatedAtMs) return b.updatedAtMs - a.updatedAtMs;
    return a.title.localeCompare(b.title, 'fr');
  });
}

/**
 * « Aujourd'hui », « Hier », puis la date AVEC son jour de semaine — « lun.
 * 15 sept. » — quelle que soit la distance : un jour de complétion est un
 * fait passé, jamais une échéance, donc jamais « Demain » ni « En retard ».
 */
export function libelleJourDeCompletion(iso: string, aujourdHui: string): string {
  if (!iso) return 'Sans date de complétion';
  const ecart = ecartJours(iso, aujourdHui);
  if (ecart === 0) return 'Aujourd’hui';
  if (ecart === 1) return 'Hier';
  return dateAvecJour(iso, aujourdHui);
}

export interface JourDeCompletion {
  /** L'ISO du jour, ou `JOUR_INCONNU`. */
  jour: string;
  libelle: string;
  taches: SuccesTask[];
}

/**
 * Regroupe par jour de complétion, dans l'ordre d'apparition — donc dans
 * l'ordre de `trierTerminees` quand on lui passe une liste triée, ou une
 * TRANCHE de cette liste : la pagination compte des tâches, pas des jours,
 * et l'en-tête d'un jour se répète sur chaque page où il tombe.
 */
export function grouperParJourDeCompletion(taches: readonly SuccesTask[], aujourdHui: string): JourDeCompletion[] {
  const groupes = new Map<string, JourDeCompletion>();
  for (const tache of taches) {
    const jour = tache.completedDate || JOUR_INCONNU;
    let groupe = groupes.get(jour);
    if (!groupe) {
      groupe = { jour, libelle: libelleJourDeCompletion(jour, aujourdHui), taches: [] };
      groupes.set(jour, groupe);
    }
    groupe.taches.push(tache);
  }
  return [...groupes.values()];
}

/** Combien de terminées par jour, sur TOUTE la liste : « Aujourd'hui · 3 » dit le jour, pas la page. */
export function compterParJour(taches: readonly SuccesTask[]): Map<string, number> {
  const comptes = new Map<string, number>();
  for (const tache of taches) {
    const jour = tache.completedDate || JOUR_INCONNU;
    comptes.set(jour, (comptes.get(jour) ?? 0) + 1);
  }
  return comptes;
}

/**
 * La sélection après un clic sur `cible`. Un clic simple bascule la ligne ;
 * Maj+clic ÉTEND depuis `ancre` (la dernière ligne cliquée sans Maj) jusqu'à
 * `cible`, dans l'ordre affiché, et ajoute toute la plage — jamais de
 * retrait par plage, un Maj+clic qui décoche serait une surprise. Sans
 * ancre visible, Maj+clic vaut un clic simple. Rend un nouvel ensemble ;
 * l'ancien n'est jamais modifié.
 */
export function etendreSelection(
  ordre: readonly string[],
  selection: ReadonlySet<string>,
  cible: string,
  ancre: string | null,
  plage: boolean,
): Set<string> {
  const suivante = new Set(selection);
  const iCible = ordre.indexOf(cible);
  const iAncre = ancre === null ? -1 : ordre.indexOf(ancre);
  if (plage && iCible >= 0 && iAncre >= 0) {
    const [de, a] = iAncre <= iCible ? [iAncre, iCible] : [iCible, iAncre];
    for (let i = de; i <= a; i += 1) suivante.add(ordre[i]);
    return suivante;
  }
  if (suivante.has(cible)) suivante.delete(cible);
  else suivante.add(cible);
  return suivante;
}

export interface EchecDeSuppression {
  titre: string;
  message: string;
}

export interface BilanDeSuppression {
  /** Vrai si TOUT a été supprimé — le seul cas d'un toast vert. */
  ok: boolean;
  titre: string;
  description?: string;
}

/**
 * Le bilan d'une suppression en masse, requête par requête : « 4
 * supprimées », ou « 3 sur 4 supprimées » avec le titre et l'erreur de ce
 * qui a échoué. Jamais un succès global déduit du nombre demandé (§100) :
 * le compte des réussites vient des réponses, et les échecs sont nommés.
 */
export function bilanSuppression(demandees: number, echecs: readonly EchecDeSuppression[]): BilanDeSuppression {
  const reussies = Math.max(0, demandees - echecs.length);
  const pluriel = (n: number) => (n > 1 ? 'supprimées' : 'supprimée');
  if (echecs.length === 0) {
    return { ok: true, titre: `${reussies} ${pluriel(reussies)}` };
  }
  const detail = echecs.map((echec) => `« ${echec.titre} » a échoué : ${echec.message}`).join('\n');
  return {
    ok: false,
    titre: `${reussies} sur ${demandees} ${pluriel(demandees)}`,
    description: detail,
  };
}
