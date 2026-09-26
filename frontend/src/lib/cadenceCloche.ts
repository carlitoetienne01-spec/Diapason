// À quel rythme la cloche relit les demandes d'approbation en attente.
//
// 26/09/2026, chantier de la fluidité (lot 2) : au repos sur la Discussion,
// le téléphone relisait `/v1/approvals/pending` toutes les 5 s — deux
// requêtes par tranche de 10 s au banc, chacune un réveil de la radio 4G
// pour une liste presque toujours vide. Au téléphone, une demande n'attend
// pas la relève : `InputArea` annonce `diapason-approval-possible` dès
// qu'un outil démarre (relecture immédiate), la coquille ouvre la cloche
// depuis sa notification (verbe `approbations`), et la cloche relit au
// retour de l'écran. La relève n'y est qu'un filet.

/** Une décision attend : on suit de près, partout — c'est le moment où l'on regarde. */
export const CLOCHE_EN_ATTENTE_MS = 1_000;
/** Au repos sur le Mac : inchangé, la boucle locale ne coûte rien. */
export const CLOCHE_REPOS_BUREAU_MS = 5_000;
/**
 * Au repos au téléphone : 30 s. Le filet rattrape une demande née hors de
 * la Discussion (un agent, l'assistant vocal) sans réveiller la radio six
 * fois plus souvent ; la notification de la coquille, elle, arrive sans lui.
 */
export const CLOCHE_REPOS_TELEPHONE_MS = 30_000;

export function intervalleCloche(enAttente: number, mobile: boolean): number {
  if (enAttente > 0) return CLOCHE_EN_ATTENTE_MS;
  return mobile ? CLOCHE_REPOS_TELEPHONE_MS : CLOCHE_REPOS_BUREAU_MS;
}
