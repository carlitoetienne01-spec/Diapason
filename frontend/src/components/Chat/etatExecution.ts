import type { ResearchSearchTrace, ToolCallInfo } from '../../types';

export type EtatExecution = ToolCallInfo['status'];

export function texteRecu(valeur: unknown): string {
  if (valeur == null) return '';
  return typeof valeur === 'string' ? valeur : JSON.stringify(valeur);
}

export function dureeValide(valeur: unknown): valeur is number {
  return typeof valeur === 'number' && Number.isFinite(valeur) && valeur >= 0;
}

export function dureeOutil(secondes: number, locale: string): string {
  // 22/09/2026 : 1,2 seconde serveur était affichée « 1 ms » ; aucune
  // conversion implicite de l'unité du contrat dans les cartes du chat.
  if (secondes === 0) return '0 s';
  if (secondes < 1) return `${new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(secondes * 1000)} ms`;
  return `${new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(secondes)} s`;
}

export function etatExecution(appel: ToolCallInfo, enDirect: boolean): EtatExecution {
  if (appel.status === 'running') return enDirect ? 'running' : 'unconfirmed';
  return ['success', 'error'].includes(appel.status) ? appel.status : 'unconfirmed';
}

export function terminerAppel(appels: ToolCallInfo[], donnees: Record<string, unknown>, maintenant?: number): boolean {
  const candidats = appels.filter(a => a.tool === donnees.tool && a.status === 'running');
  // Pas d'identifiant de corrélation dans ce flux : deux appels simultanés
  // homonymes seraient indiscernables. Ne pas attribuer une réussite au hasard.
  if (candidats.length !== 1) return false;
  const appel = candidats[0];
  appel.status = donnees.success === true ? 'success' : donnees.success === false ? 'error' : 'unconfirmed';
  appel.latency = dureeValide(donnees.latency) ? donnees.latency : undefined;
  appel.result = donnees.result == null ? undefined : texteRecu(donnees.result);
  appel.endedAtMs = maintenant;
  appel.engine = typeof donnees.engine === 'string' && donnees.engine ? donnees.engine : undefined;
  // `0` passe : c'est le cas pour lequel ce champ existe. `typeof` seul
  // laisserait entrer NaN et Infinity, qui s'afficheraient tels quels.
  appel.numResults = Number.isInteger(donnees.numResults) ? (donnees.numResults as number) : undefined;
  return true;
}

/** Ce qu'une carte de recherche dit d'elle-même : « brave/news · 8 rés. ».
 *
 *  22/09/2026 (S2 du jury). `web_search` sait depuis le 20/09 quel moteur a
 *  répondu et combien de résultats il a rendus, mais rien ne le faisait
 *  traverser : la carte affichait la durée, et rien d'autre. Une recherche
 *  vide se lisait exactement comme une recherche fructueuse — et la réponse
 *  qui suit repose alors sur du vide sans que rien ne le dise (§5).
 *
 *  `vide` est porté à part pour que l'appelant le PEIGNE : un zéro de la
 *  même couleur qu'un huit ne se remarque pas. */
export function resumeDeRecherche(
  appel: Pick<ToolCallInfo, 'engine' | 'numResults'>,
): { texte: string; vide: boolean } | null {
  const morceaux: string[] = [];
  if (appel.engine) morceaux.push(appel.engine);
  if (appel.numResults !== undefined) {
    morceaux.push(appel.numResults === 1 ? '1 rés.' : `${appel.numResults} rés.`);
  }
  if (morceaux.length === 0) return null;
  return { texte: morceaux.join(' · '), vide: appel.numResults === 0 };
}

export function cloreAppels(appels: ToolCallInfo[]): void {
  // La coupure du flux n'arrête pas nécessairement l'outil côté serveur.
  // « Fin non reçue » est la seule observation certaine (22/09/2026).
  for (const appel of appels) if (appel.status === 'running') appel.status = 'unconfirmed';
}

export function appelsDeRecherche(traces: ResearchSearchTrace[]): ToolCallInfo[] {
  return traces.map(trace => ({
    id: trace.id,
    tool: trace.tool || 'search',
    arguments: JSON.stringify({ query: trace.query, person: trace.person, time_range: trace.timeRange }),
    status: trace.status === 'pending' ? 'running' : trace.error ? 'error' : 'success',
    startedAtMs: trace.startedAtMs,
    endedAtMs: trace.endedAtMs,
    // Ni durée ni nombre de résultats ne sont inventés si le serveur ne
    // les a pas transmis. Les titres sont un extrait, jamais une page lue.
    result: trace.status === 'complete' ? JSON.stringify({
      ...(trace.error ? { error: trace.error } : {}),
      ...(typeof trace.numHits === 'number' ? { num_hits: trace.numHits } : {}),
      ...(trace.topTitles ? { top_titles: trace.topTitles } : {}),
    }, null, 2) : undefined,
  }));
}

export function bilanExecution(appels: ToolCallInfo[], enDirect: boolean) {
  const etats = appels.map(a => etatExecution(a, enDirect));
  return {
    total: appels.length,
    reussis: etats.filter(e => e === 'success').length,
    erreurs: etats.filter(e => e === 'error').length,
    actifs: etats.filter(e => e === 'running').length,
    nonConfirmes: etats.filter(e => e === 'unconfirmed').length,
  };
}
