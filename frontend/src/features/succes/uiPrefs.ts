/** Local UI preferences for Succès (view modes, collapsed trees). */

import { normaliserEchelle } from './echelleTexte';
import { estTriNotes, type TriNotes } from './triNotes';

const STORAGE_KEY = 'diapason-succes-ui-prefs';

export type SuccesTasksViewMode = 'list' | 'week' | 'month';

type Prefs = {
  tasksViewMode?: SuccesTasksViewMode;
  /** L'échelle du texte de la Ligne — voir `echelleTexte.ts`. */
  ligneEchelle?: number;
  /** taskId → whether its subtask list is expanded */
  taskSubtasksOpen?: Record<string, boolean>;
  /** subtaskId → whether its children are expanded */
  subtaskExpanded?: Record<string, boolean>;
  /** Le tri choisi pour les cartables de Notes — voir `triNotes.ts`. */
  notesSort?: TriNotes;
};

function readPrefs(): Prefs {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Prefs;
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
}

function writePrefs(patch: Prefs) {
  try {
    const next = { ...readPrefs(), ...patch };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    // Quota / private mode — preference is best-effort.
  }
}

export function loadTasksViewMode(fallback: SuccesTasksViewMode = 'week'): SuccesTasksViewMode {
  const value = readPrefs().tasksViewMode;
  return value === 'list' || value === 'week' || value === 'month' ? value : fallback;
}

export function saveTasksViewMode(mode: SuccesTasksViewMode) {
  writePrefs({ tasksViewMode: mode });
}

export function loadTaskSubtasksOpen(taskId: string, fallback = true): boolean {
  const map = readPrefs().taskSubtasksOpen;
  if (!map || !(taskId in map)) return fallback;
  return Boolean(map[taskId]);
}

export function saveTaskSubtasksOpen(taskId: string, open: boolean) {
  const map = { ...(readPrefs().taskSubtasksOpen || {}), [taskId]: open };
  writePrefs({ taskSubtasksOpen: map });
}

export function loadSubtaskExpanded(subtaskId: string, fallback = true): boolean {
  const map = readPrefs().subtaskExpanded;
  if (!map || !(subtaskId in map)) return fallback;
  return Boolean(map[subtaskId]);
}

export function saveSubtaskExpanded(subtaskId: string, expanded: boolean) {
  const map = { ...(readPrefs().subtaskExpanded || {}), [subtaskId]: expanded };
  writePrefs({ subtaskExpanded: map });
}

/** L'échelle du texte de la Ligne, telle qu'elle a été réglée la dernière fois. */
export function loadLigneEchelle(): number {
  return normaliserEchelle(readPrefs().ligneEchelle);
}

export function saveLigneEchelle(echelle: number) {
  writePrefs({ ligneEchelle: normaliserEchelle(echelle) });
}

/**
 * Le tri des cartables de Notes tel qu'il a été choisi la dernière fois,
 * ou `undefined` si rien n'a jamais été choisi (l'appelant infère alors —
 * un arrangement existant vaut « Mon ordre »).
 */
export function loadNotesSort(): TriNotes | undefined {
  const value = readPrefs().notesSort;
  return estTriNotes(value) ? value : undefined;
}

export function saveNotesSort(mode: TriNotes) {
  writePrefs({ notesSort: mode });
}
