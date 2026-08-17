/** GLSL for the voice terrain.
 *
 * The relief is built from three superposed scales — a broad apron carrying the
 * foothills to the edges of the frame, a cone giving the massif its straight
 * flanks, and a narrow off-centre spire for the summit — then cut by a ridged
 * multifractal whose crests are welded into continuous ridgelines.
 *
 * The height function is sampled five times per point: once for the position,
 * four more for the neighbours. Those neighbours pay for two things at once —
 * the analytic normal, which lights the flanks, and the discrete Laplacian,
 * which finds convex edges. The second is what draws the bright filaments
 * running down the slopes, and it is the signature of the whole look.
 */

/** Ashima 2D simplex noise, the usual compact form. */
const SIMPLEX = /* glsl */ `
vec3 mod289(vec3 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec2 mod289(vec2 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec3 permute(vec3 x) { return mod289(((x * 34.0) + 1.0) * x); }

float snoise(vec2 v) {
  const vec4 Cc = vec4(0.211324865405187, 0.366025403784439,
                      -0.577350269189626, 0.024390243902439);
  vec2 i  = floor(v + dot(v, Cc.yy));
  vec2 x0 = v - i + dot(i, Cc.xx);
  vec2 i1 = (x0.x > x0.y) ? vec2(1.0, 0.0) : vec2(0.0, 1.0);
  vec4 x12 = x0.xyxy + Cc.xxzz;
  x12.xy -= i1;
  i = mod289(i);
  vec3 p = permute(permute(i.y + vec3(0.0, i1.y, 1.0))
                            + i.x + vec3(0.0, i1.x, 1.0));
  vec3 m = max(0.5 - vec3(dot(x0, x0), dot(x12.xy, x12.xy),
                          dot(x12.zw, x12.zw)), 0.0);
  m = m * m; m = m * m;
  vec3 x = 2.0 * fract(p * Cc.www) - 1.0;
  vec3 h = abs(x) - 0.5;
  vec3 ox = floor(x + 0.5);
  vec3 a0 = x - ox;
  m *= 1.79284291400159 - 0.85373472095314 * (a0 * a0 + h * h);
  vec3 g;
  g.x  = a0.x  * x0.x  + h.x  * x0.y;
  g.yz = a0.yz * x12.xz + h.yz * x12.yw;
  return 130.0 * dot(m, g);
}
`;

export const TERRAIN_VERTEX = /* glsl */ `
attribute vec2 aGrid;
attribute float aRand;

// The live spectrum, one float per band. A uniform array rather than a texture:
// vertex texture fetch is supported unevenly and fails to a black screen on the
// drivers that lack it, whereas a float array works everywhere.
uniform float uSpectrum[SPECTRUM_BINS];
uniform float uTime;
uniform float uAmplitude;
uniform float uTurbulence;
uniform float uSpread;
uniform float uDrive;
// Poids de la flèche, piloté par la voix : ~0 au repos.
uniform float uSpire;
uniform float uLevel;
uniform float uPointSize;
uniform float uPixelRatio;
uniform float uFovScale;
uniform float uWidth;
uniform float uDepth;
uniform vec3 uLightDir;
uniform float uFogNear;
uniform float uFogFar;

varying float vShade;
varying float vCrest;
varying float vAlt;
varying float vFog;
varying float vKeep;
varying float vRand;

${SIMPLEX}

/** Linear read of the spectrum array at a normalised position, 0–1. */
float sampleSpectrum(float u) {
  float x = clamp(u, 0.0, 1.0) * float(SPECTRUM_BINS - 1);
  float i0 = floor(x);
  float f = x - i0;
  int a = int(i0);
  int b = a + 1;
  if (b > SPECTRUM_BINS - 1) b = SPECTRUM_BINS - 1;
  return mix(uSpectrum[a], uSpectrum[b], f);
}

/**
 * Ridged multifractal. Each octave is weighted by the one above it, which welds
 * the crests into continuous ridgelines instead of scattering unrelated bumps —
 * the difference between rock and noise.
 */
float ridgedMF(vec2 p, float detail) {
  float sum = 0.0;
  float amp = 0.5;
  float freq = 1.0;
  float prev = 1.0;
  for (int i = 0; i < TERRAIN_OCTAVES; i++) {
    float n = 1.0 - abs(snoise(p * freq));
    n *= n;
    n *= prev;
    prev = clamp(n * mix(1.3, 2.1, detail), 0.0, 1.0);
    sum += n * amp;
    freq *= 2.03;
    amp *= 0.52;
  }
  return sum;
}

/** The relief, as a plain function of grid position so the normal and the
 * curvature can both be derived by sampling it again a hair to each side. */
float terrainHeight(vec2 g) {
  float gx = g.x;
  float gz = g.y;

  float spread = max(uSpread, 0.3);
  float rx = gx / spread;

  // A slow bend of the frequency axis. Without it the massif is a perfect
  // mirror of itself, which no mountain ever is.
  float skew = snoise(vec2(gz * 0.8, 1.7)) * 0.10;
  float band = sampleSpectrum(pow(min(abs(rx + skew), 1.0), 0.75));

  // Three scales, superposed. The apron reaches the frame, the cone gives the
  // massif its straight flanks, the spire carries the summit — and the spire
  // sits slightly off centre, as in the reference.
  //
  // The spire dominates on purpose: it is both the narrowest and by far the
  // heaviest of the three, so the summit towers over its own shoulders instead
  // of being one peak among several.
  float rr = sqrt(rx * rx + gz * gz * 0.8);
  float sx = rx - 0.07;
  float sz = gz + 0.05;
  // Le cône se resserre (1.35 au lieu de 0.92) : les flancs remontent plus
  // droit et la masse se concentre au centre au lieu de s'étaler.
  float cone  = pow(max(0.0, 1.0 - rr * 1.35), 1.75);
  // La flèche est deux fois plus étroite qu'avant sur les deux axes. C'est ce
  // qui la fait lire comme une aiguille et non comme un sommet parmi d'autres.
  float spire = exp(-(sx * sx * 42.0 + sz * sz * 22.0));
  float apron = exp(-(rx * rx * 0.50 + gz * gz * 0.46));

  // La flèche NAÎT DE LA VOIX. Au repos il ne reste que le massif et son
  // tablier ; c'est l'arrivée du sommet qui devient l'événement, au lieu
  // d'une silhouette permanente qui grandit un peu.
  //
  // uSpire vaut ~0 au repos et monte avec le niveau : ce terme est la
  // différence entre un décor qui réagit et un corps qui répond.
  float voice = clamp(uLevel * uSpire, 0.0, 1.6);
  float env = cone * 0.34 + apron * 0.30 + spire * (0.06 + voice * 1.85);

  // Domain warp: bends the ridgelines so they meander like eroded rock rather
  // than running along the noise's own grain.
  vec2 p = vec2(gx * 2.5, gz * 1.9) + vec2(uTime * 0.035, -uTime * 0.055);
  vec2 warp = vec2(snoise(p * 0.55), snoise(p * 0.55 + 4.7));
  float rock = ridgedMF(p + warp * 0.45, uTurbulence);

  // The rock term swings roughly 0.4–1.1, and that swing is what throws up the
  // jagged spires rather than a smooth dome.
  float body = env * (0.62 + band * uDrive * 0.45) * (0.34 + 0.92 * rock);
  // Chaque fréquence creuse sa propre arête : c'est le « détail » demandé.
  // Le terme est appliqué au rayon de la bande, pas à l'enveloppe entière,
  // donc un aigu soulève les contreforts pendant qu'un grave gonfle le centre.
  float bump = env * band * uDrive * 0.62;
  return (body + bump) * uAmplitude;
}

void main() {
  float height = terrainHeight(aGrid);

  float e = 0.009;
  float hl = terrainHeight(aGrid - vec2(e, 0.0));
  float hr = terrainHeight(aGrid + vec2(e, 0.0));
  float hd = terrainHeight(aGrid - vec2(0.0, e));
  float hu = terrainHeight(aGrid + vec2(0.0, e));

  float dhdx = (hr - hl) / (2.0 * e * uWidth * 0.5);
  float dhdz = (hu - hd) / (2.0 * e * uDepth * 0.5);
  vec3 normal = normalize(vec3(-dhdx, 1.0, -dhdz));

  // Discrete Laplacian: negative where the surface is convex. Normalised by
  // amplitude so a crest reads the same whether the massif is calm or roaring.
  float lap = (hl + hr + hu + hd) * 0.25 - height;
  float crest = clamp(-lap * 130.0 / max(uAmplitude, 0.25), 0.0, 1.0);
  crest = pow(crest, 0.75);

  // The summit dissolves into scattered grains instead of ending on a point.
  float spray = smoothstep(1.00, 1.60, height) * (aRand - 0.5) * 0.12;
  vec3 world = vec3(aGrid.x * uWidth * 0.5, height + spray, aGrid.y * uDepth * 0.5);
  vec4 mv = modelViewMatrix * vec4(world, 1.0);

  vec3 lightDir = normalize(uLightDir);
  vec3 viewDir = normalize(cameraPosition - world);
  vec3 halfway = normalize(lightDir + viewDir);
  float diffuse = max(dot(normal, lightDir), 0.0);
  float specular = pow(max(dot(normal, halfway), 0.0), 30.0);

  // Valleys sit in their own shadow: the lower a point lies, the less sky it
  // can see.
  float occlusion = mix(0.38, 1.0, clamp(height * 1.4, 0.0, 1.0));
  // Grazing faces catch an edge light, which separates overlapping ridges.
  float rim = pow(1.0 - max(dot(normal, viewDir), 0.0), 2.5);
  float slope = clamp(1.0 - normal.y, 0.0, 1.0);

  vShade = clamp(
    0.10 + diffuse * 0.80 * occlusion + specular * 0.50 + rim * 0.20 +
    uLevel * 0.05,
    0.0, 1.4);
  vCrest = crest;
  vAlt = clamp(height * 0.68, 0.0, 1.3);
  vRand = aRand;

  // Density is not uniform in the reference: grains crowd the crests and the
  // steep faces, thin out across the flats, and scatter apart at the summit.
  float keep = clamp(0.40 + crest * 0.72 + slope * 0.38, 0.0, 1.0);
  keep *= 1.0 - smoothstep(1.05, 1.70, height) * 0.55;
  // Edges dissolve rather than ending on the grid's rectangle.
  keep *= (1.0 - smoothstep(0.72, 1.0, abs(aGrid.x))) *
          (1.0 - smoothstep(0.66, 1.0, abs(aGrid.y)));
  vKeep = keep;

  float dist = -mv.z;
  vFog = clamp((dist - uFogNear) / max(uFogFar - uFogNear, 0.001), 0.0, 1.0);

  gl_Position = projectionMatrix * mv;
  gl_PointSize = uPointSize * uPixelRatio * (0.72 + aRand * 0.46) *
                 (0.88 + crest * 0.5) * (uFovScale / max(dist, 0.001));
}
`;

export const TERRAIN_FRAGMENT = /* glsl */ `
precision mediump float;

uniform vec3 uAccent;
uniform float uGlow;
uniform float uIntensity;

varying float vShade;
varying float vCrest;
varying float vAlt;
varying float vFog;
varying float vKeep;
varying float vRand;

void main() {
  vec2 d = gl_PointCoord - vec2(0.5);
  float r = dot(d, d);
  if (r > 0.25) discard;

  // Thinning is done by dropping whole grains against a stable per-point
  // threshold, never by fading them: partial alpha would leave a haze hanging
  // in front of the ridges behind it, and the depth buffer would keep it.
  if (vRand > vKeep) discard;

  // One chromaticity, start to finish. Normalising the accent by its largest
  // channel gives the brightest colour of that exact hue; scaling along that
  // vector can raise the value as far as it likes and can never reach white.
  vec3 hue = uAccent / max(max(uAccent.r, max(uAccent.g, uAccent.b)), 0.001);

  float value = vShade * (0.55 + vAlt * 0.55) + vCrest * 0.85;
  value = clamp(value, 0.0, 1.7);
  vec3 col = hue * (0.04 + value) * (1.0 - vFog * 0.8);

  float alpha = (1.0 - smoothstep(0.15, 0.25, r)) * uGlow * uIntensity *
                (1.0 - vFog * 0.55);
  if (alpha <= 0.01) discard;

  gl_FragColor = vec4(col, alpha);
}
`;
