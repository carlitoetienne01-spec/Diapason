import type {
  SuccesNoteDocLang,
  SuccesNotePageBackground,
  SuccesNotePageFormat,
  SuccesNotePageMargins,
  SuccesNotePageOrientation,
  SuccesNotePageSize,
} from './types';

/**
 * La liste d'avant : elle MÉLANGEAIT deux axes que Word garde séparés.
 *
 * « A4 » et « Lettre US » sont des tailles de papier ; « Page étroite »,
 * « Marges minimales » et « Lecture » sont des réglages de marges ; « A4
 * paysage » est une orientation. Impossible, dans cette liste, de dire sur
 * quel papier « marges minimales » s'applique, ni de mettre une A5 en
 * paysage. Conservée parce que les notes déjà enregistrées la portent —
 * `decomposeLegacyFormat` la traduit à la lecture.
 */
export const NOTE_PAGE_FORMATS: Array<{ id: SuccesNotePageFormat; label: string }> = [
  { id: 'a4', label: 'A4' },
  { id: 'letter', label: 'Lettre US' },
  { id: 'a5', label: 'A5' },
  { id: 'wide', label: 'A4 paysage' },
  { id: 'narrow', label: 'Page étroite' },
  { id: 'full', label: 'Marges minimales' },
  { id: 'reading', label: 'Lecture' },
];

/**
 * Axe 1 — la taille du papier, menu « Taille » de Word.
 *
 * Cinq entrées, pas quinze : A3, Tabloid et B5 sont des formats d'imprimerie
 * qu'un éditeur de notes n'a pas à proposer (§5, une capacité que rien
 * n'exerce est une promesse en attente).
 */
export const NOTE_PAGE_SIZES: Array<{
  id: SuccesNotePageSize;
  label: string;
  w: string;
  h: string;
}> = [
  { id: 'a4', label: 'A4  ·  21 × 29,7 cm', w: '210mm', h: '297mm' },
  { id: 'letter', label: 'Lettre US  ·  21,6 × 27,9 cm', w: '8.5in', h: '11in' },
  { id: 'legal', label: 'Legal  ·  21,6 × 35,6 cm', w: '8.5in', h: '14in' },
  { id: 'a5', label: 'A5  ·  14,8 × 21 cm', w: '148mm', h: '210mm' },
  { id: 'executive', label: 'Executive  ·  18,4 × 26,7 cm', w: '7.25in', h: '10.5in' },
];

/** Axe 2 — l'orientation. Elle échange les deux dimensions, et rien d'autre. */
export const NOTE_PAGE_ORIENTATIONS: Array<{
  id: SuccesNotePageOrientation;
  label: string;
}> = [
  { id: 'portrait', label: 'Portrait' },
  { id: 'paysage', label: 'Paysage' },
];

/**
 * Axe 3 — les marges, menu « Marges » de Word, aux valeurs exactes.
 *
 * Écrites en POUCES parce que les préréglages de Word en sont : 1, 0,5, 0,75
 * et 2 pouces donnent 96, 48, 72 et 192 px entiers à 96 dpi. Les écrire en
 * centimètres — ce qu'affiche l'interface française de Word — introduirait
 * une dérive de 0,19 px sur « Modérées ». L'étiquette, elle, reste en
 * centimètres, parce que c'est ce que Carlito lit.
 */
export const NOTE_PAGE_MARGINS: Array<{
  id: SuccesNotePageMargins;
  label: string;
  t: string;
  r: string;
  b: string;
  l: string;
}> = [
  {
    id: 'normales',
    label: 'Normales  ·  2,54 cm',
    t: '1in',
    r: '1in',
    b: '1in',
    l: '1in',
  },
  {
    id: 'etroites',
    label: 'Étroites  ·  1,27 cm',
    t: '0.5in',
    r: '0.5in',
    b: '0.5in',
    l: '0.5in',
  },
  {
    id: 'moderees',
    label: 'Modérées  ·  2,54 / 1,91 cm',
    t: '1in',
    r: '0.75in',
    b: '1in',
    l: '0.75in',
  },
  {
    id: 'larges',
    label: 'Larges  ·  2,54 / 5,08 cm',
    t: '1in',
    r: '2in',
    b: '1in',
    l: '2in',
  },
];

export type MiseEnPage = {
  size: SuccesNotePageSize;
  orientation: SuccesNotePageOrientation;
  margins: SuccesNotePageMargins;
};

/**
 * Traduire une valeur héritée en trois axes.
 *
 * Deux des sept n'existaient chez Word sous aucune forme : « A5 » portait des
 * marges de 15 mm et « Lecture » de 32 mm, deux valeurs inventées. Elles
 * deviennent les préréglages les plus proches — Normales et Larges — ce qui
 * déplace légèrement la mise en page de ces notes-là. C'est assumé : le but
 * est justement d'avoir les valeurs de Word.
 */
export function decomposeLegacyFormat(format: SuccesNotePageFormat): MiseEnPage {
  switch (format) {
    case 'letter':
      return { size: 'letter', orientation: 'portrait', margins: 'normales' };
    case 'a5':
      return { size: 'a5', orientation: 'portrait', margins: 'normales' };
    case 'wide':
      return { size: 'a4', orientation: 'paysage', margins: 'normales' };
    case 'narrow':
      // Le papier « Page étroite » était un Executive de 7,25 × 10,5 po avec
      // 0,75 po sur les quatre côtés — Word met 1 po en haut et en bas.
      return { size: 'executive', orientation: 'portrait', margins: 'moderees' };
    case 'full':
      // « Marges minimales » = 12,7 mm partout = le préréglage Étroites.
      return { size: 'a4', orientation: 'portrait', margins: 'etroites' };
    case 'reading':
      return { size: 'a4', orientation: 'portrait', margins: 'larges' };
    case 'a4':
    default:
      return { size: 'a4', orientation: 'portrait', margins: 'normales' };
  }
}

/** La boîte d'une mise en page, prête pour le CSS. */
export function boitePage(mise: MiseEnPage) {
  const papier = NOTE_PAGE_SIZES.find((x) => x.id === mise.size) ?? NOTE_PAGE_SIZES[0];
  const marges =
    NOTE_PAGE_MARGINS.find((x) => x.id === mise.margins) ?? NOTE_PAGE_MARGINS[0];
  const paysage = mise.orientation === 'paysage';
  return {
    // Le paysage échange les DEUX dimensions. Ne changer que la largeur
    // donnerait une feuille qui n'est plus un format de papier.
    w: paysage ? papier.h : papier.w,
    h: paysage ? papier.w : papier.h,
    t: marges.t,
    r: marges.r,
    b: marges.b,
    l: marges.l,
  };
}

/** La mise en page d'une note, quels que soient les champs qu'elle porte. */
export function miseEnPageDeLaNote(note: {
  pageFormat?: SuccesNotePageFormat;
  pageSize?: SuccesNotePageSize;
  pageOrientation?: SuccesNotePageOrientation;
  pageMargins?: SuccesNotePageMargins;
}): MiseEnPage {
  const herite = decomposeLegacyFormat(note.pageFormat ?? 'a4');
  return {
    size: note.pageSize ?? herite.size,
    orientation: note.pageOrientation ?? herite.orientation,
    margins: note.pageMargins ?? herite.margins,
  };
}

export const NOTE_PAGE_BACKGROUNDS: Array<{ id: SuccesNotePageBackground; label: string }> = [
  { id: 'default', label: 'Blanc' },
  { id: 'lined', label: 'Ligné' },
  { id: 'grid', label: 'Quadrillé' },
  { id: 'sepia', label: 'Sépia' },
  { id: 'dark', label: 'Sombre' },
];

export const NOTE_FONTS = [
  'Press Start 2P',
  'VT323',
  'Special Elite',
  'Inter',
  'Poppins',
  'Roboto',
  'Lato',
  'Open Sans',
  'Merriweather',
  'Montserrat',
  'Source Serif 4',
  'Nunito',
  'Playfair Display',
] as const;

export const NOTE_DOC_LANGS: Array<{ id: SuccesNoteDocLang; label: string }> = [
  { id: 'fr', label: 'Français (France)' },
  { id: 'ht', label: 'Kreyòl Ayisyen' },
];

/**
 * Les tailles de Word, en POINTS.
 *
 * Ce menu proposait sept crans nommés « Très petit » à « Max », qui étaient
 * les valeurs 1 à 7 de `execCommand('fontSize')`. Il était mort de bout en
 * bout, pour deux raisons indépendantes :
 *
 * 1. `fontSize` émet `<font size="N">`, et `size` n'est PAS dans la liste
 *    d'attributs autorisés de `noteSanitize.ts` — la balise survivait à
 *    l'affichage et perdait son attribut à la première sauvegarde.
 * 2. L'échelle 1-7 se résout sur la racine à 16 px : « Normal » (3) valait
 *    donc 16 px alors que le corps de la note est à 15 px. Aucun des sept
 *    crans ne rendait la taille courante.
 *
 * Les points sont ce que Word affiche, et un style inline les exprime
 * exactement. `style` est déjà autorisé par le nettoyeur : aucune ouverture
 * de la liste blanche n'est nécessaire.
 */
export const NOTE_FONT_SIZES = [8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 36, 48, 72];

/** La déclaration à poser, séparée pour être testable sans DOM. */
export function styleDeTaille(points: number): string {
  return `font-size:${points}pt`;
}

/**
 * Les points d'une longueur CSS lue en pixels.
 *
 * `getComputedStyle` rend toujours des PIXELS, jamais l'unité écrite. La barre
 * d'outils, elle, parle en points comme Word. 1 pt = 1/72 po et 1 px = 1/96 po,
 * donc pt = px × 0,75 — et il faut arrondir : 11 pt vaut 14,6667 px, dont le
 * retour donne 11,000025.
 *
 * Une décimale est gardée : Word affiche « 10,5 », et arrondir à l'entier
 * ferait dire à la barre une taille que le texte n'a pas.
 */
export function pointsDepuisPx(px: number): number | null {
  if (!Number.isFinite(px) || px <= 0) return null;
  return Math.round(px * 0.75 * 10) / 10;
}

/**
 * Ce que la liste doit afficher pour une sélection.
 *
 * Une seule taille : on la dit. Plusieurs : on ne dit RIEN — c'est ce que fait
 * Word, et c'est la seule réponse honnête. Afficher la première, ou la plus
 * fréquente, serait annoncer une taille que le reste de la sélection n'a pas.
 */
export function tailleAffichee(tailles: readonly (number | null)[]): number | null {
  const vues = new Set<number>();
  for (const t of tailles) {
    if (t === null) return null;
    vues.add(t);
    if (vues.size > 1) return null;
  }
  return vues.size === 1 ? [...vues][0] : null;
}

export function noteFontCss(fontFamily: string) {
  const name = fontFamily.replace(/'/g, "\\'");
  const stacks: Record<string, string> = {
    'Press Start 2P': `'Press Start 2P', ui-monospace, monospace`,
    VT323: `'VT323', ui-monospace, monospace`,
    'Special Elite': `'Special Elite', 'Courier New', ui-monospace, monospace`,
    Inter: `'Inter', ui-sans-serif, system-ui, sans-serif`,
    Poppins: `'Poppins', ui-sans-serif, system-ui, sans-serif`,
    Roboto: `'Roboto', ui-sans-serif, system-ui, sans-serif`,
    Lato: `'Lato', ui-sans-serif, system-ui, sans-serif`,
    'Open Sans': `'Open Sans', ui-sans-serif, system-ui, sans-serif`,
    Merriweather: `'Merriweather', ui-serif, Georgia, serif`,
    Montserrat: `'Montserrat', ui-sans-serif, system-ui, sans-serif`,
    'Source Serif 4': `'Source Serif 4', ui-serif, Georgia, serif`,
    Nunito: `'Nunito', ui-sans-serif, system-ui, sans-serif`,
    'Playfair Display': `'Playfair Display', ui-serif, Georgia, serif`,
  };
  return stacks[fontFamily] ?? `'${name}', ui-sans-serif, system-ui, sans-serif`;
}
