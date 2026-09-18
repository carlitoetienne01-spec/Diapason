/** Local UI preferences for Succès (view modes, collapsed trees). */

import { normaliserEchelle } from './echelleTexte';
import { TAILLE_PAGE_DEFAUT, bornerPage, estTaillePage, type TaillePage } from './pagination';
import { estVueReseau, type VueReseau } from './reseau';
import { estTriNotes, type TriNotes } from './triNotes';

const STORAGE_KEY = 'diapason-succes-ui-prefs';

/**
 * `done` : l'onglet Terminées, à part de la Liste depuis le 17 sept. 2026 —
 * les 36 tâches faites traînaient sous les 690 ouvertes, barrées.
 */
export type SuccesTasksViewMode = 'list' | 'week' | 'month' | 'done';
const MODES: readonly SuccesTasksViewMode[] = ['list', 'week', 'month', 'done'];

/** Les deux onglets paginés ; chacun retient sa page. */
export type SuccesTasksOngletPagine = 'list' | 'done';

/**
 * Les filtres de la page Tâches. Ils repartaient à zéro à chaque visite —
 * les terminées revenaient, le projet choisi s'oubliait — alors que le mode
 * d'affichage, lui, était retenu (expertise du 17 sept. 2026, défaut 6).
 */
export type SuccesTasksFilters = {
  includeDone: boolean;
  projectFilter: string;
};

type Prefs = {
  tasksViewMode?: SuccesTasksViewMode;
  tasksFilters?: Partial<SuccesTasksFilters>;
  /** Tâches par page (5, 10 ou 20), commun aux deux onglets paginés. */
  tasksPageSize?: number;
  /** La page où l'on était, par onglet paginé — pour y revenir. */
  tasksPages?: Partial<Record<SuccesTasksOngletPagine, number>>;
  /** L'échelle du texte de la Ligne — voir `echelleTexte.ts`. */
  ligneEchelle?: number;
  /** taskId → whether its subtask list is expanded */
  taskSubtasksOpen?: Record<string, boolean>;
  /** subtaskId → whether its children are expanded */
  subtaskExpanded?: Record<string, boolean>;
  /** Le tri choisi pour les cartables de Notes — voir `triNotes.ts`. */
  notesSort?: TriNotes;
  /** Graphe ou Liste pour un projet réseau — voir `reseau.ts`. Absent : jamais choisi. */
  reseauVue?: VueReseau;
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
  return MODES.includes(value as SuccesTasksViewMode) ? (value as SuccesTasksViewMode) : fallback;
}

export function saveTasksViewMode(mode: SuccesTasksViewMode) {
  writePrefs({ tasksViewMode: mode });
}

/** Tâches par page, telle que choisie la dernière fois ; 5 si rien ou si la valeur n'est pas offerte. */
export function loadTasksPageSize(): TaillePage {
  const value = readPrefs().tasksPageSize;
  return estTaillePage(value) ? value : TAILLE_PAGE_DEFAUT;
}

export function saveTasksPageSize(taille: TaillePage) {
  writePrefs({ tasksPageSize: taille });
}

/**
 * La page retenue pour un onglet — au moins 1 ; la borne HAUTE n'est connue
 * qu'une fois la liste chargée, c'est la page qui la ramène dans ses bornes.
 */
export function loadTasksPage(onglet: SuccesTasksOngletPagine): number {
  const value = readPrefs().tasksPages?.[onglet];
  return typeof value === 'number' ? bornerPage(value, Number.MAX_SAFE_INTEGER) : 1;
}

export function saveTasksPage(onglet: SuccesTasksOngletPagine, page: number) {
  const pages = { ...(readPrefs().tasksPages || {}), [onglet]: page };
  writePrefs({ tasksPages: pages });
}

export function loadTasksFilters(fallback: SuccesTasksFilters): SuccesTasksFilters {
  const value = readPrefs().tasksFilters;
  if (!value || typeof value !== 'object') return fallback;
  return {
    includeDone: typeof value.includeDone === 'boolean' ? value.includeDone : fallback.includeDone,
    projectFilter: typeof value.projectFilter === 'string' ? value.projectFilter : fallback.projectFilter,
  };
}

export function saveTasksFilters(filters: SuccesTasksFilters) {
  writePrefs({ tasksFilters: filters });
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

/**
 * Graphe ou Liste pour le réseau, tel que choisi la dernière fois ; `undefined`
 * si rien n'a jamais été choisi — la vue laisse alors le CSS décider (Liste
 * sous `sm`, Graphe au-delà : la largeur se lit en CSS, jamais en JS).
 * Le `localStorage` est cloisonné par origine : le mini-panneau et la
 * fenêtre retiennent chacun le leur, ce qui est le comportement voulu.
 */
export function loadReseauVue(): VueReseau | undefined {
  const value = readPrefs().reseauVue;
  return estVueReseau(value) ? value : undefined;
}

export function saveReseauVue(vue: VueReseau) {
  writePrefs({ reseauVue: vue });
}
