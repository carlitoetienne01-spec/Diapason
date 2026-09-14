export const SOMMET = /* glsl */ `
  uniform float uTemps;
  uniform float uTaille;
  uniform float uVoix;
  uniform float uAigus;
  uniform float uPixels;
  uniform float uDensite;
  varying vec3 vCouleur;
  varying float vOpacite;

  mat3 rotationX(float a) {
    float c = cos(a), s = sin(a);
    return mat3(1.,0.,0., 0.,c,s, 0.,-s,c);
  }
  mat3 rotationY(float a) {
    float c = cos(a), s = sin(a);
    return mat3(c,0.,-s, 0.,1.,0., s,0.,c);
  }
  vec3 surface(float t, float p, float couche) {
    float phase = couche * 0.72;
    float pli = sin(3.0*t + uTemps*0.8 + phase) * pow(sin(p), 2.0);
    float vague = cos(4.0*p - uTemps*0.65 + phase) * 0.08;
    float rayon = (0.84 + couche*0.115) * (1.0 + 0.17*pli + vague);
    rayon += uVoix * (0.38 + 0.16*sin(5.0*p + 2.0*t - uTemps));
    rayon += uAigus * 0.018 * sin(15.0*p + 4.0*t);
    vec3 point = vec3(sin(p)*cos(t), cos(p), sin(p)*sin(t)) * rayon;
    point.x += 0.07*sin(p*2.0 + uTemps + phase);
    return rotationY(uTemps*0.23 + phase*0.2) * rotationX(0.62 + phase*0.22) * point * uTaille;
  }
  void main() {
    float t = position.x, p = position.y, couche = position.z;
    vec3 point = surface(t, p, couche);
    vec3 dt = surface(t+0.006, p, couche) - point;
    vec3 dp = surface(t, p+0.006, couche) - point;
    vec3 normale = normalize(cross(dt, dp));
    vec3 regard = normalize(cameraPosition - point);
    float face = abs(dot(normale, regard));
    float bord = pow(1.0-face, 3.0);
    float devant = smoothstep(-0.8, 0.8, point.z);
    float teinte = sin(t + p*1.6 + uTemps*0.15 + couche*0.55);
    vec3 iris = vec3(0.22, 0.025, 0.88);
    vec3 rose = vec3(0.86, 0.06, 0.68);
    vec3 glace = vec3(0.06, 0.72, 1.0);
    vec3 couleur = mix(iris, rose, smoothstep(-0.7, 0.65, teinte));
    couleur = mix(couleur, glace, smoothstep(0.30, 0.95, sin(t-p+1.8)) * (0.2 + bord*0.7));
    vCouleur = mix(couleur, vec3(0.92, 0.86, 1.0), bord*0.28);
    vCouleur *= 0.80 + bord*0.40;
    vOpacite = (0.34 + bord*0.42) * (0.35 + devant*0.65) * uDensite;
    vec4 vue = modelViewMatrix * vec4(point, 1.0);
    gl_Position = projectionMatrix * vue;
    gl_PointSize = clamp((1.35 + bord*0.9) * uPixels * (3.8/-vue.z), 1.0, 5.0);
  }
`;

export const FRAGMENT = /* glsl */ `
  varying vec3 vCouleur;
  varying float vOpacite;
  void main() {
    float d = length(gl_PointCoord - 0.5) * 2.0;
    if (d > 1.0) discard;
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
