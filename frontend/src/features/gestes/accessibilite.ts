/** Ce que le bandeau rouge doit dire quand Accessibilité ment. */

export function aideDroitAccessibilite(erreur: string | null): string | null {
  if (!erreur || !erreur.includes('Accessibilité')) return null;
  return (
    'La case cochée peut rester allumée alors que le droit est mort : macOS ' +
    'reconnaît le nom, pas cette copie. Retire Diapason (bouton −), ajoute ' +
    '/Applications/Diapason.app, quitte l’app et relance-la.'
  );
}

export async function ouvrirReglageAccessibilite(): Promise<void> {
  if (typeof window === 'undefined' || !window.__TAURI_INTERNALS__) return;
  const { invoke } = await import('@tauri-apps/api/core');
  await invoke('ouvrir_reglage_accessibilite');
}
