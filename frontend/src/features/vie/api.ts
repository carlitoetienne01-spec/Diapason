import { apiFetch, getBase, getApiKey } from '../../lib/api';
import { enregistrerHorsBureau } from '../../lib/enregistrerFichier';
import { creerLecturesPartagees } from './lecturesPartagees';
import type {
  FinanceAccount,
  FinanceAccountType,
  FinanceBudget,
  FinanceBudgetScope,
  FinanceCategory,
  FinanceCategoryKind,
  FinanceCsvImportSummary,
  FinanceGoal,
  FinanceOverview,
  FinancePeriod,
  FinanceSubCadence,
  FinanceSubscription,
  FinanceTransaction,
  FinanceTxnType,
  PlannerResponse,
  VieDashboard,
  VieHabit,
  VieHabitFrequency,
  VieNote,
  VieNoteResume,
  ViePairingInvitation,
  ViePriority,
  VieProject,
  VieProjectKit,
  VieQuote,
  VieSyncRunResult,
  VieSyncStatus,
  VieTask,
  VieTemplate,
  VieTemplateFrequency,
  VieTemplateKind,
  VieYearReview,
  VieCadence,
  VieProjectStructure,
  VieStructureConfig,
  VieStructureInfo,
  VieTaskEdge,
  VieAnnotation,
  VieCadre,
  ViePhoto,
  ViePhotoContenu,
  ViePhotoEnvoi,
  ViePhotoPile,
  ViePhotoPiles,
} from './types';

/**
 * Une réponse refusée par le serveur local, avec son statut et son `detail`
 * tel quel. `request` n'en gardait que le message : le 409 `ambiguous_date`
 * de /reschedule porte deux `options` datées que la carte doit proposer, et
 * elles se perdaient dans la conversion en chaîne (expertise de la page
 * Tâches, 17 sept. 2026).
 */
export class VieApiError extends Error {
  status: number;
  detail: unknown;

  constructor(message: string, status: number, detail: unknown) {
    super(message);
    this.name = 'VieApiError';
    this.status = status;
    this.detail = detail;
  }
}

/** « lundi prochain » peut désigner deux jours : le serveur les rend, à choisir. */
export class DateAmbigueError extends Error {
  options: string[];

  constructor(message: string, options: string[]) {
    super(message);
    this.name = 'DateAmbigueError';
    this.options = options;
  }
}

/** Le résolveur n'a rien reconnu (422) : la carte le dit sous le champ, pas en toast. */
export class DateInconnueError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'DateInconnueError';
  }
}

const lectures = creerLecturesPartagees();
function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const lecture = !init.method || init.method === 'GET';
  if (lecture && !init.signal) {
    return lectures.lire(`${getBase()}\0${getApiKey()}\0${path}`, () => executerRequete<T>(path, init));
  }
  if (lecture) return executerRequete<T>(path, init);
  lectures.invalider();
  return executerRequete<T>(path, init).finally(lectures.invalider);
}

async function executerRequete<T>(path: string, init: RequestInit = {}): Promise<T> {
  const requestInit = {
    ...init,
    headers: {
      ...(init.body ? { 'Content-Type': 'application/json' } : {}),
      ...((init.headers as Record<string, string> | undefined) ?? {}),
    },
  };

  let lastError: unknown = null;
  for (let attempt = 0; attempt < 4; attempt += 1) {
    let response: Response;
    try {
      response = await apiFetch(path, requestInit);
    } catch (error) {
      lastError = error;
      // WebKit reports aborted/network races as "Load failed".
      // Un POST peut avoir été enregistré avant que sa réponse se perde.
      // Le rejouer fabriquait alors un second objet : seul GET se réessaie.
      if (init.signal?.aborted) throw error;
      if ((!init.method || init.method === 'GET') && attempt < 3) {
        await new Promise((resolve) => window.setTimeout(resolve, 250 * (attempt + 1)));
        continue;
      }
      const raw = error instanceof Error ? error.message : String(error);
      throw new Error(
        /load failed|failed to fetch|networkerror/i.test(raw)
          ? (!init.method || init.method === 'GET'
            ? 'Connexion locale interrompue. Réessayez.'
            : 'Réponse interrompue : vérifiez la liste avant de réessayer, la modification peut déjà être enregistrée.')
          : /did not match the expected pattern|invalid url|failed to construct/i.test(raw)
            ? "L'URL de l'API est invalide. Vérifiez Réglages → Connexion → URL de l'API."
            : raw || 'Connexion locale impossible.',
      );
    }

    if (response.status === 429) {
      const retrySeconds = Number(response.headers.get('Retry-After') || attempt + 1);
      const delay = Math.min(2500, Math.max(300, retrySeconds * 1000));
      if ((!init.method || init.method === 'GET') && attempt < 3) {
        await new Promise((resolve) => window.setTimeout(resolve, delay));
        continue;
      }
      throw new Error('Trop de requêtes. Réessayez dans un instant.');
    }

    if (!response.ok) {
      let message = `Erreur Diapason (${response.status})`;
      let detail: unknown = null;
      try {
        const payload = await response.json();
        detail = payload?.detail;
        if (typeof detail === 'string') {
          message = detail;
        } else if (Array.isArray(detail) && detail[0]) {
          const first = detail[0];
          message =
            typeof first.msg === 'string'
              ? first.msg
              : typeof first.message === 'string'
                ? first.message
                : message;
        } else if (typeof (detail as { message?: unknown })?.message === 'string') {
          message = (detail as { message: string }).message;
        }
      } catch {
        // Keep the stable user-facing fallback; technical details stay in logs.
      }
      throw new VieApiError(message, response.status, detail);
    }

    try {
      return (await response.json()) as T;
    } catch {
      // WebKit only says "the string did not match the expected pattern" here,
      // which reads as a client bug even when the server sent a broken body.
      throw new Error(
        `Réponse illisible du serveur local (${path}). Redémarrez Diapason pour recharger le serveur.`,
      );
    }
  }

  throw lastError instanceof Error
    ? lastError
    : new Error('Connexion locale impossible.');
}

export async function listVieTasks(options: {
  date?: string;
  includeDone?: boolean;
  search?: string;
} = {}): Promise<VieTask[]> {
  const query = new URLSearchParams();
  if (options.date !== undefined) query.set('date', options.date);
  query.set('include_done', String(options.includeDone ?? true));
  if (options.search) query.set('search', options.search);
  const payload = await request<{ tasks: VieTask[] }>(`/v1/vie/tasks?${query}`);
  return payload.tasks;
}

export async function createVieTask(input: {
  title: string;
  date?: string;
  time?: string;
  priority?: ViePriority;
  notes?: string;
  journal?: string;
  projectId?: string;
  parentTaskId?: string;
  category?: string;
  emoji?: string;
  stage?: string;
  cadence?: VieCadence | null;
  estimateDays?: number;
}): Promise<VieTask> {
  const payload = await request<{ task: VieTask }>('/v1/vie/tasks', {
    method: 'POST',
    body: JSON.stringify(input),
  });
  return payload.task;
}

export async function updateVieTask(
  taskId: string,
  patch: Partial<
    Pick<
      VieTask,
      | 'title'
      | 'date'
      | 'time'
      | 'priority'
      | 'notes'
      | 'journal'
      | 'projectId'
      | 'parentTaskId'
      | 'category'
      | 'emoji'
      | 'stage'
      | 'cadence'
      | 'estimateDays'
    >
  >,
): Promise<VieTask> {
  const payload = await request<{ task: VieTask }>(
    `/v1/vie/tasks/${encodeURIComponent(taskId)}`,
    { method: 'PATCH', body: JSON.stringify(patch) },
  );
  return payload.task;
}

export async function setVieTaskDone(taskId: string, done: boolean): Promise<VieTask> {
  const payload = await request<{ task: VieTask }>(
    `/v1/vie/tasks/${encodeURIComponent(taskId)}/done`,
    { method: 'POST', body: JSON.stringify({ done }) },
  );
  return payload.task;
}

/**
 * Reporte une tâche — `date` est une ISO ou une expression (« lundi »,
 * « dans 3 jours », 80 caractères au plus) que le serveur résout lui-même.
 * Deux refus se répondent depuis la carte, d'où leurs erreurs typées :
 * 409 `{ code: 'ambiguous_date', message, options: [iso, iso] }` et 422
 * « Je n'ai pas reconnu cette date. » (17 sept. 2026).
 */
export async function rescheduleVieTask(
  taskId: string,
  date: string,
): Promise<{ task: VieTask; warning: string | null }> {
  try {
    return await request(`/v1/vie/tasks/${encodeURIComponent(taskId)}/reschedule`, {
      method: 'POST',
      body: JSON.stringify({ date }),
    });
  } catch (error) {
    if (error instanceof VieApiError) {
      const detail = error.detail as { code?: unknown; options?: unknown } | null;
      if (error.status === 409 && detail?.code === 'ambiguous_date' && Array.isArray(detail.options)) {
        throw new DateAmbigueError(
          error.message,
          detail.options.filter((option): option is string => typeof option === 'string'),
        );
      }
      if (error.status === 422) throw new DateInconnueError(error.message);
    }
    throw error;
  }
}

export async function rescheduleVieSeries(
  taskId: string,
  date: string,
): Promise<{ templateId: string; deltaDays: number; updated: number }> {
  return request(`/v1/vie/tasks/${encodeURIComponent(taskId)}/reschedule-series`, {
    method: 'POST',
    body: JSON.stringify({ date }),
  });
}

export async function addVieSubtask(
  taskId: string,
  title: string,
  parentId?: string,
): Promise<VieTask> {
  const payload = await request<{ task: VieTask }>(
    `/v1/vie/tasks/${encodeURIComponent(taskId)}/subtasks`,
    { method: 'POST', body: JSON.stringify({ title, parentId: parentId || null }) },
  );
  return payload.task;
}

export async function setVieSubtaskDone(
  taskId: string,
  subtaskId: string,
  done: boolean,
): Promise<VieTask> {
  const payload = await request<{ task: VieTask }>(
    `/v1/vie/tasks/${encodeURIComponent(taskId)}/subtasks/${encodeURIComponent(subtaskId)}/done`,
    { method: 'POST', body: JSON.stringify({ done }) },
  );
  return payload.task;
}

export async function deleteVieSubtask(
  taskId: string,
  subtaskId: string,
): Promise<VieTask> {
  const payload = await request<{ task: VieTask }>(
    `/v1/vie/tasks/${encodeURIComponent(taskId)}/subtasks/${encodeURIComponent(subtaskId)}`,
    { method: 'DELETE', body: JSON.stringify({ confirmed: true }) },
  );
  return payload.task;
}

export async function deleteVieTask(taskId: string): Promise<void> {
  await request(`/v1/vie/tasks/${encodeURIComponent(taskId)}`, {
    method: 'DELETE',
    body: JSON.stringify({ confirmed: true }),
  });
}

export function fetchViePlanner(date: string): Promise<PlannerResponse> {
  return request(`/v1/vie/planner?date=${encodeURIComponent(date)}`);
}

export interface PlannerPastilles {
  startDate: string;
  endDate: string;
  days: Record<string, { open: number; done: number }>;
}

/** Les points du petit calendrier — exacts, récurrences projetées comprises. */
export function fetchPlannerPastilles(start: string, end: string): Promise<PlannerPastilles> {
  return request(
    `/v1/vie/planner/pastilles?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`,
  );
}

export function fetchVieSyncStatus(): Promise<VieSyncStatus> {
  return request('/v1/vie/sync/status');
}

export function createViePairing(deviceName: string): Promise<ViePairingInvitation> {
  return request('/v1/vie/sync/pairings', {
    method: 'POST',
    body: JSON.stringify({ deviceName }),
  });
}

export async function revokeViePeer(peerId: string): Promise<void> {
  await request(`/v1/vie/sync/peers/${encodeURIComponent(peerId)}`, {
    method: 'DELETE',
  });
}

export function setVieSyncRelay(url: string): Promise<VieSyncStatus> {
  return request('/v1/vie/sync/relay', {
    method: 'PUT',
    body: JSON.stringify({ url }),
  });
}

export function clearVieSyncRelay(): Promise<VieSyncStatus> {
  return request('/v1/vie/sync/relay', { method: 'DELETE' });
}

export function joinVieSync(input: {
  pairingToken: string;
  relayUrl?: string;
  deviceName?: string;
}): Promise<VieSyncStatus> {
  return request('/v1/vie/sync/join', {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export function runVieSync(): Promise<VieSyncRunResult> {
  return request('/v1/vie/sync/run', { method: 'POST' });
}

export function clearVieSyncGuest(): Promise<VieSyncStatus> {
  return request('/v1/vie/sync/guest', { method: 'DELETE' });
}

/** Pourquoi un élément de la sauvegarde n'est pas entré (`vie/resume_import.py`). */
export type VieImportSkipReason =
  | 'plusRecentSurLeMac'
  | 'dejaSurLeMac'
  | 'titreVide'
  | 'tropLong'
  | 'invalide'
  | 'habitudeAbsente';

export async function importLegacyVieSnapshot(snapshot: unknown): Promise<{
  summary: {
    tasksImported: number;
    tasksSkipped: number;
    projectsImported: number;
    habitsImported?: number;
    notesImported?: number;
    habitLogsImported?: number;
    habitLogsWithoutTimestamp?: number;
    templatesImported?: number;
    quotesImported?: number;
    skipped?: Record<string, Partial<Record<VieImportSkipReason, number>>>;
    skippedItems?: { kind: string; id: string; label: string; reason: VieImportSkipReason }[];
    truncated?: Record<string, Record<string, number>>;
    ignoredKeys?: { key: string; reason: string; count?: number }[];
    alreadyImported: boolean;
  };
  /** La phrase du Mac, tirée du résumé : c'est elle qu'on affiche (§100). */
  message: string;
}> {
  return request('/v1/vie/import/legacy', {
    method: 'POST',
    body: JSON.stringify({ snapshot, source: 'Sauvegarde Life OS importée depuis Diapason' }),
  });
}

export async function listVieProjects(search = ''): Promise<VieProject[]> {
  const payload = await request<{ projects: VieProject[] }>(
    `/v1/vie/projects?search=${encodeURIComponent(search)}`,
  );
  return payload.projects;
}

export async function listVieProjectKits(): Promise<VieProjectKit[]> {
  const payload = await request<{ kits: VieProjectKit[] }>('/v1/vie/project-kits');
  return payload.kits;
}

export async function listVieProjectStructures(): Promise<VieStructureInfo[]> {
  const payload = await request<{ structures: VieStructureInfo[] }>(
    '/v1/vie/project-structures',
  );
  return payload.structures;
}

export async function createVieProject(input: {
  name: string;
  description?: string;
  color?: string;
  icon?: string;
  startDate?: string;
  endDate?: string;
  structure?: VieProjectStructure;
  structureConfig?: VieStructureConfig;
  kitId?: string;
}): Promise<VieProject> {
  const payload = await request<{ project: VieProject }>('/v1/vie/projects', {
    method: 'POST',
    body: JSON.stringify(input),
  });
  return payload.project;
}

export async function updateVieProject(
  projectId: string,
  patch: Partial<
    Pick<
      VieProject,
      | 'name'
      | 'description'
      | 'color'
      | 'icon'
      | 'startDate'
      | 'endDate'
      | 'structure'
      | 'structureConfig'
    >
  >,
): Promise<VieProject> {
  const payload = await request<{ project: VieProject }>(
    `/v1/vie/projects/${encodeURIComponent(projectId)}`,
    { method: 'PATCH', body: JSON.stringify(patch) },
  );
  return payload.project;
}

export async function listVieTaskEdges(projectId: string): Promise<VieTaskEdge[]> {
  const payload = await request<{ edges: VieTaskEdge[] }>(
    `/v1/vie/projects/${encodeURIComponent(projectId)}/edges`,
  );
  return payload.edges;
}

export async function createVieTaskEdge(
  projectId: string,
  fromTaskId: string,
  toTaskId: string,
): Promise<VieTaskEdge> {
  const payload = await request<{ edge: VieTaskEdge }>(
    `/v1/vie/projects/${encodeURIComponent(projectId)}/edges`,
    { method: 'POST', body: JSON.stringify({ fromTaskId, toTaskId }) },
  );
  return payload.edge;
}

export async function deleteVieTaskEdge(
  projectId: string,
  fromTaskId: string,
  toTaskId: string,
): Promise<void> {
  await request(
    `/v1/vie/projects/${encodeURIComponent(projectId)}/edges/${encodeURIComponent(fromTaskId)}/${encodeURIComponent(toTaskId)}`,
    { method: 'DELETE' },
  );
}

export async function resetVieProjectCycle(
  projectId: string,
): Promise<{ project: VieProject; reopened: number }> {
  return request<{ project: VieProject; reopened: number }>(
    `/v1/vie/projects/${encodeURIComponent(projectId)}/cycle/reset`,
    { method: 'POST', body: JSON.stringify({}) },
  );
}

export async function deleteVieProject(projectId: string): Promise<void> {
  await request(`/v1/vie/projects/${encodeURIComponent(projectId)}`, {
    method: 'DELETE',
    body: JSON.stringify({ confirmed: true }),
  });
}

/** Fixe l'ordre manuel des projets (leur rang = leur position dans `ids`). */
export async function reorderProjects(ids: string[]): Promise<void> {
  await request('/v1/vie/projects/ordre', { method: 'PUT', body: JSON.stringify({ ids }) });
}

export async function listVieHabits(date: string): Promise<VieHabit[]> {
  const payload = await request<{ habits: VieHabit[] }>(
    `/v1/vie/habits?date=${encodeURIComponent(date)}`,
  );
  return payload.habits;
}

export async function fetchVieHabitLogs(
  from: string,
  to: string,
  habitId?: string,
): Promise<Record<string, boolean>> {
  const params = new URLSearchParams({ from, to });
  if (habitId) params.set('habitId', habitId);
  const payload = await request<{ logs: Record<string, boolean> }>(
    `/v1/vie/habits/logs?${params.toString()}`,
  );
  return payload.logs;
}

export async function createVieHabit(input: {
  name: string;
  icon?: string;
  color?: string;
  frequency?: VieHabitFrequency;
  startDate?: string;
  endDate?: string;
  weeklyDays?: number[];
  monthWeekSlots?: Array<number | 'last'>;
  monthWeekDay?: number;
  reminderTime?: string;
}): Promise<VieHabit> {
  const payload = await request<{ habit: VieHabit }>('/v1/vie/habits', {
    method: 'POST',
    body: JSON.stringify(input),
  });
  return payload.habit;
}

export async function updateVieHabit(
  habitId: string,
  patch: Partial<Pick<VieHabit, 'name' | 'icon' | 'color' | 'frequency' | 'startDate' | 'endDate' | 'weeklyDays' | 'monthWeekSlots' | 'monthWeekDay' | 'reminderTime'>>,
): Promise<VieHabit> {
  const payload = await request<{ habit: VieHabit }>(
    `/v1/vie/habits/${encodeURIComponent(habitId)}`,
    { method: 'PATCH', body: JSON.stringify(patch) },
  );
  return payload.habit;
}

export async function setVieHabitDone(
  habitId: string,
  date: string,
  done: boolean,
): Promise<VieHabit> {
  const payload = await request<{ habit: VieHabit }>(
    `/v1/vie/habits/${encodeURIComponent(habitId)}/log`,
    { method: 'POST', body: JSON.stringify({ date, done }) },
  );
  return payload.habit;
}

export async function deleteVieHabit(habitId: string): Promise<void> {
  await request(`/v1/vie/habits/${encodeURIComponent(habitId)}`, {
    method: 'DELETE',
    body: JSON.stringify({ confirmed: true }),
  });
}

export async function listVieNotes(search = ''): Promise<VieNote[]> {
  const payload = await request<{ notes: VieNote[] }>(
    `/v1/vie/notes?search=${encodeURIComponent(search)}`,
  );
  return payload.notes;
}

export async function listVieNoteResumes(search = ''): Promise<VieNoteResume[]> {
  const payload = await request<{ notes: VieNoteResume[] }>(
    `/v1/vie/notes/resumes?search=${encodeURIComponent(search)}`,
  );
  return payload.notes;
}

export async function getVieNote(id: string): Promise<VieNote> {
  const payload = await request<{ note: VieNote }>(`/v1/vie/notes/${encodeURIComponent(id)}`);
  return payload.note;
}

export async function createVieNote(input: {
  title: string;
  content?: string;
  pageFormat?: VieNote['pageFormat'];
  pageSize?: VieNote['pageSize'];
  pageOrientation?: VieNote['pageOrientation'];
  pageMargins?: VieNote['pageMargins'];
  pageBackground?: VieNote['pageBackground'];
  fontFamily?: string;
  docLang?: VieNote['docLang'];
  color?: string;
  readingMark?: number;
  category?: string;
  projectId?: string;
}): Promise<VieNote> {
  const payload = await request<{ note: VieNote }>('/v1/vie/notes', {
    method: 'POST',
    body: JSON.stringify(input),
  });
  return payload.note;
}

export async function updateVieNote(
  noteId: string,
  patch: Partial<
    Pick<
      VieNote,
      | 'title'
      | 'content'
      | 'pageFormat'
      | 'pageSize'
      | 'pageOrientation'
      | 'pageMargins'
      | 'pageBackground'
      | 'fontFamily'
      | 'docLang'
      | 'color'
      | 'readingMark'
      | 'category'
      | 'projectId'
      | 'order'
    >
  > & { expectedContentHash?: string; appendContent?: string; opId?: string },
): Promise<VieNote> {
  const payload = await request<{ note: VieNote }>(
    `/v1/vie/notes/${encodeURIComponent(noteId)}`,
    { method: 'PATCH', body: JSON.stringify(patch) },
  );
  return payload.note;
}

/** Les catégories vivantes, dans l'ordre choisi par glisser. */
export async function listNoteCategories(): Promise<string[]> {
  const payload = await request<{ categories: string[] }>('/v1/vie/notes/categories');
  return payload.categories;
}

export async function orderNoteCategories(names: string[]): Promise<string[]> {
  const payload = await request<{ categories: string[] }>('/v1/vie/notes/categories/ordre', {
    method: 'PUT',
    body: JSON.stringify({ names }),
  });
  return payload.categories;
}

/** `nouveau` vide dissout la catégorie : ses notes redeviennent « sans catégorie ». */
export async function renameNoteCategory(ancien: string, nouveau: string): Promise<string[]> {
  const payload = await request<{ categories: string[] }>(
    '/v1/vie/notes/categories/renommer',
    { method: 'POST', body: JSON.stringify({ ancien, nouveau }) },
  );
  return payload.categories;
}

/** Fixe l'ordre manuel des notes citées (leur rang = leur position dans `ids`). */
export async function reorderNotes(ids: string[]): Promise<void> {
  await request('/v1/vie/notes/ordre', { method: 'PUT', body: JSON.stringify({ ids }) });
}

export async function deleteVieNote(noteId: string): Promise<void> {
  await request(`/v1/vie/notes/${encodeURIComponent(noteId)}`, {
    method: 'DELETE',
    body: JSON.stringify({ confirmed: true }),
  });
}

export function fetchVieDashboard(date: string): Promise<VieDashboard> {
  return request(`/v1/vie/dashboard?date=${encodeURIComponent(date)}`);
}

export async function listVieTemplates(): Promise<VieTemplate[]> {
  const payload = await request<{ templates: VieTemplate[] }>('/v1/vie/templates');
  return payload.templates;
}

export async function createVieTemplate(input: {
  title: string;
  emoji?: string;
  frequency: VieTemplateFrequency;
  weeklyDays?: number[];
  monthWeekSlots?: Array<number | 'last'>;
  monthWeekDow?: number;
  projectId?: string;
  priority?: ViePriority;
  templateKind?: VieTemplateKind;
  startDate: string;
  endDate: string;
  active?: boolean;
}): Promise<VieTemplate> {
  const payload = await request<{ template: VieTemplate }>('/v1/vie/templates', {
    method: 'POST',
    body: JSON.stringify(input),
  });
  return payload.template;
}

export async function updateVieTemplate(
  templateId: string,
  patch: Partial<Omit<VieTemplate, 'id' | 'createdAt' | 'updatedAtMs' | 'linkedHabitId'>>,
): Promise<VieTemplate> {
  const payload = await request<{ template: VieTemplate }>(
    `/v1/vie/templates/${encodeURIComponent(templateId)}`,
    { method: 'PATCH', body: JSON.stringify(patch) },
  );
  return payload.template;
}

export async function deleteVieTemplate(templateId: string): Promise<number> {
  const payload = await request<{ tasksDeleted: number }>(
    `/v1/vie/templates/${encodeURIComponent(templateId)}`,
    { method: 'DELETE', body: JSON.stringify({ confirmed: true }) },
  );
  return payload.tasksDeleted;
}

export async function materializeVieTemplates(
  startDate: string,
  endDate: string,
): Promise<number> {
  const payload = await request<{ count: number }>('/v1/vie/templates/materialize', {
    method: 'POST',
    body: JSON.stringify({ startDate, endDate }),
  });
  return payload.count;
}

export async function listVieQuotes(): Promise<VieQuote[]> {
  const payload = await request<{ quotes: VieQuote[] }>('/v1/vie/quotes');
  return payload.quotes;
}

export async function createVieQuote(input: {
  text: string;
  author?: string;
  category?: string;
}): Promise<VieQuote> {
  const payload = await request<{ quote: VieQuote }>('/v1/vie/quotes', {
    method: 'POST',
    body: JSON.stringify(input),
  });
  return payload.quote;
}

export async function deleteVieQuote(quoteId: string): Promise<void> {
  await request(`/v1/vie/quotes/${encodeURIComponent(quoteId)}`, {
    method: 'DELETE',
    body: JSON.stringify({ confirmed: true }),
  });
}

export function fetchVieYearReview(year: number, month?: number): Promise<VieYearReview> {
  const query = new URLSearchParams({ year: String(year) });
  if (month) query.set('month', String(month));
  return request(`/v1/vie/year-review?${query}`);
}

/**
 * L'export JSON de la vie. Rend le nom écrit, ou `null` si la personne a
 * renoncé dans le sélecteur du téléphone.
 *
 * 26/09/2026 : l'URL `blob:` était relâchée juste après le clic, ce qui
 * annule le téléchargement sous Safari, et le clic ne fait rien dans la
 * WebView d'Android — la page annonçait pourtant « téléchargé ».
 */
export async function downloadVieExport(): Promise<string | null> {
  const payload = await request<Record<string, unknown>>('/v1/vie/export');
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
  return enregistrerHorsBureau(blob, `diapason_${new Date().getFullYear()}.json`);
}

// ── Finances ─────────────────────────────────────────────────────────

export async function listFinanceAccounts(includeArchived = false): Promise<FinanceAccount[]> {
  const payload = await request<{ accounts: FinanceAccount[] }>(
    `/v1/vie/finances/accounts?includeArchived=${includeArchived}`,
  );
  return payload.accounts;
}

export async function createFinanceAccount(input: {
  name: string;
  type?: FinanceAccountType;
  openingBalance?: number;
  color?: string;
  icon?: string;
}): Promise<FinanceAccount> {
  const payload = await request<{ account: FinanceAccount }>('/v1/vie/finances/accounts', {
    method: 'POST',
    body: JSON.stringify(input),
  });
  return payload.account;
}

export async function updateFinanceAccount(
  accountId: string,
  patch: Partial<
    Pick<FinanceAccount, 'name' | 'type' | 'openingBalance' | 'color' | 'icon' | 'archived'>
  >,
): Promise<FinanceAccount> {
  const payload = await request<{ account: FinanceAccount }>(
    `/v1/vie/finances/accounts/${encodeURIComponent(accountId)}`,
    { method: 'PATCH', body: JSON.stringify(patch) },
  );
  return payload.account;
}

export async function deleteFinanceAccount(accountId: string): Promise<void> {
  await request(`/v1/vie/finances/accounts/${encodeURIComponent(accountId)}`, {
    method: 'DELETE',
    body: JSON.stringify({ confirmed: true }),
  });
}

export async function listFinanceCategories(kind?: FinanceCategoryKind): Promise<FinanceCategory[]> {
  const query = kind ? `?kind=${encodeURIComponent(kind)}` : '';
  const payload = await request<{ categories: FinanceCategory[] }>(
    `/v1/vie/finances/categories${query}`,
  );
  return payload.categories;
}

export async function createFinanceCategory(input: {
  name: string;
  kind?: FinanceCategoryKind;
  color?: string;
  icon?: string;
}): Promise<FinanceCategory> {
  const payload = await request<{ category: FinanceCategory }>('/v1/vie/finances/categories', {
    method: 'POST',
    body: JSON.stringify(input),
  });
  return payload.category;
}

export async function deleteFinanceCategory(categoryId: string): Promise<void> {
  await request(`/v1/vie/finances/categories/${encodeURIComponent(categoryId)}`, {
    method: 'DELETE',
    body: JSON.stringify({ confirmed: true }),
  });
}

export async function listFinanceTransactions(options: {
  from?: string;
  to?: string;
  accountId?: string;
  categoryId?: string;
  type?: FinanceTxnType;
  limit?: number;
} = {}): Promise<FinanceTransaction[]> {
  const query = new URLSearchParams();
  if (options.from) query.set('from_date', options.from);
  if (options.to) query.set('to_date', options.to);
  if (options.accountId) query.set('accountId', options.accountId);
  if (options.categoryId) query.set('categoryId', options.categoryId);
  if (options.type) query.set('type', options.type);
  if (options.limit !== undefined) query.set('limit', String(options.limit));
  const suffix = query.toString() ? `?${query}` : '';
  const payload = await request<{ transactions: FinanceTransaction[] }>(
    `/v1/vie/finances/transactions${suffix}`,
  );
  return payload.transactions;
}

export async function createFinanceTransaction(input: {
  accountId: string;
  type: FinanceTxnType;
  amount: number;
  date?: string;
  categoryId?: string;
  payee?: string;
  notes?: string;
  transferAccountId?: string;
  subscriptionId?: string;
}): Promise<FinanceTransaction> {
  const payload = await request<{ transaction: FinanceTransaction }>(
    '/v1/vie/finances/transactions',
    { method: 'POST', body: JSON.stringify(input) },
  );
  return payload.transaction;
}

export async function deleteFinanceTransaction(txnId: string): Promise<void> {
  await request(`/v1/vie/finances/transactions/${encodeURIComponent(txnId)}`, {
    method: 'DELETE',
    body: JSON.stringify({ confirmed: true }),
  });
}

export async function listFinanceSubscriptions(activeOnly = false): Promise<FinanceSubscription[]> {
  const payload = await request<{ subscriptions: FinanceSubscription[] }>(
    `/v1/vie/finances/subscriptions?activeOnly=${activeOnly}`,
  );
  return payload.subscriptions;
}

export async function createFinanceSubscription(input: {
  name: string;
  amount: number;
  cadence?: FinanceSubCadence;
  nextDueDate?: string;
  accountId?: string;
  categoryId?: string;
  reminderDays?: number;
  notes?: string;
}): Promise<FinanceSubscription> {
  const payload = await request<{ subscription: FinanceSubscription }>(
    '/v1/vie/finances/subscriptions',
    { method: 'POST', body: JSON.stringify(input) },
  );
  return payload.subscription;
}

export async function updateFinanceSubscription(
  subId: string,
  patch: Partial<
    Pick<
      FinanceSubscription,
      | 'name'
      | 'amount'
      | 'cadence'
      | 'nextDueDate'
      | 'accountId'
      | 'categoryId'
      | 'active'
      | 'reminderDays'
      | 'notes'
    >
  >,
): Promise<FinanceSubscription> {
  const payload = await request<{ subscription: FinanceSubscription }>(
    `/v1/vie/finances/subscriptions/${encodeURIComponent(subId)}`,
    { method: 'PATCH', body: JSON.stringify(patch) },
  );
  return payload.subscription;
}

export async function deleteFinanceSubscription(subId: string): Promise<void> {
  await request(`/v1/vie/finances/subscriptions/${encodeURIComponent(subId)}`, {
    method: 'DELETE',
    body: JSON.stringify({ confirmed: true }),
  });
}

export async function materializeFinanceSubscriptions(
  onDate?: string,
): Promise<{ created: FinanceTransaction[]; count: number }> {
  const query = onDate ? `?onDate=${encodeURIComponent(onDate)}` : '';
  return request(`/v1/vie/finances/subscriptions/materialize${query}`, {
    method: 'POST',
  });
}

export async function listFinanceBudgets(yearMonth?: string): Promise<FinanceBudget[]> {
  const query = yearMonth ? `?yearMonth=${encodeURIComponent(yearMonth)}` : '';
  const payload = await request<{ budgets: FinanceBudget[] }>(
    `/v1/vie/finances/budgets${query}`,
  );
  return payload.budgets;
}

export async function upsertFinanceBudget(input: {
  scope?: FinanceBudgetScope;
  categoryId?: string;
  yearMonth?: string;
  limit: number;
}): Promise<FinanceBudget> {
  const payload = await request<{ budget: FinanceBudget }>('/v1/vie/finances/budgets', {
    method: 'POST',
    body: JSON.stringify(input),
  });
  return payload.budget;
}

export async function deleteFinanceBudget(budgetId: string): Promise<void> {
  await request(`/v1/vie/finances/budgets/${encodeURIComponent(budgetId)}`, {
    method: 'DELETE',
    body: JSON.stringify({ confirmed: true }),
  });
}

export async function listFinanceGoals(): Promise<FinanceGoal[]> {
  const payload = await request<{ goals: FinanceGoal[] }>('/v1/vie/finances/goals');
  return payload.goals;
}

export async function createFinanceGoal(input: {
  name: string;
  target: number;
  current?: number;
  accountId?: string;
  deadline?: string;
  color?: string;
  icon?: string;
}): Promise<FinanceGoal> {
  const payload = await request<{ goal: FinanceGoal }>('/v1/vie/finances/goals', {
    method: 'POST',
    body: JSON.stringify(input),
  });
  return payload.goal;
}

export async function updateFinanceGoal(
  goalId: string,
  patch: Partial<
    Pick<FinanceGoal, 'name' | 'target' | 'current' | 'accountId' | 'deadline' | 'color' | 'icon'>
  >,
): Promise<FinanceGoal> {
  const payload = await request<{ goal: FinanceGoal }>(
    `/v1/vie/finances/goals/${encodeURIComponent(goalId)}`,
    { method: 'PATCH', body: JSON.stringify(patch) },
  );
  return payload.goal;
}

export async function deleteFinanceGoal(goalId: string): Promise<void> {
  await request(`/v1/vie/finances/goals/${encodeURIComponent(goalId)}`, {
    method: 'DELETE',
    body: JSON.stringify({ confirmed: true }),
  });
}

export function fetchFinanceOverview(
  period: FinancePeriod = 'month',
  anchor?: string,
): Promise<FinanceOverview> {
  const query = new URLSearchParams({ period });
  if (anchor) query.set('anchor', anchor);
  return request(`/v1/vie/finances/overview?${query}`);
}

export async function importFinanceCsv(input: {
  csvText: string;
  accountId: string;
  mapping?: Record<string, string>;
}): Promise<FinanceCsvImportSummary> {
  const payload = await request<{ summary: FinanceCsvImportSummary }>(
    '/v1/vie/finances/import/csv',
    { method: 'POST', body: JSON.stringify(input) },
  );
  return payload.summary;
}

// ── Piles de photos ──────────────────────────────────────────────────
// Tout passe en JSON base64 : la fenêtre Tauri refuse les corps binaires.

export async function listViePhotoPiles(projectId: string): Promise<ViePhotoPiles> {
  const payload = await request<ViePhotoPiles>(
    `/v1/vie/projects/${encodeURIComponent(projectId)}/photo-piles`,
  );
  return { piles: payload.piles, parTache: payload.parTache ?? {} };
}

export async function createViePhotoPile(
  projectId: string,
  name: string,
): Promise<ViePhotoPile> {
  const payload = await request<{ pile: ViePhotoPile }>(
    `/v1/vie/projects/${encodeURIComponent(projectId)}/photo-piles`,
    { method: 'POST', body: JSON.stringify({ name }) },
  );
  return payload.pile;
}

export async function updateViePhotoPile(
  pileId: string,
  patch: { name?: string; coverPhotoId?: string },
): Promise<ViePhotoPile> {
  const payload = await request<{ pile: ViePhotoPile }>(
    `/v1/vie/photo-piles/${encodeURIComponent(pileId)}`,
    { method: 'PATCH', body: JSON.stringify(patch) },
  );
  return payload.pile;
}

export async function deleteViePhotoPile(pileId: string): Promise<number> {
  const payload = await request<{ photos: number }>(
    `/v1/vie/photo-piles/${encodeURIComponent(pileId)}`,
    { method: 'DELETE', body: JSON.stringify({ confirmed: true }) },
  );
  return payload.photos;
}

export async function listViePhotos(
  pileId: string,
): Promise<{ pile: ViePhotoPile; photos: ViePhoto[] }> {
  return request(`/v1/vie/photo-piles/${encodeURIComponent(pileId)}/photos`);
}

export async function addViePhoto(
  pileId: string,
  envoi: ViePhotoEnvoi,
): Promise<ViePhoto> {
  const payload = await request<{ photo: ViePhoto }>(
    `/v1/vie/photo-piles/${encodeURIComponent(pileId)}/photos`,
    { method: 'POST', body: JSON.stringify(envoi) },
  );
  return payload.photo;
}

/** Ranger les photos d'une pile dans cet ordre ; les absentes suivent. */
export async function reorderViePhotos(
  pileId: string,
  photoIds: string[],
): Promise<ViePhoto[]> {
  const payload = await request<{ photos: ViePhoto[] }>(
    `/v1/vie/photo-piles/${encodeURIComponent(pileId)}/ordre`,
    { method: 'PUT', body: JSON.stringify({ photoIds }) },
  );
  return payload.photos;
}

export async function getViePhotoContenu(photoId: string): Promise<ViePhotoContenu> {
  return request(`/v1/vie/photos/${encodeURIComponent(photoId)}/contenu`);
}

export interface ViePhotoPatch {
  caption?: string;
  taskId?: string;
  pileId?: string;
  rotation?: number;
  crop?: VieCadre;
  /** Effacer le cadre : un `crop: null` se perdrait dans le JSON. */
  effacerCadre?: boolean;
  annotations?: VieAnnotation[];
  /** L'aperçu redessiné après une retouche, en JPEG base64. */
  thumbBase64?: string;
}

export async function updateViePhoto(
  photoId: string,
  patch: ViePhotoPatch,
): Promise<ViePhoto> {
  const payload = await request<{ photo: ViePhoto }>(
    `/v1/vie/photos/${encodeURIComponent(photoId)}`,
    { method: 'PATCH', body: JSON.stringify(patch) },
  );
  return payload.photo;
}

/** Lire le texte de la photo avec Vision et le garder (macOS seulement). */
export async function ocrViePhoto(photoId: string): Promise<ViePhoto> {
  const payload = await request<{ photo: ViePhoto }>(
    `/v1/vie/photos/${encodeURIComponent(photoId)}/ocr`,
    { method: 'POST', body: JSON.stringify({}) },
  );
  return payload.photo;
}

export async function rechercherViePhotos(
  projectId: string,
  q: string,
): Promise<Array<ViePhoto & { pileName: string }>> {
  const payload = await request<{ photos: Array<ViePhoto & { pileName: string }> }>(
    `/v1/vie/projects/${encodeURIComponent(projectId)}/photos/recherche?q=${encodeURIComponent(q)}`,
  );
  return payload.photos;
}

/** Écrire un export (PDF) à l'emplacement choisi dans le dialogue de l'app. */
export async function exporterVieFichier(
  path: string,
  dataBase64: string,
): Promise<{ path: string; bytes: number }> {
  return request('/v1/vie/photos/exporter', {
    method: 'POST',
    body: JSON.stringify({ path, dataBase64 }),
  });
}

export async function deleteViePhoto(photoId: string): Promise<void> {
  await request(`/v1/vie/photos/${encodeURIComponent(photoId)}`, {
    method: 'DELETE',
    body: JSON.stringify({ confirmed: true }),
  });
}
