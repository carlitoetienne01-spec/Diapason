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
 * Estimate how many pages a note fills. Manual page breaks always start a new
 * page; within each chunk the text volume decides how many pages it spills onto.
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

/** Sheets drawn inside the folder: one per page, capped at three. */
export function noteSheetCount(
  content: string,
  pageFormat: SuccesNotePageFormat = 'a4',
): 1 | 2 | 3 {
  return Math.min(3, countNotePages(content, pageFormat)) as 1 | 2 | 3;
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
};

export type OverflowGap = {
  /** Index in the measured block list (gaps themselves are not in that list). */
  beforeIndex: number;
  /** Empty paper left at the bottom of the current content box. */
  fill: number;
  /**
   * `sheet` — remainder + bottom margin + desk gutter + next top margin.
   * `fill` — remainder + bottom margin only; a manual `<hr>` is the gutter.
   */
  mode: 'sheet' | 'fill';
};

function sheetExtent(fill: number, gutter: number, margin: number): number {
  return fill + margin + gutter + margin;
}

function fillExtent(fill: number, margin: number): number {
  return fill + margin;
}

/** Titre, ligne courte : Word les emmène avec le paragraphe suivant. */
export function isTitleLike(block: PageBlock): boolean {
  if (block.kind === 'heading') return true;
  return block.kind === 'block' && block.height <= 52;
}

function clusterStart(items: PageBlock[], index: number, pageEnd: number): number {
  let start = index;
  while (start > 0) {
    const prev = items[start - 1];
    if (prev.kind === 'break' || !isTitleLike(prev)) break;
    if (prev.top >= pageEnd) break;
    start -= 1;
  }
  return start;
}

/**
 * Decide where to push whole blocks onto the next sheet so nothing is sliced
 * by the desk gutter. 29 août 2026 : des feuilles peintes à intervalle fixe
 * tranchaient « Constructeur autonome » ; un N2 restait orphelin en bas de page.
 */
export function overflowGapPlan(
  blocks: PageBlock[],
  contentHeight: number,
  gutter: number,
  margin: number,
): OverflowGap[] {
  // Une hauteur de page aberrante (mesure avant layout) produisait une
  // gouttière devant chaque bloc, et le HTML dépassait 100 000 caractères.
  if (!(contentHeight >= 80) || blocks.length === 0) return [];
  const items = blocks.map((block) => ({ ...block }));
  const gaps: OverflowGap[] = [];
  let pageEnd = contentHeight;
  const danger = Math.min(80, contentHeight * 0.22);

  const shiftFrom = (index: number, delta: number) => {
    for (let j = index; j < items.length; j++) items[j].top += delta;
  };

  const pushSheet = (index: number) => {
    const start = clusterStart(items, index, pageEnd);
    const fill = Math.max(0, pageEnd - items[start].top);
    const extent = sheetExtent(fill, gutter, margin);
    if (extent <= 0) return;
    gaps.push({ beforeIndex: start, fill, mode: 'sheet' });
    shiftFrom(start, extent);
    pageEnd = items[start].top + contentHeight;
  };

  for (let i = 0; i < items.length; i++) {
    const block = items[i];
    if (block.kind === 'break') {
      const fill = Math.max(0, pageEnd - block.top);
      if (fill > 1) {
        const extent = fillExtent(fill, margin);
        gaps.push({ beforeIndex: i, fill, mode: 'fill' });
        shiftFrom(i, extent);
      }
      pageEnd = items[i].top + items[i].height + margin + contentHeight;
      continue;
    }

    const bottom = block.top + block.height;
    const next = items[i + 1];
    const nextMissesPage =
      next !== undefined &&
      next.kind !== 'break' &&
      next.top + next.height > pageEnd;
    const keepWithNext =
      isTitleLike(block) &&
      bottom <= pageEnd &&
      nextMissesPage &&
      next.top < pageEnd + 1;
    const titleInDanger =
      isTitleLike(block) &&
      next !== undefined &&
      next.kind !== 'break' &&
      block.top >= pageEnd - danger &&
      bottom <= pageEnd;

    if (block.height > contentHeight) {
      if (block.top >= pageEnd - 0.5) {
        pushSheet(i);
      }
      pageEnd = items[i].top + items[i].height;
      continue;
    }

    if (block.top >= pageEnd - 0.5) {
      pushSheet(i);
      continue;
    }

    if ((block.top < pageEnd && bottom > pageEnd) || keepWithNext || titleInDanger) {
      pushSheet(i);
    }
  }

  return gaps;
}

export function overflowGapHeight(gap: OverflowGap, gutter: number, margin: number): number {
  return gap.mode === 'sheet'
    ? sheetExtent(gap.fill, gutter, margin)
    : fillExtent(gap.fill, margin);
}
