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
  worldScale: 1.0,

  /** Slow whole-body motion. */
  rotationSpeedY: 0.05,
  rotationWobbleX: 0.08,
  rotationWobbleSpeed: 0.15,

  /** Pointer parallax budget, radians (≈ ±4°). */
  pointerTilt: 0.07,

  /** Bloom — the halo lives here, not in textures. */
  bloom: { strength: 1.15, radius: 0.5, threshold: 0.15 },
  toneMappingExposure: 1.0,

  /** Core assembly. */
  core: {
    radius: 0.15,
    haloScale: 1.35,
    sparkCount: 1400,
    sparkMinRadius: 0.18,
    sparkMaxRadius: 0.95,
    ringRadii: [0.34, 0.47],
    ringOpacity: 0.09,
  },

  /** Audio smoothing time constants (seconds). */
  audioAttack: 0.06,
  audioRelease: 0.25,
} as const;

/** How many grid points each membrane gets per quality tier.
 * Three membranes → total roughly ×3 (before density culling). */
export const MEMBRANE_GRID: Record<AIQuality, { u: number; v: number }> = {
  ultra: { u: 168, v: 132 }, // ≈ 66.5k total
  high: { u: 144, v: 112 }, // ≈ 48.4k
  medium: { u: 112, v: 84 }, // ≈ 28.2k
  low: { u: 82, v: 60 }, // ≈ 14.8k
};

/** The three veils. Each has its own geometry span, motion clock and warmth
 * so nothing ever synchronizes — the "multidimensional organism" effect. */
export interface MembraneSpec {
  seed: number;
  /** Sheet half-size before wrapping. */
  scale: [number, number];
  /** How far the sheet is bent onto a spherical cap (0 flat → 1 sphere). */
  wrap: number;
  /** Spherical cap span, radians (theta, phi). */
  span: [number, number];
  radius: number;
  /** Sine wave stacks: frequencies, speeds, amplitudes (3 each). */
  freq: [number, number, number];
  speed: [number, number, number];
  amp: [number, number, number];
  noiseStrength: number;
  curlStrength: number;
  /** Portion of the warm palette allowed on this veil. */
  warmth: number;
  /** Static orientation, radians. */
  rotation: [number, number, number];
  /** Base point size multiplier. */
  size: number;
  /** Overall alpha multiplier — the third veil is the faint one. */
  alpha: number;
}

export const MEMBRANES: MembraneSpec[] = [
  {
    seed: 7.31,
    scale: [2.35, 1.35],
    wrap: 0.62,
    span: [2.5, 1.35],
    radius: 1.42,
    freq: [2.1, 2.9, 1.4],
    speed: [0.32, 0.21, 0.4],
    amp: [0.34, 0.22, 0.16],
    noiseStrength: 0.42,
    curlStrength: 0.22,
    warmth: 0.4,
    rotation: [0.0, 0.0, 0.1],
    size: 1.0,
    alpha: 1.0,
  },
  {
    seed: 19.77,
    scale: [2.1, 1.5],
    wrap: 0.55,
    span: [2.2, 1.5],
    radius: 1.3,
    freq: [1.7, 3.4, 2.2],
    speed: [-0.24, 0.31, -0.18],
    amp: [0.28, 0.18, 0.2],
    noiseStrength: 0.5,
    curlStrength: 0.28,
    warmth: 0.25,
    rotation: [0.52, -0.35, 0.26],
    size: 0.9,
    alpha: 0.85,
  },
  {
    seed: 42.13,
    scale: [2.6, 1.7],
    wrap: 0.48,
    span: [2.8, 1.6],
    radius: 1.55,
    freq: [1.2, 2.2, 3.1],
    speed: [0.17, -0.13, 0.26],
    amp: [0.22, 0.26, 0.12],
    noiseStrength: 0.36,
    curlStrength: 0.18,
    warmth: 0.12,
    rotation: [-0.42, 0.55, -0.2],
    size: 0.72,
    alpha: 0.55,
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
    glow: 1.0,
    shimmer: 0.6,
    coreActivity: 0.9,
    rotation: 0.8,
    cyanBoost: 0.55,
  },
  thinking: {
    amplitude: 0.95,
    speed: 1.25,
    turbulence: 1.35,
    focus: 1.08,
    glow: 0.95,
    shimmer: 0.45,
    coreActivity: 1.25,
    rotation: 1.8,
    cyanBoost: 0.2,
  },
  speaking: {
    amplitude: 1.25,
    speed: 1.0,
    turbulence: 0.9,
    focus: 1.0,
    glow: 1.15,
    shimmer: 0.9,
    coreActivity: 1.1,
    rotation: 1.1,
    cyanBoost: 0.15,
  },
};

/** Transition time constant (s): ~63 % of the way in τ, settled ≈ 3τ ≈ 450 ms. */
export const STATE_EASE_TAU = 0.15;
