import { useEffect, useRef, useState } from 'react';

import { useAdaptiveQuality } from '../../hooks/useAdaptiveQuality';
import { useAudioAnalysis } from '../../hooks/useAudioAnalysis';
import { AIEntityScene } from './scene';
import type { AIEntityProps } from './types';

function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined') return false;
  return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
}

/**
 * A field of luminous points whose shape is a function of time, state and
 * voice — the assistant's visible presence rather than a decoration beside it.
 *
 * The canvas is genuinely transparent: no clear colour, no backdrop, no
 * wrapper background. It can be laid over any interface.
 */
export function AIEntity({
  state = 'idle',
  intensity = 1,
  audioSource = null,
  interactive = false,
  quality: forcedQuality,
  className,
  style,
}: AIEntityProps) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const sceneRef = useRef<AIEntityScene | null>(null);
  const [failed, setFailed] = useState(false);

  const { quality, request: requestQuality } = useAdaptiveQuality(forcedQuality);
  // Only analyse while there is something to hear; an idle analyser would keep
  // an AudioContext alive for nothing.
  const analysis = useAudioAnalysis(audioSource, state === 'speaking' || state === 'listening');

  // Props the render loop reads every frame. Kept in refs so that changing
  // them never re-runs the effect that owns the WebGL context.
  const stateRef = useRef(state);
  const intensityRef = useRef(intensity);
  stateRef.current = state;
  intensityRef.current = intensity;

  // Build once. Quality changes swap the lattice in place rather than
  // recreating the renderer, so the context is created exactly one time.
  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;

    // The canvas is created here rather than rendered by React because
    // teardown calls forceContextLoss(), which retires the element for good.
    // A canvas React owns would be reused on the next mount — StrictMode does
    // exactly that — and the entity would silently never appear again.
    const canvas = document.createElement('canvas');
    canvas.style.display = 'block';
    canvas.style.width = '100%';
    canvas.style.height = '100%';
    host.appendChild(canvas);

    let scene: AIEntityScene;
    try {
      scene = new AIEntityScene({
        canvas,
        quality,
        reducedMotion: prefersReducedMotion(),
      });
    } catch {
      // No WebGL: render nothing rather than a broken rectangle.
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

    // The audio bands are pulled here, on the browser's frame clock, instead
    // of being pushed through React state at 60 Hz.
    let frame = 0;
    const pump = () => {
      frame = requestAnimationFrame(pump);
      scene.setBands(analysis.read());
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
    // `quality` is intentionally absent: it is applied through setQuality
    // below, because rebuilding the WebGL context on every tier change would
    // be both visible and wasteful.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analysis, requestQuality]);

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
    const host = hostRef.current;
    if (!host) return;

    const onMove = (event: PointerEvent) => {
      const rect = host.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      // -1..1, so the scene can scale it by its own tiny parallax budget.
      const x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      const y = ((event.clientY - rect.top) / rect.height) * 2 - 1;
      sceneRef.current?.setPointer(x, -y);
    };
    const onLeave = () => sceneRef.current?.setPointer(0, 0);

    window.addEventListener('pointermove', onMove, { passive: true });
    host.addEventListener('pointerleave', onLeave);
    return () => {
      window.removeEventListener('pointermove', onMove);
      host.removeEventListener('pointerleave', onLeave);
    };
  }, [interactive]);

  if (failed) return null;

  return (
    <div
      ref={hostRef}
      className={className}
      // No background of any kind, and transparent to the pointer: the entity
      // sits over an interface without intercepting it.
      style={{ position: 'relative', pointerEvents: 'none', ...style }}
      aria-hidden="true"
    />
  );
}

export default AIEntity;
