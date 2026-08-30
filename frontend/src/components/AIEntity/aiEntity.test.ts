// @vitest-environment node
//
// Ce banc LIT ses propres fichiers source (`new URL('./scene.ts',
// import.meta.url)`) pour confronter les uniformes déclarés dans le shader à
// ceux que la scène fournit. Sous jsdom — devenu l'environnement par défaut le
// 30 août 2026 pour que `DOMParser` existe enfin — `import.meta.url` est une
// URL http, et `fileURLToPath` refuse tout ce qui n'est pas `file:`. Ce test
// ne touche aucun DOM : node est exactement ce qu'il lui faut.
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { AI_ENTITY_CONFIG, GRID, STATE_PROFILES, calmProfile } from './config';
import { FRAGMENT_SHADER, VERTEX_SHADER } from './shaders';
import type { AIQuality, AIState, StateProfile } from './types';

/** The scene's own source, so the uniform contract can be checked against the
 * side that actually supplies the values. */
const sceneSource = () =>
  readFileSync(fileURLToPath(new URL('./scene.ts', import.meta.url)), 'utf-8');

const STATES: AIState[] = ['idle', 'listening', 'thinking', 'speaking'];
const QUALITIES: AIQuality[] = ['low', 'medium', 'high', 'ultra'];
const PROFILE_KEYS: (keyof StateProfile)[] = [
  'amplitude',
  'speed',
  'turbulence',
  'focus',
  'glow',
  'shimmer',
  'breath',
  'audioDrive',
];

describe('palette', () => {
  const swatches = Object.entries(AI_ENTITY_CONFIG.colors);

  it.each(swatches)('%s is cyan, never green', (_name, [r, g, b]) => {
    // Cyan and its lighter variants always have blue at least as strong as
    // green. The moment green leads, the colour has turned turquoise or
    // Matrix-green and the whole identity is gone.
    expect(b).toBeGreaterThanOrEqual(g);
  });

  it.each(swatches)('%s never leads with red', (_name, [r, g, b]) => {
    // Red above green or blue would take the palette toward violet, magenta
    // or white — all explicitly excluded.
    expect(r).toBeLessThan(g);
    expect(r).toBeLessThan(b);
  });

  it('gets progressively lighter from trough to peak', () => {
    const { deep, mid, bright, peak } = AI_ENTITY_CONFIG.colors;
    const luma = ([r, g, b]: readonly number[]) => 0.2126 * r! + 0.7152 * g! + 0.0722 * b!;
    expect(luma(deep)).toBeLessThan(luma(mid));
    expect(luma(mid)).toBeLessThan(luma(bright));
    expect(luma(bright)).toBeLessThan(luma(peak));
  });

  it('keeps red low enough that a dense core cannot saturate to white', () => {
    // Additive blending clamps green and blue first; whatever red remains
    // keeps accumulating, and a bright core turns white. Measured: above
    // ~0.6 the speaking peak washes out.
    expect(AI_ENTITY_CONFIG.colors.peak[0]).toBeLessThanOrEqual(0.6);
  });
});

describe('state profiles', () => {
  it.each(STATES)('%s defines every parameter', (state) => {
    for (const key of PROFILE_KEYS) {
      expect(typeof STATE_PROFILES[state][key]).toBe('number');
      expect(Number.isFinite(STATE_PROFILES[state][key])).toBe(true);
    }
  });

  it('never lets the entity go still, even at rest', () => {
    // Idle means present and attentive. A zero here would read as crashed.
    expect(STATE_PROFILES.idle.amplitude).toBeGreaterThan(0);
    expect(STATE_PROFILES.idle.speed).toBeGreaterThan(0);
    expect(STATE_PROFILES.idle.breath).toBeGreaterThan(0);
  });

  it('ignores audio while idle', () => {
    // Nothing is being said, so nothing should modulate the field — otherwise
    // background noise would make the assistant look like it is talking.
    expect(STATE_PROFILES.idle.audioDrive).toBe(0);
  });

  it('gives speaking the strongest voice coupling', () => {
    const others = STATES.filter((s) => s !== 'speaking');
    for (const state of others) {
      expect(STATE_PROFILES.speaking.audioDrive).toBeGreaterThan(
        STATE_PROFILES[state].audioDrive,
      );
    }
  });

  it('makes listening the most focused and thinking the most turbulent', () => {
    // The two states are told apart by behaviour, not colour: attention draws
    // the field in, internal work stirs it.
    expect(STATE_PROFILES.listening.focus).toBeGreaterThan(STATE_PROFILES.idle.focus);
    for (const state of STATES.filter((s) => s !== 'thinking')) {
      expect(STATE_PROFILES.thinking.turbulence).toBeGreaterThan(
        STATE_PROFILES[state].turbulence,
      );
    }
    expect(STATE_PROFILES.thinking.speed).toBeGreaterThan(STATE_PROFILES.idle.speed);
  });

  it('gives every state a distinct signature', () => {
    const signatures = STATES.map((s) => JSON.stringify(STATE_PROFILES[s]));
    expect(new Set(signatures).size).toBe(STATES.length);
  });
});

describe('reduced motion', () => {
  it.each(STATES)('calms %s without stopping it', (state) => {
    const calm = calmProfile(STATE_PROFILES[state]);
    // Hiding the entity would remove the only sign the assistant is there,
    // so the requirement is slower, never absent.
    expect(calm.amplitude).toBeGreaterThan(0);
    expect(calm.speed).toBeGreaterThan(0);
    expect(calm.amplitude).toBeLessThan(STATE_PROFILES[state].amplitude);
    expect(calm.speed).toBeLessThan(STATE_PROFILES[state].speed);
  });

  it('leaves brightness alone', () => {
    // Reduced motion is about movement; dimming would be a different, and
    // unasked-for, accessibility decision.
    expect(calmProfile(STATE_PROFILES.speaking).glow).toBe(
      STATE_PROFILES.speaking.glow,
    );
  });
});

describe('quality tiers', () => {
  it('increase monotonically', () => {
    const counts = QUALITIES.map((q) => GRID[q].cols * GRID[q].rows);
    expect(counts).toEqual([...counts].sort((a, b) => a - b));
  });

  it('stay in the thousands-of-points range the brief asks for', () => {
    for (const quality of QUALITIES) {
      const count = GRID[quality].cols * GRID[quality].rows;
      expect(count).toBeGreaterThan(6_000);
      expect(count).toBeLessThan(80_000);
    }
  });

  it('are wider than they are deep', () => {
    // The silhouette is a horizontal soundwave, not a square terrain.
    for (const quality of QUALITIES) {
      expect(GRID[quality].cols).toBeGreaterThan(GRID[quality].rows * 2);
    }
  });

  it('has a downgrade threshold that cannot oscillate against the upgrade one', () => {
    expect(AI_ENTITY_CONFIG.quality.upgradeMs).toBeLessThan(
      AI_ENTITY_CONFIG.quality.downgradeMs,
    );
  });
});

describe('camera framing', () => {
  it('keeps the distance clamp ordered around the default', () => {
    const { minDistance, distance, maxDistance } = AI_ENTITY_CONFIG.camera;
    expect(minDistance).toBeLessThanOrEqual(distance);
    expect(distance).toBeLessThanOrEqual(maxDistance);
  });

  it('stays off both the flat and the overhead extremes', () => {
    // Edge-on the sheet collapses to a line; from above its rows overlap into
    // an opaque mound. The look only exists between the two.
    expect(AI_ENTITY_CONFIG.camera.elevationDeg).toBeGreaterThan(5);
    expect(AI_ENTITY_CONFIG.camera.elevationDeg).toBeLessThan(35);
  });

  it('keeps parallax subtle enough that nobody can orbit the entity', () => {
    expect(AI_ENTITY_CONFIG.camera.parallax).toBeLessThan(
      AI_ENTITY_CONFIG.camera.distance * 0.05,
    );
  });
});

describe('transitions', () => {
  it('land inside the 300–900 ms band', () => {
    expect(AI_ENTITY_CONFIG.transition.seconds).toBeGreaterThanOrEqual(0.3);
    expect(AI_ENTITY_CONFIG.transition.seconds).toBeLessThanOrEqual(0.9);
  });
});

describe('audio smoothing', () => {
  it('rises faster than it falls', () => {
    // Symmetric smoothing either lags a syllable or flickers between them.
    expect(AI_ENTITY_CONFIG.audio.attack).toBeGreaterThan(
      AI_ENTITY_CONFIG.audio.release,
    );
  });

  it('keeps a peak floor so silence cannot be amplified into motion', () => {
    expect(AI_ENTITY_CONFIG.audio.peakFloor).toBeGreaterThan(0);
  });

  it('lets the rolling peak decay rather than latch', () => {
    const { peakDecay } = AI_ENTITY_CONFIG.audio;
    expect(peakDecay).toBeGreaterThan(0.9);
    expect(peakDecay).toBeLessThan(1);
  });
});

describe('shaders', () => {
  const both = `${VERTEX_SHADER}\n${FRAGMENT_SHADER}`;

  it('declare every uniform they read', () => {
    // An undeclared uniform is a shader that fails to link at runtime, on a
    // GPU, in a browser — never at build time. Cheap to catch here.
    const declared = new Set(
      [...VERTEX_SHADER.matchAll(/uniform\s+\w+\s+(\w+)\s*;/g)].map((m) => m[1]),
    );
    const body = VERTEX_SHADER.slice(VERTEX_SHADER.indexOf('void main'));
    const used = new Set(body.match(/\bu[A-Z]\w*/g) ?? []);
    const undeclared = [...used].filter((name) => !declared.has(name));
    expect(undeclared).toEqual([]);
  });

  it('pass every declared uniform from the scene', () => {
    // The mirror of the test above: a uniform the shader declares but the
    // scene never sets silently stays at zero, which is far harder to spot
    // than a link error.
    const declared = [...VERTEX_SHADER.matchAll(/uniform\s+\w+\s+(\w+)\s*;/g)].map(
      (m) => m[1],
    );
    const source = sceneSource();
    const missing = declared.filter((name) => !source.includes(`${name}:`));
    expect(missing).toEqual([]);
  });

  it('never emit a bare integer where GLSL needs a float', () => {
    // `1` is an int in GLSL and fails to compile against a float; every
    // interpolated config value goes through a formatter for this reason.
    const interpolated = VERTEX_SHADER.match(/[-*+(\s]\d+\.?\d*\s*[)*+\-;,]/g) ?? [];
    const bareInts = interpolated.filter((m) => !/\d\./.test(m) && /\d/.test(m));
    // Loop bounds and swizzle indices are legitimately integers.
    const suspicious = bareInts.filter((m) => !/i\s*<|\bint\b/.test(m));
    expect(suspicious.join('|')).not.toMatch(/[*+\-]\s*\d+\s*[)*+\-;,]/);
  });

  it('are deterministic — no per-frame randomness', () => {
    expect(both).not.toContain('Math.random');
    expect(both).not.toMatch(/\brandom\s*\(/);
  });

  it('discard outside the point disc so no square edge can appear', () => {
    expect(FRAGMENT_SHADER).toContain('gl_PointCoord');
    expect(FRAGMENT_SHADER).toContain('discard');
  });

  it('output premultiplied alpha', () => {
    // Straight alpha with additive blending only composites correctly over
    // black; premultiplication is what makes the canvas transparent over a
    // white page or a photograph.
    expect(FRAGMENT_SHADER).toMatch(/gl_FragColor\s*=\s*vec4\(\s*vColor\s*\*\s*alpha/);
  });

  it('force the envelope to zero at the lattice boundary', () => {
    // A Gaussian alone never reaches zero, so the last column stays visible
    // and the field ends on a hard vertical edge instead of dissolving.
    expect(VERTEX_SHADER).toMatch(/smoothstep\(1\.0,\s*0\.\d+,\s*abs\(u\)\)/);
    expect(VERTEX_SHADER).toMatch(/smoothstep\(1\.0,\s*0\.\d+,\s*abs\(v\)\)/);
  });

  it('drive position from time, so the geometry is never static', () => {
    expect(VERTEX_SHADER).toContain('uTime');
    expect(VERTEX_SHADER).toMatch(/height\s*[+*]?=/);
  });

  it('let every audio band reach the field', () => {
    for (const band of ['uBass', 'uMid', 'uHigh', 'uLevel']) {
      const uses = VERTEX_SHADER.split(band).length - 1;
      // Declaration plus at least one use.
      expect(uses).toBeGreaterThan(1);
    }
  });

  it('clamp point size so a near point cannot become a blob', () => {
    expect(VERTEX_SHADER).toMatch(/gl_PointSize\s*=\s*clamp\(/);
  });

  it('carry no leftover attribute from the earlier grid layout', () => {
    expect(VERTEX_SHADER).not.toContain('aGrid');
  });
});
