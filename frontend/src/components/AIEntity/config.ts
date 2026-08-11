import type { AIQuality, AIState, StateProfile } from './types';

/**
 * Every number the entity's look depends on, in one place, so the behaviour
 * can be retuned without touching a shader.
 */

/** Grid resolution per quality tier. The field is far wider than it is deep —
 * it is a soundwave seen in volume, not a square terrain — so the column count
 * dominates. Products are ~8k / 21k / 38k / 66k points. */
export const GRID: Record<AIQuality, { cols: number; rows: number }> = {
  low: { cols: 168, rows: 48 },
  medium: { cols: 268, rows: 80 },
  high: { cols: 360, rows: 106 },
  ultra: { cols: 470, rows: 140 },
};

export const AI_ENTITY_CONFIG = {
  /** World size of the field. */
  geometry: {
    width: 13.5,
    depth: 6.4,
    /** Falls off from the centre outwards; this is what thins the ends into
     * transparency instead of cutting them off. */
    envelopeX: 1.55,
    envelopeZ: 1.15,
  },

  camera: {
    fov: 34,
    /** Framing moves the camera along a fixed elevation, never in height
     * alone. From high above the sheet's rows overlap into an opaque mound;
     * edge-on it collapses to a line. Holding the angle is what makes a phone
     * and a 4K display show the same object rather than two different ones. */
    elevationDeg: 15.3,
    distance: 9.6,
    minDistance: 8.6,
    maxDistance: 11.4,
    /** Fraction of the field's width to keep in frame. The ends have already
     * faded to nothing, so letting them spill costs nothing visually and
     * avoids shrinking the entity to a thread on a narrow screen. */
    framedWidth: 0.97,
    /** Ceiling on the horizontal stretch used to fill a wide banner. Beyond
     * this the lattice columns separate visibly and the surface goes sparse. */
    maxStretch: 3.2,
    lookAt: [0, -0.05, 0] as const,
    /** Pointer parallax ceiling, in world units. Deliberately tiny: the shot
     * stays cinematic, the user never "orbits a model". */
    parallax: 0.2,
    /** Autonomous drift so the frame breathes even with the pointer still. */
    drift: 0.075,
  },

  /**
   * The dictation banner's own palette: a spectrum laid across the width
   * rather than a single hue. Six stops, left to right, taken from the
   * reference — green through cyan and blue into violet, magenta and red.
   *
   * Kept apart from `colors` on purpose. The Talk panel keeps its strict cyan
   * identity; the dictation overlay is a different object with a different
   * job, and it will not inherit this by accident.
   */
  spectrum: {
    stops: [
      [0.0, 0.9, 0.52],   // #00E685 vert
      [0.0, 0.83, 0.92],  // #00D4EB cyan
      [0.13, 0.44, 1.0],  // #2170FF bleu
      [0.49, 0.24, 1.0],  // #7D3DFF violet
      [0.91, 0.22, 0.78], // #E838C7 magenta
      [1.0, 0.19, 0.42],  // #FF306B rouge
    ] as const,
    /** A handful of points burn far brighter than the rest — the specks that
     * make the reference feel lit rather than drawn. */
    sparkleChance: 0.012,
    sparkleGain: 5.5,
    /** Rows that read as bright strands running through the field, which is
     * what gives the reference its ribbon texture. */
    strandEvery: 7.0,
    strandGain: 1.9,
  },

  /** The banner's ribbon: rows become strands stacked vertically. */
  ribbon: {
    /** Vertical extent of the strand bundle, in world units. Generous on
     * purpose: the reference's ribbons are thick sheaves, not thin bands.
     * Widening this alone would thin the strands out, so the banner also
     * runs at the densest lattice — the two go together. */
    spread: 2.45,
    /** What little depth the strands keep, so the bundle still has body. */
    depth: 0.4,
    /** Alternations across the width. Four to five reads as a waveform; one
     * is a hump, and past eight the trace goes busy at banner height.
     * u spans -1..1, so sin(u·cycles·2π) covers 2·cycles cycles — four
     * alternations per unit. 1.15 therefore gives the four to five wanted. */
    cycles: 1.15,
    /** How gently the ribbon fades toward the ends. Far flatter than the
     * terrain's envelope, which concentrates everything centrally and leaves
     * exactly one peak. */
    falloff: 0.55,
    /** The second, thinner ribbon: its phase offset, its share of the
     * thickness and of the light. */
    second: { phase: 2.35, spread: 0.62, glow: 0.6 },
    /** How far a loud band lifts the peak sitting over it. This is what makes
     * one crest dominate, and makes which one depend on what was said. */
    peakGain: 1.5,
  },

  /** Framing for the dictation banner, which is a different shot entirely:
   * a low bed with room above it for the columns. Kept separate so the Talk
   * panel, which has no columns, is not dragged along with it. */
  banner: {
    elevationDeg: 4.5,
    lookAtY: 0.0,
  },


  points: {
    /** Multiplied by the perspective term; the real pixel size also depends on
     * the envelope and on the device pixel ratio. */
    baseSize: 2.55,
    /** Ceiling in device pixels, so a point never becomes a blob up close. */
    maxSize: 5.2,
    /** Softness of the round falloff inside each point sprite. */
    softness: 0.42,
  },

  /** Strictly cyan → ice → white-cyan. Nothing else may enter the palette:
   * a single green or violet sample would break the whole identity. */
  colors: {
    deep: [0.0, 0.42, 0.66] as const, // #006BA8 — troughs, far edges
    mid: [0.0, 0.78, 0.98] as const, // #00C7FA — body of the wave
    bright: [0.24, 0.9, 1.0] as const, // #5CEDFF — crests
    peak: [0.55, 0.94, 1.0] as const, // #C9FAFF — the few hottest points
  },

  /** Three superposed frequencies keep the motion from reading as mechanical. */
  waves: {
    slow: { freq: 0.9, speed: 0.115, amp: 1.0 },
    medium: { freq: 1.72, speed: 0.255, amp: 0.44 },
    micro: { freq: 4.35, speed: 0.62, amp: 0.115 },
    /** Octaves of fbm layered over the sines for ridges and valleys. */
    noiseOctaves: 4,
    noiseFreq: 0.92,
    noiseSpeed: 0.135,
  },

  audio: {
    /** Exponential smoothing per band. Attack is faster than release so the
     * field answers a syllable but does not flicker between them. */
    attack: 0.34,
    release: 0.085,
    /** Rolling peak normalisation keeps a whisper and a shout both usable. */
    peakDecay: 0.9985,
    peakFloor: 0.045,
  },

  transition: {
    /** Seconds to cover ~95% of the distance to a new state's profile.
     * Inside the 300–900 ms band the brief asks for. */
    seconds: 0.55,
  },

  quality: {
    maxPixelRatio: 2,
    /** Drop a tier when the rolling frame time stays above this (≈45 fps). */
    downgradeMs: 22,
    /** Climb back only well clear of the boundary, so it cannot oscillate. */
    upgradeMs: 12.5,
    sampleFrames: 90,
  },
} as const;

/**
 * Per-state targets. The render loop eases the live parameters toward these,
 * so `idle → speaking` is a continuous deformation of one field rather than a
 * swap between two animations.
 */
export const STATE_PROFILES: Record<AIState, StateProfile> = {
  /** Present and attentive, never asleep — and never miming speech. */
  idle: {
    amplitude: 1.15,
    speed: 0.55,
    turbulence: 0.34,
    focus: 0.94,
    glow: 1.3,
    shimmer: 0.3,
    breath: 0.3,
    audioDrive: 0.0,
  },
  /** Attention: the field draws in on itself and pulses lightly. */
  listening: {
    amplitude: 1.12,
    speed: 0.72,
    turbulence: 0.42,
    focus: 1.16,
    glow: 2.35,
    shimmer: 0.52,
    breath: 0.62,
    audioDrive: 0.62,
  },
  /** Internal work: waves travel through the structure, density shifts.
   * Deliberately not a spinner — the field itself looks like it is computing. */
  thinking: {
    amplitude: 1.24,
    speed: 1.35,
    turbulence: 1.0,
    focus: 1.05,
    glow: 2.25,
    shimmer: 0.72,
    breath: 1.0,
    audioDrive: 0.2,
  },
  /** Expression: the voice becomes the topography. */
  speaking: {
    amplitude: 1.62,
    speed: 0.95,
    turbulence: 0.52,
    focus: 0.9,
    glow: 1.75,
    shimmer: 0.86,
    breath: 0.45,
    audioDrive: 1.0,
  },
};

/** Reduced-motion variant: the entity still lives, far more slowly. Hiding it
 * would remove the only indication that the assistant is present. */
export function calmProfile(profile: StateProfile): StateProfile {
  return {
    ...profile,
    amplitude: profile.amplitude * 0.42,
    speed: profile.speed * 0.2,
    turbulence: profile.turbulence * 0.25,
    shimmer: profile.shimmer * 0.25,
    breath: profile.breath * 0.3,
    audioDrive: profile.audioDrive * 0.3,
  };
}
