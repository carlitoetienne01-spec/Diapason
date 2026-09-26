/**
 * Copier un texte, et dire si c'est fait.
 *
 * 26/09/2026 : trois boutons (Démarrer, Agents, Sources) appelaient
 * `navigator.clipboard.writeText` sans l'attendre ; Démarrer affichait
 * « Copié » dans la foulée, même quand l'écriture échouait (page hors
 * focus, permission refusée, WebView d'Android sans presse-papiers). Et
 * depuis 0239897 ce bouton est toujours visible au doigt. Rend `true`
 * seulement quand l'écriture a réussi.
 */
export async function copierTexte(
  texte: string,
  presse: { writeText(texte: string): Promise<void> } | undefined = typeof navigator !== 'undefined'
    ? navigator.clipboard
    : undefined,
): Promise<boolean> {
  if (!presse) return false;
  try {
    await presse.writeText(texte);
    return true;
  } catch {
    return false;
  }
}
