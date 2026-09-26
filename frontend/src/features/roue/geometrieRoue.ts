// La géométrie de la roue du téléphone — toute, et rien d'autre.
//
// 26/09/2026, chantier de la fluidité (lot 3). La roue pose les pages sur un
// arc dont le centre est HORS de l'écran, du côté de la main qui la tient ;
// l'élément au milieu de l'écran est « allumé ». Tout ce qui décide d'un
// pixel ou d'une milliseconde vit ici, en fonctions pures : le composant
// (RoueNavigation.tsx) ne fait qu'écrire `transform` et `opacity`, jamais une
// propriété qui relance la mise en page — c'est ce qui tient 60 images/s sur
// un téléphone de milieu de gamme (banc ×4, voir le commit).
//
// L'unité de rotation est l'ÉLÉMENT : `rotation = 3` met le quatrième au
// centre ; `3,4` le montre en chemin vers le cinquième.

export type Cote = 'droite' | 'gauche';

/**
 * Longueur d'arc entre deux éléments. 64 px : la pastille allumée fait
 * 52 px (40 × 1,3) et sa voisine 40 ; leurs centres à 64 px laissent 18 px
 * entre elles, plus que les ~45 px d'un doigt n'en débordent de chaque cible
 * de 40 px (index.css). À 48 px, les deux se touchaient.
 */
export const ECART_PX = 64;

/** Le rayon de l'arc suit la hauteur utile, borné : 0,6 × la hauteur donne
 *  une courbe lisible à 812 px ; sous 300 px l'arc devient un cercle serré
 *  où les noms se chevauchent, au-delà de 620 (tablette) une droite. */
export const RAYON_MIN_PX = 300;
export const RAYON_MAX_PX = 620;
export const PART_RAYON = 0.6;

/** Où tombe la pastille allumée : 38 % de la largeur depuis le bord de la
 *  roue (143 px à 375 px), ce qui laisse ~190 px au nom le plus long
 *  (« Vue d'ensemble du système » en 17 px gras) sans le couper. */
export const PART_RETRAIT = 0.38;

/** La bande du bord où un glissé ouvre la roue : 16 px, sous le pouce sans
 *  couvrir les contrôles, qui gardent 16 px de marge (index.css). */
export const BORD_PX = 16;

/** Ce qu'un glissé doit parcourir vers l'intérieur pour ouvrir la roue :
 *  12 px, au-dessus des 8 px qui distinguent un toucher d'un glissé
 *  (`TOUCHER_PX`) — un pouce posé au bord qui tremble n'ouvre rien. */
export const OUVERTURE_PX = 12;

/** Sous 8 px de déplacement, un relâché est un toucher, pas un choix. */
export const TOUCHER_PX = 8;

/** L'inertie projette la vitesse sur 120 ms, trois éléments au plus. Un
 *  lancer vif du pouce (~20 éléments/s) avance ainsi de 2,4 éléments ; sur
 *  250 ms il en ferait 5 — un tiers de la roue (17 éléments) — et ne se
 *  viserait plus. « Courte », disait la décision du 26/09/2026. */
export const INERTIE_S = 0.12;
export const INERTIE_MAX = 3;

/** L'aimantation dure de 150 à 250 ms (décision du 26/09/2026). */
export const DUREE_MIN_MS = 150;
export const DUREE_MAX_MS = 250;

/** Ce que perd l'opacité par élément d'écart : le sixième voisin s'éteint. */
export const ESTOMPE_PAR_ELEMENT = 0.17;

/** La pastille allumée grandit de 30 %. */
export const GROSSISSEMENT = 0.3;

/** Au-delà du bout de la roue, le doigt tire un ressort : 0,35 élément au plus. */
export const RESSORT_MAX = 0.35;

export type Geometrie = {
  largeur: number;
  hauteur: number;
  /** Le haut de la zone de la roue (sous le titre « Aller à »). */
  haut: number;
  /** Le bas de la zone de la roue. */
  bas: number;
  cote: Cote;
  rayon: number;
  /** Centre de l'arc, hors de l'écran, côté roue (coordonnée x côté DROIT ;
   *  le côté gauche est son miroir, appliqué par `placerElement`). */
  centreX: number;
  centreY: number;
  /** Angle entre deux éléments, en radians. */
  pas: number;
  /** Abscisse de la pastille allumée (côté réel, miroir compris). */
  xAllume: number;
};

function borner(v: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, v));
}

export function geometrieRoue(entree: {
  largeur: number;
  hauteur: number;
  cote: Cote;
  haut?: number;
  bas?: number;
}): Geometrie {
  const { largeur, hauteur, cote } = entree;
  const haut = entree.haut ?? 0;
  const bas = entree.bas ?? hauteur;
  const utile = Math.max(1, bas - haut);
  const rayon = borner(utile * PART_RAYON, RAYON_MIN_PX, RAYON_MAX_PX);
  const retrait = largeur * PART_RETRAIT;
  const xDroite = largeur - retrait;
  return {
    largeur,
    hauteur,
    haut,
    bas,
    cote,
    rayon,
    centreX: xDroite + rayon,
    centreY: haut + utile / 2,
    pas: ECART_PX / rayon,
    xAllume: cote === 'droite' ? xDroite : largeur - xDroite,
  };
}

export type Placement = {
  /** Centre de la pastille. */
  x: number;
  y: number;
  /** Écart à l'élément allumé, en éléments (signé). */
  distance: number;
  opacite: number;
  /** Échelle de la pastille. */
  echelle: number;
  allume: boolean;
  /** Faux quand l'élément est hors de la zone : il ne se touche pas. */
  visible: boolean;
};

/** 1 au cœur de la zone, 0 à ses bords, sur 40 px : un nom ne passe pas
 *  sous le titre « Aller à » en restant lisible par-dessus. */
function attenuationAuxBords(y: number, haut: number, bas: number): number {
  const fondu = 40;
  return borner(Math.min(y - haut, bas - y) / fondu, 0, 1);
}

export function placerElement(index: number, rotation: number, g: Geometrie): Placement {
  const distance = index - rotation;
  const angle = distance * g.pas;
  // Au-delà d'un quart de tour, l'arc repart vers le centre : on n'y pose rien.
  const surLArc = Math.abs(angle) < Math.PI / 2;
  const xDroite = g.centreX - g.rayon * Math.cos(angle);
  const x = g.cote === 'droite' ? xDroite : g.largeur - xDroite;
  const y = g.centreY + g.rayon * Math.sin(angle);
  const ecart = Math.abs(distance);
  const opacite = surLArc
    ? borner(1 - ESTOMPE_PAR_ELEMENT * ecart, 0, 1) * attenuationAuxBords(y, g.haut, g.bas)
    : 0;
  return {
    x,
    y,
    distance,
    opacite,
    echelle: 1 + GROSSISSEMENT * Math.max(0, 1 - ecart),
    allume: ecart < 0.5,
    visible: opacite > 0.05,
  };
}

/** L'élément allumé pour une rotation donnée, toujours dans la liste. */
export function indexAllume(rotation: number, n: number): number {
  if (n <= 0) return 0;
  return borner(Math.round(rotation), 0, n - 1);
}

/** Le ressort au-delà des bouts : le doigt continue, la roue résiste. */
function ressort(depassement: number): number {
  return (RESSORT_MAX * depassement) / (1 + depassement);
}

/**
 * La rotation après un glissé vertical de `dyPx` depuis `depart`. Le pouce
 * qui DESCEND fait descendre les éléments : c'est l'élément du dessus qui
 * vient au centre (la rotation diminue), comme une liste qu'on fait défiler.
 */
export function rotationDuGlisse(depart: number, dyPx: number, n: number): number {
  const brute = depart - dyPx / ECART_PX;
  const fin = Math.max(0, n - 1);
  if (brute < 0) return -ressort(-brute);
  if (brute > fin) return fin + ressort(brute - fin);
  return brute;
}

/**
 * La vitesse du glissé, en éléments par seconde (positive quand la rotation
 * augmente), lue sur les 100 dernières millisecondes d'échantillons.
 */
export function vitesseDuGlisse(echantillons: readonly { t: number; y: number }[]): number {
  if (echantillons.length < 2) return 0;
  const dernier = echantillons[echantillons.length - 1];
  let premier = echantillons[echantillons.length - 2];
  for (let i = echantillons.length - 2; i >= 0; i -= 1) {
    if (dernier.t - echantillons[i].t > 100) break;
    premier = echantillons[i];
  }
  const dt = (dernier.t - premier.t) / 1000;
  if (dt <= 0) return 0;
  return -(dernier.y - premier.y) / ECART_PX / dt;
}

/**
 * Où la roue s'aimante au relâché : l'élément le plus proche de la position
 * projetée par l'inertie. Sans mouvement (prefers-reduced-motion), pas
 * d'inertie : l'élément le plus proche du doigt, tout de suite.
 */
export function cibleAimantation(
  rotation: number,
  vitesse: number,
  n: number,
  mouvementReduit: boolean,
): number {
  const elan = mouvementReduit ? 0 : borner(vitesse * INERTIE_S, -INERTIE_MAX, INERTIE_MAX);
  return indexAllume(rotation + elan, n);
}

/** La durée de l'aimantation : 150 ms pour un cran, 250 pour un long trajet,
 *  0 sans mouvement (bascule directe). */
export function dureeAimantation(depuis: number, vers: number, mouvementReduit: boolean): number {
  if (mouvementReduit) return 0;
  return borner(DUREE_MIN_MS + 35 * Math.abs(vers - depuis), DUREE_MIN_MS, DUREE_MAX_MS);
}

/** La rotation à l'instant `ecouleMs` d'une aimantation (sortie cubique). */
export function rotationAuTemps(depuis: number, vers: number, ecouleMs: number, dureeMs: number): number {
  if (dureeMs <= 0 || ecouleMs >= dureeMs) return vers;
  const t = borner(ecouleMs / dureeMs, 0, 1);
  const lisse = 1 - (1 - t) ** 3;
  return depuis + (vers - depuis) * lisse;
}

/** Le doigt s'est-il posé dans la bande du bord de la roue ? */
export function commenceAuBord(x: number, largeur: number, cote: Cote): boolean {
  return cote === 'droite' ? x >= largeur - BORD_PX : x <= BORD_PX;
}

/** La hauteur de la bande, depuis le bas : 200 px, les 200 dp qu'Android
 *  accorde au plus par bord (verbe `bordRoue`) ; plus haut, le glissé reste
 *  le « retour » du système. */
export const BANDE_BORD_PX = 200;

/** Le départ d'un glissé qui peut ouvrir la roue : au bord, dans les 200 px du bas. */
export function commenceDansLaBande(
  x: number,
  y: number,
  largeur: number,
  hauteur: number,
  cote: Cote,
): boolean {
  return commenceAuBord(x, largeur, cote) && y >= hauteur - BANDE_BORD_PX;
}

/**
 * Que faire d'un glissé parti de la bande, à chaque mouvement du doigt.
 * 26/09/2026, contre-épreuve : la bande était un élément fixe de 16 × 200 px
 * posé PAR-DESSUS la page (`touch-action: none`) ; un glissé vertical qui y
 * commençait ne faisait plus défiler la page (scrollTop 0 sur 12 des 17
 * pages) et le bord droit d'un bouton pleine largeur ne se touchait plus.
 * Plus rien n'est posé sur la page : on écoute, sans jamais retenir, et un
 * départ vertical reste un défilement.
 */
export function decisionDuBord(dx: number, dy: number, cote: Cote): 'ouvrir' | 'attendre' | 'laisser' {
  if (glisseOuvreLaRoue(dx, dy, cote)) return 'ouvrir';
  const versLInterieur = cote === 'droite' ? -dx : dx;
  // Le doigt est parti ailleurs que vers l'intérieur : c'est un défilement
  // (ou un retour du système), plus jamais une ouverture.
  if (Math.abs(dy) >= TOUCHER_PX && Math.abs(dy) >= versLInterieur) return 'laisser';
  if (versLInterieur <= -TOUCHER_PX) return 'laisser';
  return 'attendre';
}

/**
 * Un glissé parti du bord ouvre-t-il la roue ? Vers l'intérieur, d'au moins
 * 12 px, et plus horizontal que vertical — un pouce qui fait défiler une
 * liste le long du bord ne l'ouvre pas.
 */
export function glisseOuvreLaRoue(dx: number, dy: number, cote: Cote): boolean {
  const versLInterieur = cote === 'droite' ? -dx : dx;
  return versLInterieur >= OUVERTURE_PX && versLInterieur > Math.abs(dy);
}

/**
 * Ce que fait le relâché. En geste CONTINU (posé au bord ou sur le bouton,
 * glissé, relâché), le relâché choisit : la page allumée s'ouvre — mais
 * seulement si le pouce a tourné la roue ; sinon on l'a juste ouverte pour
 * regarder, et elle reste. Dans la roue déjà ouverte, le relâché ne fait
 * que s'aimanter : c'est le toucher qui ouvre.
 */
export function issueDuRelache(entree: { continu: boolean; deplacementPx: number }): 'ouvrir' | 'garder' {
  return entree.continu && entree.deplacementPx >= TOUCHER_PX ? 'ouvrir' : 'garder';
}

/**
 * Ce que la coquille reçoit pour retirer un bord aux gestes d'Android (verbe
 * `bordRoue`, lib/natif.ts). Un seul champ, le côté de la roue ; la coquille
 * refuse toute autre valeur.
 */
export function chargeBordRoue(cote: Cote): { cote: Cote } {
  return { cote };
}
