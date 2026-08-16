import { useEffect, useRef, useState } from 'react';

import { useAdaptiveQuality } from '../../hooks/useAdaptiveQuality';
import { SPECTRUM_BINS, useAudioSpectrum } from '../../hooks/useAudioSpectrum';
import type { AIAudioSource, AIState } from '../AIEntity/types';
import { VoiceTerrainScene } from './scene';

/** Full-length zeroes: a shorter array would leave the last frame's ridges
 * frozen in place instead of letting them settle. */
const SILENT_BINS = new Float32Array(SPECTRUM_BINS);

function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined') return false;
  return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
}

function readAccent(): string {
  if (typeof window === 'undefined') return '#22d3ee';
  const value = getComputedStyle(document.documentElement)
    .getPropertyValue('--color-accent')
    .trim();
  return value || '#22d3ee';
}

export interface VoiceTerrainProps {
  state?: AIState;
  /** Global energy multiplier, 0–1. */
  intensity?: number;
  /** The assistant's own voice — sculpts the relief while SPEAKING. */
  audioSource?: AIAudioSource;
  /** The user's microphone — sculpts the relief while LISTENING. */
  micSource?: AIAudioSource;
  /** Reports the smoothed loudness for the readouts, ~8 Hz. */
  onLevel?: (level: number) => void;
  className?: string;
  style?: React.CSSProperties;
}

/**
 * Diapason's body as a relief: a massif of luminous points seen head-on, its
 * ridges cut by the live spectrum. Bass raises the central summit, treble
 * pushes the outer foothills, so the silhouette is the voice itself.
 */
export function VoiceTerrain({
  state = 'idle',
  intensity = 1,
  audioSource = null,
  micSource = null,
  onLevel,
  className,
  style,
}: VoiceTerrainProps) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const sceneRef = useRef<VoiceTerrainScene | null>(null);
  const [failed, setFailed] = useState(false);

  const { quality, request: requestQuality } = useAdaptiveQuality();
  const voice = useAudioSpectrum(audioSource, state === 'speaking');
  const mic = useAudioSpectrum(micSource, state === 'listening');

  const stateRef = useRef(state);
  const intensityRef = useRef(intensity);
  const levelRef = useRef(onLevel);
  stateRef.current = state;
  intensityRef.current = intensity;
  levelRef.current = onLevel;

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;

    // Own the canvas outside React: dispose() force-loses the GL context, and
    // a React-reused canvas would come back dead under StrictMode.
    const canvas = document.createElement('canvas');
    canvas.style.display = 'block';
    canvas.style.width = '100%';
    canvas.style.height = '100%';
    host.appendChild(canvas);

    let scene: VoiceTerrainScene;
    try {
      scene = new VoiceTerrainScene({
        canvas,
        quality,
        reducedMotion: prefersReducedMotion(),
      });
    } catch {
      canvas.remove();
      setFailed(true);
      return;
    }
    sceneRef.current = scene;
    scene.onQuality(requestQuality);
    scene.setState(stateRef.current);
    scene.setIntensity(intensityRef.current);
    scene.setAccent(readAccent());

    // The accent is a theme token, so it changes when the theme class does.
    const themeObserver = new MutationObserver(() => scene.setAccent(readAccent()));
    themeObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['class'],
    });

    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      scene.resize(width, height);
    });
    observer.observe(host);
    scene.resize(host.clientWidth, host.clientHeight);

    const motionQuery = window.matchMedia?.('(prefers-reduced-motion: reduce)');
    const onMotionChange = () => scene.setReducedMotion(motionQuery?.matches ?? false);
    motionQuery?.addEventListener('change', onMotionChange);

    // Pull audio on the frame clock: the microphone while listening, the
    // assistant's voice while speaking, silence otherwise.
    let frame = 0;
    let lastReport = 0;
    const pump = (now: number) => {
      frame = requestAnimationFrame(pump);
      const current = stateRef.current;
      const spectrum =
        current === 'speaking'
          ? voice.read()
          : current === 'listening'
            ? mic.read()
            : null;
      if (spectrum) scene.setSpectrum(spectrum);
      else scene.setSpectrum({ level: 0, bins: SILENT_BINS });
      scene.setIntensity(intensityRef.current);
      // Readouts are text: refreshing them at 60 Hz would cost more than the
      // visualisation and be unreadable anyway.
      if (levelRef.current && now - lastReport > 120) {
        lastReport = now;
        levelRef.current(spectrum ? spectrum.level : 0);
      }
    };
    frame = requestAnimationFrame(pump);

    scene.start();

    const onVisibility = () => {
      if (document.hidden) scene.stop();
      else scene.start();
    };
    document.addEventListener('visibilitychange', onVisibility);

    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener('visibilitychange', onVisibility);
      motionQuery?.removeEventListener('change', onMotionChange);
      themeObserver.disconnect();
      observer.disconnect();
      scene.dispose();
      canvas.remove();
      sceneRef.current = null;
    };
    // quality is applied through setQuality below — rebuilding the GL context
    // on tier changes would flash.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [voice, mic, requestQuality]);

  useEffect(() => {
    sceneRef.current?.setQuality(quality);
  }, [quality]);

  useEffect(() => {
    sceneRef.current?.setState(state);
  }, [state]);

  if (failed) return null;

  return (
    <div
      ref={hostRef}
      className={className}
      style={{ position: 'relative', pointerEvents: 'none', ...style }}
      aria-hidden="true"
    />
  );
}

export default VoiceTerrain;
