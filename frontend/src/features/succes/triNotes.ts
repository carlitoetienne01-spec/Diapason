// Le tri des cartables de Notes, et ce qu'on en retient.
//
// 17 sept. 2026 : « pourquoi Notes ne garde pas ma préférence, où j'ai placé
// mes cartables — et non pas celui que j'ai édité en dernier ». Le rang
// manuel était bien enregistré côté serveur (order_index, posé par le
// glisser), mais le CHOIX de tri de la page repartait à « Récent » à chaque
// ouverture : l'arrangement existait et n'était jamais montré.

export type TriNotes = 'manuel' | 'recent' | 'oldest' | 'name-asc' | 'name-desc';

export const TRIS_NOTES: readonly TriNotes[] = ['manuel', 'recent', 'oldest', 'name-asc', 'name-desc'];

export function estTriNotes(valeur: unknown): valeur is TriNotes {
  return typeof valeur === 'string' && (TRIS_NOTES as readonly string[]).includes(valeur);
}

/**
 * Vrai si Carlito a déjà rangé ses cartables : le serveur numérote 0..n-1
 * les notes glissées, une note jamais rangée reste à 0. Dès qu'une note
 * porte un rang > 0, un arrangement existe.
 */
export function unArrangementExiste(notes: readonly { order?: number }[]): boolean {
  return notes.some((note) => (note.order ?? 0) > 0);
}

/**
 * Le tri à l'ouverture : le choix mémorisé s'il y en a un ; sinon « Mon
 * ordre » dès qu'un arrangement existe — le glisser EST la préférence —,
 * et « Récent » pour qui n'a jamais rien rangé.
 */
export function triInitialDesNotes(
  memorise: unknown,
  notes: readonly { order?: number }[],
): TriNotes {
  if (estTriNotes(memorise)) return memorise;
  return unArrangementExiste(notes) ? 'manuel' : 'recent';
}
