// Ce que la roue ouverte fait du bouton retour d'Android et de la page
// dessous — en fonctions pures, pour que vitest les tienne.
//
// 26/09/2026, contre-épreuve de la fluidité : retirer `fermer()` du
// gestionnaire du verbe `retour` (le retour était avalé, la roue restait
// ouverte et le bouton retour ne faisait plus rien), ou retirer
// `el.inert = true` (les 44 boutons de la page des Tâches redevenaient
// lisibles au lecteur d'écran sous l'écran « Aller à »), laissait les
// 1 580 tests verts. Ces deux effets n'étaient mesurés qu'au banc.

/**
 * La réponse au verbe `retour` du pont : roue ouverte, on la ferme et le
 * retour est consommé (`true`) ; fermée, on laisse la coquille reculer.
 */
export function reponseAuRetour(ouverte: boolean, fermer: () => void): boolean {
  if (!ouverte) return false;
  fermer();
  return true;
}

/**
 * Ce que fait un toucher du voile — la page visible derrière la roue en
 * surimpression (26/09/2026). Il ferme, SAUF s'il a atteint un bouton (la
 * roue, une action, le X : chacun sait quoi faire) ou s'il est le clic
 * fantôme qui suit un glissé — sans quoi chaque rotation relâchée sur le
 * voile refermait la roue que le pouce venait d'ouvrir.
 */
export function toucherDuVoile(surUnBouton: boolean, clicApresGlisse: boolean): 'fermer' | 'rien' {
  return surUnBouton || clicApresGlisse ? 'rien' : 'fermer';
}

/**
 * Les éléments à rendre inertes sous l'écran « Aller à » : les frères de
 * `moi` (la cloche, la colonne de la page…), sauf ceux déjà inertes — que
 * la roue ne doit pas réveiller en se refermant.
 */
export function freresARendreInertes(moi: Element): HTMLElement[] {
  const parent = moi.parentElement;
  if (!parent) return [];
  return [...parent.children].filter(
    (el): el is HTMLElement => el !== moi && el instanceof HTMLElement && !el.inert,
  );
}

/** Rend `elements` inertes ; rend de quoi les réveiller, eux seuls. */
export function rendreInertes(elements: readonly HTMLElement[]): () => void {
  for (const el of elements) el.inert = true;
  return () => {
    for (const el of elements) el.inert = false;
  };
}
