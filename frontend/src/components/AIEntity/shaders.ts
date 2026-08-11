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
// 1 lays the rows out as a vertical ribbon of strands instead of a terrain
// spread in depth. Banner only.
uniform float uRibbon;

uniform vec3 uDeep;
uniform vec3 uMidColor;
uniform vec3 uBright;
uniform vec3 uPeak;
uniform vec3 uStops[6];
// 0 keeps the cyan identity (Talk panel); 1 lays the spectrum across the
// width (dictation banner).
uniform float uSpectrumMix;
uniform float uSparkleChance;
uniform float uSparkleGain;

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

/**
 * Gaussian envelope, forced to zero at the lattice boundary.
 *
 * A Gaussian never actually reaches zero, so however the frame is cropped the
 * last column still carries visible points and the field ends on a hard
 * vertical edge. The smoothsteps are what make the ends dissolve rather than
 * stop. uFocus is how "listening" pulls the field in on itself.
 */

/**
 * The banner's spectrum, laid across the width.
 *
 * Six stops interpolated in linear RGB. A hue rotation would be shorter, but
 * it walks through yellows and oranges the reference never contains — the
 * stops are the picture's actual colours, so mixing between them cannot
 * invent one that does not belong.
 */
vec3 spectrumAt(float t) {
  // Same fix as the ribbon copy: at t = 1.0 the floor lands on 5, no loop
  // iteration matches, and the right edge wears the first stop's green.
  float tt = clamp(t, 0.0, 1.0) * 5.0;
  int i = int(min(floor(tt), 4.0));
  float sf = tt - float(i);
  sf = sf * sf * (3.0 - 2.0 * sf);
  vec3 a = uStops[0];
  vec3 b = uStops[1];
  for (int k = 0; k < 5; k++) {
    if (k == i) { a = uStops[k]; b = uStops[k + 1]; }
  }
  return mix(a, b, sf);
}

float fieldEnvelope(float u, float v) {
  // The terrain's envelope concentrates everything centrally, which leaves
  // exactly one hump. The ribbon needs peaks all along its length, so its
  // falloff is far gentler — it still dissolves at the ends, just later.
  float sharpness = mix(${f(C.geometry.envelopeX)}, ${f(C.ribbon.falloff)}, uRibbon);
  float envX = exp(-sharpness * u * u * uFocus);
  float envZ = exp(-${f(C.geometry.envelopeZ)} * v * v);
  envX *= smoothstep(1.0, 0.68, abs(u));
  envZ *= smoothstep(1.0, 0.74, abs(v));
  return envX * envZ;
}

/**
 * Height of the surface at a point, before the spectrum touches it.
 *
 * Shared rather than duplicated because the columns must start exactly on the
 * surface: computed twice, the two would drift apart the moment either is
 * tuned, and the bars would float above the body or sink into it.
 */
float fieldHeight(float u, float v, float env, float seed) {
  float t = uTime * uSpeed;
  float wave =
      sin(u * ${f(C.waves.slow.freq)} * PI - t * ${f(C.waves.slow.speed)} * 6.2831853) * ${f(C.waves.slow.amp)}
    + sin(u * ${f(C.waves.medium.freq)} * PI + v * 1.74 + t * ${f(C.waves.medium.speed)} * 6.2831853) * ${f(C.waves.medium.amp)}
    + sin(u * ${f(C.waves.micro.freq)} * PI - v * 2.61 + t * ${f(C.waves.micro.speed)} * 6.2831853) * ${f(C.waves.micro.amp)};

  float ridge = fbm(vec3(
    u * ${f(C.waves.noiseFreq)} * 2.35,
    v * ${f(C.waves.noiseFreq)} * 1.62,
    uTime * ${f(C.waves.noiseSpeed)} * uSpeed
  ));

  float breath = 0.86 + 0.14 * sin(uTime * uBreath * 1.15 + seed * 0.4);
  float height = (wave + ridge * uTurbulence * 1.3) * uAmplitude * breath;
  float voice = (uMid * 0.95 + uLevel * 0.55) * uAudioDrive;
  height += voice * env * 1.15;
  float spectrum = sampleBands(u);
  // With the columns gone the spectrum amplifies again instead of damping.
  // The 0.42 factor was there to keep the body low enough for branches to
  // grow out of it; left in place it would quietly SHRINK the ribbon exactly
  // when the user speaks — the opposite of what the motion is for.
  height = mix(height, height * (0.92 + spectrum * 0.45), uEqMix);
  return height * env;
}

void main() {
  float u = position.x / ${f(C.geometry.width * 0.5)};
  float v = position.z / ${f(C.geometry.depth * 0.5)};

  float env = fieldEnvelope(u, v);
  float height = fieldHeight(u, v, env, aSeed);
  float spectrum = sampleBands(u);

  float x = u * ${f(C.geometry.width * 0.5)};
  float z = v * ${f(C.geometry.depth * 0.5)} * (1.0 + uBass * 0.42 * uAudioDrive);

  // Sub-cell jitter: enough to kill the moire a perfect lattice produces at
  // this density, small enough that the mesh structure still reads.
  float j1 = hash33(vec3(aSeed * 71.3, 11.7, 3.1)).x;
  float j2 = hash33(vec3(aSeed * 43.9, 27.3, 9.4)).y;
  x += j1 * uCell * 0.42;
  z += j2 * uCell * 0.42;

  // Local swirl — a hint of internal circulation, strongest while thinking.
  float swirl = gnoise(vec3(u * 1.4, v * 1.4, uTime * 0.19 * uSpeed)) * uTurbulence;
  x += swirl * 0.085 * env;
  z += swirl * 0.055 * env;

  // The ribbon's own waveform. The terrain's three superposed waves make a
  // slow swell; this is a proper trace — several alternations across the
  // width, with the crest sitting over the loudest band lifted above its
  // neighbours. That is what makes one peak dominate, and makes *which* peak
  // depend on what was just said.
  float phase = u * ${f(C.ribbon.cycles)} * 6.2831853 - uTime * 0.55 * uSpeed;
  float trace = sin(phase) * 0.72
              + sin(phase * 0.47 + 1.7) * 0.42
              + sin(phase * 2.13 - 0.6) * 0.16;
  // Non-mirrored, so the peaks differ from one side to the other rather than
  // coming in symmetric pairs, and weighted toward the centre so the dominant
  // crest tends to land where the eye already is.
  float bandEnergy = sampleBands(u * 0.55);
  float centreBias = exp(-1.1 * u * u);
  float peak = 1.0 + bandEnergy * ${f(C.ribbon.peakGain)} * centreBias * uEqMix;
  float ribbonWave = trace * peak * uAmplitude * 0.48;

  // Ribbon mode. The rows stop being depth and become strands stacked in Y,
  // each following the same curve — which is exactly what the reference's
  // ribbons are: one wave drawn many times, slightly apart. The fan narrows
  // and widens along the length so the bundle breathes instead of running as
  // a constant-width band.
  // Two bundles. The upper half of the rows carries a phase-shifted copy
  // that weaves through the main one — the interlacing of the reference.
  float isSecond = step(0.0, v);
  // Each bundle gets a FULL sheaf, symmetric about its own curve. The first
  // cut fed the raw row coordinate straight in, which put every strand of a
  // bundle on one side of its curve only — two half-sheaves whose facing
  // edges pulled apart wherever the curves diverged. Those were the black
  // lens-shaped holes: not a spacing problem, a one-sidedness problem.
  float vLocal = mix(v * 2.0 + 1.0, v * 2.0 - 1.0, isSecond);
  float p2 = phase + ${f(C.ribbon.second.phase)};
  float secondWave = (sin(p2) * 0.72 + sin(p2 * 0.47 + 1.7) * 0.42) * peak
                   * uAmplitude * 0.44;
  float bundleWave = mix(ribbonWave, secondWave, isSecond);
  // Opens far wider than before: the reference's sheaves flare where the
  // wave turns, and stay full rather than tapering to a thread.
  float fan = 0.62 + 0.38 * (0.5 + 0.5 * cos(u * 1.7 + uTime * 0.19 * uSpeed));
  float thickness = mix(1.0, ${f(C.ribbon.second.spread)}, isSecond);
  float ribbonY = vLocal * ${f(C.ribbon.spread)} * fan * thickness * 0.62;
  // Voice stretches the whole bundle vertically. This is the motion asked
  // for: not a surface swelling, a wave reaching further up and further down.
  // Bounded: past this the ribbon simply leaves the panel, and a wave you
  // cannot see the top of reads as broken rather than loud.
  float stretch = 1.0 + min((uLevel * 1.5 + uMid * 0.8) * uAudioDrive, 1.35);
  float y = mix(height, bundleWave * stretch + ribbonY, uRibbon);
  float zPos = mix(z, v * ${f(C.ribbon.depth)}, uRibbon);

  vec4 mv = modelViewMatrix * vec4(x, y, zPos, 1.0);
  gl_Position = projectionMatrix * mv;

  float hn = clamp(height / max(uAmplitude, 0.001) * 0.62 + 0.5, 0.0, 1.0);
  float twinkle = 0.5 + 0.5 * sin(uTime * (1.1 + aSeed * 2.3) + aSeed * 43.0);
  float spark = twinkle * uShimmer * (0.32 + uHigh * 0.68);

  vec3 col = mix(uDeep, uMidColor, smoothstep(0.12, 0.56, hn));
  col = mix(col, uBright, smoothstep(0.54, 0.86, hn));
  col = mix(col, uPeak, smoothstep(0.8, 1.0, hn) * spark);

  // State tint, pulled in by how loud this part of the field actually is, so
  // the colour answers the voice instead of merely announcing a mode.
  float heat = clamp(max(uTintFloor, spectrum * uEqMix + uLevel * 0.6), 0.0, 1.0);
  col = mix(col, uTint, heat * 0.85);

  // The banner's spectrum. Brightened toward white at the crests so the peaks
  // glow rather than simply being a lighter shade of their own hue.
  vec3 band = spectrumAt(u * 0.68 + 0.5);
  band = mix(band, vec3(1.0), smoothstep(0.82, 1.0, hn) * 0.22);
  col = mix(col, band, uSpectrumMix);

  // Depth cue: points further from the camera recede, in size and in light.
  float depthFade = clamp(1.0 - (-mv.z - 4.0) * 0.085, 0.35, 1.0);

  vColor = col;
  // Only a gentle bias toward the crests. The bright ridge lines are not
  // painted on: where the sheet folds toward the camera many points land on
  // the same pixels and additive blending accumulates them.
  // Strands: every few rows runs brighter, which is what gives the reference
  // its ribbon texture instead of a uniform dusting.
  float row = floor((v * 0.5 + 0.5) * ${f(C.spectrum.strandEvery)} * 12.0);
  float strand = 1.0 + ${f(C.spectrum.strandGain - 1.0)}
    * uSpectrumMix * step(0.5, fract(row / 2.0));

  // Sparkles: a deterministic few burn far brighter. Scattered by seed, so
  // they sit still in the field rather than crawling across it.
  float sparkle = step(1.0 - uSparkleChance, fract(aSeed * 91.7));
  float burn = 1.0 + sparkle * uSparkleGain * uSpectrumMix * (0.4 + 0.6 * twinkle);

  vAlpha = env * (0.3 + 0.7 * hn) * uGlow * uIntensity * depthFade
         * (0.72 + 0.28 * twinkle) * strand * burn
         * (1.0 - 0.42 * uSpectrumMix)
         * mix(1.0, mix(1.0, ${f(C.ribbon.second.glow)}, isSecond), uRibbon);

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



// ── The line-drawn banner ribbon ───────────────────────────────────────────
//
// Shared mathematics for the four banner draws (strand lines, hair curves,
// glow sprites, floating specks). One template so the curve is computed the
// same way everywhere: a glow sprite that disagreed with its strand about
// where the crest is would hover beside the wave instead of on it.
const RIBBON_CORE = /* glsl */ `
uniform float uTime;
uniform float uSpeed;
uniform float uAmplitude;
uniform float uAudioDrive;
uniform float uLevel;
uniform float uMid;
uniform float uGlow;
uniform float uIntensity;
uniform float uPixelRatio;
uniform float uFocus;
uniform vec3 uTint;
uniform float uTintFloor;
uniform float uBands[16];
uniform float uBandCount;
uniform float uEqMix;
uniform vec3 uStops[6];

varying vec3 vColor;
varying float vAlpha;

const float TAU = 6.2831853;

float sampleBands(float u) {
  float count = max(uBandCount, 1.0);
  float pos = clamp(abs(u) * (count - 1.0), 0.0, count - 1.0);
  int i = int(floor(pos));
  float ff = pos - float(i);
  ff = ff * ff * (3.0 - 2.0 * ff);
  float a = 0.0;
  float b = 0.0;
  for (int k = 0; k < 16; k++) {
    if (k == i) a = uBands[k];
    if (k == i + 1) b = uBands[k];
  }
  if (i + 1 >= int(count)) b = a;
  return mix(a, b, ff);
}

vec3 spectrumAt(float t) {
  // min() on the index, not just clamp() on t: at t = 1.0 exactly the floor
  // lands on 5, no loop iteration matches, and a/b keep their DEFAULTS — the
  // first stop. The right edge then wears the left edge's green, as a hard
  // band after the magenta. Seen on screen, at the ribbon's right end.
  float tt = clamp(t, 0.0, 1.0) * 5.0;
  int i = int(min(floor(tt), 4.0));
  float ff = tt - float(i);
  ff = ff * ff * (3.0 - 2.0 * ff);
  vec3 a = uStops[0];
  vec3 b = uStops[1];
  for (int k = 0; k < 5; k++) {
    if (k == i) { a = uStops[k]; b = uStops[k + 1]; }
  }
  return mix(a, b, ff);
}

// Gentle end fade: the wave settles to its axis and dims at the edges
// instead of being cropped.
float ribbonEnv(float u) {
  return exp(-${f(C.ribbon.falloff)} * u * u) * smoothstep(1.0, 0.78, abs(u));
}

// The centreline of a bundle. 0 = main, 1 = second (phase-shifted weave),
// 2 = hair curves, each detuned by its seed so the three cross rather than
// stack. Voice stretches every curve vertically — bounded, because a wave
// whose top leaves the frame reads as broken rather than loud.
float ribbonCurve(float u, float bundle, float seed) {
  float t = uTime * uSpeed;
  float phase = u * ${f(C.ribbon.cycles)} * TAU - t * 0.55;
  float bandEnergy = sampleBands(u * 0.55);
  float centreBias = exp(-1.1 * u * u);
  float peak = 1.0 + bandEnergy * ${f(C.ribbon.peakGain)} * centreBias * uEqMix;
  float w;
  if (bundle < 0.5) {
    w = (sin(phase) * 0.72 + sin(phase * 0.47 + 1.7) * 0.42
       + sin(phase * 2.13 - 0.6) * 0.16) * 0.48;
  } else if (bundle < 1.5) {
    float p2 = phase + ${f(C.ribbon.second.phase)};
    w = (sin(p2) * 0.72 + sin(p2 * 0.47 + 1.7) * 0.42) * 0.44;
  } else {
    float p3 = phase * 0.62 + seed * TAU;
    w = (sin(p3) * 0.8 + sin(p3 * 1.7 + 2.1) * 0.3) * 0.55;
  }
  float stretch = 1.0 + min((uLevel * 1.5 + uMid * 0.8) * uAudioDrive, 1.35);
  return w * peak * uAmplitude * stretch * ribbonEnv(u);
}
`;

/**
 * The strand lines themselves. `position` carries (u, strandOffset, bundle);
 * the real position is computed here, so the geometry never changes — only
 * the field it is evaluated in.
 */
export const RIBBON_LINES_VERTEX = /* glsl */ `
precision highp float;

attribute float aSeed;

${RIBBON_CORE}

void main() {
  float u = position.x;
  float offset = position.y;
  float bundle = position.z;

  float env = ribbonEnv(u);
  float curve = ribbonCurve(u, bundle, aSeed);

  // The sheaf: strands fan out around the centreline, wider where the wave
  // turns. Hairs carry no fan — they are single threads by definition.
  float fan = 0.62 + 0.38 * (0.5 + 0.5 * cos(u * 1.7 + uTime * 0.19 * uSpeed));
  float thickness = bundle < 0.5 ? 1.0 : (bundle < 1.5 ? ${f(C.ribbon.second.spread)} : 0.0);
  float y = curve + offset * ${f(C.ribbon.spread)} * fan * thickness * 0.62;
  float x = u * ${f(C.geometry.width * 0.5)};
  float z = offset * 0.35 - bundle * 0.15;

  vec4 mv = modelViewMatrix * vec4(x, y, z, 1.0);
  gl_Position = projectionMatrix * mv;

  float bandEnergy = sampleBands(u * 0.55);
  vec3 col = spectrumAt(u * 0.68 + 0.5);
  // The sheaf's luminous core: strands near the centreline run brighter,
  // edges dim — which is how the reference reads as a lit membrane rather
  // than a flat band of equal lines.
  float core = 1.0 - abs(offset);
  col = mix(col, vec3(1.0), core * core * 0.38);

  // The spectrum IS the ribbon's identity. The state signal keeps its floor
  // (thinking must still read amber) but the voice no longer bleaches the
  // gradient toward the tint.
  float voiceHeat = (bandEnergy * uEqMix + uLevel * 0.6) * 0.22;
  float heat = clamp(max(uTintFloor, voiceHeat), 0.0, 1.0);
  col = mix(col, uTint, heat * 0.85);

  float hairDim = bundle > 1.5 ? 0.34 : 1.0;
  float secondDim = (bundle > 0.5 && bundle < 1.5) ? ${f(C.ribbon.second.glow)} : 1.0;

  vColor = col;
  vAlpha = env * (0.22 + 0.5 * core) * uGlow * uIntensity * 0.72
         * hairDim * secondDim;
}
`;

export const RIBBON_LINES_FRAGMENT = /* glsl */ `
precision highp float;
varying vec3 vColor;
varying float vAlpha;
void main() {
  gl_FragColor = vec4(vColor * vAlpha, vAlpha);
}
`;

/**
 * The glow: large, very soft sprites strung along the main centreline. Their
 * brightness follows the spectrum, so the dominant crest of the moment gets
 * the halo — voice decides where the light is. No backdrop is drawn: glow
 * without a rectangle is the entire point.
 */
export const RIBBON_GLOW_VERTEX = /* glsl */ `
precision highp float;

attribute float aSeed;
uniform float uGlowSize;

${RIBBON_CORE}

void main() {
  float u = position.x;
  float env = ribbonEnv(u);
  float curve = ribbonCurve(u, 0.0, 0.0);

  vec4 mv = modelViewMatrix * vec4(u * ${f(C.geometry.width * 0.5)}, curve, -0.6, 1.0);
  gl_Position = projectionMatrix * mv;

  float bandEnergy = sampleBands(u * 0.55);
  float centreBias = exp(-1.1 * u * u);

  vec3 col = mix(spectrumAt(u * 0.68 + 0.5), vec3(1.0), 0.22);
  float voiceHeat = (bandEnergy * uEqMix + uLevel * 0.6) * 0.22;
  float heat = clamp(max(uTintFloor, voiceHeat), 0.0, 1.0);
  col = mix(col, uTint, heat * 0.85);

  vColor = col;
  // A quiet baseline so the wave always carries some light, rising over the
  // loudest band — that rise IS the peak halo. Sized for the SUM: dozens of
  // these gaussians overlap at every pixel, so the unit alpha must be tiny
  // or the halo saturates into a white sausage (it did).
  vAlpha = env * (0.011 + bandEnergy * centreBias * 0.11 * uEqMix
                + uLevel * 0.007) * uGlow * uIntensity;

  gl_PointSize = uGlowSize * (0.65 + bandEnergy * 0.9) * uPixelRatio
               * (7.6 / max(-mv.z, 0.1));
}
`;

export const RIBBON_GLOW_FRAGMENT = /* glsl */ `
precision highp float;
varying vec3 vColor;
varying float vAlpha;
void main() {
  float d = length(gl_PointCoord - 0.5) * 2.0;
  if (d > 1.0) discard;
  // Gaussian, not a rimmed disc: a visible edge on a glow reads as a bubble.
  float g = exp(-d * d * 4.2);
  float a = g * vAlpha;
  gl_FragColor = vec4(vColor * a, a);
}
`;

/**
 * The floating specks around the wave. They drift slowly and twinkle, and
 * they are particles because that is what they are in the reference too —
 * the one part of the old system the new ribbon keeps.
 */
export const RIBBON_FLOATER_VERTEX = /* glsl */ `
precision highp float;

attribute float aSeed;

${RIBBON_CORE}

void main() {
  float u = position.x;
  float baseY = position.y;
  // A slow personal orbit per speck; nothing here ever repeats visibly.
  float drift = sin(uTime * (0.12 + aSeed * 0.2) + aSeed * 41.0) * 0.35;
  float y = baseY + drift;

  vec4 mv = modelViewMatrix * vec4(u * ${f(C.geometry.width * 0.5)}, y, position.z, 1.0);
  gl_Position = projectionMatrix * mv;

  float twinkle = 0.5 + 0.5 * sin(uTime * (0.9 + aSeed * 1.8) + aSeed * 73.0);
  vec3 col = mix(spectrumAt(u * 0.68 + 0.5), vec3(1.0), 0.55);

  vColor = col;
  vAlpha = (0.05 + 0.3 * twinkle * twinkle) * uIntensity
         * smoothstep(1.25, 0.9, abs(u));

  gl_PointSize = (1.4 + aSeed * 2.2) * uPixelRatio;
}
`;
