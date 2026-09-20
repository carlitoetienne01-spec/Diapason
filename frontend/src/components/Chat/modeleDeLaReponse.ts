// 20/09/2026 : le pied de chaque réponse affichait le modèle du SÉLECTEUR
// (« qwen3.8:27b-mlx »), jamais celui qui avait répondu. Dès qu'un tour
// léger part sur le petit modèle (server/tour_leger.py), cette étiquette
// mentirait (§5). Le serveur écrit le modèle dans chaque fragment et, quand
// il a changé, un bloc routing {model, from, reason} dans le bilan.

export interface RoutageServeur {
  model?: string;
  from?: string | null;
  reason?: string;
}

export interface ModeleDeLaReponse {
  model_id?: string;
  routed_from?: string;
}

export function modeleDeLaReponse(
  choisi: string,
  serveur: string | undefined,
  routage: RoutageServeur | undefined,
  eclair = false,
): ModeleDeLaReponse {
  // Revue du 20/09/2026 : la voie éclair n'appelle aucun modèle, mais ses
  // fragments portent le nom du sélecteur (forme OpenAI oblige). Afficher
  // « lightning · qwen3.8:27b-mlx » attribuait 1,2 s à un modèle qui n'a
  // rien fait.
  if (eclair) return {};
  const reel = (serveur || '').trim() || choisi;
  const origine = (routage?.from || '').trim();
  if (origine && origine !== reel) return { model_id: reel, routed_from: origine };
  return { model_id: reel };
}

/** « qwen3.5:9b ← qwen3.8:27b-mlx » dans le résumé replié ; le modèle seul sinon. */
export function etiquetteDuModele(t: { model_id?: string; routed_from?: string }): string {
  if (!t.model_id) return '';
  return t.routed_from ? `${t.model_id} ← ${t.routed_from}` : t.model_id;
}
