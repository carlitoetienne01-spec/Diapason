import { rangerProjet } from './gesteProjet';

type NoteClassee = { id: string; category?: string; order?: number };
export type PlacementNote = { id: string; zone?: string };

/** Une carte cible donne le rang ; un en-tête reçoit en fin de catégorie. */
export function rangerNoteMobile(notes: NoteClassee[], ids: string[], id: string, cible: string | null, zone: string): string[] {
  if (cible) return rangerProjet(ids, id, cible);
  const sans = ids.filter(cle => cle !== id);
  const categorie = new Map(notes.map(note => [note.id, note.category || '']));
  const derniers = sans.filter(cle => categorie.get(cle) === zone);
  const index = derniers.length ? sans.indexOf(derniers[derniers.length - 1]) + 1 : sans.length;
  sans.splice(index, 0, id);
  return sans;
}

/** Le contenu des notes reste intact ; seuls le rang et la catégorie bougent. */
export function appliquerClassementNotes<T extends NoteClassee>(notes: T[], ids: string[], placement: PlacementNote): T[] {
  const parId = new Map(notes.map(note => [note.id, note]));
  const ordre = [...new Set([...ids, ...notes.map(note => note.id)])];
  return ordre.flatMap((id, order) => {
    const note = parId.get(id);
    return note ? [{ ...note, order, ...(id === placement.id && placement.zone !== undefined ? { category: placement.zone } : {}) }] : [];
  });
}
