import { AI_ENTITY_CONFIG as C } from './config';

/** GLSL float literal. `1` is an int in GLSL and would fail to compile where a
 * float is expected, so every interpolated number goes through this. */
const f = (n: number): string => (Number.isInteger(n) ? n.toFixed(1) : String(n));

/**
 * Gradient noise, written out rather than pulled from a library: four octaves
 * of it is the entire dependency, and a hand-rolled hash keeps the whole
 * displacement deterministic — the same time value always yields the same
 * field, which is what makes the motion continuous instead of jittery.
 */
const NOISE = /* glsl */ `
vec3 hash33(vec3 p) {
  p = vec3(dot(p, vec3(127.1, 311.7, 74.7)),
           dot(p, vec3(269.5, 183.3, 246.1)),
           dot(p, vec3(113.5, 271.9, 124.6)));
  return fract(sin(p) * 43758.5453123) * 2.0 - 1.0;
}

float gnoise(vec3 p) {
  vec3 i = floor(p);
  vec3 w = fract(p);
  // Quintic interpolant: its first and second derivatives vanish at the cell
  // edges, so no grid seam is ever visible in the surface.
  vec3 u = w * w * w * (w * (w * 6.0 - 15.0) + 10.0);
  return mix(
    mix(mix(dot(hash33(i + vec3(0.0, 0.0, 0.0)), w - vec3(0.0, 0.0, 0.0)),
            dot(hash33(i + vec3(1.0, 0.0, 0.0)), w - vec3(1.0, 0.0, 0.0)), u.x),
        mix(dot(hash33(i + vec3(0.0, 1.0, 0.0)), w - vec3(0.0, 1.0, 0.0)),
            dot(hash33(i + vec3(1.0, 1.0, 0.0)), w - vec3(1.0, 1.0, 0.0)), u.x), u.y),
    mix(mix(dot(hash33(i + vec3(0.0, 0.0, 1.0)), w - vec3(0.0, 0.0, 1.0)),
            dot(hash33(i + vec3(1.0, 0.0, 1.0)), w - vec3(1.0, 0.0, 1.0)), u.x),
        mix(dot(hash33(i + vec3(0.0, 1.0, 1.0)), w - vec3(0.0, 1.0, 1.0)),
            dot(hash33(i + vec3(1.0, 1.0, 1.0)), w - vec3(1.0, 1.0, 1.0)), u.x), u.y),
    u.z);
}

float fbm(vec3 p) {
  float sum = 0.0;
  float amp = 0.5;
  float norm = 0.0;
  for (int i = 0; i < ${C.waves.noiseOctaves}; i++) {
    sum += gnoise(p) * amp;
    norm += amp;
    p *= 2.02;
    amp *= 0.5;
  }
  return sum / norm;
}
`;

/**
 * The 4th dimension lives here. Every particle's position is
 * `f(gridPosition, time, audio)` — nothing is stored between frames, so the
 * CPU never touches a vertex and the geometry is never "at rest".
 */
export const VERTEX_SHADER = /* glsl */ `
precision highp float;

// The built-in position attribute holds the undisplaced lattice in world
// units; three needs it anyway, so the grid coordinates are recovered from it
// rather than stored a second time.
attribute float aSeed;  // fixed per-point randomness, generated once

uniform float uTime;
uniform float uAmplitude;
uniform float uSpeed;
uniform float uTurbulence;
uniform float uFocus;
uniform float uGlow;
uniform float uShimmer;
uniform float uBreath;
uniform float uAudioDrive;
uniform float uLevel;
uniform float uBass;
uniform float uMid;
uniform float uHigh;
uniform float uIntensity;
uniform float uPixelRatio;
uniform float uSize;
uniform float uMaxSize;
uniform float uCell;

// Spectral shape, low frequencies first. uEqMix is 0 whenever nobody supplies
// bands, which is what keeps the Talk panel — same shader, no analyser —
// exactly as it was.
uniform float uBands[16];
uniform float uBandCount;
uniform float uEqMix;
uniform vec3 uTint;
// Minimum tint for the current state. Gating the colour purely on loudness
// left "transcribing" grey, because by then nobody is speaking.
uniform float uTintFloor;

uniform vec3 uDeep;
uniform vec3 uMidColor;
uniform vec3 uBright;
uniform vec3 uPeak;

varying vec3 vColor;
varying float vAlpha;

${NOISE}

const float PI = 3.141592653589793;

/**
 * Read the spectrum at a horizontal position, interpolating between bands.
 *
 * Twelve bars drawn as twelve steps reads as a cheap meter. Interpolating —
 * and smoothing the interpolant — turns the same twelve numbers into one
 * continuous ridge, which is what makes it look like a voice rather than a
 * bar chart.
 */
float sampleBands(float u) {
  float count = max(uBandCount, 1.0);
  // Mirrored: lows at the centre, highs toward the ends. Mapped left-to-right
  // instead, the display leans permanently to one side, because speech energy
  // sits in the low-mids — and a lopsided shape is the opposite of calm.
  float pos = clamp(abs(u) * (count - 1.0), 0.0, count - 1.0);
  int i = int(floor(pos));
  float f = pos - float(i);
  f = f * f * (3.0 - 2.0 * f);
  float a = 0.0;
  float b = 0.0;
  for (int k = 0; k < 16; k++) {
    if (k == i) a = uBands[k];
    if (k == i + 1) b = uBands[k];
  }
  if (i + 1 >= int(count)) b = a;
  return mix(a, b, f);
}

void main() {
  float u = position.x / ${f(C.geometry.width * 0.5)};
  float v = position.z / ${f(C.geometry.depth * 0.5)};

  // Gaussian envelope: dense and tall at the centre, thinning to nothing at
  // the ends. This is what dissolves the edges instead of cropping them, and
  // uFocus is how "listening" pulls the field in on itself.
  float envX = exp(-${f(C.geometry.envelopeX)} * u * u * uFocus);
  float envZ = exp(-${f(C.geometry.envelopeZ)} * v * v);
  // A Gaussian never actually reaches zero, so however the frame is cropped
  // the last column still carries visible points and the field ends on a hard
  // vertical edge. These force it to nothing at the lattice boundary, which is
  // what makes the ends dissolve rather than stop.
  envX *= smoothstep(1.0, 0.68, abs(u));
  envZ *= smoothstep(1.0, 0.74, abs(v));
  float env = envX * envZ;

  float t = uTime * uSpeed;

  // Three superposed travelling waves. One alone reads as a machine sweeping
  // a sine; three at unrelated periods never visibly repeat.
  float wave =
      sin(u * ${f(C.waves.slow.freq)} * PI - t * ${f(C.waves.slow.speed)} * 6.2831853) * ${f(C.waves.slow.amp)}
    + sin(u * ${f(C.waves.medium.freq)} * PI + v * 1.74 + t * ${f(C.waves.medium.speed)} * 6.2831853) * ${f(C.waves.medium.amp)}
    + sin(u * ${f(C.waves.micro.freq)} * PI - v * 2.61 + t * ${f(C.waves.micro.speed)} * 6.2831853) * ${f(C.waves.micro.amp)};

  // Ridges and valleys. Time is the third noise axis, so the terrain is not
  // scrolled past the camera — it evolves in place, which is what sells a
  // 3D slice of something with more dimensions than we can draw.
  float ridge = fbm(vec3(
    u * ${f(C.waves.noiseFreq)} * 2.35,
    v * ${f(C.waves.noiseFreq)} * 1.62,
    uTime * ${f(C.waves.noiseSpeed)} * uSpeed
  ));

  // Slow global breathing so the field is never metronomic.
  float breath = 0.86 + 0.14 * sin(uTime * uBreath * 1.15 + aSeed * 0.4);

  float height = (wave + ridge * uTurbulence * 1.3) * uAmplitude * breath;

  // Voice drives the topography rather than a bar chart: mids swell the
  // main wave, overall level lifts the whole field, bass deepens it.
  float voice = (uMid * 0.95 + uLevel * 0.55) * uAudioDrive;
  height += voice * env * 1.15;

  // The spectrum MODULATES the field instead of replacing it. Driving the
  // silhouette directly makes the shape follow wherever speech energy happens
  // to sit — a lopsided lump, or a W when it straddles the centre. Multiplying
  // keeps the wide, centred form and lets the voice make it swell and ripple,
  // which is both calmer and easier to read.
  float spectrum = sampleBands(u);
  height = mix(height, height * (0.5 + spectrum * 2.2), uEqMix);
  height *= env;

  float x = u * ${f(C.geometry.width * 0.5)};
  float z = v * ${f(C.geometry.depth * 0.5)} * (1.0 + uBass * 0.42 * uAudioDrive);

  // Sub-cell jitter: enough to kill the moiré a perfect lattice produces at
  // this density, small enough that the mesh structure still reads.
  float j1 = hash33(vec3(aSeed * 71.3, 11.7, 3.1)).x;
  float j2 = hash33(vec3(aSeed * 43.9, 27.3, 9.4)).y;
  x += j1 * uCell * 0.42;
  z += j2 * uCell * 0.42;

  // Local swirl — a hint of internal circulation, strongest while thinking.
  float swirl = gnoise(vec3(u * 1.4, v * 1.4, uTime * 0.19 * uSpeed)) * uTurbulence;
  x += swirl * 0.085 * env;
  z += swirl * 0.055 * env;

  vec4 mv = modelViewMatrix * vec4(x, height, z, 1.0);
  gl_Position = projectionMatrix * mv;

  // Normalised height, for colour and brightness.
  float hn = clamp(height / max(uAmplitude, 0.001) * 0.62 + 0.5, 0.0, 1.0);

  // Deterministic twinkle: a slow per-point phase, lit further by treble.
  float twinkle = 0.5 + 0.5 * sin(uTime * (1.1 + aSeed * 2.3) + aSeed * 43.0);
  float spark = twinkle * uShimmer * (0.32 + uHigh * 0.68);

  vec3 col = mix(uDeep, uMidColor, smoothstep(0.12, 0.56, hn));
  col = mix(col, uBright, smoothstep(0.54, 0.86, hn));
  col = mix(col, uPeak, smoothstep(0.8, 1.0, hn) * spark);

  // State tint, pulled in by how loud this part of the field actually is, so
  // the colour answers the voice instead of merely announcing a mode.
  float heat = clamp(max(uTintFloor, spectrum * uEqMix + uLevel * 0.6), 0.0, 1.0);
  col = mix(col, uTint, heat * 0.85);

  // Depth cue: points further from the camera recede, both in size and light.
  float depthFade = clamp(1.0 - (-mv.z - 4.0) * 0.085, 0.35, 1.0);

  vColor = col;
  // Only a gentle bias toward the crests. The bright ridge lines are not
  // painted on: where the sheet folds toward the camera many points land on
  // the same pixels and additive blending accumulates them. Forcing contrast
  // here as well only drowns the troughs and flattens the whole field.
  vAlpha = env * (0.3 + 0.7 * hn) * uGlow * uIntensity * depthFade
         * (0.72 + 0.28 * twinkle);

  float size = uSize * (0.5 + 0.5 * env) * (1.0 + spark * 0.55);
  gl_PointSize = clamp(
    size * uPixelRatio * (7.6 / max(-mv.z, 0.1)),
    1.0,
    uMaxSize * uPixelRatio
  );
}
`;

/**
 * Round, soft-edged, premultiplied. Premultiplication is not a detail: it is
 * what lets an additively-blended field composite correctly over a white page
 * or a photograph instead of leaving a visible rectangle.
 */
export const FRAGMENT_SHADER = /* glsl */ `
precision highp float;

varying vec3 vColor;
varying float vAlpha;

void main() {
  // gl_PointCoord is 0..1 across the sprite; centre it and discard outside the
  // disc so no square edge can ever appear.
  float d = length(gl_PointCoord - 0.5) * 2.0;
  if (d > 1.0) discard;

  // Bright core, edge fading to nothing. Squared for a tighter, cleaner dot
  // than a linear falloff, which reads as blur at this size.
  float shape = smoothstep(1.0, ${f(C.points.softness)}, d);
  shape *= shape;

  float alpha = shape * vAlpha;
  if (alpha < 0.0025) discard;

  gl_FragColor = vec4(vColor * alpha, alpha);
}
`;
