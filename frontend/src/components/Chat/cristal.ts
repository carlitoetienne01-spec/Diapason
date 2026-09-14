import type { DecoupeVitree } from './verreTexture';

/** Simulation du biseau, pas du contenu : le déplacement s'annule au bord
 * extérieur et à 16 px vers l'intérieur (une ligne de glyphes du canevas).
 * Le centre et tout ce qui est hors du rectangle arrondi restent intacts. */
export function refractionDuBiseau(x: number, y: number, vitre: DecoupeVitree) {
  const { largeur, hauteur } = vitre;
  if (largeur <= 0 || hauteur <= 0 || x < vitre.x || y < vitre.y
    || x > vitre.x + largeur || y > vitre.y + hauteur) return null;
  const rayon = Math.max(0, Math.min(vitre.rayon, largeur / 2, hauteur / 2));
  const cx = x - vitre.x - largeur / 2;
  const cy = y - vitre.y - hauteur / 2;
  const qx = Math.abs(cx) - (largeur / 2 - rayon);
  const qy = Math.abs(cy) - (hauteur / 2 - rayon);
  const ex = Math.max(qx, 0);
  const ey = Math.max(qy, 0);
  const norme = Math.hypot(ex, ey);
  const profondeur = rayon - norme - Math.min(Math.max(qx, qy), 0);
  const bande = Math.min(16, largeur / 4, hauteur / 4);
  if (profondeur <= 0 || profondeur >= bande) return null;
  const nx = norme ? Math.sign(cx) * ex / norme : qx > qy ? Math.sign(cx) : 0;
  const ny = norme ? Math.sign(cy) * ey / norme : qy >= qx ? Math.sign(cy) : 0;
  const courbure = Math.sin(Math.PI * profondeur / bande);
  // 2,8 px et 14 % : le signe est courbé, pas changé en un autre caractère.
  return {
    dx: -nx * 2.8 * courbure,
    dy: -ny * 2.8 * courbure,
    echelleX: 1 + Math.abs(nx) * 0.14 * courbure,
    echelleY: 1 + Math.abs(ny) * 0.14 * courbure,
  };
}

/** Le reflet suit seulement un pointeur présent sur la vitre. Aucun état
 * React ni minuteur permanent : au plus une mise à jour par image demandée. */
export function suivreReflet(surface: HTMLElement): () => void {
  const mouvementReduit = window.matchMedia('(prefers-reduced-motion: reduce)');
  let frame = 0;
  let point = { x: 0, y: 0 };
  const arreter = () => {
    if (frame) cancelAnimationFrame(frame);
    frame = 0;
    surface.removeAttribute('data-reflet');
  };
  const suivre = (e: PointerEvent) => {
    if (e.pointerType === 'touch' || mouvementReduit.matches) return;
    point = { x: e.clientX, y: e.clientY };
    if (frame) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      const rect = surface.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      const borne = (n: number) => Math.max(0, Math.min(100, n)).toFixed(2);
      surface.style.setProperty('--composer-reflet-x', `${borne((point.x - rect.left) / rect.width * 100)}%`);
      surface.style.setProperty('--composer-reflet-y', `${borne((point.y - rect.top) / rect.height * 100)}%`);
      surface.setAttribute('data-reflet', 'actif');
    });
  };
  surface.addEventListener('pointermove', suivre, { passive: true });
  surface.addEventListener('pointerenter', suivre, { passive: true });
  surface.addEventListener('pointerleave', arreter);
  mouvementReduit.addEventListener('change', arreter);
  return () => {
    arreter();
    surface.removeEventListener('pointermove', suivre);
    surface.removeEventListener('pointerenter', suivre);
    surface.removeEventListener('pointerleave', arreter);
    mouvementReduit.removeEventListener('change', arreter);
    surface.style.removeProperty('--composer-reflet-x');
    surface.style.removeProperty('--composer-reflet-y');
  };
}
