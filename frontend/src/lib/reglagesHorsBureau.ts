// Ce que les Réglages affichent de l'état du Mac quand la page ne tourne
// pas dans l'app de bureau (le téléphone, un navigateur).
//
// 26/09/2026 : le commit 4be917d disait avoir cessé d'inventer l'état des
// clés hors de l'app de bureau, mais n'avait corrigé que la palette. Les
// Réglages gardaient `if (!isTauri()) setHasKey(false)` : les quatre
// pastilles OpenAI, Anthropic, Google et OpenRouter restaient grises sous
// « un point vert signale une clé configurée », même quand le Mac avait les
// clés — et la palette, relisant le même état, disait l'inverse (§5 : deux
// vérités pour une même clé). La source d'inférence, elle, s'affichait
// « Ollama intégré » tant qu'elle n'était pas lue, et encore après un échec
// de lecture, bouton « Enregistrer » actif.

import type { CloudKeyStatus, InferenceSource } from './api';

/** Ce qu'on sait d'une clé : lue présente ou absente, pas encore lue, ou illisible. */
export type EtatCle = 'presente' | 'absente' | 'attente' | 'illisible';

export function etatDeLaCle(
  lecture: { statut: CloudKeyStatus } | { echec: true } | null,
  cle: string,
): EtatCle {
  if (lecture === null) return 'attente';
  if ('echec' in lecture) return 'illisible';
  return lecture.statut[cle] ? 'presente' : 'absente';
}

/**
 * La phrase du champ d'une clé. Hors de l'app de bureau, la clé ne se
 * saisit pas (seule l'app écrit le trousseau), mais la page dit ce qu'elle
 * sait du Mac au lieu d'un champ vide et désactivé sans explication.
 */
export type IndicationCle =
  | 'savedSecure'
  | 'savedServer'
  | 'surLeMac'
  | 'ajouterSurLeBureau'
  | 'illisible'
  | null;

export function indicationCle(entree: {
  bureau: boolean;
  outilServeur: boolean;
  etat: EtatCle;
}): IndicationCle {
  const { bureau, outilServeur, etat } = entree;
  if (bureau) return etat === 'presente' ? 'savedSecure' : null;
  if (outilServeur) return etat === 'presente' ? 'savedServer' : null;
  if (etat === 'presente') return 'surLeMac';
  if (etat === 'absente') return 'ajouterSurLeBureau';
  if (etat === 'illisible') return 'illisible';
  return null;
}

/** La lecture de la source d'inférence du Mac. */
export type LectureSource =
  | { etat: 'attente' }
  | { etat: 'lue'; source: InferenceSource }
  | { etat: 'echec'; message: string };

/**
 * La valeur du sélecteur : jamais « ollama » pour une source qu'on n'a pas
 * lue — « inconnue » tant que la lecture n'a pas réussi.
 */
export function choixDeSourceAffiche(
  lecture: LectureSource,
  choisie: InferenceSource['kind'],
): InferenceSource['kind'] | 'inconnue' {
  return lecture.etat === 'lue' ? choisie : 'inconnue';
}

/** On n'enregistre pas par-dessus une source qu'on n'a pas lue. */
export function sourceEnregistrable(lecture: LectureSource): boolean {
  return lecture.etat === 'lue';
}
