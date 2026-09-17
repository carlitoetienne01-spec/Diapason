/**
 * Ce que la carte de tâche dit sans mot — pur, donc vérifiable sous vitest.
 *
 * Expertise de la page Tâches, 17 sept. 2026 (défaut 2) : chaque carte
 * portait une pastille « Normale » — un signal sur 90 % des cartes, donc
 * aucun signal — et le nom du projet teinté sur 12 px, qu'on ne lit qu'en
 * s'y arrêtant. La valeur par défaut doit être silencieuse (Rappels : !, !!,
 * !!!) et une bande de couleur se lit en périphérie, un mot non.
 */

import type { SuccesPriority } from './types';

export interface SignePriorite {
  /** Le signe devant le titre ; vide quand la priorité est celle par défaut. */
  signe: string;
  /** Le jeton de couleur du signe ; `undefined` quand il n'y a rien à teinter. */
  couleur?: string;
  /** Ce que lit le lecteur d'écran — le signe seul ne se lit pas. */
  libelle: string;
}

/**
 * Le « !! » de la haute : `--color-warning` seul (#ca8a04) fait 2,94:1 sur
 * la surface blanche du thème clair — sous les 4,5:1 d'un texte de 16 px,
 * et c'est le SEUL porteur visuel du niveau depuis que la pastille-mot est
 * partie (revue du 17 sept. 2026, défaut 18). Mêlé à 35 % d'encre en OKLab :
 * #7f591a, 6,28:1 sur #ffffff et 5,96:1 sur #f9f9f9 ; l'encre étant claire
 * sur les thèmes sombres, le mélange y ÉCLAIRCIT (sombre 9,17 → 11,30,
 * vert 11,87 → 13,25) et n'abaisse que sauge, de 8,18 à 7,84 — calcul
 * `scratchpad/contraste.py`, formules OKLab et WCAG 2.
 */
export const COULEUR_SIGNE_HAUTE = 'color-mix(in oklab, var(--color-warning), var(--color-text) 35%)';

export const SIGNES_PRIORITE: Record<SuccesPriority, SignePriorite> = {
  urgent: { signe: '!!!', couleur: 'var(--color-error)', libelle: 'Priorité urgente' },
  high: { signe: '!!', couleur: COULEUR_SIGNE_HAUTE, libelle: 'Priorité haute' },
  medium: { signe: '', libelle: 'Priorité normale' },
  low: { signe: '', libelle: 'Priorité basse' },
};

/**
 * Deux lettres pour un projet — l'initiale du premier mot et celle du
 * dernier : « La Cité » → « LC », « Zéro à Héro » → « ZH », « English
 * Mastery » → « EM » ; un seul mot donne ses deux premières lettres,
 * « Diapason » → « DI ». Pas de liste de mots vides : « La Cité » se
 * reconnaît à son « L », et une liste qu'on n'entretient pas finit par
 * manger une initiale qu'on attendait. En Ardéchine, où toute couleur se
 * replie sur l'encre, la forme remplace la teinte : le monogramme dans une
 * boîte bordée est ce qui distingue deux projets.
 */
export function monogrammeProjet(nom: string): string {
  const mots = nom
    .split(/[\s\-–—_/.,:;'’]+/)
    .filter((mot) => mot.length > 0);
  if (mots.length === 0) return '··';
  if (mots.length === 1) return mots[0].slice(0, 2).toUpperCase().padEnd(2, '·');
  return (mots[0][0] + mots[mots.length - 1][0]).toUpperCase();
}
