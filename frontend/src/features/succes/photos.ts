// Les piles de photos — la logique pure, donc vérifiable sous node.
//
// Demandé le 13 septembre 2026 : « des photos empilées l'une sur l'autre, par
// catégorie, qui se distribuent à l'écran quand on clique ». Tout ce qui ne
// touche ni au DOM ni au réseau vit ici ; `photosClient.ts` fait le canvas,
// `PilesPhotos.tsx` fait l'écran.

import type { SuccesAnnotation, SuccesCadre, SuccesPhoto } from './types';

/** Ce que le serveur accepte, et ce qu'on convertit avant de lui envoyer. */
export const TYPES_ACCEPTES = new Set([
  'image/jpeg',
  'image/png',
  'image/webp',
  'image/gif',
]);
/** Décodés par WebKit dans un `<img>`, donc convertibles en JPEG par un canvas. */
export const TYPES_CONVERTIS = new Set(['image/heic', 'image/heif', 'image/tiff', 'image/bmp']);
const EXTENSIONS_CONVERTIES = /\.(heic|heif|tif|tiff|bmp)$/i;

/** Au-delà, ce n'est pas une photo qu'on range dans une pile. */
export const OCTETS_MAX_ORIGINAL = 25 * 1024 * 1024;
/** Le grand côté de l'aperçu : 480 px suffisent à une carte de 132 px en Retina. */
export const COTE_APERCU = 480;
/** Le grand côté au-delà duquel une photo est réduite avant l'envoi. */
export const COTE_MAX_ENVOI = 4096;

export interface VerdictFichier {
  ok: boolean;
  /** Le type qu'on enverra : l'original, ou `image/jpeg` après conversion. */
  convertir: boolean;
  raison?: string;
}

/**
 * Accepter, convertir ou refuser un fichier — AVANT de le lire.
 *
 * Un `.mov` de 400 Mo glissé par erreur ne doit pas être lu en mémoire pour
 * être refusé ensuite : le verdict tombe sur le type et la taille.
 */
export function verifierFichierImage(fichier: {
  type: string;
  size: number;
  name: string;
}): VerdictFichier {
  const type = (fichier.type || '').toLowerCase();
  if (fichier.size <= 0) {
    return { ok: false, convertir: false, raison: 'Ce fichier est vide.' };
  }
  if (fichier.size > OCTETS_MAX_ORIGINAL) {
    return {
      ok: false,
      convertir: false,
      raison: `« ${fichier.name} » dépasse ${Math.round(OCTETS_MAX_ORIGINAL / 1024 / 1024)} Mo.`,
    };
  }
  if (TYPES_ACCEPTES.has(type)) return { ok: true, convertir: false };
  // Le Finder ne renseigne pas toujours le type d'un HEIC ; l'extension
  // tranche alors, et le canvas fera la conversion.
  if (TYPES_CONVERTIS.has(type) || (!type && EXTENSIONS_CONVERTIES.test(fichier.name))) {
    return { ok: true, convertir: true };
  }
  if (type.startsWith('image/')) return { ok: true, convertir: true };
  return {
    ok: false,
    convertir: false,
    raison: `« ${fichier.name} » n'est pas une image.`,
  };
}

/** Le grand côté ramené à `max`, proportions gardées, jamais agrandi. */
export function dimensionsReduites(
  largeur: number,
  hauteur: number,
  max: number,
): { largeur: number; hauteur: number } {
  const l = Math.max(1, Math.round(largeur));
  const h = Math.max(1, Math.round(hauteur));
  const grand = Math.max(l, h);
  if (grand <= max) return { largeur: l, hauteur: h };
  const facteur = max / grand;
  return {
    largeur: Math.max(1, Math.round(l * facteur)),
    hauteur: Math.max(1, Math.round(h * facteur)),
  };
}

/** La charge utile d'une URL de données, sans son préfixe `data:…;base64,`. */
export function chargeUtile(dataUrl: string): string {
  const virgule = dataUrl.indexOf(',');
  return virgule >= 0 ? dataUrl.slice(virgule + 1) : dataUrl;
}

/**
 * La couleur dominante d'une image, depuis ses pixels RGBA.
 *
 * Idée 7 : la pile prend la teinte de sa couverture. Une moyenne donnerait
 * du gris-brun sur presque toute photo ; on compte plutôt les pixels par
 * case de couleur (4 bits par canal) en ignorant ce qui est presque blanc,
 * presque noir ou presque gris — le fond d'une capture d'écran, la neige
 * d'Ottawa — et l'on rend le centre de la case la plus peuplée. Si tout
 * est gris, on rend la moyenne : une capture de terminal reste sombre.
 */
export function teinteDominante(pixels: ArrayLike<number>): string {
  const cases = new Map<number, number>();
  let rTotal = 0;
  let gTotal = 0;
  let bTotal = 0;
  let total = 0;
  for (let i = 0; i + 3 < pixels.length; i += 4) {
    const r = pixels[i];
    const g = pixels[i + 1];
    const b = pixels[i + 2];
    const a = pixels[i + 3];
    if (a < 128) continue;
    total += 1;
    rTotal += r;
    gTotal += g;
    bTotal += b;
    const max = Math.max(r, g, b);
    const min = Math.min(r, g, b);
    // Trop clair, trop sombre, ou sans saturation : ça ne « teinte » rien.
    if (max < 40 || min > 225 || max - min < 40) continue;
    const cle = ((r >> 4) << 8) | ((g >> 4) << 4) | (b >> 4);
    cases.set(cle, (cases.get(cle) ?? 0) + 1);
  }
  if (total === 0) return '';
  let meilleure = -1;
  let compte = 0;
  for (const [cle, n] of cases) {
    if (n > compte) {
      compte = n;
      meilleure = cle;
    }
  }
  // Une case doit peser au moins 2 % de l'image : un bouton rouge sur une
  // capture grise ne fait pas une pile rouge.
  if (meilleure >= 0 && compte >= total * 0.02) {
    const r = ((meilleure >> 8) & 0xf) * 16 + 8;
    const g = ((meilleure >> 4) & 0xf) * 16 + 8;
    const b = (meilleure & 0xf) * 16 + 8;
    return hex(r, g, b);
  }
  return hex(rTotal / total, gTotal / total, bTotal / total);
}

function hex(r: number, g: number, b: number): string {
  const c = (v: number) =>
    Math.max(0, Math.min(255, Math.round(v)))
      .toString(16)
      .padStart(2, '0');
  return `#${c(r)}${c(g)}${c(b)}`;
}

/** `#rrggbb` → `rgba(r, g, b, alpha)` ; une teinte invalide rend `undefined`. */
export function teinteAvecAlpha(teinte: string, alpha: number): string | undefined {
  if (!/^#[0-9a-f]{6}$/i.test(teinte)) return undefined;
  const r = parseInt(teinte.slice(1, 3), 16);
  const g = parseInt(teinte.slice(3, 5), 16);
  const b = parseInt(teinte.slice(5, 7), 16);
  return `rgba(${r}, ${g}, ${b}, ${Math.max(0, Math.min(1, alpha))})`;
}

export interface CartePile {
  photo: SuccesPhoto;
  /** Degrés ; la carte du dessus est droite. */
  rotation: number;
  dx: number;
  dy: number;
  /** 0 = tout en dessous. */
  z: number;
}

// Trois inclinaisons fixes, pas aléatoires : une pile qui change d'allure à
// chaque rendu donne l'impression que quelque chose a bougé.
const INCLINAISONS: ReadonlyArray<{ rotation: number; dx: number; dy: number }> = [
  { rotation: -7, dx: -4, dy: 4 },
  { rotation: 5, dx: 4, dy: 2 },
  { rotation: 0, dx: 0, dy: 0 },
];

/**
 * Les cartes d'une pile fermée, du dessous vers le dessus.
 *
 * `apercus` arrive couverture en tête ; à l'écran, la couverture est celle
 * qu'on voit, donc la dernière peinte.
 */
export function dispositionPile(apercus: SuccesPhoto[]): CartePile[] {
  const visibles = apercus.slice(0, INCLINAISONS.length);
  // La couverture (index 0) prend l'inclinaison du dessus ; les suivantes
  // remplissent les places du dessous dans l'ordre.
  const places = INCLINAISONS.slice(INCLINAISONS.length - visibles.length);
  return visibles
    .map((photo, i) => {
      const place = places[places.length - 1 - i];
      return { photo, ...place, z: visibles.length - 1 - i };
    })
    .reverse();
}

/** « 1,2 Mo », « 340 Ko ». */
export function libelleTaille(octets: number): string {
  if (octets >= 1024 * 1024) {
    return `${(octets / 1024 / 1024).toLocaleString('fr-CA', { maximumFractionDigits: 1 })} Mo`;
  }
  return `${Math.max(1, Math.round(octets / 1024))} Ko`;
}

/** « 13 sept. 2026 ». */
export function libelleDate(ms: number): string {
  if (!Number.isFinite(ms) || ms <= 0) return '';
  return new Date(ms).toLocaleDateString('fr-CA', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  });
}

/** L'index de la photo à afficher après une flèche, en boucle. */
export function indexSuivant(courant: number, total: number, sens: 1 | -1): number {
  if (total <= 0) return -1;
  return (courant + sens + total) % total;
}


// ── Le rangement à la main ─────────────────────────────────────────────

/** Le type de données d'un glisser interne, pour ne pas le confondre avec des fichiers. */
export const TYPE_GLISSER_PHOTO = 'text/x-diapason-photo';

/**
 * Déposer `source` sur `cible` : la photo prend la place de la cible, et
 * tout ce qui est entre les deux glisse d'un cran vers l'ancienne place.
 *
 * « Je la prends avec le curseur pour la mettre en deuxième position » :
 * on la lâche sur la deuxième, elle devient la deuxième.
 */
export function deplacerVers(ids: string[], source: string, cible: string): string[] {
  const de = ids.indexOf(source);
  const vers = ids.indexOf(cible);
  if (de < 0 || vers < 0 || de === vers) return ids;
  const suite = ids.slice();
  suite.splice(de, 1);
  suite.splice(vers, 0, source);
  return suite;
}

// Le glisser interne se signale AUSSI par un drapeau de module : pendant un
// `dragover`, WebKit ne garantit pas que `dataTransfer.types` liste un type
// personnalisé, et le rangement ne marchait alors qu'une fois sur deux
// selon le moteur (constaté le 13 septembre 2026 dans l'app de bureau).
let glisserPhotoEnCours = false;
export function debuterGlisserPhoto(): void {
  glisserPhotoEnCours = true;
}
export function finirGlisserPhoto(): void {
  glisserPhotoEnCours = false;
}

/** Vrai si le glisser en cours transporte une photo de la grille, pas des fichiers. */
export function estGlisserDePhoto(types: ArrayLike<string> | null | undefined): boolean {
  if (glisserPhotoEnCours) return true;
  return !!types && Array.from(types).includes(TYPE_GLISSER_PHOTO);
}

/**
 * La case la plus proche d'un point — pour qu'un dépôt entre deux cases, ou
 * un peu à côté, tombe quand même sur une photo au lieu de ne rien faire.
 */
export function celluleLaPlusProche(
  rects: Iterable<[string, { left: number; top: number; width: number; height: number }]>,
  x: number,
  y: number,
): string | null {
  let meilleure: string | null = null;
  let distance = Infinity;
  for (const [id, r] of rects) {
    const cx = r.left + r.width / 2;
    const cy = r.top + r.height / 2;
    const d = (cx - x) ** 2 + (cy - y) ** 2;
    if (d < distance) {
      distance = d;
      meilleure = id;
    }
  }
  return meilleure;
}

// ── Le zoom en plein cadre ─────────────────────────────────────────────

export interface Zoom {
  /** 1 = ajustée au cadre. */
  echelle: number;
  /** Décalage du centre de l'image par rapport au centre du cadre, en px. */
  x: number;
  y: number;
}

export interface Taille {
  largeur: number;
  hauteur: number;
}

export const ZOOM_MIN = 1;
export const ZOOM_MAX = 8;
/** Un double-clic va là ; assez pour lire une ligne de code sur une capture. */
export const ZOOM_DOUBLE_CLIC = 2.5;
export const ZOOM_NEUTRE: Zoom = { echelle: 1, x: 0, y: 0 };

const arrondi = (v: number) => Math.round(v * 1000) / 1000;

/**
 * Garder l'image dans le cadre : elle peut dépasser, jamais s'en aller.
 *
 * Quand l'image agrandie est plus petite que le cadre dans un axe, elle y
 * reste centrée ; sinon son bord ne rentre pas au-delà du bord du cadre.
 */
export function bornerZoom(zoom: Zoom, cadre: Taille, image: Taille): Zoom {
  const echelle = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, zoom.echelle));
  const jeuX = Math.max(0, (image.largeur * echelle - cadre.largeur) / 2);
  const jeuY = Math.max(0, (image.hauteur * echelle - cadre.hauteur) / 2);
  return {
    echelle: arrondi(echelle),
    x: arrondi(Math.min(jeuX, Math.max(-jeuX, zoom.x))),
    y: arrondi(Math.min(jeuY, Math.max(-jeuY, zoom.y))),
  };
}

/**
 * Zoomer d'un facteur autour d'un point du cadre — ce qui est sous le
 * curseur y reste. `point` est relatif au coin haut-gauche du cadre.
 */
export function zoomerAutour(
  zoom: Zoom,
  facteur: number,
  point: { x: number; y: number },
  cadre: Taille,
  image: Taille,
): Zoom {
  const suivante = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, zoom.echelle * facteur));
  if (suivante === zoom.echelle) return bornerZoom(zoom, cadre, image);
  // Le point, relatif au centre du cadre ; puis dans le repère de l'image.
  const px = point.x - cadre.largeur / 2;
  const py = point.y - cadre.hauteur / 2;
  const ux = (px - zoom.x) / zoom.echelle;
  const uy = (py - zoom.y) / zoom.echelle;
  return bornerZoom(
    { echelle: suivante, x: px - ux * suivante, y: py - uy * suivante },
    cadre,
    image,
  );
}

/** Le facteur de zoom d'un cran de molette ; le trackpad envoie des deltas fins. */
export function facteurMolette(deltaY: number): number {
  return Math.exp(-deltaY * 0.0025);
}

/** « 250 % ». */
export function libelleZoom(echelle: number): string {
  return `${Math.round(echelle * 100)} %`;
}

// ── L'éventail du plein cadre ──────────────────────────────────────────
//
// Demandé le 13 septembre 2026 : « la précédente s'en va à gauche, la
// suivante prend le milieu, celle d'après se met à droite ». Deux de chaque
// côté, inclinées et décroissantes ; au-delà, hors champ.

export const EVENTAIL_PORTEE = 2;

export interface PlaceEventail {
  /** Décalage horizontal, en fraction de l'écart de base. */
  x: number;
  y: number;
  echelle: number;
  rotation: number;
  opacite: number;
  z: number;
  /** Hors champ : la carte existe mais ne se voit pas. */
  visible: boolean;
}

/** La distance signée la plus courte de `index` à `courant`, en boucle. */
export function distanceCirculaire(index: number, courant: number, total: number): number {
  if (total <= 0) return 0;
  let d = ((index - courant) % total + total) % total;
  if (d > total / 2) d -= total;
  return d;
}

/** La place d'une carte à la distance `d` du centre. */
export function placeEventail(d: number): PlaceEventail {
  const a = Math.abs(d);
  if (a > EVENTAIL_PORTEE) {
    return {
      x: d < 0 ? -3 : 3,
      y: 0,
      echelle: 0.4,
      rotation: 0,
      opacite: 0,
      z: 0,
      visible: false,
    };
  }
  return {
    x: d,
    y: a * 0.04,
    echelle: 1 - a * 0.18,
    rotation: d * 4,
    opacite: a === 0 ? 1 : a === 1 ? 0.7 : 0.4,
    z: 10 - a,
    visible: true,
  };
}

// ── La retouche non destructive ────────────────────────────────────────

/** La taille d'une image après rotation (90/270 échangent les côtés) puis cadre. */
export function tailleRetouchee(
  largeur: number,
  hauteur: number,
  rotation: number,
  cadre: SuccesCadre | null,
): Taille {
  const tournee = rotation % 180 === 0 ? { largeur, hauteur } : { largeur: hauteur, hauteur: largeur };
  if (!cadre) return tournee;
  return {
    largeur: Math.max(1, Math.round(tournee.largeur * cadre.w)),
    hauteur: Math.max(1, Math.round(tournee.hauteur * cadre.h)),
  };
}

/**
 * Composer un nouveau cadre, dessiné SUR l'image déjà cadrée, avec l'ancien.
 * Le résultat est exprimé dans l'image entière (après rotation).
 */
export function composerCadres(ancien: SuccesCadre | null, nouveau: SuccesCadre): SuccesCadre {
  const r5 = (v: number) => Math.round(v * 100000) / 100000;
  if (!ancien) return { x: r5(nouveau.x), y: r5(nouveau.y), w: r5(nouveau.w), h: r5(nouveau.h) };
  return {
    x: r5(ancien.x + nouveau.x * ancien.w),
    y: r5(ancien.y + nouveau.y * ancien.h),
    w: r5(nouveau.w * ancien.w),
    h: r5(nouveau.h * ancien.h),
  };
}

/** Un cadre à partir de deux coins, normalisé et borné à l'image. */
export function cadreDepuisCoins(
  a: { x: number; y: number },
  b: { x: number; y: number },
): SuccesCadre | null {
  const x1 = Math.max(0, Math.min(1, Math.min(a.x, b.x)));
  const y1 = Math.max(0, Math.min(1, Math.min(a.y, b.y)));
  const x2 = Math.max(0, Math.min(1, Math.max(a.x, b.x)));
  const y2 = Math.max(0, Math.min(1, Math.max(a.y, b.y)));
  const w = x2 - x1;
  const h = y2 - y1;
  if (w < 0.02 || h < 0.02) return null;
  const r5 = (v: number) => Math.round(v * 100000) / 100000;
  return { x: r5(x1), y: r5(y1), w: r5(w), h: r5(h) };
}

/** Faire suivre les annotations à une rotation d'un quart de tour (sens horaire). */
export function tournerAnnotations(
  annotations: SuccesAnnotation[],
  quartsHoraires: number,
): SuccesAnnotation[] {
  const n = ((quartsHoraires % 4) + 4) % 4;
  if (n === 0) return annotations;
  return annotations.map((a) => ({
    ...a,
    points: a.points.map(([x, y]) => {
      let px = x;
      let py = y;
      for (let i = 0; i < n; i += 1) {
        // Un quart de tour horaire : (x, y) → (1 − y, x).
        const nx = 1 - py;
        const ny = px;
        px = nx;
        py = ny;
      }
      return [px, py] as [number, number];
    }),
  }));
}

/** Faire suivre un cadre à une rotation d'un quart de tour (sens horaire). */
export function tournerCadre(cadre: SuccesCadre | null, quartsHoraires: number): SuccesCadre | null {
  if (!cadre) return null;
  const n = ((quartsHoraires % 4) + 4) % 4;
  let c = { ...cadre };
  for (let i = 0; i < n; i += 1) {
    // Un quart de tour horaire : le coin haut-gauche (x, y+h) devient (1−(y+h), x).
    c = { x: 1 - (c.y + c.h), y: c.x, w: c.h, h: c.w };
  }
  const r5 = (v: number) => Math.round(v * 100000) / 100000;
  return { x: r5(c.x), y: r5(c.y), w: r5(c.w), h: r5(c.h) };
}

/** L'inverse de `recadrerAnnotations` : ramener des fractions du cadre à l'image entière. */
export function deRecadrerAnnotations(
  annotations: SuccesAnnotation[],
  cadre: SuccesCadre | null,
): SuccesAnnotation[] {
  if (!cadre) return annotations;
  return annotations.map((a) => ({
    ...a,
    points: a.points.map(
      ([x, y]) => [cadre.x + x * cadre.w, cadre.y + y * cadre.h] as [number, number],
    ),
  }));
}

/**
 * Faire suivre les annotations à un cadre dessiné sur l'image affichée :
 * celles qui sortent entièrement du cadre sont abandonnées.
 */
export function recadrerAnnotations(
  annotations: SuccesAnnotation[],
  cadre: SuccesCadre,
): SuccesAnnotation[] {
  const sortie: SuccesAnnotation[] = [];
  for (const a of annotations) {
    const points = a.points.map(
      ([x, y]) => [(x - cadre.x) / cadre.w, (y - cadre.y) / cadre.h] as [number, number],
    );
    const dedans = points.some(([x, y]) => x >= 0 && x <= 1 && y >= 0 && y <= 1);
    if (dedans) sortie.push({ ...a, points });
  }
  return sortie;
}

// ── Les annotations ────────────────────────────────────────────────────

export const COULEURS_ANNOTATION = ['#ff3b30', '#ffcc00', '#34c759', '#0a84ff', '#ffffff', '#111111'];

/** La boîte d'une forme à deux coins, en fractions. */
export function boiteDe(points: Array<[number, number]>): SuccesCadre {
  const xs = points.map((p) => p[0]);
  const ys = points.map((p) => p[1]);
  const r5 = (v: number) => Math.round(v * 100000) / 100000;
  const x = Math.min(...xs);
  const y = Math.min(...ys);
  return { x: r5(x), y: r5(y), w: r5(Math.max(...xs) - x), h: r5(Math.max(...ys) - y) };
}

/**
 * Les trois points de la pointe d'une flèche, en pixels : de `a` vers `b`.
 * La pointe fait 4 épaisseurs de long — visible à 3 px, pas grotesque à 12.
 */
export function pointeFleche(
  a: { x: number; y: number },
  b: { x: number; y: number },
  epaisseur: number,
): Array<{ x: number; y: number }> {
  const longueur = Math.max(10, epaisseur * 4);
  const angle = Math.atan2(b.y - a.y, b.x - a.x);
  const ouverture = Math.PI / 7;
  return [
    b,
    { x: b.x - longueur * Math.cos(angle - ouverture), y: b.y - longueur * Math.sin(angle - ouverture) },
    { x: b.x - longueur * Math.cos(angle + ouverture), y: b.y - longueur * Math.sin(angle + ouverture) },
  ];
}

/** Un identifiant court pour une forme, sans dépendre de `crypto` sous node. */
export function idAnnotation(): string {
  return `a-${Date.now().toString(36)}-${Math.floor(Math.random() * 1e6).toString(36)}`;
}

// ── L'export ───────────────────────────────────────────────────────────

/** « Python.pdf » — un nom de fichier sûr d'après le nom de la pile. */
export function nomFichierPdf(nom: string): string {
  const propre = nom
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^A-Za-z0-9 _-]+/g, '')
    .trim()
    .replace(/\s+/g, ' ');
  return `${propre || 'photos'}.pdf`;
}
