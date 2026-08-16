import { useEffect, useRef } from 'react';

import { AI_ENTITY_CONFIG as C } from '../components/AIEntity/config';
import type { AIAudioSource } from '../components/AIEntity/types';

/** Number of log-spaced bands handed to the terrain. One band is one ridge. */
export const SPECTRUM_BINS = 64;

/** Voice lives between these; below is rumble, above is hiss. */
const LOW_HZ = 55;
const HIGH_HZ = 12000;

export interface SpectrumFrame {
  /** Overall loudness, 0–1. */
  level: number;
  /** Per-band energy, 0–1, low frequency first. */
  bins: Float32Array;
}

interface Analysis {
  /** Read on the render loop's schedule — never triggers a React render. */
  read: () => SpectrumFrame;
}

function silentFrame(): SpectrumFrame {
  return { level: 0, bins: new Float32Array(SPECTRUM_BINS) };
}

/** Log-spaced bin edges: an octave of bass gets as much width as an octave
 * of treble, which is how the ear hears it and how the ridges should read. */
function bandEdges(): Float32Array {
  const edges = new Float32Array(SPECTRUM_BINS + 1);
  const ratio = Math.log(HIGH_HZ / LOW_HZ);
  for (let i = 0; i <= SPECTRUM_BINS; i++) {
    edges[i] = LOW_HZ * Math.exp((i / SPECTRUM_BINS) * ratio);
  }
  return edges;
}

/**
 * Turns an audio source into a smoothed, normalised spectrum.
 *
 * Same treatment as the coarse three-band analysis, applied per band: fast
 * attack and slow release so a syllable lands but the gap after it does not
 * flicker, and a decaying rolling peak so a whisper and a shout both fill the
 * visual range. Raw FFT bins fed straight to a shader make the terrain boil.
 */
export function useAudioSpectrum(source: AIAudioSource, enabled: boolean): Analysis {
  const frameRef = useRef<SpectrumFrame>(silentFrame());
  const readRef = useRef<() => SpectrumFrame>(() => frameRef.current);

  useEffect(() => {
    if (!enabled || !source) {
      frameRef.current = silentFrame();
      readRef.current = () => frameRef.current;
      return;
    }

    const AudioCtor: typeof AudioContext | undefined =
      window.AudioContext ??
      (window as unknown as { webkitAudioContext?: typeof AudioContext })
        .webkitAudioContext;
    if (!AudioCtor) return;

    // An AudioNode arrives with a context owned by its caller and must not be
    // closed here; every other source needs one created and torn down.
    const attached = isAudioNode(source);
    let context: AudioContext;
    try {
      context = attached ? (source.context as AudioContext) : new AudioCtor();
    } catch {
      return;
    }

    let input: AudioNode | null = null;
    try {
      if (isAudioNode(source)) {
        input = source;
      } else if (source instanceof MediaStream) {
        input = context.createMediaStreamSource(source);
      } else {
        input = context.createMediaElementSource(source);
        // Routing a media element through Web Audio silences it unless it is
        // reconnected; visualising must never mute the assistant.
        input.connect(context.destination);
      }
    } catch {
      if (!attached) void context.close();
      return;
    }

    const analyser = context.createAnalyser();
    analyser.fftSize = 2048;
    analyser.smoothingTimeConstant = 0.7;
    input.connect(analyser);

    const spectrum = new Uint8Array(analyser.frequencyBinCount);
    const edges = bandEdges();
    const smoothed = new Float32Array(SPECTRUM_BINS);
    const output = new Float32Array(SPECTRUM_BINS);
    let level = 0;
    let peak: number = C.audio.peakFloor;

    readRef.current = () => {
      if (context.state === 'suspended') void context.resume().catch(() => {});
      analyser.getByteFrequencyData(spectrum);

      const nyquist = context.sampleRate / 2;
      const binHz = nyquist / analyser.frequencyBinCount;

      let loudest = 0;
      let sum = 0;
      for (let i = 0; i < SPECTRUM_BINS; i++) {
        const from = Math.max(0, Math.floor(edges[i] / binHz));
        const to = Math.min(spectrum.length - 1, Math.ceil(edges[i + 1] / binHz));
        let energy = 0;
        if (to >= from) {
          for (let j = from; j <= to; j++) energy += spectrum[j];
          energy = energy / (to - from + 1) / 255;
        }
        const rate = energy > smoothed[i] ? C.audio.attack : C.audio.release;
        smoothed[i] += (energy - smoothed[i]) * rate;
        loudest = Math.max(loudest, smoothed[i]);
        sum += smoothed[i];
      }

      const rms = sum / SPECTRUM_BINS;
      level += (rms - level) * (rms > level ? C.audio.attack : C.audio.release);

      peak = Math.max(loudest, peak * C.audio.peakDecay, C.audio.peakFloor);
      const norm = 1 / peak;
      for (let i = 0; i < SPECTRUM_BINS; i++) {
        output[i] = Math.min(1, smoothed[i] * norm);
      }

      frameRef.current = { level: Math.min(1, level * norm), bins: output };
      return frameRef.current;
    };

    return () => {
      frameRef.current = silentFrame();
      readRef.current = () => frameRef.current;
      try {
        input?.disconnect();
        analyser.disconnect();
      } catch {
        /* already torn down with the context */
      }
      if (!attached) void context.close().catch(() => {});
    };
  }, [source, enabled]);

  const stable = useRef<Analysis>({ read: () => readRef.current() });
  return stable.current;
}

function isAudioNode(value: unknown): value is AudioNode {
  return typeof AudioNode !== 'undefined' && value instanceof AudioNode;
}
