/** Détacher une branche empruntée, sans débrancher les autres sorties. */
export function deconnecterBrancheAudio(source: AudioNode, destination: AudioNode): void {
  try {
    source.disconnect(destination);
  } catch (erreur) {
    // 27/09/2026 : arrêter Orion déconnecte sa sortie avant que React ne
    // démonte le visualiseur. WebKit lève alors InvalidAccessError :
    // « The given destination is not connected », et tout le chat tombe.
    // Seule cette branche déjà retirée est un nettoyage réussi.
    if (!(erreur instanceof DOMException) || erreur.name !== 'InvalidAccessError') throw erreur;
  }
}
