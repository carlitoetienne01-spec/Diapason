import type { VoiceLiveState } from '../../hooks/useVoiceLive';
import type { AIQuality } from '../AIEntity/types';

export const DENSITES: Record<AIQuality, readonly [number, number]> = {
  low: [128, 72], medium: [176, 96], high: [240, 128], ultra: [288, 152],
};

export const PROFILS: Record<VoiceLiveState, { taille: number; vitesse: number; voix: number }> = {
  idle: { taille: 0.95, vitesse: 0.16, voix: 0 },
  connecting: { taille: 0.92, vitesse: 0.24, voix: 0 },
  // 29/09/2026 : 0,20 à l'écoute ne déplaçait le rayon que de quelques
  // centièmes. 0,95 laisse la voix pousser des lobes.
  listening: { taille: 0.91, vitesse: 0.22, voix: 0.95 },
  speaking: { taille: 1.02, vitesse: 0.30, voix: 1 },
  error: { taille: 0.95, vitesse: 0, voix: 0 },
};

export function energieVocale(niveau: number, etat: VoiceLiveState, mouvementReduit: boolean): number {
  if (mouvementReduit || !PROFILS[etat].voix || !Number.isFinite(niveau)) return 0;
  // 12 septembre 2026 : le souffle du micro gonflait une forme pourtant
  // silencieuse. Les 3,5 % inférieurs ne doivent pas simuler une syllabe.
  return Math.max(0, Math.min(1, (niveau - 0.035) / 0.965));
}

/** Au-dessus du seuil, une voix douce doit déjà déformer le volume.
 * 29/09/2026 : la courbe linéaire laissait une phrase à 0,12 d'énergie
 * presque immobile. L'exposant 0,55 porte ce 0,12 vers 0,31 ; un cri reste à 1. */
export function presenceVocale(energie: number): number {
  if (energie <= 0 || !Number.isFinite(energie)) return 0;
  return Math.pow(Math.min(1, energie), 0.55);
}

export function approcher(valeur: number, cible: number, delta: number, duree: number): number {
  return valeur + (cible - valeur) * (1 - Math.exp(-Math.max(0, delta) / duree));
}

/** Trois voiles fermés ; les pôles sont évités pour ne pas empiler une
 * longitude entière dans un seul pixel blanc. Aucun aléatoire par image. */
export function pointsDesVoiles(qualite: AIQuality): Float32Array {
  const [colonnes, lignes] = DENSITES[qualite];
  const points = new Float32Array(colonnes * lignes * 3 * 3);
  let i = 0;
  for (let voile = 0; voile < 3; voile++) {
    for (let y = 0; y < lignes; y++) {
      for (let x = 0; x < colonnes; x++) {
        points[i++] = ((x + (y % 2) * 0.5) / colonnes) * Math.PI * 2;
        points[i++] = ((y + 0.5) / lignes) * Math.PI;
        points[i++] = voile;
      }
    }
  }
  return points;
}
