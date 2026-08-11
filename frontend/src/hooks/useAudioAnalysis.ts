import { useEffect, useRef } from 'react';

import { AI_ENTITY_CONFIG as C } from '../components/AIEntity/config';
import { SILENT_BANDS } from '../components/AIEntity/types';
import type { AIAudioSource, AudioBands } from '../components/AIEntity/types';

/** Hz boundaries. Bass carries depth, mids carry the swell, treble the sparkle. */
const BANDS: ReadonlyArray<readonly [number, number]> = [
  [20, 250],
  [250, 2000],
  [2000, 16000],
];

interface Analysis {
  /** Read on the render loop's schedule, not React's — this never triggers a
   * re-render, which is the whole point: state updates at 60 Hz would cost
   * more than the visualisation. */
  read: () => AudioBands;
}

function bandEnergy(
  spectrum: Uint8Array,
  sampleRate: number,
  fftSize: number,
  low: number,
  high: number,
): number {
  const nyquist = sampleRate / 2;
  const binHz = nyquist / (fftSize / 2);
  const from = Math.max(0, Math.floor(low / binHz));
  const to = Math.min(spectrum.length - 1, Math.ceil(high / binHz));
  if (to < from) return 0;
  let sum = 0;
  for (let i = from; i <= to; i++) sum += spectrum[i];
  return sum / (to - from + 1) / 255;
}

/**
 * Turns an audio source into smoothed, normalised bands.
 *
 * Raw FFT output is unusable here: fed straight to a shader it makes the field
 * tremble. Three things fix that — a fast attack with a slow release so the
 * structure answers a syllable but coasts through the gap after it, a decaying
 * rolling peak so a whisper and a shout both fill the same visual range, and a
 * floor so silence reads as silence rather than amplified noise.
 */
export function useAudioAnalysis(source: AIAudioSource, enabled: boolean): Analysis {
  const bandsRef = useRef<AudioBands>(SILENT_BANDS);
  const readRef = useRef<() => AudioBands>(() => bandsRef.current);

  useEffect(() => {
    if (!enabled || !source) {
      bandsRef.current = SILENT_BANDS;
      return;
    }

    const AudioCtor: typeof AudioContext | undefined =
      window.AudioContext ??
      (window as unknown as { webkitAudioContext?: typeof AudioContext })
        .webkitAudioContext;
    if (!AudioCtor) return;

    // An AudioNode arrives with a context that belongs to its owner and must
    // not be closed here; every other source needs one created and torn down.
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
        // A media element routed through Web Audio stops reaching the speakers
        // unless it is reconnected; visualising must not mute the assistant.
        input.connect(context.destination);
      }
    } catch {
      if (!attached) void context.close();
      return;
    }

    const analyser = context.createAnalyser();
    analyser.fftSize = 1024;
    // Some smoothing in the analyser itself, the rest below — this alone is
    // too slow to feel responsive and too fast to look calm.
    analyser.smoothingTimeConstant = 0.72;
    input.connect(analyser);

    const spectrum = new Uint8Array(analyser.frequencyBinCount);
    const smoothed = [0, 0, 0];
    let level = 0;
    let peak: number = C.audio.peakFloor;

    readRef.current = () => {
      if (context.state === 'suspended') void context.resume().catch(() => {});
      analyser.getByteFrequencyData(spectrum);

      let loudest = 0;
      for (let i = 0; i < BANDS.length; i++) {
        const [low, high] = BANDS[i];
        const raw = bandEnergy(spectrum, context.sampleRate, analyser.fftSize, low, high);
        const rate = raw > smoothed[i] ? C.audio.attack : C.audio.release;
        smoothed[i] += (raw - smoothed[i]) * rate;
        loudest = Math.max(loudest, smoothed[i]);
      }

      const rms = (smoothed[0] + smoothed[1] + smoothed[2]) / 3;
      level += (rms - level) * (rms > level ? C.audio.attack : C.audio.release);

      // Decaying peak: adapts to a quiet talker within a second or two, then
      // relaxes so a single loud burst does not flatten everything after it.
      peak = Math.max(loudest, peak * C.audio.peakDecay, C.audio.peakFloor);
      const norm = 1 / peak;

      const bands: AudioBands = {
        level: Math.min(1, level * norm),
        bass: Math.min(1, smoothed[0] * norm),
        mid: Math.min(1, smoothed[1] * norm),
        high: Math.min(1, smoothed[2] * norm),
      };
      bandsRef.current = bands;
      return bands;
    };

    return () => {
      readRef.current = () => SILENT_BANDS;
      bandsRef.current = SILENT_BANDS;
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
