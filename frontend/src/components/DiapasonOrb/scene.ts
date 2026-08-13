/** Diapason's energetic body — the Three.js orchestration.
 *
 * Layer map (see the reference visual):
 *   1. core: emissive sphere + additive halo sprite + two whisper-thin rings
 *   2. sparks: radial particles exhaled by the core
 *   3. three membranes: independent point veils, each with its own clock
 *
 * JavaScript's per-frame job is deliberately tiny: advance clocks, ease the
 * state profile, smooth the audio bands, update uniforms. Every particle
 * position is computed in the vertex shader.
 */

import {
  ACESFilmicToneMapping,
  AdditiveBlending,
  BufferAttribute,
  BufferGeometry,
  CanvasTexture,
  Group,
  LineBasicMaterial,
  LineLoop,
  Mesh,
  NormalBlending,
  PerspectiveCamera,
  Points,
  Scene,
  ShaderMaterial,
  SphereGeometry,
  Sprite,
  SpriteMaterial,
  Vector4,
  WebGLRenderer,
} from 'three';
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js';
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';
import { Vector2 } from 'three';

import { SILENT_BANDS } from '../AIEntity/types';
import type { AIQuality, AIState, AudioBands } from '../AIEntity/types';
import {
  DIAPASON_ORB_CONFIG as C,
  MEMBRANES,
  MEMBRANE_GRID,
  ORB_STATE_PROFILES,
  STATE_EASE_TAU,
  type OrbStateProfile,
} from './config';
import {
  CORE_FRAGMENT,
  CORE_VERTEX,
  MEMBRANE_FRAGMENT,
  MEMBRANE_VERTEX,
  SPARK_FRAGMENT,
  SPARK_VERTEX,
} from './shaders';

interface SceneOptions {
  canvas: HTMLCanvasElement;
  quality: AIQuality;
  reducedMotion: boolean;
}

/** Deterministic per-index random — rebuilds are identical across mounts. */
function hash(n: number): number {
  const s = Math.sin(n * 127.1 + 311.7) * 43758.5453;
  return s - Math.floor(s);
}

function membraneGeometry(u: number, v: number): BufferGeometry {
  const count = u * v;
  const uv = new Float32Array(count * 2);
  const rand = new Float32Array(count * 4);
  const pos = new Float32Array(count * 3); // required by three, animated on GPU
  let k = 0;
  for (let i = 0; i < u; i++) {
    for (let j = 0; j < v; j++) {
      uv[k * 2] = (i / (u - 1)) * 2 - 1;
      uv[k * 2 + 1] = (j / (v - 1)) * 2 - 1;
      rand[k * 4] = hash(k * 4 + 1);
      rand[k * 4 + 1] = hash(k * 4 + 2);
      rand[k * 4 + 2] = hash(k * 4 + 3);
      rand[k * 4 + 3] = hash(k * 4 + 4);
      k++;
    }
  }
  const geometry = new BufferGeometry();
  geometry.setAttribute('position', new BufferAttribute(pos, 3));
  geometry.setAttribute('aUV', new BufferAttribute(uv, 2));
  geometry.setAttribute('aRand', new BufferAttribute(rand, 4));
  // GPU-displaced points would otherwise be frustum-culled by their static
  // (all-zero) positions.
  geometry.boundingSphere = null;
  return geometry;
}

function sparkGeometry(count: number): BufferGeometry {
  const dir = new Float32Array(count * 3);
  const rand = new Float32Array(count * 3);
  const pos = new Float32Array(count * 3);
  for (let i = 0; i < count; i++) {
    // Uniform directions on the sphere.
    const z = hash(i * 3 + 11) * 2 - 1;
    const a = hash(i * 3 + 12) * Math.PI * 2;
    const r = Math.sqrt(Math.max(0, 1 - z * z));
    dir[i * 3] = r * Math.cos(a);
    dir[i * 3 + 1] = z;
    dir[i * 3 + 2] = r * Math.sin(a);
    rand[i * 3] = hash(i * 3 + 13);
    rand[i * 3 + 1] = hash(i * 3 + 14);
    rand[i * 3 + 2] = hash(i * 3 + 15);
  }
  const geometry = new BufferGeometry();
  geometry.setAttribute('position', new BufferAttribute(pos, 3));
  geometry.setAttribute('aDir', new BufferAttribute(dir, 3));
  geometry.setAttribute('aRand', new BufferAttribute(rand, 3));
  geometry.boundingSphere = null;
  return geometry;
}

/** Soft radial halo texture — one canvas, reused by the sprite. */
function haloTexture(): CanvasTexture {
  const size = 256;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d')!;
  const g = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  g.addColorStop(0.0, 'rgba(220, 245, 255, 0.9)');
  g.addColorStop(0.25, 'rgba(120, 205, 255, 0.42)');
  g.addColorStop(0.55, 'rgba(30, 120, 255, 0.14)');
  g.addColorStop(1.0, 'rgba(0, 30, 80, 0.0)');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, size, size);
  return new CanvasTexture(canvas);
}

function ringGeometry(radius: number, segments = 160): BufferGeometry {
  const pos = new Float32Array(segments * 3);
  for (let i = 0; i < segments; i++) {
    const a = (i / segments) * Math.PI * 2;
    pos[i * 3] = Math.cos(a) * radius;
    pos[i * 3 + 1] = Math.sin(a) * radius * 0.98;
    pos[i * 3 + 2] = 0;
  }
  const geometry = new BufferGeometry();
  geometry.setAttribute('position', new BufferAttribute(pos, 3));
  return geometry;
}

export class DiapasonOrbScene {
  private renderer: WebGLRenderer;
  private composer: EffectComposer;
  private bloom: UnrealBloomPass;
  private scene = new Scene();
  private camera: PerspectiveCamera;
  private group = new Group();

  private membranes: Points[] = [];
  private membraneMaterials: ShaderMaterial[] = [];
  private sparks!: Points;
  private sparkMaterial!: ShaderMaterial;
  private core!: Mesh;
  private coreMaterial!: ShaderMaterial;
  private halo!: Sprite;
  private rings: LineLoop[] = [];

  private clock = 0;
  private raf = 0;
  private running = false;
  private lastFrame = 0;
  private quality: AIQuality;
  private reducedMotion: boolean;

  private state: AIState = 'idle';
  private profile: OrbStateProfile = { ...ORB_STATE_PROFILES.idle };
  private bandsTarget: AudioBands = SILENT_BANDS;
  private bands: AudioBands = { ...SILENT_BANDS };
  private intensity = 1;
  private pointer = { x: 0, y: 0 };
  private qualityCallback: ((quality: AIQuality) => void) | null = null;
  private fpsAccum = 0;
  private fpsFrames = 0;
  private fpsWindow = 0;

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
    this.renderer.toneMapping = ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = C.toneMappingExposure;

    this.camera = new PerspectiveCamera(C.camera.fov, 1, 0.1, 100);
    this.camera.position.z = C.camera.z;

    this.scene.add(this.group);
    this.buildCore();
    this.buildMembranes();

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

  // ── construction ─────────────────────────────────────────────────────────

  private buildCore(): void {
    this.coreMaterial = new ShaderMaterial({
      vertexShader: CORE_VERTEX,
      fragmentShader: CORE_FRAGMENT,
      uniforms: { uIntensity: { value: 2.6 } },
      blending: AdditiveBlending,
      depthWrite: false,
      transparent: true,
    });
    this.core = new Mesh(new SphereGeometry(C.core.radius, 32, 24), this.coreMaterial);
    this.group.add(this.core);

    this.halo = new Sprite(
      new SpriteMaterial({
        map: haloTexture(),
        blending: AdditiveBlending,
        depthWrite: false,
        transparent: true,
        opacity: 0.85,
      }),
    );
    this.halo.scale.setScalar(C.core.haloScale);
    this.group.add(this.halo);

    for (const [index, radius] of C.core.ringRadii.entries()) {
      const ring = new LineLoop(
        ringGeometry(radius),
        new LineBasicMaterial({
          color: 0x9fdcff,
          transparent: true,
          opacity: C.core.ringOpacity,
          blending: AdditiveBlending,
          depthWrite: false,
        }),
      );
      ring.rotation.x = 0.9 + index * 0.5;
      ring.rotation.y = index * 0.8;
      this.rings.push(ring);
      this.group.add(ring);
    }

    this.sparkMaterial = new ShaderMaterial({
      vertexShader: SPARK_VERTEX,
      fragmentShader: SPARK_FRAGMENT,
      uniforms: {
        uTime: { value: 0 },
        uMinR: { value: C.core.sparkMinRadius },
        uMaxR: { value: C.core.sparkMaxRadius },
        uPixelRatio: { value: 1 },
        uFovScale: { value: 1 },
        uActivity: { value: 1 },
        uAudio: { value: new Vector4() },
      },
      blending: AdditiveBlending,
      depthWrite: false,
      transparent: true,
    });
    this.sparks = new Points(sparkGeometry(C.core.sparkCount), this.sparkMaterial);
    this.group.add(this.sparks);
  }

  private buildMembranes(): void {
    const grid = MEMBRANE_GRID[this.quality];
    for (const spec of MEMBRANES) {
      const material = new ShaderMaterial({
        vertexShader: MEMBRANE_VERTEX,
        fragmentShader: MEMBRANE_FRAGMENT,
        uniforms: {
          uTime: { value: 0 },
          uSeed: { value: spec.seed },
          uScale3: { value: [spec.scale[0], spec.scale[1], 0] },
          uSpan: { value: spec.span },
          uRadius: { value: spec.radius },
          uWrap: { value: spec.wrap },
          uFreq: { value: spec.freq },
          uSpeed: { value: spec.speed },
          uAmpv: { value: spec.amp },
          uNoiseStrength: { value: spec.noiseStrength },
          uCurlStrength: { value: spec.curlStrength },
          uWarmth: { value: spec.warmth },
          uSizeBase: { value: spec.size },
          uAlphaBase: { value: spec.alpha },
          uPixelRatio: { value: 1 },
          uFovScale: { value: 1 },
          uProf: { value: new Vector4(0.75, 0.55, 0.55, 1) },
          uAudio: { value: new Vector4() },
          uGlow: { value: 0.8 },
          uShimmer: { value: 0.25 },
          uCyanBoost: { value: 0 },
          uIntensity: { value: 1 },
        },
        blending: spec.alpha < 0.7 ? NormalBlending : AdditiveBlending,
        depthWrite: false,
        transparent: true,
      });
      const points = new Points(membraneGeometry(grid.u, grid.v), material);
      points.rotation.set(...spec.rotation);
      this.membranes.push(points);
      this.membraneMaterials.push(material);
      this.group.add(points);
    }
  }

  // ── public contract (mirrors AIEntityScene) ──────────────────────────────

  setState(state: AIState): void {
    this.state = state;
  }

  setBands(bands: AudioBands): void {
    this.bandsTarget = bands;
  }

  setIntensity(value: number): void {
    this.intensity = value;
  }

  setPointer(x: number, y: number): void {
    this.pointer.x = x;
    this.pointer.y = y;
  }

  setReducedMotion(reduced: boolean, _state: AIState): void {
    this.reducedMotion = reduced;
  }

  onQuality(callback: (quality: AIQuality) => void): void {
    this.qualityCallback = callback;
  }

  setQuality(quality: AIQuality): void {
    if (quality === this.quality) return;
    this.quality = quality;
    const grid = MEMBRANE_GRID[quality];
    for (const points of this.membranes) {
      const old = points.geometry;
      points.geometry = membraneGeometry(grid.u, grid.v);
      old.dispose();
    }
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
    // Point sizes are expressed in px at z≈camera distance; this converts.
    const fovScale = height / (2 * Math.tan((this.camera.fov * Math.PI) / 360));
    for (const material of this.membraneMaterials) {
      material.uniforms.uPixelRatio.value = dpr;
      material.uniforms.uFovScale.value = fovScale / 500;
    }
    this.sparkMaterial.uniforms.uPixelRatio.value = dpr;
    this.sparkMaterial.uniforms.uFovScale.value = fovScale / 500;
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
    for (const points of this.membranes) points.geometry.dispose();
    for (const material of this.membraneMaterials) material.dispose();
    this.sparks.geometry.dispose();
    this.sparkMaterial.dispose();
    this.core.geometry.dispose();
    this.coreMaterial.dispose();
    (this.halo.material as SpriteMaterial).map?.dispose();
    (this.halo.material as SpriteMaterial).dispose();
    for (const ring of this.rings) {
      ring.geometry.dispose();
      (ring.material as LineBasicMaterial).dispose();
    }
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
    // State easing: exponential approach — 300–600 ms perceived, no jumps.
    const target = ORB_STATE_PROFILES[this.state];
    const ease = 1 - Math.exp(-dt / STATE_EASE_TAU);
    const p = this.profile;
    for (const key of Object.keys(p) as (keyof OrbStateProfile)[]) {
      p[key] += (target[key] - p[key]) * ease;
    }

    // Audio smoothing: fast attack, slow release — musical, never jittery.
    const smooth = (current: number, goal: number) => {
      const tau = goal > current ? C.audioAttack : C.audioRelease;
      return current + (goal - current) * (1 - Math.exp(-dt / tau));
    };
    const silent = this.reducedMotion ? SILENT_BANDS : this.bandsTarget;
    this.bands = {
      level: smooth(this.bands.level, silent.level),
      bass: smooth(this.bands.bass, silent.bass),
      mid: smooth(this.bands.mid, silent.mid),
      high: smooth(this.bands.high, silent.high),
    };

    this.clock += dt * motion * (0.6 + p.speed * 0.4);
    const t = this.clock;

    // Whole-body motion + pointer parallax (±4° budget).
    this.group.rotation.y += dt * C.rotationSpeedY * p.rotation * motion;
    this.group.rotation.x =
      Math.sin(t * C.rotationWobbleSpeed) * C.rotationWobbleX +
      this.pointer.y * C.pointerTilt;
    this.group.rotation.z = this.pointer.x * C.pointerTilt * 0.5;

    // Core breathing: several incommensurate frequencies, never a metronome.
    const breath =
      1 +
      Math.sin(t * 2.2) * 0.035 +
      Math.sin(t * 3.7 + 1.3) * 0.02 +
      Math.sin(t * 0.9 + 4.1) * 0.015 +
      this.bands.level * 0.16 * p.coreActivity;
    this.core.scale.setScalar(breath);
    this.coreMaterial.uniforms.uIntensity.value =
      (2.2 + p.coreActivity * 1.2 + this.bands.level * 1.4) * this.intensity;
    this.halo.scale.setScalar(
      C.core.haloScale * (breath * 0.9 + 0.1) * (0.9 + p.coreActivity * 0.25),
    );

    for (const [index, ring] of this.rings.entries()) {
      ring.rotation.z += dt * (index ? -0.12 : 0.18) * p.rotation * motion;
    }

    const audio = [this.bands.bass, this.bands.mid, this.bands.high, this.bands.level];
    this.sparkMaterial.uniforms.uTime.value = t;
    this.sparkMaterial.uniforms.uActivity.value = 0.6 + p.coreActivity;
    (this.sparkMaterial.uniforms.uAudio.value as Vector4).fromArray(audio);

    for (const material of this.membraneMaterials) {
      material.uniforms.uTime.value = t;
      (material.uniforms.uProf.value as Vector4).set(
        p.amplitude,
        p.speed,
        p.turbulence,
        p.focus,
      );
      (material.uniforms.uAudio.value as Vector4).fromArray(audio);
      material.uniforms.uGlow.value = p.glow;
      material.uniforms.uShimmer.value = p.shimmer;
      material.uniforms.uCyanBoost.value = p.cyanBoost;
      material.uniforms.uIntensity.value = this.intensity;
    }

    this.composer.render();
  }
}
