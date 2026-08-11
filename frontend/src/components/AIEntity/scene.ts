import {
  AddEquation,
  BufferAttribute,
  BufferGeometry,
  Color,
  CustomBlending,
  OneFactor,
  PerspectiveCamera,
  Points,
  Scene,
  ShaderMaterial,
  Vector2,
  WebGLRenderer,
} from 'three';

import { AI_ENTITY_CONFIG as C, GRID, STATE_PROFILES, calmProfile } from './config';
import { FRAGMENT_SHADER, VERTEX_SHADER } from './shaders';
import { SILENT_BANDS } from './types';
import type { AIQuality, AIState, AudioBands, StateProfile } from './types';

export interface SceneOptions {
  canvas: HTMLCanvasElement;
  quality: AIQuality;
  reducedMotion: boolean;
}

/** Live values the render loop owns. Everything here is mutated in place — no
 * object is allocated per frame. */
type LiveProfile = { -readonly [K in keyof StateProfile]: number };

/** Deterministic per-point randomness. `Math.random` would make the field
 * differ between reloads and, worse, invites per-frame use; this is seeded and
 * runs exactly once per geometry build. */
function makeRandom(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function buildGeometry(quality: AIQuality): BufferGeometry {
  const { cols, rows } = GRID[quality];
  const count = cols * rows;
  const positions = new Float32Array(count * 3);
  const seeds = new Float32Array(count);
  const random = makeRandom(0x9e3779b9);

  const halfW = C.geometry.width * 0.5;
  const halfD = C.geometry.depth * 0.5;

  let i = 0;
  for (let r = 0; r < rows; r++) {
    // Cell centres rather than edges, so the lattice is symmetric about the
    // origin and the entity cannot drift half a cell off-centre.
    const v = rows === 1 ? 0 : ((r + 0.5) / rows) * 2 - 1;
    for (let c = 0; c < cols; c++) {
      const u = cols === 1 ? 0 : ((c + 0.5) / cols) * 2 - 1;
      positions[i * 3] = u * halfW;
      positions[i * 3 + 1] = 0;
      positions[i * 3 + 2] = v * halfD;
      seeds[i] = random();
      i++;
    }
  }

  const geometry = new BufferGeometry();
  geometry.setAttribute('position', new BufferAttribute(positions, 3));
  geometry.setAttribute('aSeed', new BufferAttribute(seeds, 1));
  return geometry;
}

/**
 * Colour per state, mixed in by how loud the field is.
 *
 * The earlier hand-drawn indicator changed colour between recording,
 * transcribing and done, and that was the fastest thing to read at a glance —
 * faster than any shape. These keep that, while staying inside a palette that
 * still belongs to the same object.
 */
/**
 * How present the state colour is before the voice adds to it.
 *
 * Listening keeps a low floor on purpose: the colour should visibly answer
 * speech rather than announce the mode. Thinking sits high because there is no
 * voice left to drive it — that is the whole point of the state.
 */
const STATE_TINT_FLOOR: Record<AIState, number> = {
  idle: 0.0,
  listening: 0.12,
  thinking: 0.9,
  speaking: 0.45,
};

const STATE_TINTS: Record<AIState, readonly [number, number, number]> = {
  idle: C.colors.mid,
  listening: [0.62, 0.94, 1.0],
  thinking: [1.0, 0.66, 0.24],
  speaking: [0.55, 0.9, 1.0],
};

/** Scratch colour, so the render loop allocates nothing per frame. */
const TEMP_COLOR = new Color();

function cellSize(quality: AIQuality): number {
  return C.geometry.width / GRID[quality].cols;
}

/**
 * The entity, as a plain object with a start/stop lifecycle. Deliberately free
 * of React so the render loop can never be entangled with a re-render.
 */
export class AIEntityScene {
  private readonly renderer: WebGLRenderer;
  private readonly scene: Scene;
  private readonly camera: PerspectiveCamera;
  private readonly material: ShaderMaterial;
  private geometry: BufferGeometry;
  private points: Points;

  /** Camera height for the current framing; parallax is added on top. */
  private baseY = 0;

  private quality: AIQuality;
  private reducedMotion: boolean;

  private frame = 0;
  private lastTime = 0;
  private elapsed = 0;
  private running = false;

  /** Eased toward the active state's profile; never snapped. */
  private readonly live: LiveProfile = { ...STATE_PROFILES.idle };
  private target: StateProfile = STATE_PROFILES.idle;
  private stateName: AIState = 'idle';

  private intensity = 1;
  private bands: AudioBands = SILENT_BANDS;
  /** Spectrum, when someone supplies one. Empty means "no equaliser". */
  private spectrum: number[] = [];
  private readonly tint = new Color(...C.colors.bright);

  private readonly pointer = new Vector2(0, 0);
  private readonly pointerEased = new Vector2(0, 0);

  /** Rolling frame time for adaptive quality. */
  private frameTimes: number[] = [];
  private onQualityChange?: (q: AIQuality) => void;

  constructor(options: SceneOptions) {
    this.quality = options.quality;
    this.reducedMotion = options.reducedMotion;

    this.renderer = new WebGLRenderer({
      canvas: options.canvas,
      alpha: true,
      antialias: false, // points are already soft-edged; MSAA would only cost
      premultipliedAlpha: true,
      powerPreference: 'high-performance',
      depth: false,
      stencil: false,
    });
    // A genuinely empty backdrop: no clear colour, no opaque veil, nothing for
    // the canvas rectangle to show against.
    this.renderer.setClearColor(0x000000, 0);
    this.renderer.setPixelRatio(this.pixelRatio());

    this.scene = new Scene();
    this.camera = new PerspectiveCamera(C.camera.fov, 1, 0.1, 80);
    this.applyDistance(C.camera.distance);

    this.geometry = buildGeometry(this.quality);
    this.material = new ShaderMaterial({
      vertexShader: VERTEX_SHADER,
      fragmentShader: FRAGMENT_SHADER,
      transparent: true,
      depthWrite: false,
      depthTest: false,
      // Additive on premultiplied values: bright where points overlap, while
      // the alpha channel still accumulates so the result composites onto any
      // background instead of only reading correctly over black.
      blending: CustomBlending,
      blendEquation: AddEquation,
      blendSrc: OneFactor,
      blendDst: OneFactor,
      blendSrcAlpha: OneFactor,
      blendDstAlpha: OneFactor,
      uniforms: {
        uTime: { value: 0 },
        uAmplitude: { value: this.live.amplitude },
        uSpeed: { value: this.live.speed },
        uTurbulence: { value: this.live.turbulence },
        uFocus: { value: this.live.focus },
        uGlow: { value: this.live.glow },
        uShimmer: { value: this.live.shimmer },
        uBreath: { value: this.live.breath },
        uAudioDrive: { value: this.live.audioDrive },
        uLevel: { value: 0 },
        uBass: { value: 0 },
        uMid: { value: 0 },
        uHigh: { value: 0 },
        uIntensity: { value: 1 },
        uPixelRatio: { value: this.renderer.getPixelRatio() },
        uSize: { value: C.points.baseSize },
        uMaxSize: { value: C.points.maxSize },
        uCell: { value: cellSize(this.quality) },
        // Sixteen slots because GLSL wants a fixed-size array; uBandCount says
        // how many are real. Zero bands leaves uEqMix at 0 and the field
        // behaves exactly as it did before the analyser existed.
        uBands: { value: new Float32Array(16) },
        uBandCount: { value: 0 },
        uEqMix: { value: 0 },
        uTint: { value: new Color(...C.colors.bright) },
        uTintFloor: { value: 0 },
        uDeep: { value: new Color(...C.colors.deep) },
        uMidColor: { value: new Color(...C.colors.mid) },
        uBright: { value: new Color(...C.colors.bright) },
        uPeak: { value: new Color(...C.colors.peak) },
      },
    });

    this.points = new Points(this.geometry, this.material);
    // The shader displaces well outside the rest lattice, so three's bounds
    // would cull the entity at some camera angles.
    this.points.frustumCulled = false;
    this.scene.add(this.points);
  }

  private pixelRatio(): number {
    const dpr = typeof window === 'undefined' ? 1 : window.devicePixelRatio || 1;
    return Math.min(dpr, C.quality.maxPixelRatio);
  }

  setState(state: AIState): void {
    this.stateName = state;
    const profile = STATE_PROFILES[state];
    this.target = this.reducedMotion ? calmProfile(profile) : profile;
  }

  setIntensity(value: number): void {
    this.intensity = Math.max(0, Math.min(1, value));
  }

  setBands(bands: AudioBands): void {
    this.bands = bands;
  }

  /** Per-band energies, 0–1, low frequencies first. */
  setSpectrum(values: readonly number[]): void {
    this.spectrum = values.slice(0, 16).map((v) => (Number.isFinite(v) ? v : 0));
  }

  setReducedMotion(reduced: boolean, state: AIState): void {
    this.reducedMotion = reduced;
    this.setState(state);
  }

  setPointer(x: number, y: number): void {
    this.pointer.set(x, y);
  }

  onQuality(callback: (q: AIQuality) => void): void {
    this.onQualityChange = callback;
  }

  /** Swap the lattice for a denser or sparser one. The material, uniforms and
   * eased parameters survive, so a quality change is invisible in motion. */
  setQuality(quality: AIQuality): void {
    if (quality === this.quality) return;
    this.quality = quality;
    const next = buildGeometry(quality);
    this.points.geometry = next;
    this.geometry.dispose();
    this.geometry = next;
    this.material.uniforms.uCell.value = cellSize(quality);
    this.frameTimes.length = 0;
  }

  /** Place the camera at `distance` along the fixed elevation. */
  private applyDistance(distance: number): void {
    const elevation = (C.camera.elevationDeg * Math.PI) / 180;
    this.camera.position.set(
      0,
      C.camera.lookAt[1] + Math.sin(elevation) * distance,
      Math.cos(elevation) * distance,
    );
    this.baseY = this.camera.position.y;
    this.camera.lookAt(...C.camera.lookAt);
  }

  resize(width: number, height: number): void {
    if (width <= 0 || height <= 0) return;
    const ratio = this.pixelRatio();
    this.renderer.setPixelRatio(ratio);
    this.renderer.setSize(width, height, false);
    this.material.uniforms.uPixelRatio.value = ratio;

    const aspect = width / height;
    this.camera.aspect = aspect;

    // Distance that puts the framed share of the field's width across the
    // viewport, from the horizontal half-angle: tan(hFov/2) = tan(vFov/2)·aspect.
    const halfV = ((C.camera.fov * Math.PI) / 180) / 2;
    const halfTarget = (C.geometry.width * C.camera.framedWidth) / 2;
    const ideal = halfTarget / Math.max(Math.tan(halfV) * aspect, 0.0001);
    const distance = Math.min(
      Math.max(ideal, C.camera.minDistance),
      C.camera.maxDistance,
    );
    this.applyDistance(distance);
    this.camera.updateProjectionMatrix();

    // On a very wide, short banner the clamped distance leaves the field
    // occupying a third of the frame with emptiness either side. Rather than
    // pull the camera closer — which would put the near rows in the viewer's
    // face — the field itself is stretched horizontally to meet the frame.
    // Never squeezed: below 1 the wave would bunch up and lose its silhouette.
    const visibleWidth = 2 * distance * Math.tan(halfV) * aspect;
    const wanted = (visibleWidth * C.camera.framedWidth) / C.geometry.width;
    this.points.scale.x = Math.max(1, Math.min(wanted, C.camera.maxStretch));
  }

  start(): void {
    if (this.running) return;
    this.running = true;
    this.lastTime = performance.now();
    this.frame = requestAnimationFrame(this.tick);
  }

  stop(): void {
    this.running = false;
    if (this.frame) cancelAnimationFrame(this.frame);
    this.frame = 0;
  }

  private readonly tick = (now: number): void => {
    if (!this.running) return;
    this.frame = requestAnimationFrame(this.tick);

    // Clamped so a backgrounded tab does not resume with a huge jump.
    const dt = Math.min((now - this.lastTime) / 1000, 0.05);
    this.lastTime = now;
    this.elapsed += dt;

    this.ease(dt);
    this.updateCamera(dt);
    this.pushUniforms();
    this.renderer.render(this.scene, this.camera);
    this.measure(dt * 1000);
  };

  /** Exponential approach, frame-rate independent: the same wall-clock time to
   * settle whether the display runs at 60 or 120 Hz. */
  private ease(dt: number): void {
    const k = 1 - Math.exp((-dt * 3) / C.transition.seconds);
    const t = this.target;
    const l = this.live;
    l.amplitude += (t.amplitude - l.amplitude) * k;
    l.speed += (t.speed - l.speed) * k;
    l.turbulence += (t.turbulence - l.turbulence) * k;
    l.focus += (t.focus - l.focus) * k;
    l.glow += (t.glow - l.glow) * k;
    l.shimmer += (t.shimmer - l.shimmer) * k;
    l.breath += (t.breath - l.breath) * k;
    l.audioDrive += (t.audioDrive - l.audioDrive) * k;
  }

  private updateCamera(dt: number): void {
    const k = 1 - Math.exp(-dt * 2.4);
    this.pointerEased.x += (this.pointer.x - this.pointerEased.x) * k;
    this.pointerEased.y += (this.pointer.y - this.pointerEased.y) * k;

    // A slow autonomous drift on top of the pointer, so the frame lives even
    // when nothing is touched — but only ever a few hundredths of a unit.
    const driftX = Math.sin(this.elapsed * 0.11) * C.camera.drift;
    const driftY = Math.cos(this.elapsed * 0.083) * C.camera.drift * 0.6;

    this.camera.position.x = this.pointerEased.x * C.camera.parallax + driftX;
    this.camera.position.y =
      this.baseY + this.pointerEased.y * C.camera.parallax * 0.5 + driftY;
    this.camera.lookAt(...C.camera.lookAt);
  }

  private pushUniforms(): void {
    const u = this.material.uniforms;
    u.uTime.value = this.elapsed;
    u.uAmplitude.value = this.live.amplitude * (0.55 + 0.45 * this.intensity);
    u.uSpeed.value = this.live.speed;
    u.uTurbulence.value = this.live.turbulence;
    u.uFocus.value = this.live.focus;
    u.uGlow.value = this.live.glow;
    u.uShimmer.value = this.live.shimmer;
    u.uBreath.value = this.live.breath;
    u.uAudioDrive.value = this.live.audioDrive;
    u.uLevel.value = this.bands.level;
    u.uBass.value = this.bands.bass;
    u.uMid.value = this.bands.mid;
    u.uHigh.value = this.bands.high;
    u.uIntensity.value = 0.35 + 0.65 * this.intensity;

    const array = u.uBands.value as Float32Array;
    for (let i = 0; i < array.length; i++) {
      array[i] = this.spectrum[i] ?? 0;
    }
    u.uBandCount.value = this.spectrum.length;
    // Eased rather than switched: a spectrum arriving mid-word would
    // otherwise snap the surface into a new shape.
    const wanted = this.spectrum.length ? 1 : 0;
    u.uEqMix.value += (wanted - u.uEqMix.value) * 0.12;

    const target = STATE_TINTS[this.stateName] ?? C.colors.bright;
    this.tint.lerp(TEMP_COLOR.setRGB(target[0], target[1], target[2]), 0.06);
    (u.uTint.value as Color).copy(this.tint);
    const floor = STATE_TINT_FLOOR[this.stateName] ?? 0;
    u.uTintFloor.value += (floor - u.uTintFloor.value) * 0.06;
  }

  /** Watch the rolling frame time and step quality down (or back up) rather
   * than letting the entity stutter. */
  private measure(frameMs: number): void {
    if (!this.onQualityChange) return;
    this.frameTimes.push(frameMs);
    const times = this.frameTimes;
    if (times.length < C.quality.sampleFrames) return;

    let sum = 0;
    for (const t of times) sum += t;
    const mean = sum / times.length;
    times.length = 0;

    const order: AIQuality[] = ['low', 'medium', 'high', 'ultra'];
    const index = order.indexOf(this.quality);
    if (mean > C.quality.downgradeMs && index > 0) {
      this.onQualityChange(order[index - 1]);
    } else if (mean < C.quality.upgradeMs && index < order.length - 1) {
      this.onQualityChange(order[index + 1]);
    }
  }

  /** Release every GPU resource. Called on unmount; nothing may outlive it. */
  dispose(): void {
    this.stop();
    this.scene.remove(this.points);
    this.geometry.dispose();
    this.material.dispose();
    this.renderer.dispose();
    this.renderer.forceContextLoss();
  }
}
