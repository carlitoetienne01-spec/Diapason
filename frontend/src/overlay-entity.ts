/**
 * The dictation overlay's page: the AI entity, with no React around it.
 *
 * The dictation service is a Python process that owns an NSPanel; this runs
 * inside a WKWebView filling that panel. `AIEntityScene` was deliberately
 * written free of React, so the exact component from the Talk panel renders
 * here without a framework, a router or a reconciler coming along for the
 * ride.
 *
 * The native side drives it through `window.diapasonOverlay`, called from the
 * main thread by the panel's own timer. Nothing is pushed per audio block:
 * the page keeps rendering on its own rAF and simply reads the last values it
 * was given, so a slow bridge call can never stall the animation.
 */

import { AIEntityScene } from './components/AIEntity/scene';
import type { AIQuality, AIState } from './components/AIEntity/types';

const VALID_STATES: ReadonlySet<string> = new Set([
  'idle',
  'listening',
  'thinking',
  'speaking',
]);

declare global {
  interface Window {
    diapasonOverlay: {
      setState: (state: string) => void;
      setLevel: (level: number) => void;
      setBands: (bands: number[]) => void;
      setQuality: (quality: string) => void;
      ready: boolean;
    };
  }
}

const canvas = document.createElement('canvas');
canvas.style.cssText = 'display:block;width:100%;height:100%';
document.body.appendChild(canvas);

const reducedMotion =
  window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;

// The panel is a wide, short banner, so the point budget buys detail across
// the width rather than depth the geometry cannot show at this height.
const scene = new AIEntityScene({ canvas, quality: 'high', reducedMotion });

const resize = () => scene.resize(window.innerWidth, window.innerHeight);
window.addEventListener('resize', resize);
resize();
scene.start();

/**
 * Dictation gives a single RMS number, not a spectrum — there is no FFT on
 * that path. Turning it into bands is overlay policy, not scene behaviour, so
 * it lives here rather than widening the scene's contract.
 *
 * The curve is the one the previous native overlay used and that was tuned on
 * this microphone: ordinary speech sits near 1.0 on a 0–100 RMS scale, so a
 * square root over a full scale of 4 spreads the useful range across the bar.
 * Bass and treble are derived rather than measured — honest enough, since the
 * shape they drive is a field, not a spectrum analyser.
 */
let target = 0;
let smoothed = 0;

const pump = () => {
  requestAnimationFrame(pump);
  // Fast attack, slow release: answers a syllable, coasts through the gap
  // after it. Pushing the raw value would make the field tremble.
  smoothed += (target - smoothed) * (target > smoothed ? 0.35 : 0.08);
  const norm = Math.min(1, Math.sqrt(smoothed / 4));
  scene.setBands({
    level: norm,
    bass: norm * 0.85,
    mid: norm,
    high: norm * 0.62,
  });
};
requestAnimationFrame(pump);

window.diapasonOverlay = {
  ready: true,
  setState(state) {
    if (VALID_STATES.has(state)) scene.setState(state as AIState);
  },
  setLevel(level) {
    target = Number.isFinite(level) ? Math.max(0, level) : 0;
  },
  setBands(bands) {
    // The native side sends the spectrum every frame it has one; the scene
    // eases it in, so an empty array simply lets the equaliser fade out.
    scene.setSpectrum(Array.isArray(bands) ? bands : []);
  },
  setQuality(quality) {
    if (['low', 'medium', 'high', 'ultra'].includes(quality)) {
      scene.setQuality(quality as AIQuality);
    }
  },
};
