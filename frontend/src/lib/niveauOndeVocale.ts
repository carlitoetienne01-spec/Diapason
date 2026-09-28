/** Niveau réellement mesuré ; gain d'affichage seulement, jamais du micro. */
export function niveauOndeVocale(echantillons: Uint8Array, precedent: number, delaiMs: number): number {
  let energie = 0;
  for (const valeur of echantillons) energie += ((valeur - 128) / 128) ** 2;
  const rms = echantillons.length ? Math.sqrt(energie / echantillons.length) : 0;
  // 27/09/2026 : le tracé linéaire disparaissait sur les voix douces.
  // Seuil -50 dB pour le silence, pleine hauteur dès -18 dB environ ;
  // 35 ms à la montée, 160 ms à la descente pour garder les syllabes lisibles.
  const cible = Math.min(1, Math.sqrt(Math.max(0, rms - 0.003) / 0.12));
  const duree = cible > precedent ? 35 : 160;
  return precedent + (cible - precedent) * (1 - Math.exp(-Math.max(0, delaiMs) / duree));
}
