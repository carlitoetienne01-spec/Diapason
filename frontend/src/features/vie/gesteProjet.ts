// 28/09/2026 : draggable HTML ne permettait pas de ranger les dossiers au
// doigt. 400 ms distingue le toucher d'ouverture de la prise ; 8 px avant
// ce délai laisse partir le défilement natif, sans sélectionner un dossier.
export const APPUI_PROJET_MS = 400;
export const MARGE_PROJET_PX = 8;
export type PointProjet = { x: number; y: number };
export function doigtDeplace(a: PointProjet, b: PointProjet): boolean {
  return Math.hypot(a.x - b.x, a.y - b.y) > MARGE_PROJET_PX;
}
export function rangerProjet(ids: readonly string[], id: string, cible: string): string[] {
  const de = ids.indexOf(id);
  const vers = ids.indexOf(cible);
  if (de < 0 || vers < 0 || de === vers) return [...ids];
  const ordre = [...ids];
  ordre.splice(de, 1);
  ordre.splice(vers, 0, id);
  return ordre;
}
// 40 px au bord, au plus 10 px par image : on peut atteindre le rang
// suivant sans que le dernier dossier bondisse hors de portée du pouce.
export function pasDefilementProjet(y: number, haut: number, bas: number): number {
  if (y < haut + 40) return -Math.min(10, Math.max(0, (haut + 40 - y) / 4));
  if (y > bas - 40) return Math.min(10, Math.max(0, (y - bas + 40) / 4));
  return 0;
}
