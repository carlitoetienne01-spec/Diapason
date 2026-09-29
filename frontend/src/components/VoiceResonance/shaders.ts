export const SOMMET = /* glsl */ `
  uniform float uTemps;
  uniform float uTaille;
  uniform float uVoix;
  uniform float uGrave;
  uniform float uAigus;
  uniform float uPixels;
  uniform float uDensite;
  varying vec3 vCouleur;
  varying float vOpacite;

  void main() {
    float t = position.x, p = position.y, couche = position.z;
    // 29/09/2026 : la peau de points dessinait une texture et un rectangle
    // rose. Au repos les points sont absents. La voix en fait sortir
    // quelques-uns, dans toutes les directions, à des distances différentes.
    float grain = fract(sin(t*127.1 + p*311.7 + couche*74.7) * 43758.5453);
    if (uVoix < 0.045 || grain > 0.006) {
      vOpacite = 0.0;
      vCouleur = vec3(0.0);
      gl_PointSize = 0.0;
      gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
      return;
    }
    float portee = fract(sin(t*91.3 + p*47.1 + couche*19.2) * 23421.631);
    float sortie = 0.38 + uVoix * (0.2 + 1.15*portee);
    sortie += uGrave * 0.22 * (1.0 - portee);
    sortie += uAigus * 0.34 * portee;
    vec3 dir = vec3(sin(p)*cos(t), cos(p), sin(p)*sin(t));
    vec3 point = dir * uTaille * (0.84 + sortie);
    vec3 glace = vec3(0.62, 0.88, 1.0);
    vCouleur = mix(vec3(1.0), glace, portee);
    vOpacite = (0.45 + 0.55*portee) * uDensite;
    vec4 vue = modelViewMatrix * vec4(point, 1.0);
    gl_Position = projectionMatrix * vue;
    gl_PointSize = clamp((2.2 + portee*2.4) * uPixels * (3.8/-vue.z), 1.2, 7.0);
  }
`;

export const SOMMET_SPHERE = /* glsl */ `
  uniform float uTaille;
  varying vec3 vNormale;
  varying vec3 vVue;
  void main() {
    vec3 point = position * 0.84 * uTaille;
    vec4 monde = modelMatrix * vec4(point, 1.0);
    vNormale = normalize(mat3(modelMatrix) * normal);
    vVue = cameraPosition - monde.xyz;
    gl_Position = projectionMatrix * viewMatrix * monde;
  }
`;

export const FRAGMENT_SPHERE = /* glsl */ `
  uniform float uTemps;
  varying vec3 vNormale;
  varying vec3 vVue;
  void main() {
    vec3 n = normalize(vNormale);
    vec3 vue = normalize(vVue);
    float face = abs(dot(n, vue));
    float bord = pow(1.0 - face, 1.65);
    float a = uTemps * 0.35;
    vec3 lumiere = normalize(vec3(cos(a)*0.55, 0.72, sin(a)*0.45));
    float spec = pow(max(0.0, dot(reflect(-lumiere, n), vue)), 64.0);
    float volume = pow(face, 1.6) * 0.16;
    vec3 couleur = vec3(0.78, 0.92, 1.0) * (bord + volume) + vec3(1.0) * spec;
    gl_FragColor = vec4(couleur, bord * 0.9 + volume + spec);
  }
`;

export const FRAGMENT = /* glsl */ `
  varying vec3 vCouleur;
  varying float vOpacite;
  void main() {
    float d = length(gl_PointCoord - 0.5) * 2.0;
    if (d > 1.0) discard;
    if (vOpacite < 0.01) discard;
    float point = exp(-3.8*d*d);
    gl_FragColor = vec4(vCouleur, vOpacite*point);
  }
`;

// 12 septembre 2026 — UnrealBloomPass force l'alpha à 1 dans ses flous.
// alpha:true seul gardait donc un disque noir sur la vitre. Après conversion
// sRGB, l'alpha suit le canal le plus lumineux : RGB <= alpha, comme l'exige
// le canevas prémultiplié. Le noir disparaît, la lumière sur noir est conservée.
export const SORTIE_VITREE = {
  uniforms: { tDiffuse: { value: null } },
  vertexShader: /* glsl */ `
    varying vec2 vUv;
    void main() {
      vUv = uv;
      gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    }
  `,
  fragmentShader: /* glsl */ `
    uniform sampler2D tDiffuse;
    varying vec2 vUv;
    void main() {
      vec3 lumiere = clamp(texture2D(tDiffuse, vUv).rgb, 0.0, 1.0);
      float alpha = max(lumiere.r, max(lumiere.g, lumiere.b));
      gl_FragColor = vec4(lumiere, alpha);
    }
  `,
};
