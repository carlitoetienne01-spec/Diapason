// Les tours d'avant qui partent avec une recherche approfondie.
//
// 22/09/2026 : « Donne-moi les liens de ces sites web » partait seul vers
// /api/research — sans les tours d'avant, « ces sites » n'avait pas de
// référent et l'agent rendait des liens tirés des courriels. Les six
// derniers tours, sans la demande courante ni les messages vides.

export const TOURS_D_AVANT = 6;

export function historiqueDeRecherche(
  messages: Array<{ role: string; content: string }>,
): Array<{ role: string; content: string }> {
  const avant = messages.slice(0, -1);
  return avant
    .filter((m) => (m.role === 'user' || m.role === 'assistant') && m.content.trim())
    .slice(-TOURS_D_AVANT)
    .map((m) => ({ role: m.role, content: m.content }));
}

// Les sources renumérotées du serveur remplacent celles des recherches.
//
// 22/09/2026 : le serveur renumérote les [N] du texte par ordre d'apparition
// (« CodinGame [3] » devient « [1] ») et envoie la liste correspondante ;
// le client gardait les numéros d'origine, et la pastille [1] sous CodinGame
// ouvrait le relevé de la Banque Nationale (ref 1 de la recherche corpus).
/** Les sources d'un lot rejoignent celles qu'on a déjà, par numéro.
 *
 *  22/09/2026. Les deux sites qui recevaient un lot écartaient toute pastille
 *  DÉJÀ connue (`!parRef.has(src.ref)`). C'était sans effet tant qu'aucun
 *  émetteur ne réémettait un numéro — et le jour où le serveur a voulu dire
 *  « cette source-là est officielle, lue aujourd'hui » sur une page que la
 *  recherche avait déjà rendue, la mise à jour se perdait en silence.
 *
 *  FUSION, pas remplacement : une carte officielle ne porte que six champs,
 *  une source de recherche en porte davantage. Les écraser jetterait ce
 *  qu'on avait déjà reçu.
 *
 *  Le lot arrive du réseau : chaque entrée est vérifiée, et une forme
 *  inattendue est ignorée plutôt que de faire tomber la réception. */
export function fusionnerLesSources<T extends { ref: number }>(
  parRef: Map<number, T>,
  lot: unknown,
): void {
  for (const src of Array.isArray(lot) ? lot : []) {
    if (!src || typeof src !== 'object') continue;
    const candidat = src as T;
    if (typeof candidat.ref !== 'number') continue;
    const connue = parRef.get(candidat.ref);
    parRef.set(candidat.ref, connue ? { ...connue, ...candidat } : candidat);
  }
}

export function remplacerLesSources<T extends { ref: number }>(
  parRef: Map<number, T>,
  finales: ReadonlyArray<T> | undefined,
): void {
  if (!finales) return;
  parRef.clear();
  for (const src of finales) {
    if (src && typeof src.ref === 'number') parRef.set(src.ref, src);
  }
}
