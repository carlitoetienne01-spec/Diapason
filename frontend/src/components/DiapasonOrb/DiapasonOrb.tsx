import { useEffect, useRef, useState } from 'react';

import { useAdaptiveQuality } from '../../hooks/useAdaptiveQuality';
import { useAudioAnalysis } from '../../hooks/useAudioAnalysis';
import { SILENT_BANDS } from '../AIEntity/types';
import type { AIAudioSource, AIState } from '../AIEntity/types';
import { DiapasonOrbScene } from './scene';

function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined') return false;
  return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
}

export interface DiapasonOrbProps {
  state?: AIState;
  /** Global energy multiplier, 0–1. */
  intensity?: number;
  /** The assistant's own voice — drives the body while SPEAKING. */
  audioSource?: AIAudioSource;
  /** The user's microphone — drives the body while LISTENING. */
  micSource?: AIAudioSource;
  /** Subtle pointer parallax (±4°); off keeps the canvas fully passive. */
  interactive?: boolean;
  className?: string;
  style?: React.CSSProperties;
}

/**
 * Diapason's physical body: a blue-white energy core wrapped in three
 * independent veils of tens of thousands of luminous particles. It breathes
 * on its own, tightens when it listens, stirs when it thinks, and vibrates
 * with whichever voice is alive — yours or its own.
 */
export function DiapasonOrb({
  state = 'idle',
  intensity = 1,
  audioSource = null,
  micSource = null,
  interactive = true,
  className,
  style,
}: DiapasonOrbProps) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const sceneRef = useRef<DiapasonOrbScene | null>(null);
  const [failed, setFailed] = useState(false);

  const { quality, request: requestQuality } = useAdaptiveQuality();
  const voice = useAudioAnalysis(audioSource, state === 'speaking');
  const mic = useAudioAnalysis(micSource, state === 'listening');

  const stateRef = useRef(state);
  const intensityRef = useRef(intensity);
  stateRef.current = state;
  intensityRef.current = intensity;

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;

    // Own the canvas outside React: dispose() force-loses the GL context,
    // and a React-reused canvas would come back dead under StrictMode.
    const canvas = document.createElement('canvas');
    canvas.style.display = 'block';
    canvas.style.width = '100%';
    canvas.style.height = '100%';
    host.appendChild(canvas);

    let scene: DiapasonOrbScene;
    try {
      scene = new DiapasonOrbScene({
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

    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      scene.resize(width, height);
    });
    observer.observe(host);
    scene.resize(host.clientWidth, host.clientHeight);

    const motionQuery = window.matchMedia?.('(prefers-reduced-motion: reduce)');
    const onMotionChange = () =>
      scene.setReducedMotion(motionQuery?.matches ?? false, stateRef.current);
    motionQuery?.addEventListener('change', onMotionChange);

    // Pull audio on the frame clock: the microphone while listening, the
    // assistant's voice while speaking, silence otherwise.
    let frame = 0;
    const pump = () => {
      frame = requestAnimationFrame(pump);
      const current = stateRef.current;
      const bands =
        current === 'speaking'
          ? voice.read()
          : current === 'listening'
            ? mic.read()
            : SILENT_BANDS;
      scene.setBands(bands);
      scene.setIntensity(intensityRef.current);
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
      observer.disconnect();
      scene.dispose();
      canvas.remove();
      sceneRef.current = null;
    };
    // quality is applied through setQuality below — rebuilding the GL
    // context on tier changes would flash.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [voice, mic, requestQuality]);

  useEffect(() => {
    sceneRef.current?.setQuality(quality);
  }, [quality]);

  useEffect(() => {
    sceneRef.current?.setState(state);
  }, [state]);

  useEffect(() => {
    if (!interactive) {
      sceneRef.current?.setPointer(0, 0);
      return;
    }
    const onMove = (event: PointerEvent) => {
      const w = window.innerWidth || 1;
      const h = window.innerHeight || 1;
      const x = (event.clientX / w) * 2 - 1;
      const y = (event.clientY / h) * 2 - 1;
      sceneRef.current?.setPointer(x, -y);
    };
    window.addEventListener('pointermove', onMove, { passive: true });
    return () => window.removeEventListener('pointermove', onMove);
  }, [interactive]);

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

export default DiapasonOrb;
