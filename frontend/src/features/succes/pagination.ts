/**
 * Paginer une liste — pur, donc vérifiable sous vitest.
 *
 * Demande de Carlito, 17 sept. 2026 : « je ne veux pas toutes les tâches
 * dans la vue Liste, ça fait long et je dois scroller : mets-les dans des
 * pages, par exemple cinq tâches par page ». Avec un filtre projet, la Liste
 * ramenait 473 étapes d'un coup — 473 cartes vitrées montées, et la
 * molette pour retrouver la seule qu'on voulait.
 *
 * Tout ce qui décide d'une page vit ici : la borne, la tranche, la fenêtre
 * de numéros avec ses ellipses, et la flèche du clavier. Le composant
 * (`Pageur.tsx`) ne fait que peindre.
 */

/** Les tailles offertes ; la première est aussi le seuil sous lequel il n'y a rien à paginer. */
export const TAILLES_PAGE = [5, 10, 20] as const;
export type TaillePage = (typeof TAILLES_PAGE)[number];
/** Cinq, le chiffre que Carlito a donné : une page se lit sans défiler à 620 px de haut. */
export const TAILLE_PAGE_DEFAUT: TaillePage = 5;

export function estTaillePage(valeur: unknown): valeur is TaillePage {
  return (TAILLES_PAGE as readonly number[]).includes(valeur as number);
}

/** Le nombre de pages — jamais 0 : une liste vide a une page, vide. */
export function nombreDePages(total: number, parPage: number): number {
  return Math.max(1, Math.ceil(Math.max(0, total) / Math.max(1, parPage)));
}

/**
 * La page ramenée dans `[1, nbPages]`. La page 12 retenue d'une visite où
 * la liste en avait 20 pointait dans le vide après un filtre qui en laisse
 * 3 : « Aucune tâche ici » au-dessus d'un pageur qui disait le contraire.
 */
export function bornerPage(page: number, nbPages: number): number {
  if (!Number.isFinite(page)) return 1;
  return Math.min(Math.max(1, Math.trunc(page)), Math.max(1, nbPages));
}

export interface Pagination<T> {
  /** La page réellement affichée, bornée. */
  page: number;
  nbPages: number;
  total: number;
  tranche: T[];
  /** Rang du premier et du dernier élément de la tranche, à partir de 1 ; 0–0 si vide. */
  debut: number;
  fin: number;
}

export function paginer<T>(items: readonly T[], page: number, parPage: number): Pagination<T> {
  const total = items.length;
  const nbPages = nombreDePages(total, parPage);
  const courante = bornerPage(page, nbPages);
  const depuis = (courante - 1) * parPage;
  const tranche = items.slice(depuis, depuis + parPage);
  return {
    page: courante,
    nbPages,
    total,
    tranche,
    debut: tranche.length === 0 ? 0 : depuis + 1,
    fin: depuis + tranche.length,
  };
}

/**
 * La page à afficher quand la taille change, telle que le PREMIER élément
 * de la page courante reste visible : de 5 à 20 depuis la page 7 (éléments
 * 31–35), la page 2 (21–40). Revenir à la page 1 aurait fait perdre sa
 * place à qui venait de choisir « 20 par page » pour voir plus loin.
 */
export function pageApresRetaille(page: number, avant: number, apres: number): number {
  const premier = (bornerPage(page, Number.MAX_SAFE_INTEGER) - 1) * Math.max(1, avant);
  return Math.floor(premier / Math.max(1, apres)) + 1;
}

/** La page où tombe le premier élément qui satisfait `predicat` ; `null` s'il n'y en a pas. */
export function pageDe<T>(items: readonly T[], predicat: (item: T) => boolean, parPage: number): number | null {
  const index = items.findIndex(predicat);
  if (index < 0) return null;
  return Math.floor(index / Math.max(1, parPage)) + 1;
}

export const ELLIPSE = '…';
export type CaseDePageur = number | typeof ELLIPSE;

/**
 * Les numéros à montrer : la première page, la dernière, la courante et
 * ses voisines, une ellipse pour chaque trou. Un trou d'UNE page est
 * comblé par son numéro — une ellipse qui cache un seul chiffre prend la
 * même place que lui en disant moins. Sept cases au plus (1 … 49 50 51 …
 * 95) : à 32 px chacune, 224 px, ce qui tient dans les 340 px du
 * mini-panneau avec les deux flèches.
 */
export function fenetrePages(page: number, nbPages: number, voisins = 1): CaseDePageur[] {
  const total = Math.max(1, nbPages);
  const courante = bornerPage(page, total);
  const retenues = new Set<number>([1, total]);
  for (let n = courante - voisins; n <= courante + voisins; n += 1) {
    if (n >= 1 && n <= total) retenues.add(n);
  }
  const ordonnees = [...retenues].sort((a, b) => a - b);
  const cases: CaseDePageur[] = [];
  let precedente = 0;
  for (const n of ordonnees) {
    if (precedente > 0) {
      const trou = n - precedente - 1;
      if (trou === 1) cases.push(precedente + 1);
      else if (trou > 1) cases.push(ELLIPSE);
    }
    cases.push(n);
    precedente = n;
  }
  return cases;
}

export interface GardeDuClavier {
  /** Une touche de modification (⌘, Ctrl, Alt, Maj) : ce n'est pas notre raccourci. */
  modifieur: boolean;
  /** Le curseur est dans un champ : les flèches y déplacent le caret. */
  saisie: boolean;
  /** Une modale ou un menu est ouvert : les flèches lui appartiennent. */
  surcouche: boolean;
}

/**
 * La page qu'une flèche demande, ou `null` si la touche n'est pas pour
 * nous, si une garde s'y oppose, ou si l'on est déjà au bout — au bout,
 * `null` laisse la touche à qui la voulait (le défilement horizontal, rien).
 */
export function pageParFleche(touche: string, page: number, nbPages: number, garde: GardeDuClavier): number | null {
  if (touche !== 'ArrowLeft' && touche !== 'ArrowRight') return null;
  if (garde.modifieur || garde.saisie || garde.surcouche) return null;
  const courante = bornerPage(page, nbPages);
  const suivante = touche === 'ArrowLeft' ? courante - 1 : courante + 1;
  if (suivante < 1 || suivante > nbPages) return null;
  return suivante;
}
