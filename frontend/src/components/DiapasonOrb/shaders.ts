/** GLSL programs for Diapason's body.
 *
 * All animation lives on the GPU: JavaScript only sends time, audio bands,
 * the eased state profile and a handful of constants. The noise library is
 * Ashima's simplex (public domain), the standard of the genre.
 */

/** 3D simplex noise + fbm + curl, shared by every vertex program. */
const NOISE_LIB = /* glsl */ `
vec3 mod289(vec3 x){return x - floor(x * (1.0/289.0)) * 289.0;}
vec4 mod289(vec4 x){return x - floor(x * (1.0/289.0)) * 289.0;}
vec4 permute(vec4 x){return mod289(((x*34.0)+1.0)*x);}
vec4 taylorInvSqrt(vec4 r){return 1.79284291400159 - 0.85373472095314 * r;}

float snoise(vec3 v){
  const vec2 C = vec2(1.0/6.0, 1.0/3.0);
  const vec4 D = vec4(0.0, 0.5, 1.0, 2.0);
  vec3 i  = floor(v + dot(v, C.yyy));
  vec3 x0 = v - i + dot(i, C.xxx);
  vec3 g = step(x0.yzx, x0.xyz);
  vec3 l = 1.0 - g;
  vec3 i1 = min(g.xyz, l.zxy);
  vec3 i2 = max(g.xyz, l.zxy);
  vec3 x1 = x0 - i1 + C.xxx;
  vec3 x2 = x0 - i2 + C.yyy;
  vec3 x3 = x0 - D.yyy;
  i = mod289(i);
  vec4 p = permute(permute(permute(
      i.z + vec4(0.0, i1.z, i2.z, 1.0))
    + i.y + vec4(0.0, i1.y, i2.y, 1.0))
    + i.x + vec4(0.0, i1.x, i2.x, 1.0));
  float n_ = 0.142857142857;
  vec3 ns = n_ * D.wyz - D.xzx;
  vec4 j = p - 49.0 * floor(p * ns.z * ns.z);
  vec4 x_ = floor(j * ns.z);
  vec4 y_ = floor(j - 7.0 * x_);
  vec4 x = x_ * ns.x + ns.yyyy;
  vec4 y = y_ * ns.x + ns.yyyy;
  vec4 h = 1.0 - abs(x) - abs(y);
  vec4 b0 = vec4(x.xy, y.xy);
  vec4 b1 = vec4(x.zw, y.zw);
  vec4 s0 = floor(b0)*2.0 + 1.0;
  vec4 s1 = floor(b1)*2.0 + 1.0;
  vec4 sh = -step(h, vec4(0.0));
  vec4 a0 = b0.xzyw + s0.xzyw*sh.xxyy;
  vec4 a1 = b1.xzyw + s1.xzyw*sh.zzww;
  vec3 p0 = vec3(a0.xy, h.x);
  vec3 p1 = vec3(a0.zw, h.y);
  vec3 p2 = vec3(a1.xy, h.z);
  vec3 p3 = vec3(a1.zw, h.w);
  vec4 norm = taylorInvSqrt(vec4(dot(p0,p0), dot(p1,p1), dot(p2,p2), dot(p3,p3)));
  p0 *= norm.x; p1 *= norm.y; p2 *= norm.z; p3 *= norm.w;
  vec4 m = max(0.6 - vec4(dot(x0,x0), dot(x1,x1), dot(x2,x2), dot(x3,x3)), 0.0);
  m = m * m;
  return 42.0 * dot(m*m, vec4(dot(p0,x0), dot(p1,x1), dot(p2,x2), dot(p3,x3)));
}

float fbm(vec3 p){
  float value = 0.0;
  float amplitude = 0.5;
  for (int i = 0; i < 4; i++) {
    value += amplitude * snoise(p);
    p *= 2.0;
    amplitude *= 0.5;
  }
  return value;
}

/* Curl of a noise potential: divergence-free flow, the fluid look. */
vec3 curlNoise(vec3 p){
  const float e = 0.12;
  float n1 = snoise(p + vec3(0.0, e, 0.0));
  float n2 = snoise(p - vec3(0.0, e, 0.0));
  float n3 = snoise(p + vec3(0.0, 0.0, e));
  float n4 = snoise(p - vec3(0.0, 0.0, e));
  float n5 = snoise(p + vec3(e, 0.0, 0.0));
  float n6 = snoise(p - vec3(e, 0.0, 0.0));
  float x = (n1 - n2) - (n3 - n4);
  float y = (n3 - n4) - (n5 - n6);
  float z = (n5 - n6) - (n1 - n2);
  return normalize(vec3(x, y, z) + 1e-5);
}
`;

/** Membrane points — the veils. One draw call per membrane. */
export const MEMBRANE_VERTEX = /* glsl */ `
${NOISE_LIB}

attribute vec2 aUV;      // grid coordinates in [-1, 1]²
attribute vec4 aRand;    // per-particle randoms: size, phase, density, tint

uniform float uTime;
uniform float uSeed;
uniform vec3 uScale3;    // sheet half-size (x, y) — z unused
uniform vec2 uSpan;      // spherical cap span (theta, phi)
uniform float uRadius;
uniform float uWrap;
uniform vec3 uFreq;
uniform vec3 uSpeed;
uniform vec3 uAmpv;
uniform float uNoiseStrength;
uniform float uCurlStrength;
uniform float uWarmth;
uniform float uSizeBase;
uniform float uAlphaBase;
uniform float uPixelRatio;
uniform float uFovScale;
// Eased state profile: x amplitude, y speed, z turbulence, w focus.
uniform vec4 uProf;
// Audio bands: x bass, y mid, z high, w level.
uniform vec4 uAudio;
uniform float uGlow;
uniform float uShimmer;
uniform float uCyanBoost;
uniform float uIntensity;

varying vec3 vColor;
varying float vAlpha;

const vec3 DEEP  = vec3(0.086, 0.486, 1.0);   // #167CFF
const vec3 CYAN  = vec3(0.0,   0.851, 1.0);   // #00D9FF
const vec3 ICE   = vec3(0.659, 0.929, 1.0);   // #A8EDFF
const vec3 WARM  = vec3(1.0,   0.55,  0.10);  // amber-orange
const vec3 VIOLET= vec3(0.467, 0.408, 1.0);   // #7768FF

void main() {
  float t = uTime;

  // ── Base surface: a sheet bent onto a spherical cap. The wrap keeps a
  //    globally round presence without ever drawing an actual sphere.
  float theta = aUV.x * uSpan.x;
  float phi   = aUV.y * uSpan.y * 0.5;
  vec3 cap = vec3(cos(phi) * sin(theta), sin(phi), cos(phi) * cos(theta)) * uRadius;
  vec3 sheet = vec3(aUV.x * uScale3.x, aUV.y * uScale3.y, 0.0);
  vec3 p = mix(sheet, cap, uWrap);

  // ── Travelling waves, three interfering trains (the textile undulation).
  float amp = uProf.x * (1.0 + uAudio.x * 0.9);
  float clockSpeed = uProf.y;
  p.z += (sin(aUV.x * uFreq.x + t * uSpeed.x * clockSpeed * 3.0) * uAmpv.x
        + sin(aUV.y * uFreq.y - t * uSpeed.y * clockSpeed * 3.0) * uAmpv.y
        + sin((aUV.x + aUV.y) * uFreq.z + t * uSpeed.z * clockSpeed * 3.0) * uAmpv.z)
        * amp;

  // ── Multi-octave breathing of the whole cloth, along its radial dir.
  float n = fbm(vec3(aUV * 1.35 + uSeed, t * 0.10 * clockSpeed));
  vec3 radial = normalize(p + vec3(0.0, 0.0, 1e-4));
  p += radial * n * uNoiseStrength * amp;

  // ── Curl flow: slow, divergence-free drift — the fluid signature.
  vec3 flow = curlNoise(vec3(aUV * 0.9 + uSeed * 0.7, t * 0.06 * clockSpeed));
  p += flow * uCurlStrength * uProf.z * (0.7 + uAudio.y * 0.8);

  // ── Gentle twist around Y; mids feed the torsion when speaking.
  float ang = p.y * 0.8 + t * 0.15 * clockSpeed + uAudio.y * 0.6;
  float ca = cos(ang), sa = sin(ang);
  p.xz = mat2(ca, -sa, sa, ca) * p.xz;

  // ── Implicit shell: a breathing radial ripple keeps the silhouette
  //    orb-like without a rigid boundary.
  float r = length(p);
  p *= 1.0 + sin(r * 4.0 - t * 1.2 * clockSpeed) * 0.06 * uProf.x;

  // ── Focus: listening draws the veils toward the core.
  p *= mix(1.0, 1.0 / uProf.w, 0.6);

  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  gl_Position = projectionMatrix * mv;

  // ── Density: procedural patchiness — denser knots, sparse fringes.
  float density = smoothstep(0.15, 0.85,
      snoise(vec3(aUV * 2.4 + uSeed * 1.9, uSeed)) * 0.5 + 0.5);
  float keep = step(aRand.z, density * 0.92 + 0.08);

  // ── Size classes: 75 % fine grain, 20 % medium, 5 % bright rare.
  float size = mix(0.5, 1.2, fract(aRand.x * 7.77));
  if (aRand.x > 0.75) size = mix(1.2, 2.0, fract(aRand.x * 13.13));
  if (aRand.x > 0.95) size = mix(2.0, 4.0, fract(aRand.x * 29.29));

  // Highs make individual rare points twinkle — the shimmer channel.
  float twinkle = step(0.82, aRand.y)
      * (0.5 + 0.5 * sin(t * 9.0 + aRand.y * 61.7))
      * uAudio.z * uShimmer;
  size *= 1.0 + twinkle * 1.6;

  float depth = clamp(1.6 / max(-mv.z, 0.4), 0.0, 1.4);
  gl_PointSize = clamp(
      size * uSizeBase * uPixelRatio * uFovScale * depth / max(-mv.z, 0.4),
      0.5, 9.0);

  // ── Color: cool gradient, whitened crests, slow warm currents,
  //    a rare violet accent (≈ 2 % of points).
  float crest = smoothstep(0.25, 0.85, abs(n));
  vec3 cool = mix(DEEP, CYAN, clamp(0.35 + n * 0.6 + uCyanBoost * 0.5, 0.0, 1.0));
  cool = mix(cool, ICE, crest * 0.6);

  // Warm currents: slow amber rivers crossing the cold veils, like the
  // golden sections of the reference. The gate opens earlier and the mix
  // runs hotter so ACES + additive blending cannot wash them out.
  float warmZone = smoothstep(0.28, 0.72,
      snoise(vec3(aUV * 0.45 + uSeed * 3.1, t * 0.045)) * 0.5 + 0.5);
  vec3 col = mix(cool, WARM, clamp(warmZone * uWarmth * 1.9, 0.0, 0.85));
  col = mix(col, VIOLET, step(0.985, aRand.w) * 0.55);
  col = mix(col, vec3(1.0), crest * 0.28 + twinkle * 0.5);

  float brightness = uGlow * uIntensity * (0.85 + uAudio.w * 0.55);
  vColor = col * brightness;
  vAlpha = keep * uAlphaBase * (0.55 + density * 0.45);
}
`;

export const MEMBRANE_FRAGMENT = /* glsl */ `
precision highp float;
varying vec3 vColor;
varying float vAlpha;

void main() {
  if (vAlpha <= 0.001) discard;
  vec2 uv = gl_PointCoord - vec2(0.5);
  float dist = length(uv);
  // Perfectly round grain with a hot little heart — never a square pixel.
  float shape = smoothstep(0.5, 0.15, dist);
  float core = smoothstep(0.2, 0.0, dist);
  float alpha = (shape * 0.7 + core) * vAlpha;
  if (alpha <= 0.003) discard;
  gl_FragColor = vec4(vColor, alpha);
}
`;

/** The core sphere — near-white heart with an electric-blue rim. */
export const CORE_VERTEX = /* glsl */ `
varying vec3 vNormal;
varying vec3 vView;
void main() {
  vNormal = normalize(normalMatrix * normal);
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  vView = normalize(-mv.xyz);
  gl_Position = projectionMatrix * mv;
}
`;

export const CORE_FRAGMENT = /* glsl */ `
precision highp float;
varying vec3 vNormal;
varying vec3 vView;
uniform float uIntensity;

void main() {
  float facing = clamp(dot(normalize(vNormal), normalize(vView)), 0.0, 1.0);
  // White heart → #C8F5FF → #66D9FF → #178BFF towards the limb.
  vec3 heart = vec3(1.0);
  vec3 inner = vec3(0.784, 0.961, 1.0);
  vec3 mid   = vec3(0.4,   0.851, 1.0);
  vec3 rim   = vec3(0.09,  0.545, 1.0);
  vec3 col = mix(rim, mid, smoothstep(0.0, 0.45, facing));
  col = mix(col, inner, smoothstep(0.45, 0.8, facing));
  col = mix(col, heart, smoothstep(0.8, 1.0, facing));
  gl_FragColor = vec4(col * uIntensity, 1.0);
}
`;

/** Radial sparks drifting away from the core, reborn as they fade. */
export const SPARK_VERTEX = /* glsl */ `
attribute vec3 aDir;     // unit direction from the core
attribute vec3 aRand;    // phase, speed, size

uniform float uTime;
uniform float uMinR;
uniform float uMaxR;
uniform float uPixelRatio;
uniform float uFovScale;
uniform float uActivity;
uniform vec4 uAudio;

varying float vFade;

void main() {
  float cycle = fract(aRand.x + uTime * (0.02 + aRand.y * 0.05) * uActivity);
  float radius = mix(uMinR, uMaxR, cycle);
  vec3 p = aDir * radius;
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  gl_Position = projectionMatrix * mv;
  // Born bright near the core, exhale into darkness.
  vFade = (1.0 - cycle) * (0.35 + uAudio.w * 0.65);
  gl_PointSize = clamp(
      (0.6 + aRand.z * 1.6) * uPixelRatio * uFovScale / max(-mv.z, 0.4),
      0.4, 4.0);
}
`;

export const SPARK_FRAGMENT = /* glsl */ `
precision highp float;
varying float vFade;
void main() {
  vec2 uv = gl_PointCoord - vec2(0.5);
  float dist = length(uv);
  float alpha = smoothstep(0.5, 0.1, dist) * vFade;
  if (alpha <= 0.004) discard;
  // Ice blue, close to the core's inner tone.
  gl_FragColor = vec4(vec3(0.66, 0.9, 1.0), alpha);
}
`;
