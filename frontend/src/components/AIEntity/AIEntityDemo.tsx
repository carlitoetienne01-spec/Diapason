import { useEffect, useRef, useState } from 'react';

import { AIEntity } from './AIEntity';
import type { AIQuality, AIState } from './types';

const STATES: AIState[] = ['idle', 'listening', 'thinking', 'speaking'];
const QUALITIES: (AIQuality | 'auto')[] = ['auto', 'low', 'medium', 'high', 'ultra'];

/** Backgrounds the entity must sit on without ever revealing its canvas. */
const BACKDROPS: Record<string, string> = {
  black: '#000000',
  white: '#ffffff',
  red: '#c81e1e',
  photo:
    'radial-gradient(circle at 20% 20%, #f2b705 0%, transparent 45%),' +
    'radial-gradient(circle at 80% 30%, #d9376e 0%, transparent 50%),' +
    'radial-gradient(circle at 50% 85%, #2b9348 0%, transparent 55%),' +
    'linear-gradient(135deg, #f6f5f2 0%, #b8b5ad 100%)',
};

/** Live harness for the four states, every backdrop and each quality tier. */
export function AIEntityDemo() {
  const [state, setState] = useState<AIState>('idle');
  const [backdrop, setBackdrop] = useState<keyof typeof BACKDROPS>('black');
  const [quality, setQuality] = useState<AIQuality | 'auto'>('auto');
  const [intensity, setIntensity] = useState(1);
  const [mic, setMic] = useState<MediaStream | null>(null);
  const [fps, setFps] = useState(0);
  const framesRef = useRef({ count: 0, last: performance.now() });

  useEffect(() => {
    let raf = 0;
    const loop = () => {
      raf = requestAnimationFrame(loop);
      const f = framesRef.current;
      f.count++;
      const now = performance.now();
      if (now - f.last >= 500) {
        setFps(Math.round((f.count * 1000) / (now - f.last)));
        f.count = 0;
        f.last = now;
      }
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, []);

  useEffect(() => () => mic?.getTracks().forEach((t) => t.stop()), [mic]);

  const toggleMic = async () => {
    if (mic) {
      mic.getTracks().forEach((t) => t.stop());
      setMic(null);
      return;
    }
    try {
      setMic(await navigator.mediaDevices.getUserMedia({ audio: true }));
    } catch {
      setMic(null);
    }
  };

  const button = (active: boolean): React.CSSProperties => ({
    padding: '6px 12px',
    fontSize: 12,
    borderRadius: 6,
    cursor: 'pointer',
    border: `1px solid ${active ? '#00cfff' : 'rgba(128,128,128,0.4)'}`,
    background: active ? 'rgba(0,207,255,0.16)' : 'transparent',
    color: active ? '#00cfff' : 'inherit',
  });

  return (
    <div
      style={{
        minHeight: '100vh',
        background: BACKDROPS[backdrop],
        color: backdrop === 'white' || backdrop === 'photo' ? '#111' : '#eee',
        fontFamily: 'system-ui, sans-serif',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: 16,
          padding: 16,
          alignItems: 'center',
        }}
      >
        <div style={{ display: 'flex', gap: 6 }}>
          {STATES.map((s) => (
            <button key={s} onClick={() => setState(s)} style={button(state === s)}>
              {s}
            </button>
          ))}
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          {Object.keys(BACKDROPS).map((b) => (
            <button
              key={b}
              onClick={() => setBackdrop(b as keyof typeof BACKDROPS)}
              style={button(backdrop === b)}
            >
              {b}
            </button>
          ))}
        </div>
        <select
          value={quality}
          onChange={(e) => setQuality(e.target.value as AIQuality | 'auto')}
          style={{ ...button(false), padding: '6px 8px' }}
        >
          {QUALITIES.map((q) => (
            <option key={q} value={q}>
              {q}
            </option>
          ))}
        </select>
        <label style={{ fontSize: 12, display: 'flex', alignItems: 'center', gap: 8 }}>
          intensity {intensity.toFixed(2)}
          <input
            type="range"
            min={0}
            max={1}
            step={0.01}
            value={intensity}
            onChange={(e) => setIntensity(Number(e.target.value))}
          />
        </label>
        <button onClick={() => void toggleMic()} style={button(!!mic)}>
          {mic ? 'mic on' : 'mic off'}
        </button>
        <span style={{ fontSize: 12, opacity: 0.8 }}>{fps} fps</span>
      </div>

      <div style={{ flex: 1, minHeight: 0, position: 'relative' }}>
        <AIEntity
          state={state}
          intensity={intensity}
          audioSource={mic}
          quality={quality === 'auto' ? undefined : quality}
          interactive
          style={{ position: 'absolute', inset: 0 }}
        />
      </div>
    </div>
  );
}

export default AIEntityDemo;
