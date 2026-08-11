/** Public surface of the AI entity. Kept separate so the scene layer, which
 * knows nothing about React, can share it. */

/** What the entity is doing. Everything visual derives from this. */
export type AIState = 'idle' | 'listening' | 'thinking' | 'speaking';

export type AIQuality = 'low' | 'medium' | 'high' | 'ultra';

/** Anything the analyser can be attached to. `null` means "no audio" — the
 * entity is fully alive on procedural animation alone. */
export type AIAudioSource =
  | HTMLAudioElement
  | MediaStream
  | AudioNode
  | null
  | undefined;

/** Smoothed, normalised spectral energy. Raw FFT bins jitter; these do not. */
export interface AudioBands {
  /** Overall loudness, 0–1. */
  level: number;
  /** 20–250 Hz — drives depth. */
  bass: number;
  /** 250–2000 Hz — drives the main swell. */
  mid: number;
  /** 2–16 kHz — drives the shimmer on individual points. */
  high: number;
}

export const SILENT_BANDS: AudioBands = { level: 0, bass: 0, mid: 0, high: 0 };

export interface AIEntityProps {
  state?: AIState;
  /** Global energy multiplier, 0–1. Scales amplitude and brightness. */
  intensity?: number;
  audioSource?: AIAudioSource;
  /** Pointer parallax. Off by default so the canvas stays click-through. */
  interactive?: boolean;
  /** Omit to pick from the device and adapt to measured frame time. */
  quality?: AIQuality;
  className?: string;
  style?: React.CSSProperties;
}

/** The per-state numbers the render loop eases between. Each field is a plain
 * scalar precisely so a transition is a lerp and never a branch. */
export interface StateProfile {
  /** Vertical swell of the main waves. */
  amplitude: number;
  /** Travelling-wave speed. */
  speed: number;
  /** Weight of the fine noise octaves — internal activity. */
  turbulence: number;
  /** Horizontal squeeze; >1 pulls the field toward the centre. */
  focus: number;
  /** Base brightness. */
  glow: number;
  /** Per-point twinkle. */
  shimmer: number;
  /** Rate of the slow breathing envelope. */
  breath: number;
  /** How strongly audio bands displace the field. */
  audioDrive: number;
}
