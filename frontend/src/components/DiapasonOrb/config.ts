/** Tuning table for Diapason's energetic body.
 *
 * Everything the eye can notice has a knob here — counts, palette, noise,
 * bloom, per-state behavior — so the look is adjusted in one place instead
 * of by spelunking through shaders.
 */

import type { AIQuality, AIState } from '../AIEntity/types';

export const DIAPASON_ORB_CONFIG = {
  /** Camera: mild perspective, per spec — volume without distortion. */
  camera: { fov: 35, z: 5.2 },

  /** Global scene scale multiplier applied to the whole group. */
  worldScale: 0.9,

  /** Slow whole-body motion. */
  rotationSpeedY: 0.008,
  rotationWobbleX: 0.055,
  rotationWobbleSpeed: 0.15,

  /** Pointer parallax budget, radians (≈ ±4°). */
  pointerTilt: 0.07,

  /** Bloom — the halo lives here, not in textures. */
  bloom: { strength: 0.86, radius: 0.32, threshold: 0.28 },
  toneMappingExposure: 0.98,

  /** Core assembly. */
  core: {
    radius: 0.075,
    haloScale: 0.52,
    sparkCount: 900,
    sparkMinRadius: 0.15,
    sparkMaxRadius: 1.22,
    ringRadii: [0.3, 0.45, 0.62],
    ringOpacity: 0.075,
  },

  /** Audio smoothing time constants (seconds). */
  audioAttack: 0.06,
  audioRelease: 0.25,
} as const;

/** How many grid points each membrane gets per quality tier.
 * Five membranes keep the total in the same performance envelope as the old
 * three denser sheets, while producing the layered spherical silhouette. */
export const MEMBRANE_GRID: Record<AIQuality, { u: number; v: number }> = {
  ultra: { u: 116, v: 84 }, // ≈ 49k total
  high: { u: 102, v: 74 }, // ≈ 38k
  medium: { u: 84, v: 60 }, // ≈ 25k
  low: { u: 64, v: 44 }, // ≈ 14k
};

/** The five broad ribbons visible in the reference. They share the same
 * luminous point-grid material but follow independent spatial loops. */
export interface MembraneSpec {
  seed: number;
  /** Elliptical path around the core: horizontal, vertical and depth radii. */
  orbit: [number, number, number];
  /** Half-width of the cloth around its centreline. */
  width: number;
  /** Number of turns completed from one tapered end to the other. */
  turns: number;
  /** Vertical undulations along the centreline. */
  lobes: number;
  /** Starting position on the orbit. */
  phase: number;
  /** Frequency and height of the large folds across the cloth. */
  foldFrequency: number;
  foldAmplitude: number;
  /** Rotation of the cloth around its own path. */
  twist: number;
  /** Independent animation speed. */
  speed: number;
  /** Portion of the warm palette allowed on this veil. */
  warmth: number;
  /** Static orientation, radians. */
  rotation: [number, number, number];
  /** Composition offset: keeps the five ribbons from collapsing at centre. */
  offset: [number, number, number];
  /** Base point size multiplier. */
  size: number;
  /** Overall alpha multiplier — the third veil is the faint one. */
  alpha: number;
}

export const MEMBRANES: MembraneSpec[] = [
  {
    seed: 7.31,
    orbit: [1.7, 0.46, 0.72],
    width: 0.9,
    turns: 0.58,
    lobes: 1.2,
    phase: -0.2,
    foldFrequency: 0.9,
    foldAmplitude: 0.24,
    twist: 0.12,
    speed: 0.2,
    warmth: 0.08,
    rotation: [0.04, 0.08, -0.1],
    offset: [-0.08, -0.34, 0.2],
    size: 1.18,
    alpha: 0.94,
  },
  {
    seed: 19.77,
    orbit: [1.58, 0.42, 0.68],
    width: 0.86,
    turns: 0.64,
    lobes: 1.0,
    phase: 1.35,
    foldFrequency: 1.05,
    foldAmplitude: 0.25,
    twist: -0.15,
    speed: -0.16,
    warmth: 0.96,
    rotation: [0.16, -0.12, 0.1],
    offset: [-0.06, 0.55, -0.16],
    size: 1.08,
    alpha: 0.86,
  },
  {
    seed: 42.13,
    orbit: [1.48, 0.48, 0.72],
    width: 0.8,
    turns: 0.68,
    lobes: 1.35,
    phase: 2.45,
    foldFrequency: 1.2,
    foldAmplitude: 0.26,
    twist: 0.18,
    speed: 0.14,
    warmth: 0.04,
    rotation: [-0.18, 0.35, 0.32],
    offset: [0.46, 0.09, 0.02],
    size: 0.96,
    alpha: 0.78,
  },
  {
    seed: 63.41,
    orbit: [1.42, 0.5, 0.7],
    width: 0.78,
    turns: 0.62,
    lobes: 1.25,
    phase: -2.2,
    foldFrequency: 1.15,
    foldAmplitude: 0.24,
    twist: -0.2,
    speed: -0.12,
    warmth: 0.18,
    rotation: [0.2, -0.3, -0.36],
    offset: [-0.46, 0.08, -0.24],
    size: 0.9,
    alpha: 0.72,
  },
  {
    seed: 88.09,
    orbit: [1.62, 0.44, 0.78],
    width: 0.88,
    turns: 0.66,
    lobes: 1.15,
    phase: 0.75,
    foldFrequency: 0.95,
    foldAmplitude: 0.27,
    twist: 0.2,
    speed: 0.1,
    warmth: 0.74,
    rotation: [-0.18, -0.2, 0.16],
    offset: [0.18, -0.5, 0.22],
    size: 1.0,
    alpha: 0.8,
  },
];

/** Palette, as linear-ish RGB triples fed straight to the shaders. */
export const PALETTE = {
  deepBlue: [0.024, 0.09, 0.165],
  electricBlue: [0.086, 0.486, 1.0],
  neonCyan: [0.0, 0.851, 1.0],
  iceBlue: [0.659, 0.929, 1.0],
  white: [1.0, 1.0, 1.0],
  amber: [1.0, 0.667, 0.2],
  gold: [1.0, 0.82, 0.4],
  violet: [0.467, 0.408, 1.0],
} as const;

/** Per-state targets. A state change is a lerp toward these, never a jump
 * (300–600 ms, exponential easing in the scene clock). */
export interface OrbStateProfile {
  /** Wave/noise displacement multiplier. */
  amplitude: number;
  /** Advance rate of every membrane clock. */
  speed: number;
  /** Weight of fine noise octaves + curl — internal agitation. */
  turbulence: number;
  /** >1 draws the veils toward the core (listening). */
  focus: number;
  /** Base brightness multiplier. */
  glow: number;
  /** Audio-driven twinkle strength on individual points. */
  shimmer: number;
  /** Core activity: halo scale + breathing depth. */
  coreActivity: number;
  /** Whole-body rotation multiplier. */
  rotation: number;
  /** Cyan boost, 0–1 (listening leans colder/brighter). */
  cyanBoost: number;
}

export const ORB_STATE_PROFILES: Record<AIState, OrbStateProfile> = {
  idle: {
    amplitude: 0.75,
    speed: 0.55,
    turbulence: 0.55,
    focus: 1.0,
    glow: 0.8,
    shimmer: 0.25,
    coreActivity: 0.7,
    rotation: 1.0,
    cyanBoost: 0.0,
  },
  listening: {
    amplitude: 0.85,
    speed: 0.7,
    turbulence: 0.7,
    focus: 1.28,
    glow: 0.8,
    shimmer: 0.6,
    coreActivity: 0.72,
    rotation: 0.8,
    cyanBoost: 0.38,
  },
  thinking: {
    amplitude: 0.95,
    speed: 1.25,
    turbulence: 1.35,
    focus: 1.08,
    glow: 0.84,
    shimmer: 0.45,
    coreActivity: 0.95,
    rotation: 1.8,
    cyanBoost: 0.2,
  },
  speaking: {
    amplitude: 1.25,
    speed: 1.0,
    turbulence: 0.9,
    focus: 1.0,
    glow: 0.9,
    shimmer: 0.9,
    coreActivity: 0.88,
    rotation: 1.1,
    cyanBoost: 0.15,
  },
};

/** Transition time constant (s): ~63 % of the way in τ, settled ≈ 3τ ≈ 450 ms. */
export const STATE_EASE_TAU = 0.15;
