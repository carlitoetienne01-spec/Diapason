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
    position: [0, 1.5, 4.4] as const,
    target: [0, 0.55, 0] as const,
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

  /** Seconds. Spectrum smoothing on the render side, on top of the analyser's. */
  spectrumAttack: 0.05,
  spectrumRelease: 0.2,
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
}

export const TERRAIN_STATE_PROFILES: Record<AIState, TerrainStateProfile> = {
  /** At rest: a real massif, only lower and calmer, breathing very slowly. */
  idle: {
    amplitude: 0.62,
    turbulence: 0.55,
    speed: 0.16,
    spread: 1.0,
    glow: 0.82,
    spectrumDrive: 0.35,
  },
  /** Listening: the mass narrows and sharpens, leaning toward the voice. */
  listening: {
    amplitude: 0.72,
    turbulence: 0.85,
    speed: 0.4,
    spread: 0.86,
    glow: 1.0,
    spectrumDrive: 1.35,
  },
  /** Thinking: no voice to follow, so the rock itself churns. */
  thinking: {
    amplitude: 0.66,
    turbulence: 1.6,
    speed: 1.4,
    spread: 0.95,
    glow: 0.9,
    spectrumDrive: 0.5,
  },
  /** Speaking: full height, peaks driven hard by the assistant's own voice. */
  speaking: {
    amplitude: 0.80,
    turbulence: 1.05,
    speed: 0.7,
    spread: 1.05,
    glow: 1.15,
    spectrumDrive: 1.6,
  },
};

/** Transition time constant (s): settled in ≈ 3τ ≈ 450 ms. */
export const TERRAIN_EASE_TAU = 0.15;
