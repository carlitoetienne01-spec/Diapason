// Le verbe `approbations` du côté du bundle : la notification d'approbation
// touchée sur le téléphone ouvre la cloche.
//
// 26/09/2026, phase 5 du plan mobile (docs/development/diapason-mobile.md).
// La notification ne décide jamais : elle ouvre l'app (le verrou passe
// d'abord), la coquille demande la cloche, et c'est la personne qui touche
// Approuver ou Refuser. L'ordre compte, et il est tenu ici parce qu'aucun
// test ne monte `ApprovalBell` :
//
// - relire AVANT d'ouvrir : la cloche du téléphone n'a peut-être pas encore
//   sondé depuis le réveil (5 s), et elle s'ouvrirait sur « Aucune demande »
//   alors qu'une attend — ou sur une demande déjà tranchée depuis le Mac ;
// - une relecture qui échoue n'ouvre RIEN : une cloche vide sur un échec
//   dirait « aucune demande » à la place de « je n'ai pas pu lire ».

import { traduire } from '../i18n/translate';

export interface DependancesDeLaCloche<T> {
  /** `GET /v1/approvals/pending`, par le cookie de la WebView. */
  lire: () => Promise<T[]>;
  /** Pose la liste lue dans la cloche. */
  afficher: (demandes: T[]) => void;
  /** Déplie la cloche. */
  ouvrir: () => void;
}

/** Rend `{nombre}` une fois la cloche ouverte sur la liste fraîche. */
export async function ouvrirLaCloche<T>(d: DependancesDeLaCloche<T>): Promise<{ nombre: number }> {
  let demandes: T[];
  try {
    demandes = await d.lire();
  } catch {
    throw new Error(traduire('natif.approbations.illisibles'));
  }
  d.afficher(demandes);
  d.ouvrir();
  return { nombre: demandes.length };
}
