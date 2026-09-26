import type { VieNote, VieNoteResume } from './types';
import { countNotePages } from './notePages';
export type CartableNote = VieNote | VieNoteResume;
export function resumeDeNote(note: CartableNote): VieNoteResume {
  if (!('content' in note)) return note;
  const { content, ...meta } = note;
  return { ...meta, pageCountEstimate: countNotePages(content, note.pageFormat) };
}
