// Préparer une photo dans le navigateur avant de l'envoyer au serveur.
//
// Le serveur ne décode aucune image (pas de Pillow dans le venv, et pas
// envie d'ouvrir un décodeur sur des fichiers venus d'ailleurs). C'est donc
// ici que se font : la lecture du fichier, sa conversion en JPEG quand
// WebKit sait le lire mais pas le serveur (HEIC d'iPhone), l'aperçu de
// 480 px, la teinte dominante, et la réduction d'un original démesuré.
//
// Tout part en base64 dans du JSON — la fenêtre Tauri échoue sur un `Blob`.

import {
  COTE_APERCU,
  COTE_MAX_ENVOI,
  chargeUtile,
  dimensionsReduites,
  pointeFleche,
  tailleRetouchee,
  teinteDominante,
  verifierFichierImage,
} from './photos';
import type { SuccesAnnotation, SuccesCadre, SuccesPhotoEnvoi } from './types';

function lireEnDataUrl(fichier: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const lecteur = new FileReader();
    lecteur.onerror = () => reject(new Error('Ce fichier ne peut pas être lu.'));
    lecteur.onload = () => resolve(String(lecteur.result));
    lecteur.readAsDataURL(fichier);
  });
}

function chargerImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () =>
      reject(new Error("Cette image ne peut pas être décodée par l'application."));
    image.src = src;
  });
}

function dessiner(
  image: HTMLImageElement,
  largeur: number,
  hauteur: number,
): HTMLCanvasElement {
  const canvas = document.createElement('canvas');
  canvas.width = largeur;
  canvas.height = hauteur;
  const contexte = canvas.getContext('2d');
  if (!contexte) throw new Error("Le navigateur n'a pas pu préparer l'image.");
  contexte.drawImage(image, 0, 0, largeur, hauteur);
  return canvas;
}

/**
 * Le fichier → ce que la route `POST /photo-piles/{id}/photos` attend.
 *
 * L'original est gardé tel quel s'il est d'un type que le serveur range et
 * s'il tient dans 4096 px ; sinon il est redessiné en JPEG à 0,92. L'aperçu
 * est toujours un JPEG de 480 px au plus, à 0,8. La teinte se lit sur un
 * échantillon de 64 px : lire quatre millions de pixels pour une couleur
 * bloquerait l'interface une demi-seconde par photo.
 */
export async function preparerPhoto(fichier: File): Promise<SuccesPhotoEnvoi> {
  const verdict = verifierFichierImage(fichier);
  if (!verdict.ok) throw new Error(verdict.raison ?? "Ce fichier n'est pas une image.");

  const dataUrl = await lireEnDataUrl(fichier);
  const image = await chargerImage(dataUrl);
  const largeur = image.naturalWidth;
  const hauteur = image.naturalHeight;
  if (!largeur || !hauteur) throw new Error('Cette image est vide.');

  let dataBase64: string;
  const envoi = dimensionsReduites(largeur, hauteur, COTE_MAX_ENVOI);
  const reduire = envoi.largeur !== largeur || envoi.hauteur !== hauteur;
  if (verdict.convertir || reduire) {
    const canvas = dessiner(image, envoi.largeur, envoi.hauteur);
    dataBase64 = chargeUtile(canvas.toDataURL('image/jpeg', 0.92));
  } else {
    dataBase64 = chargeUtile(dataUrl);
  }

  const apercu = dimensionsReduites(largeur, hauteur, COTE_APERCU);
  const canvasApercu = dessiner(image, apercu.largeur, apercu.hauteur);
  const thumbBase64 = chargeUtile(canvasApercu.toDataURL('image/jpeg', 0.8));

  let tint = '';
  try {
    const echantillon = dimensionsReduites(largeur, hauteur, 64);
    const petit = dessiner(image, echantillon.largeur, echantillon.hauteur);
    const pixels = petit
      .getContext('2d')
      ?.getImageData(0, 0, echantillon.largeur, echantillon.hauteur).data;
    if (pixels) tint = teinteDominante(pixels);
  } catch {
    // Un canvas « souillé » (image d'une autre origine) refuse la lecture
    // des pixels. Une pile sans teinte vaut mieux qu'un import qui échoue.
    tint = '';
  }

  return {
    fileName: fichier.name || 'photo',
    dataBase64,
    thumbBase64,
    width: envoi.largeur,
    height: envoi.hauteur,
    tint,
  };
}

/** Les images d'un glisser-déposer ou d'un collage, dans l'ordre reçu. */
export function fichiersImages(transfert: DataTransfer | null): File[] {
  if (!transfert) return [];
  const fichiers: File[] = [];
  // `items` porte le collage (⌘V d'une capture) ; `files`, le dépôt du
  // Finder. Les deux à la fois arrivent dans certains navigateurs : on
  // dédoublonne par nom et taille.
  const vus = new Set<string>();
  const ajouter = (f: File | null) => {
    if (!f) return;
    const cle = `${f.name}:${f.size}:${f.lastModified}`;
    if (vus.has(cle)) return;
    vus.add(cle);
    fichiers.push(f);
  };
  for (const item of Array.from(transfert.items ?? [])) {
    if (item.kind === 'file') ajouter(item.getAsFile());
  }
  for (const f of Array.from(transfert.files ?? [])) ajouter(f);
  return fichiers.filter((f) => verifierFichierImage(f).ok || f.type.startsWith('image/'));
}

// ── La retouche et le calque, rendus dans un canvas ────────────────────

export { chargerImage };

export interface RenduPhoto {
  canvas: HTMLCanvasElement;
  largeur: number;
  hauteur: number;
}

/**
 * L'image telle qu'on la voit : tournée, cadrée, et — si demandé — avec
 * ses annotations gravées. `maxCote` réduit le résultat (aperçu, note, PDF).
 */
export function rendrePhoto(
  image: HTMLImageElement,
  rotation: number,
  cadre: SuccesCadre | null,
  options: { annotations?: SuccesAnnotation[]; maxCote?: number } = {},
): RenduPhoto {
  const nl = image.naturalWidth;
  const nh = image.naturalHeight;
  const tournee = rotation % 180 === 0 ? { l: nl, h: nh } : { l: nh, h: nl };
  const finale = tailleRetouchee(nl, nh, rotation, cadre);
  const reduite = options.maxCote
    ? dimensionsReduites(finale.largeur, finale.hauteur, options.maxCote)
    : finale;
  const facteur = reduite.largeur / finale.largeur;

  const canvas = document.createElement('canvas');
  canvas.width = reduite.largeur;
  canvas.height = reduite.hauteur;
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error("Le navigateur n'a pas pu préparer l'image.");

  // Le cadre est exprimé sur l'image TOURNÉE ; on translate pour que son
  // coin haut-gauche soit l'origine, puis on tourne autour du centre de
  // l'image tournée, et on dessine l'original.
  const cx = cadre ? cadre.x * tournee.l : 0;
  const cy = cadre ? cadre.y * tournee.h : 0;
  ctx.save();
  ctx.scale(facteur, facteur);
  ctx.translate(-cx, -cy);
  ctx.translate(tournee.l / 2, tournee.h / 2);
  ctx.rotate((rotation * Math.PI) / 180);
  ctx.drawImage(image, -nl / 2, -nh / 2, nl, nh);
  ctx.restore();

  if (options.annotations?.length) {
    graverAnnotations(ctx, options.annotations, reduite.largeur, reduite.hauteur);
  }
  return { canvas, largeur: reduite.largeur, hauteur: reduite.hauteur };
}

/** Les formes du calque, dessinées dans un contexte 2D de `l`×`h` pixels. */
export function graverAnnotations(
  ctx: CanvasRenderingContext2D,
  annotations: SuccesAnnotation[],
  l: number,
  h: number,
): void {
  // L'épaisseur est pensée pour une image d'environ 1000 px de côté : elle
  // suit la taille réelle pour rester lisible sur un aperçu comme sur un PDF.
  const unite = Math.max(l, h) / 1000;
  for (const a of annotations) {
    const pts = a.points.map(([x, y]) => ({ x: x * l, y: y * h }));
    const epaisseur = Math.max(1, a.width * unite);
    ctx.save();
    ctx.strokeStyle = a.color;
    ctx.fillStyle = a.color;
    ctx.lineWidth = epaisseur;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    if (a.type === 'arrow' && pts.length >= 2) {
      const [p, q] = [pts[0], pts[pts.length - 1]];
      ctx.beginPath();
      ctx.moveTo(p.x, p.y);
      ctx.lineTo(q.x, q.y);
      ctx.stroke();
      const [t, u, v] = pointeFleche(p, q, epaisseur);
      ctx.beginPath();
      ctx.moveTo(t.x, t.y);
      ctx.lineTo(u.x, u.y);
      ctx.lineTo(v.x, v.y);
      ctx.closePath();
      ctx.fill();
    } else if ((a.type === 'rect' || a.type === 'ellipse') && pts.length >= 2) {
      const x = Math.min(pts[0].x, pts[1].x);
      const y = Math.min(pts[0].y, pts[1].y);
      const w = Math.abs(pts[1].x - pts[0].x);
      const hh = Math.abs(pts[1].y - pts[0].y);
      ctx.beginPath();
      if (a.type === 'rect') ctx.rect(x, y, w, hh);
      else ctx.ellipse(x + w / 2, y + hh / 2, w / 2, hh / 2, 0, 0, Math.PI * 2);
      ctx.stroke();
    } else if (a.type === 'highlight' && pts.length >= 2) {
      ctx.globalAlpha = 0.35;
      ctx.lineWidth = epaisseur * 5;
      ctx.beginPath();
      ctx.moveTo(pts[0].x, pts[0].y);
      for (const p of pts.slice(1)) ctx.lineTo(p.x, p.y);
      ctx.stroke();
    } else if (a.type === 'pen' && pts.length >= 1) {
      ctx.beginPath();
      ctx.moveTo(pts[0].x, pts[0].y);
      for (const p of pts.slice(1)) ctx.lineTo(p.x, p.y);
      ctx.stroke();
    } else if (a.type === 'text' && pts.length >= 1 && a.text) {
      const taille = Math.max(12, 22 * unite + a.width * unite);
      ctx.font = `600 ${taille}px -apple-system, "Helvetica Neue", Arial, sans-serif`;
      ctx.textBaseline = 'top';
      const largeurTexte = ctx.measureText(a.text).width;
      ctx.globalAlpha = 0.75;
      ctx.fillStyle = '#000';
      ctx.fillRect(pts[0].x - 4 * unite, pts[0].y - 3 * unite, largeurTexte + 8 * unite, taille + 6 * unite);
      ctx.globalAlpha = 1;
      ctx.fillStyle = a.color;
      ctx.fillText(a.text, pts[0].x, pts[0].y);
    }
    ctx.restore();
  }
}

/** Un canvas → les octets JPEG et leur base64 (sans préfixe). */
export function canvasEnJpeg(
  canvas: HTMLCanvasElement,
  qualite = 0.85,
): { base64: string; octets: Uint8Array } {
  const base64 = chargeUtile(canvas.toDataURL('image/jpeg', qualite));
  const binaire = atob(base64);
  const octets = new Uint8Array(binaire.length);
  for (let i = 0; i < binaire.length; i += 1) octets[i] = binaire.charCodeAt(i);
  return { base64, octets };
}

/** L'aperçu de 480 px d'une photo retouchée, prêt pour `thumbBase64`. */
export function apercuRetouche(
  image: HTMLImageElement,
  rotation: number,
  cadre: SuccesCadre | null,
): string {
  const { canvas } = rendrePhoto(image, rotation, cadre, { maxCote: COTE_APERCU });
  return canvasEnJpeg(canvas, 0.8).base64;
}
