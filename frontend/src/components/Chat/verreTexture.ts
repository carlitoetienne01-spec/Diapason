interface ZoneVitree {
  x: number;
  y: number;
  largeur: number;
  hauteur: number;
}

export interface DecoupeVitree extends ZoneVitree {
  rayon: number;
  limite?: ZoneVitree;
}

/** 12 septembre 2026 : le quadrillage CRT (z-index 9999) était dessiné
 * APRÈS le flou. Des découpes alpha réunies retirent seulement cette couche
 * au-dessus du verre, même lorsqu'un menu chevauche le compositeur. */
export function masqueTexture(largeur: number, hauteur: number, decoupes: DecoupeVitree[]): string {
  if (![largeur, hauteur].every((n) => Number.isFinite(n) && n > 0)) return 'none';
  const visibles = decoupes.filter((d) =>
    [d.x, d.y, d.largeur, d.hauteur, d.rayon].every(Number.isFinite) && d.largeur > 0 && d.hauteur > 0
    && d.x < largeur && d.y < hauteur && d.x + d.largeur > 0 && d.y + d.hauteur > 0
    && (!d.limite || (
      Object.values(d.limite).every(Number.isFinite) && d.limite.largeur > 0 && d.limite.hauteur > 0
      && Math.max(d.x, d.limite.x, 0) < Math.min(d.x + d.largeur, d.limite.x + d.limite.largeur, largeur)
      && Math.max(d.y, d.limite.y, 0) < Math.min(d.y + d.hauteur, d.limite.y + d.limite.hauteur, hauteur)
    )),
  );
  if (!visibles.length) return 'none';
  const n = (valeur: number) => Math.round(valeur * 100) / 100;
  const trous = visibles.map((d, i) => {
    const trou = `<rect x="${n(d.x)}" y="${n(d.y)}" width="${n(d.largeur)}" height="${n(d.hauteur)}" rx="${n(Math.max(0, Math.min(d.rayon, d.largeur / 2, d.hauteur / 2)))}" fill="black"/>`;
    if (!d.limite) return trou;
    const l = d.limite;
    return `<clipPath id="limite-${i}" clipPathUnits="userSpaceOnUse"><rect x="${n(l.x)}" y="${n(l.y)}" width="${n(l.largeur)}" height="${n(l.hauteur)}"/></clipPath><g clip-path="url(#limite-${i})">${trou}</g>`;
  }).join('');
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${largeur} ${hauteur}" preserveAspectRatio="none"><defs><mask id="verre" maskUnits="userSpaceOnUse" x="0" y="0" width="${largeur}" height="${hauteur}"><rect width="100%" height="100%" fill="white"/>${trous}</mask></defs><rect width="100%" height="100%" fill="white" mask="url(#verre)"/></svg>`;
  return `url("data:image/svg+xml,${encodeURIComponent(svg)}")`;
}

const surfaces = new Set<HTMLElement>();
let geometrie: readonly DecoupeVitree[] = [];
// Même mesure pour le quadrillage et le biseau ; la pluie ne relit pas le
// DOM à chaque image pour trouver la vitre qu'elle traverse.
export const lireSurfacesVitrees = (): readonly DecoupeVitree[] => geometrie;
let dernierMasque = '';
const propriete = '--diapason-decoupes-verre';

function actualiser() {
  const decoupes = [...surfaces].filter((el) => el.isConnected).map((el) => {
    const r = el.getBoundingClientRect();
    // Les cartes du panneau défilent. Leur découpe CRT doit rester dans
    // cette fenêtre, pas se promener sur l'en-tête une fois la carte sortie.
    const conteneur = el.closest<HTMLElement>('[data-verre-defilement]');
    const bord = conteneur?.getBoundingClientRect();
    return {
      x: r.left, y: r.top, largeur: r.width, hauteur: r.height,
      rayon: Number.parseFloat(getComputedStyle(el).borderTopLeftRadius) || 0,
      ...(conteneur && bord ? { limite: {
        x: bord.left + conteneur.clientLeft,
        y: bord.top + conteneur.clientTop,
        largeur: conteneur.clientWidth,
        hauteur: conteneur.clientHeight,
      } } : {}),
    };
  });
  const masque = masqueTexture(window.innerWidth, window.innerHeight, decoupes);
  geometrie = decoupes;
  if (masque === dernierMasque) return;
  document.documentElement.style.setProperty(propriete, masque);
  dernierMasque = masque;
}

export function inscrireSurfaceVitree(surface: HTMLElement): () => void {
  surfaces.add(surface);
  const observation = new ResizeObserver(actualiser);
  // Le panneau peut garder ses 720 px tout en se déplaçant à l'ouverture
  // d'une barre latérale. Observer sa seule taille laissait le trou derrière.
  for (let parent: HTMLElement | null = surface; parent; parent = parent.parentElement) {
    observation.observe(parent);
  }
  if (surfaces.size === 1) {
    window.addEventListener('resize', actualiser);
    window.addEventListener('scroll', actualiser, true);
  }
  actualiser();
  return () => {
    observation.disconnect();
    surfaces.delete(surface);
    if (surfaces.size) actualiser();
    else {
      window.removeEventListener('resize', actualiser);
      window.removeEventListener('scroll', actualiser, true);
      document.documentElement.style.removeProperty(propriete);
      dernierMasque = '';
      geometrie = [];
    }
  };
}
