import { stripNoteHtml } from './noteSanitize';
import type { SuccesNotePageFormat } from './types';

/** Marker inserted by the editor's "Saut de page" button. */
export const PAGE_BREAK_CLASS = 'succes-page-break';
export const PAGE_BREAK_HTML = `<hr class="${PAGE_BREAK_CLASS}"><p><br></p>`;

/**
 * Characters a page of each format holds at the default type size. The editor
 * has no real pagination — the page element simply grows — so these are the
 * calibration constants that turn a content length back into a page count.
 */
const PAGE_CAPACITY: Record<SuccesNotePageFormat, number> = {
  a4: 2800,
  letter: 2800,
  a5: 1400,
  wide: 1300,
  narrow: 760,
  full: 1000,
  reading: 900,
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
