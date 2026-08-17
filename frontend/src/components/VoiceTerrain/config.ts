/** Tuning table for the voice terrain.
 *
 * The entity is a point-cloud relief: a single massif seen head-on, its ridges
 * sculpted by the live spectrum. Bass raises the central summit, treble pushes
 * the outer foothills, so the silhouette is the voice itself rather than a
 * decoration reacting to it.
 */

import type { AIQuality, AIState } from '../AIEntity/types';

/** Grid resolution per tier. Products are ~15k / 34k / 68k / 105k points.
 * Roughly a third of them are dropped by the density mask, so the visible
 * counts land near the reference's grain. Density is what makes the relief
 * read as rock rather than as a scatter, so it is the first thing to spend on
 * and the adaptive tier is there to take it back if the GPU cannot hold 60. */
export const TERRAIN_GRID: Record<AIQuality, { cols: number; rows: number }> = {
  low: { cols: 160, rows: 95 },
  medium: { cols: 240, rows: 140 },
  high: { cols: 340, rows: 200 },
  ultra: { cols: 420, rows: 250 },
};

/** Noise octaves per tier. Fine detail is the other half of "rock". */
export const TERRAIN_OCTAVES: Record<AIQuality, number> = {
  low: 4,
  medium: 5,
  high: 6,
  ultra: 7,
};

export const TERRAIN_CONFIG = {
  /** Fixed framing: head-on, slightly above. Pulled back far enough that a
   * crest thrown up by a loud syllable has somewhere to go. */
  camera: {
    fov: 32,
    // Reculée et relevée depuis que la flèche existe : à l'ancien cadrage,
    // un mot un peu fort projetait le sommet hors de l'image, et une crête
    // qu'on ne voit pas ne sert à rien.
    position: [0, 2.05, 5.6] as const,
    target: [0, 1.0, 0] as const,
  },

  /** World size of the sheet the relief is built on. Wider than the frame, so
   * the foothills run off the edges instead of dissolving inside it. */
  geometry: { width: 4.8, depth: 3.4 },

  /** Key light, in world space: high and to the left, so the massif has a lit
   * flank and a shaded one instead of reading flat. */
  light: [-0.55, 0.68, 0.48] as const,

  /** Depth cueing. Back ridges sink toward the background, which is most of
   * what sells the distance between them. */
  fog: { near: 3.7, far: 6.6 },

  /** Deliberately faint: the surface is lit, not glowing. Bloom is here only to
   * let the crests catch, and it must never wash the hue out. */
  bloom: { strength: 0.28, radius: 0.5, threshold: 0.58 },

  /** Base point size in pixels, before the per-point variation. Small grains,
   * many of them. */
  pointSize: 1.2,

  /** Secondes. Lissage du spectre côté rendu, par-dessus celui de l'analyseur.
   *
   * L'attaque est presque nulle : une syllabe doit lever la crête AVANT qu'on
   * ait fini de la prononcer, sinon le relief a l'air de commenter la voix
   * plutôt que de l'être. La retombée reste lente — une crête qui disparaît
   * avant qu'on l'ait vue n'a pas servi. */
  spectrumAttack: 0.012,
  spectrumRelease: 0.28,

  /** En dessous, on considère qu'il n'y a personne.
   *
   * Mesuré sur une pièce calme avec le Mac allumé : le bruit de fond monte
   * à peine au-dessus de 0,02. Le seuil est juste au-dessus, assez bas pour
   * qu'un mot murmuré passe, assez haut pour qu'un ventilateur ne passe pas. */
  gateThreshold: 0.035,

  /** Gain appliqué aux bandes une fois la porte franchie.
   *
   * Ce qui rend la réaction spectaculaire : au-delà de 1, une voix ordinaire
   * sature les bandes hautes et jette la flèche au plafond. La saturation est
   * voulue — elle est ce qui donne le pic, et le shader la borne. */
  spectrumGain: 2.6,
} as const;

/** Per-state targets. A state change is a lerp toward these, never a jump. */
export interface TerrainStateProfile {
  /** Overall height of the relief. */
  amplitude: number;
  /** Weight of the fine noise octaves — how broken the rock reads. */
  turbulence: number;
  /** Drift rate of the noise field. */
  speed: number;
  /** <1 pulls the massif into a narrower, taller spine. */
  spread: number;
  /** Base brightness. */
  glow: number;
  /** How strongly the spectrum sculpts the ridges. */
  spectrumDrive: number;
  /** Poids de la flèche centrale, multiplié par le niveau vocal.
   *
   * À 0 le sommet n'existe pas : c'est l'état de repos voulu, où il ne reste
   * que le massif. Ce qui monte, c'est la voix — pas un décor qui grossit. */
  spire: number;
}

export const TERRAIN_STATE_PROFILES: Record<AIState, TerrainStateProfile> = {
  /** At rest: a real massif, only lower and calmer, breathing very slowly. */
  idle: {
    amplitude: 0.74,
    turbulence: 0.62,
    speed: 0.16,
    spread: 0.72,
    glow: 0.82,
    spectrumDrive: 0.30,
    spire: 0.0,
  },
  /** Listening: the mass narrows and sharpens, leaning toward the voice. */
  listening: {
    amplitude: 0.78,
    turbulence: 0.95,
    speed: 0.45,
    spread: 0.58,
    glow: 1.0,
    spectrumDrive: 2.4,
    spire: 2.9,
  },
  /** Thinking: no voice to follow, so the rock itself churns. */
  thinking: {
    amplitude: 0.60,
    turbulence: 1.6,
    speed: 1.4,
    spread: 0.70,
    glow: 0.9,
    spectrumDrive: 0.5,
    spire: 0.25,
  },
  /** Speaking: full height, peaks driven hard by the assistant's own voice. */
  speaking: {
    amplitude: 0.86,
    turbulence: 1.15,
    speed: 0.7,
    spread: 0.60,
    glow: 1.15,
    spectrumDrive: 2.6,
    spire: 3.1,
  },
};

/** Transition time constant (s): settled in ≈ 3τ ≈ 450 ms. */
export const TERRAIN_EASE_TAU = 0.15;
