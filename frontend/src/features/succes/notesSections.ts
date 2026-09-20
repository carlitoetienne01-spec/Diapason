// Le classement des notes en sections de catégories — pur, testé sous vitest.
//
// Demandé le 15 septembre 2026 : « mes propres catégories, le nom en haut,
// un trait horizontal qui sépare, les cartables de la catégorie dans sa
// section ». Une catégorie n'est pas un état à entretenir : elle existe tant
// qu'une note la porte (le serveur ne mémorise que l'ORDRE des sections).

import type { SuccesNote } from './types';

export interface SectionDeNotes<T extends { category?: string } = SuccesNote> {
  /** Vide : la section « Sans catégorie » (ou la page à plat). */
  nom: string;
  notes: T[];
}

/**
 * Groupe les notes (déjà triées : le tri de la page vaut DANS chaque
 * section) selon l'ordre choisi. Une catégorie que l'ordre ne connaît pas —
 * note importée, synchronisée — se range à la fin, alphabétiquement. Les
 * sans-catégorie ferment la marche. Et tant qu'AUCUNE catégorie n'existe, la
 * page reste à plat : une seule section sans nom, pas d'en-tête pour rien.
 */
export function grouperEnSections<T extends { category?: string }>(
  notes: T[],
  ordre: string[],
): SectionDeNotes<T>[] {
  const parCategorie = new Map<string, T[]>();
  for (const note of notes) {
    const nom = note.category || '';
    const liste = parCategorie.get(nom) ?? [];
    liste.push(note);
    parCategorie.set(nom, liste);
  }
  const nommees = [...parCategorie.keys()].filter((n) => n !== '');
  if (!nommees.length) return [{ nom: '', notes }];
  const connues = ordre.filter((n) => parCategorie.has(n));
  const inconnues = nommees.filter((n) => !connues.includes(n)).sort((a, b) => a.localeCompare(b, 'fr'));
  const sections: SectionDeNotes<T>[] = [...connues, ...inconnues].map((nom) => ({
    nom,
    notes: parCategorie.get(nom) ?? [],
  }));
  const sans = parCategorie.get('');
  if (sans?.length) sections.push({ nom: '', notes: sans });
  return sections;
}

/** Déplace `nom` juste avant `avant` (ou à la fin si `avant` est vide). */
export function deplacerCategorie(ordre: string[], nom: string, avant: string): string[] {
  if (nom === avant) return ordre;
  const sans = ordre.filter((n) => n !== nom);
  if (!avant) return [...sans, nom];
  const index = sans.indexOf(avant);
  if (index < 0) return [...sans, nom];
  return [...sans.slice(0, index), nom, ...sans.slice(index)];
}
