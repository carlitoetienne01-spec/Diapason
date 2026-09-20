import type { SuccesNote, SuccesNoteResume } from './types';
import { countNotePages } from './notePages';
export type CartableNote = SuccesNote | SuccesNoteResume;
export function resumeDeNote(note: CartableNote): SuccesNoteResume {
  if (!('content' in note)) return note;
  const { content, ...meta } = note;
  return { ...meta, pageCountEstimate: countNotePages(content, note.pageFormat) };
}
