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

/**
 * Le masque de la couche CRT : plein partout, troué à l'endroit des vitres.
 *
 * 12 septembre 2026 : le quadrillage CRT (z-index 9999) était dessiné APRÈS
 * le flou ; des découpes alpha réunies retirent seulement cette couche
 * au-dessus du verre, même lorsqu'un menu chevauche le compositeur.
 *
 * 17 septembre 2026 : ces découpes étaient un SVG en data-URI, régénéré à
 * CHAQUE événement de défilement. Une nouvelle image à décoder par tick :
 * le temps du décodage, le quadrillage repassait sur les cartes (elles
 * pâlissaient), puis le trou revenait — « le graphisme scintille et devient
 * pâle quand je scroll » (Carlito). Le masque est désormais fait de
 * DÉGRADÉS CSS : aucune image, une liste de calques dont seules les
 * positions bougent. Chaque trou arrondi = une colonne, une rangée et
 * jusqu'à quatre disques de coin, réunis (`add`) sous un calque plein qui
 * les soustrait (`subtract` = source-out). Une tranche coupée par la
 * fenêtre de défilement perd son arrondi de ce côté : la colonne ou la
 * rangée y va jusqu'au bord.
 */
export interface MasqueVerre {
  image: string;
  taille: string;
  position: string;
  composite: string;
  compositeWebkit: string;
}

interface Calque {
  image: string;
  x: number;
  y: number;
  largeur: number;
  hauteur: number;
}

const PLEIN = 'linear-gradient(#000 0 0)';
const DISQUE = 'radial-gradient(circle closest-side, #000 98%, transparent 100%)';

function calquesDuTrou(d: DecoupeVitree): Calque[] {
  let x0 = d.x;
  let y0 = d.y;
  let x1 = d.x + d.largeur;
  let y1 = d.y + d.hauteur;
  let haut = false;
  let bas = false;
  let gauche = false;
  let droite = false;
  if (d.limite) {
    const l = d.limite;
    if (l.x > x0) { x0 = l.x; gauche = true; }
    if (l.y > y0) { y0 = l.y; haut = true; }
    if (l.x + l.largeur < x1) { x1 = l.x + l.largeur; droite = true; }
    if (l.y + l.hauteur < y1) { y1 = l.y + l.hauteur; bas = true; }
  }
  const largeur = x1 - x0;
  const hauteur = y1 - y0;
  if (largeur <= 0 || hauteur <= 0) return [];
  const r = Math.max(0, Math.min(d.rayon, largeur / 2, hauteur / 2));
  const rg = gauche ? 0 : r;
  const rd = droite ? 0 : r;
  const rh = haut ? 0 : r;
  const rb = bas ? 0 : r;
  const calques: Calque[] = [
    { image: PLEIN, x: x0 + rg, y: y0, largeur: largeur - rg - rd, hauteur },
    { image: PLEIN, x: x0, y: y0 + rh, largeur, hauteur: hauteur - rh - rb },
  ];
  if (r > 0) {
    const coins: Array<[boolean, number, number]> = [
      [!haut && !gauche, x0, y0],
      [!haut && !droite, x1 - 2 * r, y0],
      [!bas && !droite, x1 - 2 * r, y1 - 2 * r],
      [!bas && !gauche, x0, y1 - 2 * r],
    ];
    for (const [arrondi, cx, cy] of coins) {
      if (arrondi) calques.push({ image: DISQUE, x: cx, y: cy, largeur: 2 * r, hauteur: 2 * r });
    }
  }
  return calques.filter((c) => c.largeur > 0 && c.hauteur > 0);
}

export function masqueTexture(largeur: number, hauteur: number, decoupes: DecoupeVitree[]): MasqueVerre | null {
  if (![largeur, hauteur].every((n) => Number.isFinite(n) && n > 0)) return null;
  const visibles = decoupes.filter((d) =>
    [d.x, d.y, d.largeur, d.hauteur, d.rayon].every(Number.isFinite) && d.largeur > 0 && d.hauteur > 0
    && d.x < largeur && d.y < hauteur && d.x + d.largeur > 0 && d.y + d.hauteur > 0
    && (!d.limite || (
      Object.values(d.limite).every(Number.isFinite) && d.limite.largeur > 0 && d.limite.hauteur > 0
      && Math.max(d.x, d.limite.x, 0) < Math.min(d.x + d.largeur, d.limite.x + d.limite.largeur, largeur)
      && Math.max(d.y, d.limite.y, 0) < Math.min(d.y + d.hauteur, d.limite.y + d.limite.hauteur, hauteur)
    )),
  );
  const calques = visibles.flatMap(calquesDuTrou);
  if (!calques.length) return null;
  const n = (valeur: number) => `${Math.round(valeur * 100) / 100}px`;
  // Le calque plein est PREMIER (au-dessus) : il se composite en dernier,
  // en soustrayant la réunion des trous qui se sont additionnés dessous.
  return {
    image: [PLEIN, ...calques.map((c) => c.image)].join(', '),
    taille: ['100% 100%', ...calques.map((c) => `${n(c.largeur)} ${n(c.hauteur)}`)].join(', '),
    position: ['0 0', ...calques.map((c) => `${n(c.x)} ${n(c.y)}`)].join(', '),
    composite: ['subtract', ...calques.map(() => 'add')].join(', '),
    compositeWebkit: ['source-out', ...calques.map(() => 'source-over')].join(', '),
  };
}

const surfaces = new Set<HTMLElement>();
let geometrie: readonly DecoupeVitree[] = [];
// Même mesure pour le quadrillage et le biseau ; la pluie ne relit pas le
// DOM à chaque image pour trouver la vitre qu'elle traverse.
export const lireSurfacesVitrees = (): readonly DecoupeVitree[] => geometrie;
let dernierMasque = '';
const PROPRIETES: Array<[string, keyof MasqueVerre]> = [
  ['--diapason-verre-masque', 'image'],
  ['--diapason-verre-taille', 'taille'],
  ['--diapason-verre-position', 'position'],
  ['--diapason-verre-composite', 'composite'],
  ['--diapason-verre-composite-webkit', 'compositeWebkit'],
];

function poserMasque(masque: MasqueVerre | null) {
  const style = document.documentElement.style;
  for (const [nom, cle] of PROPRIETES) {
    if (masque) style.setProperty(nom, masque[cle]);
    else style.removeProperty(nom);
  }
}

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
  const empreinte = masque ? `${masque.image}|${masque.taille}|${masque.position}` : 'none';
  if (empreinte === dernierMasque) return;
  poserMasque(masque);
  dernierMasque = empreinte;
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
      poserMasque(null);
      dernierMasque = '';
      geometrie = [];
    }
  };
}
