/**
 * Le volet de navigation d'un document long, à la manière de Word.
 *
 * Cliquer sur « Page 28 sur 47 » y ouvre deux onglets : les pages en
 * miniature, pour aller exactement où l'on veut, et le plan des titres, pour
 * se déplacer par chapitre. Sans cela, un document de quarante-sept pages ne
 * se parcourt qu'à la molette.
 *
 * Ce fichier ne contient que la logique — découper, indenter, numéroter —
 * pour qu'elle se teste sans monter le moindre composant : ce dépôt n'a aucun
 * test de composant React et il ne faut pas en inventer l'outillage.
 */

export type EntreeDeSommaire = {
  /** Le texte du titre, tel qu'il apparaît. */
  titre: string;
  /** 1 pour H1, 2 pour H2… C'est ce qui donne l'indentation. */
  niveau: number;
  /** Le rang du titre dans le document, pour le retrouver. */
  index: number;
  /** La page où il se trouve, si on la connaît. */
  page: number;
};

/** Ce qu'un titre doit fournir pour entrer au sommaire. */
export type TitreBrut = { balise: string; texte: string; haut: number };

/**
 * Construire le sommaire.
 *
 * Un titre vide n'y entre pas : le collage depuis un traitement de texte en
 * produit — un `<h2>` qui ne contient qu'une image ou une ancre — et une
 * ligne vide dans un sommaire ne mène nulle part.
 *
 * Les niveaux sont RESSERRÉS : un document qui n'a que des H2 et des H3 les
 * voit indentés sur deux crans, pas sur trois. Word fait de même, et cela
 * évite un sommaire décalé à droite sans raison.
 */
export function construireSommaire(
  titres: TitreBrut[],
  bornesDePage: number[],
): EntreeDeSommaire[] {
  const gardes = titres
    .map((t, index) => ({ ...t, index }))
    .filter((t) => t.texte.trim().length > 0);
  const niveauxPresents = Array.from(
    new Set(gardes.map((t) => Number(t.balise.slice(1)) || 1)),
  ).sort((a, b) => a - b);
  return gardes.map((t) => ({
    titre: t.texte.trim(),
    niveau: niveauxPresents.indexOf(Number(t.balise.slice(1)) || 1) + 1,
    index: t.index,
    page: pageDe(t.haut, bornesDePage),
  }));
}

/**
 * Sur quelle page tombe une position.
 *
 * `bornesDePage` porte le BAS de chaque coupure, dans l'ordre. Une position
 * située avant la première borne est en page 1.
 */
export function pageDe(haut: number, bornesDePage: number[]): number {
  let page = 1;
  for (const borne of bornesDePage) {
    // Un demi-pixel de tolérance, pas un : avec 1, une position à 999 sur une
    // coupure à 1000 basculait déjà en page suivante.
    if (haut >= borne - 0.5) page += 1;
    else break;
  }
  return page;
}

/**
 * Les bornes hautes de chaque page, pour amener une page sous les yeux.
 *
 * La page 1 commence à 0 ; la page N+1 commence au bas de la coupure N.
 */
export function debutsDePage(bornesDePage: number[]): number[] {
  return [0, ...bornesDePage];
}
