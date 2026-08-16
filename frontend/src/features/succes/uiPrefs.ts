/** Local UI preferences for Succès (view modes, collapsed trees). */

const STORAGE_KEY = 'diapason-succes-ui-prefs';

export type SuccesTasksViewMode = 'list' | 'week' | 'month';

type Prefs = {
  tasksViewMode?: SuccesTasksViewMode;
  /** taskId → whether its subtask list is expanded */
  taskSubtasksOpen?: Record<string, boolean>;
  /** subtaskId → whether its children are expanded */
  subtaskExpanded?: Record<string, boolean>;
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
