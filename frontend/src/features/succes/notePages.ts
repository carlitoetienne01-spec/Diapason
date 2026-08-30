import { stripNoteHtml } from './noteSanitize';
import type { SuccesNotePageFormat } from './types';

/** Marker inserted by the editor's "Saut de page" button. */
export const PAGE_BREAK_CLASS = 'succes-page-break';
export const PAGE_BREAK_HTML = `<hr class="${PAGE_BREAK_CLASS}"><p><br></p>`;

/** Espace entre deux feuilles, comme le gris de Word en mode Page (~20–30 px). */
export const PAGE_GUTTER_PX = 28;

/** Espacements insérés pour paginer ; jamais enregistrés avec la note. */
export const OVERFLOW_GAP_CLASS = 'succes-overflow-gap';

/**
 * Characters a page of each format holds at the default type size. Used when
 * we cannot measure the editor (folder icon, footer). Visual pagination in
 * the editor is driven by page height, not these constants.
 */
const PAGE_CAPACITY: Record<SuccesNotePageFormat, number> = {
  a4: 2800,
  letter: 2800,
  a5: 1400,
  wide: 1900,
  narrow: 2200,
  full: 3000,
  reading: 2400,
};

const BREAK_SPLIT = /<hr[^>]*class=["'][^"']*succes-page-break[^"']*["'][^>]*>/gi;

/**
 * Une ESTIMATION du nombre de pages, à partir du volume de texte.
 *
 * Réservée à la LISTE des notes, où rien n'est monté et où l'on ne peut donc
 * rien mesurer. Le pied de page de l'éditeur, lui, doit prendre le compte
 * RÉEL que l'éditeur remonte : les deux ne coïncident pas, et le 30 août 2026
 * une note affichait « 20 pages » sous un éditeur qui en dessinait 43. Un
 * compte de caractères ne sait rien des titres, des tableaux, des images ni
 * des sauts que la mise en page impose (§100).
 */
export function countNotePages(
  content: string,
  pageFormat: SuccesNotePageFormat = 'a4',
): number {
  const capacity = PAGE_CAPACITY[pageFormat] ?? PAGE_CAPACITY.a4;
  const chunks = String(content || '').split(BREAK_SPLIT);
  let pages = 0;
  for (const chunk of chunks) {
    const length = stripNoteHtml(chunk).length;
    pages += Math.max(1, Math.ceil(length / capacity));
  }
  return Math.max(1, pages);
}

export function cssLengthToPx(value: string, fallback: number): number {
  const raw = value.trim();
  const amount = parseFloat(raw);
  if (!Number.isFinite(amount)) return fallback;
  if (raw.endsWith('px')) return amount;
  if (raw.endsWith('mm')) return amount * (96 / 25.4);
  if (raw.endsWith('cm')) return amount * (96 / 2.54);
  if (raw.endsWith('in')) return amount * 96;
  return amount;
}

export type PageBlockKind = 'break' | 'heading' | 'block';

export type PageBlock = {
  top: number;
  height: number;
  kind: PageBlockKind;
  /**
   * Haut de chaque ligne du bloc, dans le même repère que `top`. Absent ou
   * trop court : le bloc est INSÉCABLE et part d'un seul tenant.
   */
  lines?: number[];
};

export type OverflowGap = {
  /** Index du bloc dans la liste mesurée (les cales n'y figurent pas). */
  beforeIndex: number;
  /**
   * Ligne AVANT laquelle couper, à l'intérieur de ce bloc. Absent : la coupe
   * est devant le bloc entier. C'est toute la différence entre « Word » et ce
   * que ce fichier faisait jusqu'au 30 août 2026.
   */
  atLine?: number;
  /** Papier blanc laissé en bas de la boîte de contenu courante. */
  fill: number;
  /**
   * `sheet` — reste + marge basse + gouttière du bureau + marge haute.
   * `fill`  — reste + marge basse ; un `<hr>` manuel fait office de gouttière.
   */
  mode: 'sheet' | 'fill';
};

/**
 * Veuves et orphelines, comme Word : au moins DEUX lignes de chaque côté
 * d'une coupe. Microsoft l'active par défaut dans le style Normal.
 *
 * Conséquence arithmétique, qu'il vaut mieux écrire que redécouvrir : un
 * paragraphe de deux ou trois lignes ne se coupe JAMAIS (1+2 et 2+1 laissent
 * une ligne seule). Le premier coupable est celui de quatre lignes, en 2+2.
 */
const MIN_LIGNES = 2;

/**
 * Combien de blocs « Paragraphe solidaire » peut remonter.
 *
 * Le code d'avant remontait SANS BORNE tant que le bloc précédent faisait
 * moins de 52 px. Mesuré le 30 août 2026 sur une vraie note de Carlito :
 * 887 blocs sur 926 passaient ce seuil — 95,8 % du document — et la remontée
 * atteignait le premier bloc. Résultat, 88 cales dont 43 collées les unes aux
 * autres, une série de 31 d'affilée totalisant 462 968 px : quatre cent
 * cinquante pages blanches consécutives, pour 37 000 px de texte.
 *
 * Trois bornes remplacent le seuil : seuls les TITRES sont solidaires, la
 * remontée s'arrête à trois blocs, et elle est abandonnée si la grappe ne
 * tient pas dans une page. Word traite « Paragraphe solidaire » comme une
 * contrainte souple, abandonnée dès qu'elle rend la mise en page impossible.
 */
const KEEP_NEXT_MAX = 3;

function sheetExtent(fill: number, gutter: number, margin: number): number {
  return fill + margin + gutter + margin;
}

function fillExtent(fill: number, margin: number): number {
  return fill + margin;
}

/** Un bloc se coupe si on connaît ses lignes ET qu'il en a de quoi laisser 2+2. */
export function peutSeCouper(block: PageBlock): boolean {
  return (
    block.kind === 'block' &&
    Array.isArray(block.lines) &&
    block.lines.length >= 2 * MIN_LIGNES
  );
}

/**
 * Le début de la grappe « solidaire » qui doit partir avec le bloc `index`.
 *
 * Remplace `clusterStart` + `isTitleLike(52 px)`. Ce qui a changé n'est pas le
 * seuil : c'est qu'il n'y a plus de seuil. Un titre est un titre parce que
 * c'est un H1-H6, pas parce qu'il est court.
 */
function debutDeGrappe(
  items: PageBlock[],
  index: number,
  contentHeight: number,
): number {
  let start = index;
  let hauteur = items[index].height;
  for (let pas = 0; pas < KEEP_NEXT_MAX && start > 0; pas++) {
    const prev = items[start - 1];
    if (prev.kind !== 'heading') break;
    if (hauteur + prev.height > contentHeight) break;
    hauteur += prev.height;
    start -= 1;
  }
  return start;
}

/**
 * Où poser les cales pour que rien ne soit tranché par la gouttière du bureau.
 *
 * L'ordre des règles est celui de Word : un saut manuel gagne sur tout ; un
 * bloc qui tient ne bouge pas ; un titre ne se coupe jamais ; un paragraphe se
 * coupe ENTRE DEUX LIGNES en laissant deux lignes de chaque côté ; et si
 * aucune coupe n'est admissible, alors seulement le bloc entier se déplace.
 */
export function overflowGapPlan(
  blocks: PageBlock[],
  contentHeight: number,
  gutter: number,
  margin: number,
): OverflowGap[] {
  // Une hauteur de page aberrante (mesure prise avant le layout) produisait
  // une cale devant chaque bloc, et le HTML dépassait 100 000 caractères.
  if (!(contentHeight >= 80) || blocks.length === 0) return [];

  const items: PageBlock[] = blocks.map((block) => ({
    ...block,
    lines: block.lines ? [...block.lines] : undefined,
  }));
  const gaps: OverflowGap[] = [];
  let pageEnd = contentHeight;

  const decaler = (index: number, delta: number) => {
    for (let j = index; j < items.length; j++) {
      items[j].top += delta;
      const lignes = items[j].lines;
      if (lignes) for (let l = 0; l < lignes.length; l++) lignes[l] += delta;
    }
  };

  /** Poser une cale devant `y`. `atLine` absent : devant le bloc entier. */
  const couper = (index: number, y: number, atLine?: number) => {
    const fill = Math.max(0, pageEnd - y);
    const extent = sheetExtent(fill, gutter, margin);
    gaps.push(
      atLine === undefined
        ? { beforeIndex: index, fill, mode: 'sheet' }
        : { beforeIndex: index, atLine, fill, mode: 'sheet' },
    );
    if (atLine === undefined) {
      decaler(index, extent);
    } else {
      // Seule la QUEUE du paragraphe descend : son début reste où il est.
      items[index].height += extent;
      const lignes = items[index].lines as number[];
      for (let l = atLine; l < lignes.length; l++) lignes[l] += extent;
      decaler(index + 1, extent);
    }
    pageEnd = y + extent + contentHeight;
  };

  for (let i = 0; i < items.length; i++) {
    const block = items[i];

    // 1. Saut de page manuel : impératif, il gagne sur tout le reste.
    if (block.kind === 'break') {
      const fill = Math.max(0, pageEnd - block.top);
      if (fill > 1) {
        gaps.push({ beforeIndex: i, fill, mode: 'fill' });
        decaler(i, fillExtent(fill, margin));
      }
      pageEnd = items[i].top + items[i].height + margin + contentHeight;
      continue;
    }

    // 2. Le bloc tient : rien à faire.
    if (block.top + block.height <= pageEnd + 0.5) continue;

    // 3. Le bloc déborde. On tente de le couper entre deux lignes.
    if (peutSeCouper(block)) {
      let depuis = 0;
      // Garde-fou : une cale ne peut que déplacer une coupe vers l'aval, donc
      // la boucle avance. Le compteur existe pour qu'un défaut futur se
      // signale par un plan tronqué plutôt que par un onglet figé.
      for (let tour = 0; tour < 500; tour++) {
        const lignes = items[i].lines as number[];
        const n = lignes.length;
        if (items[i].top + items[i].height <= pageEnd + 0.5) break;

        // Combien de lignes tiennent : la ligne k-1 finit là où k commence.
        let tiennent = depuis;
        while (tiennent < n && lignes[tiennent] <= pageEnd + 0.5) tiennent += 1;

        // Toutes les lignes commencent avant la limite, mais la dernière la
        // franchit : c'est elle qui doit passer.
        let k = tiennent === n ? n - 1 : tiennent;
        // Veuves : au moins deux lignes doivent partir sur la page suivante.
        if (k > n - MIN_LIGNES) k = n - MIN_LIGNES;
        // Orphelines : au moins deux lignes doivent rester sur celle-ci.
        const admissible = k >= depuis + MIN_LIGNES;

        if (admissible) {
          couper(i, lignes[k], k);
          depuis = k;
          continue;
        }
        // Aucune coupe admissible dans ce qui reste : le reste part entier.
        if (depuis === 0) break; // traité par le chemin « bloc entier »
        couper(i, lignes[depuis], depuis);
        break;
      }
      if (items[i].top + items[i].height <= pageEnd + 0.5) continue;
      if (depuis > 0) continue;
    }

    // 4. Insécable, ou aucune coupe admissible : le bloc entier se déplace,
    //    avec les titres qui lui sont solidaires.
    const start = debutDeGrappe(items, i, contentHeight);
    couper(start, items[start].top);
  }

  return gaps;
}

export function overflowGapHeight(
  gap: OverflowGap,
  gutter: number,
  margin: number,
): number {
  return gap.mode === 'sheet'
    ? sheetExtent(gap.fill, gutter, margin)
    : fillExtent(gap.fill, margin);
}
