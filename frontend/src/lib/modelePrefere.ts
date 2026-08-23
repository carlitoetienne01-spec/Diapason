// Le choix du modèle initial d'une session (23 août 2026) : la préférence
// retenue de l'utilisateur d'abord — si elle existe encore — sinon la tête
// de liste, où le serveur place déjà son modèle par défaut.

export function modeleInitial(
  prefere: string,
  modeles: ReadonlyArray<{ id: string }>,
): string | null {
  if (modeles.length === 0) return null;
  if (prefere && modeles.some((m) => m.id === prefere)) return prefere;
  return modeles[0].id;
}
