/** The voice terrain — Three.js orchestration.
 *
 * One layer only: a point grid whose every vertex is displaced in the shader.
 * The per-frame job here is deliberately small — ease the state profile,
 * smooth the spectrum, upload it as a 1-pixel-tall texture, render.
 */

import {
  BufferAttribute,
  BufferGeometry,
  Color,
  NoToneMapping,
  NormalBlending,
  PerspectiveCamera,
  Points,
  Scene,
  ShaderMaterial,
  Vector2,
  Vector3,
  WebGLRenderer,
} from 'three';
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js';
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';

import type { AIQuality, AIState } from '../AIEntity/types';
import { SPECTRUM_BINS, type SpectrumFrame } from '../../hooks/useAudioSpectrum';
import {
  TERRAIN_CONFIG as C,
  TERRAIN_EASE_TAU,
  TERRAIN_GRID,
  TERRAIN_OCTAVES,
  TERRAIN_STATE_PROFILES,
  type TerrainStateProfile,
} from './config';
import { TERRAIN_FRAGMENT, TERRAIN_VERTEX } from './shaders';

interface SceneOptions {
  canvas: HTMLCanvasElement;
  quality: AIQuality;
  reducedMotion: boolean;
}

/** Deterministic per-index noise, so a rebuild at another quality tier does not
 * reshuffle the grain. */
function hash(n: number): number {
  const x = Math.sin(n * 127.1 + 311.7) * 43758.5453;
  return x - Math.floor(x);
}

function terrainGeometry(cols: number, rows: number): BufferGeometry {
  const count = cols * rows;
  const grid = new Float32Array(count * 2);
  const rand = new Float32Array(count);
  const pos = new Float32Array(count * 3); // required by three, animated on GPU
  const cellX = 2 / (cols - 1);
  const cellZ = 2 / (rows - 1);
  let k = 0;
  for (let i = 0; i < cols; i++) {
    for (let j = 0; j < rows; j++) {
      // Jitter inside each cell: a regular lattice betrays itself as moiré and
      // as rows of dots marching across the slopes. Scattered samples read as
      // grains of rock.
      grid[k * 2] = (i / (cols - 1)) * 2 - 1 + (hash(k * 2 + 1) - 0.5) * cellX * 0.9;
      grid[k * 2 + 1] = (j / (rows - 1)) * 2 - 1 + (hash(k * 2 + 2) - 0.5) * cellZ * 0.9;
      rand[k] = hash(k * 3 + 7);
      k++;
    }
  }
  const geometry = new BufferGeometry();
  geometry.setAttribute('position', new BufferAttribute(pos, 3));
  geometry.setAttribute('aGrid', new BufferAttribute(grid, 2));
  geometry.setAttribute('aRand', new BufferAttribute(rand, 1));
  // GPU-displaced points would otherwise be culled by their all-zero positions.
  geometry.boundingSphere = null;
  return geometry;
}

export class VoiceTerrainScene {
  private renderer: WebGLRenderer;
  private composer: EffectComposer;
  private bloom: UnrealBloomPass;
  private scene = new Scene();
  private camera: PerspectiveCamera;
  private points: Points;
  private material: ShaderMaterial;

  /** Render-side smoothing, on top of the analyser's own. Uploaded as a uniform
   * array each frame; the shader reads it by index. */
  private bins = new Float32Array(SPECTRUM_BINS);
  private binsTarget = new Float32Array(SPECTRUM_BINS);
  private level = 0;
  private levelTarget = 0;

  private clock = 0;
  private raf = 0;
  private running = false;
  private lastFrame = 0;
  private quality: AIQuality;
  private reducedMotion: boolean;

  private state: AIState = 'idle';
  private profile: TerrainStateProfile = { ...TERRAIN_STATE_PROFILES.idle };
  private intensity = 1;
  private accent = new Color(0.35, 0.85, 1.0);
  private qualityCallback: ((quality: AIQuality) => void) | null = null;
  private fpsAccum = 0;
  private fpsFrames = 0;
  private fpsWindow = 0;

  /** Last measured frame rate, over the adaptive window. 0 before the first
   * window closes — a readout should show « — » rather than a made-up 60. */
  get measuredFps(): number {
    return this.lastFps;
  }

  /** The tier the scene is actually rendering at, which is not always the one
   * it was asked for: the adaptive loop can step it down mid-session. */
  get currentQuality(): AIQuality {
    return this.quality;
  }

  /** Points currently in the cloud. */
  get pointCount(): number {
    return this.pointTotal;
  }

  private lastFps = 0;
  private pointTotal = 0;

  constructor({ canvas, quality, reducedMotion }: SceneOptions) {
    this.quality = quality;
    this.reducedMotion = reducedMotion;

    this.renderer = new WebGLRenderer({
      canvas,
      antialias: true,
      alpha: true,
      powerPreference: 'high-performance',
    });
    this.renderer.setClearColor(0x000000, 0);
    // No tone mapping: the filmic curve desaturates anything bright toward
    // white, which is exactly what a single-hue terrain must not do.
    this.renderer.toneMapping = NoToneMapping;

    this.camera = new PerspectiveCamera(C.camera.fov, 1, 0.1, 100);
    this.camera.position.set(...C.camera.position);
    this.camera.lookAt(new Vector3(...C.camera.target));

    this.material = new ShaderMaterial({
      vertexShader: TERRAIN_VERTEX,
      fragmentShader: TERRAIN_FRAGMENT,
      defines: { SPECTRUM_BINS, TERRAIN_OCTAVES: TERRAIN_OCTAVES[quality] },
      uniforms: {
        uSpectrum: { value: this.bins },
        uTime: { value: 0 },
        uAmplitude: { value: this.profile.amplitude },
        uTurbulence: { value: this.profile.turbulence },
        uSpread: { value: this.profile.spread },
        uDrive: { value: this.profile.spectrumDrive },
        uLevel: { value: 0 },
        uPointSize: { value: C.pointSize },
        uPixelRatio: { value: 1 },
        uFovScale: { value: 1 },
        uWidth: { value: C.geometry.width },
        uDepth: { value: C.geometry.depth },
        uLightDir: { value: new Vector3(...C.light) },
        uFogNear: { value: C.fog.near },
        uFogFar: { value: C.fog.far },
        uAccent: { value: this.accent },
        uGlow: { value: this.profile.glow },
        uIntensity: { value: 1 },
      },
      // Solid, depth-tested points: the front of the massif must hide its back.
      // Additive blending made every ridge visible through every other one and
      // piled the overlaps up to white, which flattened the whole relief.
      blending: NormalBlending,
      depthWrite: true,
      depthTest: true,
      transparent: true,
    });

    const grid = TERRAIN_GRID[quality];
    this.pointTotal = grid.cols * grid.rows;
    this.points = new Points(terrainGeometry(grid.cols, grid.rows), this.material);
    this.points.frustumCulled = false;
    this.scene.add(this.points);

    this.composer = new EffectComposer(this.renderer);
    this.composer.addPass(new RenderPass(this.scene, this.camera));
    this.bloom = new UnrealBloomPass(
      new Vector2(2, 2),
      C.bloom.strength,
      C.bloom.radius,
      C.bloom.threshold,
    );
    this.composer.addPass(this.bloom);
    this.composer.addPass(new OutputPass());
  }

  // ── public contract (shared with AIEntityScene, the dictation ribbon) ────

  setState(state: AIState): void {
    this.state = state;
  }

  setSpectrum(frame: SpectrumFrame): void {
    this.binsTarget.set(frame.bins);
    this.levelTarget = frame.level;
  }

  setIntensity(value: number): void {
    this.intensity = value;
  }

  /** Accepts any CSS colour; the theme's accent is read from a custom property. */
  setAccent(css: string): void {
    try {
      this.accent.set(css);
    } catch {
      /* an unparseable token keeps the previous colour */
    }
  }

  setReducedMotion(reduced: boolean): void {
    this.reducedMotion = reduced;
  }

  onQuality(callback: (quality: AIQuality) => void): void {
    this.qualityCallback = callback;
  }

  setQuality(quality: AIQuality): void {
    if (quality === this.quality) return;
    this.quality = quality;
    const grid = TERRAIN_GRID[quality];
    const old = this.points.geometry;
    this.pointTotal = grid.cols * grid.rows;
    this.points.geometry = terrainGeometry(grid.cols, grid.rows);
    old.dispose();
    // Octave count is a compile-time constant, so the program has to be rebuilt.
    this.material.defines.TERRAIN_OCTAVES = TERRAIN_OCTAVES[quality];
    this.material.needsUpdate = true;
  }

  resize(width: number, height: number): void {
    if (!width || !height) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    this.renderer.setPixelRatio(dpr);
    this.renderer.setSize(width, height, false);
    this.composer.setSize(width, height);
    this.bloom.resolution.set(width, height);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    const fovScale = height / (2 * Math.tan((this.camera.fov * Math.PI) / 360));
    this.material.uniforms.uPixelRatio.value = dpr;
    this.material.uniforms.uFovScale.value = fovScale / 320;
  }

  start(): void {
    if (this.running) return;
    this.running = true;
    this.lastFrame = performance.now();
    const frame = (now: number) => {
      if (!this.running) return;
      this.raf = requestAnimationFrame(frame);
      const dt = Math.min((now - this.lastFrame) / 1000, 0.1);
      this.lastFrame = now;
      this.tick(dt);
      this.measure(dt);
    };
    this.raf = requestAnimationFrame(frame);
  }

  stop(): void {
    this.running = false;
    cancelAnimationFrame(this.raf);
  }

  dispose(): void {
    this.stop();
    this.points.geometry.dispose();
    this.material.dispose();
    this.composer.dispose();
    this.renderer.dispose();
    this.renderer.forceContextLoss();
  }

  /** Rolling 2 s frame-rate window → suggest the tier that fits the GPU. */
  private measure(dt: number): void {
    this.fpsAccum += dt;
    this.fpsFrames += 1;
    this.fpsWindow += dt;
    if (this.fpsWindow < 2) return;
    const fps = this.fpsFrames / this.fpsAccum;
    this.lastFps = fps;
    this.fpsAccum = 0;
    this.fpsFrames = 0;
    this.fpsWindow = 0;
    const order: AIQuality[] = ['low', 'medium', 'high', 'ultra'];
    const index = order.indexOf(this.quality);
    let suggestion = this.quality;
    if (fps < 34 && index > 0) suggestion = order[index - 1];
    else if (fps > 57 && index < order.length - 1) suggestion = order[index + 1];
    if (suggestion !== this.quality) this.qualityCallback?.(suggestion);
  }

  // ── the frame ────────────────────────────────────────────────────────────

  private tick(dt: number): void {
    const motion = this.reducedMotion ? 0.25 : 1;

    const target = TERRAIN_STATE_PROFILES[this.state];
    const ease = 1 - Math.exp(-dt / TERRAIN_EASE_TAU);
    const p = this.profile;
    for (const key of Object.keys(p) as (keyof TerrainStateProfile)[]) {
      p[key] += (target[key] - p[key]) * ease;
    }

    // Fast attack, slow release: a syllable lifts a ridge, the gap after it
    // lets the ridge settle instead of snapping flat.
    const attack = 1 - Math.exp(-dt / C.spectrumAttack);
    const release = 1 - Math.exp(-dt / C.spectrumRelease);
    const silent = this.reducedMotion;
    for (let i = 0; i < SPECTRUM_BINS; i++) {
      const goal = silent ? 0 : this.binsTarget[i];
      this.bins[i] += (goal - this.bins[i]) * (goal > this.bins[i] ? attack : release);
    }

    const levelGoal = silent ? 0 : this.levelTarget;
    this.level +=
      (levelGoal - this.level) * (levelGoal > this.level ? attack : release);

    this.clock += dt * motion * (0.4 + p.speed);

    const u = this.material.uniforms;
    u.uTime.value = this.clock;
    u.uAmplitude.value = p.amplitude;
    u.uTurbulence.value = p.turbulence;
    u.uSpread.value = p.spread;
    u.uDrive.value = p.spectrumDrive;
    u.uGlow.value = p.glow;
    u.uLevel.value = this.level;
    u.uIntensity.value = this.intensity;
    (u.uAccent.value as Color).copy(this.accent);

    this.composer.render();
  }
}
