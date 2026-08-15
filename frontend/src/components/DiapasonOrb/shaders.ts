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
uniform vec3 uOrbit;
uniform float uWidth;
uniform float uTurns;
uniform float uLobes;
uniform float uPhase;
uniform float uFoldFrequency;
uniform float uFoldAmplitude;
uniform float uTwist;
uniform float uRibbonSpeed;
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

const vec3 DEEP  = vec3(0.01,  0.18,  0.95);  // saturated electric blue
const vec3 CYAN  = vec3(0.0,   0.96,  1.0);   // reference cyan
const vec3 ICE   = vec3(0.36,  0.88,  1.0);   // blue highlight, not white
const vec3 WARM  = vec3(1.0,   0.28,  0.03);  // amber-orange
const vec3 GOLD  = vec3(1.0,   0.68,  0.08);  // illuminated gold
const vec3 ROSE  = vec3(1.0,   0.16,  0.54);  // warm/cool intersection
const vec3 VIOLET= vec3(0.42,  0.2,   1.0);   // violet seam

vec3 ribbonCenter(float path) {
  float drift = uTime * uRibbonSpeed * uProf.y;
  float theta = path * 3.14159265 * uTurns + uPhase;
  return vec3(
    path * uOrbit.x,
    sin(theta + drift * 0.22) * uOrbit.y
      + sin(path * 3.14159265 * uLobes + uSeed * 0.11) * 0.16,
    cos(theta * 0.72 + uSeed * 0.07 - drift * 0.16) * uOrbit.z * 0.52
  );
}

void main() {
  float t = uTime;

  // A real ribbon: one coordinate travels along a looping centreline, the
  // other crosses a broad cloth. This replaces the former spherical cap,
  // which could only ever look like a particle cloud.
  float theta = aUV.x * 3.14159265 * uTurns + uPhase;
  vec3 center = ribbonCenter(aUV.x);
  vec3 tangent = normalize(ribbonCenter(aUV.x + 0.012) - center);
  vec3 side = normalize(cross(vec3(0.0, 0.0, 1.0), tangent) + vec3(0.0, 0.0001, 0.0));
  vec3 normal = normalize(cross(tangent, side));

  float twistAngle = aUV.x * 3.14159265 * uTwist
    + sin(theta * 1.7 + t * uRibbonSpeed) * 0.36
    + uAudio.y * 0.28;
  float ct = cos(twistAngle);
  float st = sin(twistAngle);
  vec3 across = side * ct + normal * st;
  vec3 foldAxis = -side * st + normal * ct;

  float endTaper = 1.0 - smoothstep(0.7, 1.0, abs(aUV.x));
  float width = uWidth * endTaper
    * (0.88 + sin(theta * 1.3 + uSeed) * 0.12);
  float foldPhase = aUV.y * 3.14159265 * 1.35
    + theta * uFoldFrequency
    - t * uRibbonSpeed * 1.8;
  float fold = sin(foldPhase) * uFoldAmplitude * uProf.x
    + sin(foldPhase * 2.1 + uSeed) * uFoldAmplitude * 0.22 * uProf.z;
  fold *= 1.0 + uAudio.x * 0.8;

  vec3 p = center * (1.0 + uAudio.x * 0.06);
  p += across * aUV.y * width;
  p += foldAxis * fold;
  // Very low-amplitude noise keeps the cloth organic without destroying its
  // continuous rows of points.
  float n = fbm(vec3(aUV * 0.85 + uSeed, t * 0.035));
  p += foldAxis * n * 0.045 * uProf.z;

  // ── Focus: listening draws the veils toward the core.
  p *= mix(1.0, 1.0 / uProf.w, 0.48);

  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  gl_Position = projectionMatrix * mv;

  // Preserve the reference's visible regular rows. Only the outermost fringe
  // thins into free points; the body remains a continuous luminous textile.
  float edgeU = 1.0 - smoothstep(0.7, 1.0, abs(aUV.x));
  float edgeV = 1.0 - smoothstep(0.82, 1.0, abs(aUV.y));
  float edge = edgeU * edgeV;
  float keep = step(aRand.z, clamp(edge * 1.08, 0.0, 1.0));

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
      size * uSizeBase * 1.42 * uPixelRatio * uFovScale * depth / max(-mv.z, 0.4),
      0.5, 9.0);

  // ── Color: cool gradient, whitened crests, slow warm currents,
  //    a rare violet accent (≈ 2 % of points).
  float crest = 0.5 + 0.5 * sin(foldPhase);
  float ribbonFlow = 0.5 + 0.5 * sin(theta * 0.72 + aUV.y * 1.4 + uSeed * 0.23);
  vec3 cool = mix(DEEP, CYAN, clamp(0.42 + ribbonFlow * 0.45 + uCyanBoost * 0.35, 0.0, 1.0));
  cool = mix(cool, ICE, crest * 0.12);
  vec3 warmColor = mix(ROSE, GOLD, smoothstep(0.15, 0.82, ribbonFlow));
  vec3 col = mix(cool, warmColor, clamp(uWarmth * (0.7 + ribbonFlow * 0.35), 0.0, 0.95));
  float violetSeam = (1.0 - smoothstep(0.08, 0.34, abs(aUV.y - sin(theta) * 0.22))) * uWarmth;
  col = mix(col, VIOLET, violetSeam * 0.32);
  // The folds and outer edges form the bright contour lines in the target.
  float rim = smoothstep(0.58, 0.98, abs(aUV.y));
  col = mix(col, ICE, rim * 0.1 + twinkle * 0.18);

  // Stay below the tone-mapper's white-clipping range: the target is made of
  // saturated cyan, blue and gold light, with white reserved for the core.
  float brightness = uGlow * uIntensity * 1.24
    * (0.94 + uAudio.w * 0.18) * (1.0 + uWarmth * 0.08);
  vColor = col * brightness;
  vAlpha = keep * pow(edge, 0.38) * uAlphaBase * (0.78 + crest * 0.22);
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
