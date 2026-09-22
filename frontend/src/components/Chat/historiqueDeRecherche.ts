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
