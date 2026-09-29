// 28/09/2026 : la roue tourne avant que le préchargement au repos ait fini.
// Elle prépare en priorité la destination et ses voisines, avec les mêmes
// promesses que React.lazy, sans monter des pages ni leurs effets de bord.
const pages = new Map<string, () => Promise<unknown>>();
export function enregistrerPrechargements(routes: Record<string, () => Promise<unknown>>) {
  for (const [chemin, charger] of Object.entries(routes)) pages.set(chemin, charger);
}
export function prechargerRoutes(chemins: string[]) {
  for (const chemin of chemins) void pages.get(chemin)?.().catch(() => {});
}
