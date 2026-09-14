/** Énergie PCM réelle, indépendante du nombre de bandes FFT silencieuses. */
export function rmsVocal(echantillons: Float32Array): number {
  if (!echantillons.length) return 0;
  let somme = 0;
  for (const valeur of echantillons) {
    if (!Number.isFinite(valeur)) return 0;
    somme += valeur * valeur;
  }
  return Math.sqrt(somme / echantillons.length);
}

export class NiveauVocal {
  // -50 dBFS environ écarte le souffle faible ; le plancher du pic
  // (~-28 dBFS) empêche un micro silencieux d'amplifier son propre bruit.
  private pic = 0.04;
  private precedent: number | null = null;

  lire(echantillons: Float32Array, maintenant: number): number {
    const rms = rmsVocal(echantillons);
    const delta = this.precedent === null ? 0 : Math.max(0, (maintenant - this.precedent) / 1000);
    this.precedent = maintenant;
    // Trois secondes pour oublier une voix forte, indépendamment des FPS.
    this.pic = Math.max(0.04, rms, this.pic * Math.exp(-delta / 3));
    return Math.sqrt(Math.max(0, Math.min(1, (rms - 0.003) / (this.pic - 0.003))));
  }
}
