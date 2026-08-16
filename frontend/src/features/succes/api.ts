import { apiFetch } from '../../lib/api';
import type {
  PlannerResponse,
  SuccesDashboard,
  SuccesHabit,
  SuccesHabitFrequency,
  SuccesNote,
  SuccesPairingInvitation,
  SuccesPriority,
  SuccesProject,
  SuccesQuote,
  SuccesSyncRunResult,
  SuccesSyncStatus,
  SuccesTask,
  SuccesTemplate,
  SuccesTemplateFrequency,
  SuccesTemplateKind,
  SuccesYearReview,
} from './types';

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
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
      if (attempt < 3) {
        await new Promise((resolve) => window.setTimeout(resolve, 250 * (attempt + 1)));
        continue;
      }
      const raw = error instanceof Error ? error.message : String(error);
      throw new Error(
        /load failed|failed to fetch|networkerror/i.test(raw)
          ? 'Connexion locale interrompue. Réessayez.'
          : /did not match the expected pattern|invalid url|failed to construct/i.test(raw)
            ? "L'URL de l'API est invalide. Vérifiez Réglages → Connexion → URL de l'API."
            : raw || 'Connexion locale impossible.',
      );
    }

    if (response.status === 429) {
      const retrySeconds = Number(response.headers.get('Retry-After') || attempt + 1);
      const delay = Math.min(2500, Math.max(300, retrySeconds * 1000));
      if (attempt < 3) {
        await new Promise((resolve) => window.setTimeout(resolve, delay));
        continue;
      }
      throw new Error('Trop de requêtes. Réessayez dans un instant.');
    }

    if (!response.ok) {
      let message = `Erreur Succès (${response.status})`;
      try {
        const payload = await response.json();
        const detail = payload?.detail;
        message =
          typeof detail === 'string'
            ? detail
            : detail?.message || message;
      } catch {
        // Keep the stable user-facing fallback; technical details stay in logs.
      }
      throw new Error(message);
    }

    return response.json() as Promise<T>;
  }

  throw lastError instanceof Error
    ? lastError
    : new Error('Connexion locale impossible.');
}

export async function listSuccesTasks(options: {
  date?: string;
  includeDone?: boolean;
  search?: string;
} = {}): Promise<SuccesTask[]> {
  const query = new URLSearchParams();
  if (options.date !== undefined) query.set('date', options.date);
  query.set('include_done', String(options.includeDone ?? true));
  if (options.search) query.set('search', options.search);
  const payload = await request<{ tasks: SuccesTask[] }>(`/v1/succes/tasks?${query}`);
  return payload.tasks;
}

export async function createSuccesTask(input: {
  title: string;
  date?: string;
  time?: string;
  priority?: SuccesPriority;
  notes?: string;
  projectId?: string;
  category?: string;
  emoji?: string;
}): Promise<SuccesTask> {
  const payload = await request<{ task: SuccesTask }>('/v1/succes/tasks', {
    method: 'POST',
    body: JSON.stringify(input),
  });
  return payload.task;
}

export async function updateSuccesTask(
  taskId: string,
  patch: Partial<
    Pick<SuccesTask, 'title' | 'date' | 'time' | 'priority' | 'notes' | 'projectId' | 'category' | 'emoji'>
  >,
): Promise<SuccesTask> {
  const payload = await request<{ task: SuccesTask }>(
    `/v1/succes/tasks/${encodeURIComponent(taskId)}`,
    { method: 'PATCH', body: JSON.stringify(patch) },
  );
  return payload.task;
}

export async function setSuccesTaskDone(taskId: string, done: boolean): Promise<SuccesTask> {
  const payload = await request<{ task: SuccesTask }>(
    `/v1/succes/tasks/${encodeURIComponent(taskId)}/done`,
    { method: 'POST', body: JSON.stringify({ done }) },
  );
  return payload.task;
}

export async function rescheduleSuccesTask(
  taskId: string,
  date: string,
): Promise<{ task: SuccesTask; warning: string | null }> {
  return request(`/v1/succes/tasks/${encodeURIComponent(taskId)}/reschedule`, {
    method: 'POST',
    body: JSON.stringify({ date }),
  });
}

export async function rescheduleSuccesSeries(
  taskId: string,
  date: string,
): Promise<{ templateId: string; deltaDays: number; updated: number }> {
  return request(`/v1/succes/tasks/${encodeURIComponent(taskId)}/reschedule-series`, {
    method: 'POST',
    body: JSON.stringify({ date }),
  });
}

export async function addSuccesSubtask(
  taskId: string,
  title: string,
  parentId?: string,
): Promise<SuccesTask> {
  const payload = await request<{ task: SuccesTask }>(
    `/v1/succes/tasks/${encodeURIComponent(taskId)}/subtasks`,
    { method: 'POST', body: JSON.stringify({ title, parentId: parentId || null }) },
  );
  return payload.task;
}

export async function setSuccesSubtaskDone(
  taskId: string,
  subtaskId: string,
  done: boolean,
): Promise<SuccesTask> {
  const payload = await request<{ task: SuccesTask }>(
    `/v1/succes/tasks/${encodeURIComponent(taskId)}/subtasks/${encodeURIComponent(subtaskId)}/done`,
    { method: 'POST', body: JSON.stringify({ done }) },
  );
  return payload.task;
}

export async function deleteSuccesSubtask(
  taskId: string,
  subtaskId: string,
): Promise<SuccesTask> {
  const payload = await request<{ task: SuccesTask }>(
    `/v1/succes/tasks/${encodeURIComponent(taskId)}/subtasks/${encodeURIComponent(subtaskId)}`,
    { method: 'DELETE', body: JSON.stringify({ confirmed: true }) },
  );
  return payload.task;
}

export async function deleteSuccesTask(taskId: string): Promise<void> {
  await request(`/v1/succes/tasks/${encodeURIComponent(taskId)}`, {
    method: 'DELETE',
    body: JSON.stringify({ confirmed: true }),
  });
}

export function fetchSuccesPlanner(date: string): Promise<PlannerResponse> {
  return request(`/v1/succes/planner?date=${encodeURIComponent(date)}`);
}

export function fetchSuccesSyncStatus(): Promise<SuccesSyncStatus> {
  return request('/v1/succes/sync/status');
}

export function createSuccesPairing(deviceName: string): Promise<SuccesPairingInvitation> {
  return request('/v1/succes/sync/pairings', {
    method: 'POST',
    body: JSON.stringify({ deviceName }),
  });
}

export async function revokeSuccesPeer(peerId: string): Promise<void> {
  await request(`/v1/succes/sync/peers/${encodeURIComponent(peerId)}`, {
    method: 'DELETE',
  });
}

export function setSuccesSyncRelay(url: string): Promise<SuccesSyncStatus> {
  return request('/v1/succes/sync/relay', {
    method: 'PUT',
    body: JSON.stringify({ url }),
  });
}

export function clearSuccesSyncRelay(): Promise<SuccesSyncStatus> {
  return request('/v1/succes/sync/relay', { method: 'DELETE' });
}

export function joinSuccesSync(input: {
  pairingToken: string;
  relayUrl?: string;
  deviceName?: string;
}): Promise<SuccesSyncStatus> {
  return request('/v1/succes/sync/join', {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export function runSuccesSync(): Promise<SuccesSyncRunResult> {
  return request('/v1/succes/sync/run', { method: 'POST' });
}

export function clearSuccesSyncGuest(): Promise<SuccesSyncStatus> {
  return request('/v1/succes/sync/guest', { method: 'DELETE' });
}

export async function importLegacySuccesSnapshot(snapshot: unknown): Promise<{
  summary: {
    tasksImported: number;
    projectsImported: number;
    habitsImported?: number;
    notesImported?: number;
    habitLogsImported?: number;
    alreadyImported: boolean;
  };
  message: string;
}> {
  return request('/v1/succes/import/legacy', {
    method: 'POST',
    body: JSON.stringify({ snapshot, source: 'Sauvegarde Life OS importée depuis Diapason' }),
  });
}

export async function listSuccesProjects(search = ''): Promise<SuccesProject[]> {
  const payload = await request<{ projects: SuccesProject[] }>(
    `/v1/succes/projects?search=${encodeURIComponent(search)}`,
  );
  return payload.projects;
}

export async function createSuccesProject(input: {
  name: string;
  description?: string;
  color?: string;
  icon?: string;
  startDate?: string;
  endDate?: string;
}): Promise<SuccesProject> {
  const payload = await request<{ project: SuccesProject }>('/v1/succes/projects', {
    method: 'POST',
    body: JSON.stringify(input),
  });
  return payload.project;
}

export async function updateSuccesProject(
  projectId: string,
  patch: Partial<Pick<SuccesProject, 'name' | 'description' | 'color' | 'icon' | 'startDate' | 'endDate'>>,
): Promise<SuccesProject> {
  const payload = await request<{ project: SuccesProject }>(
    `/v1/succes/projects/${encodeURIComponent(projectId)}`,
    { method: 'PATCH', body: JSON.stringify(patch) },
  );
  return payload.project;
}

export async function deleteSuccesProject(projectId: string): Promise<void> {
  await request(`/v1/succes/projects/${encodeURIComponent(projectId)}`, {
    method: 'DELETE',
    body: JSON.stringify({ confirmed: true }),
  });
}

export async function listSuccesHabits(date: string): Promise<SuccesHabit[]> {
  const payload = await request<{ habits: SuccesHabit[] }>(
    `/v1/succes/habits?date=${encodeURIComponent(date)}`,
  );
  return payload.habits;
}

export async function fetchSuccesHabitLogs(
  from: string,
  to: string,
  habitId?: string,
): Promise<Record<string, boolean>> {
  const params = new URLSearchParams({ from, to });
  if (habitId) params.set('habitId', habitId);
  const payload = await request<{ logs: Record<string, boolean> }>(
    `/v1/succes/habits/logs?${params.toString()}`,
  );
  return payload.logs;
}

export async function createSuccesHabit(input: {
  name: string;
  icon?: string;
  color?: string;
  frequency?: SuccesHabitFrequency;
  startDate?: string;
  endDate?: string;
  weeklyDays?: number[];
  monthWeekSlots?: Array<number | 'last'>;
  monthWeekDay?: number;
  reminderTime?: string;
}): Promise<SuccesHabit> {
  const payload = await request<{ habit: SuccesHabit }>('/v1/succes/habits', {
    method: 'POST',
    body: JSON.stringify(input),
  });
  return payload.habit;
}

export async function updateSuccesHabit(
  habitId: string,
  patch: Partial<Pick<SuccesHabit, 'name' | 'icon' | 'color' | 'frequency' | 'startDate' | 'endDate' | 'weeklyDays' | 'monthWeekSlots' | 'monthWeekDay' | 'reminderTime'>>,
): Promise<SuccesHabit> {
  const payload = await request<{ habit: SuccesHabit }>(
    `/v1/succes/habits/${encodeURIComponent(habitId)}`,
    { method: 'PATCH', body: JSON.stringify(patch) },
  );
  return payload.habit;
}

export async function setSuccesHabitDone(
  habitId: string,
  date: string,
  done: boolean,
): Promise<SuccesHabit> {
  const payload = await request<{ habit: SuccesHabit }>(
    `/v1/succes/habits/${encodeURIComponent(habitId)}/log`,
    { method: 'POST', body: JSON.stringify({ date, done }) },
  );
  return payload.habit;
}

export async function deleteSuccesHabit(habitId: string): Promise<void> {
  await request(`/v1/succes/habits/${encodeURIComponent(habitId)}`, {
    method: 'DELETE',
    body: JSON.stringify({ confirmed: true }),
  });
}

export async function listSuccesNotes(search = ''): Promise<SuccesNote[]> {
  const payload = await request<{ notes: SuccesNote[] }>(
    `/v1/succes/notes?search=${encodeURIComponent(search)}`,
  );
  return payload.notes;
}

export async function createSuccesNote(input: {
  title: string;
  content?: string;
  pageFormat?: SuccesNote['pageFormat'];
  pageBackground?: SuccesNote['pageBackground'];
  fontFamily?: string;
  docLang?: SuccesNote['docLang'];
  color?: string;
}): Promise<SuccesNote> {
  const payload = await request<{ note: SuccesNote }>('/v1/succes/notes', {
    method: 'POST',
    body: JSON.stringify(input),
  });
  return payload.note;
}

export async function updateSuccesNote(
  noteId: string,
  patch: Partial<
    Pick<
      SuccesNote,
      | 'title'
      | 'content'
      | 'pageFormat'
      | 'pageBackground'
      | 'fontFamily'
      | 'docLang'
      | 'color'
    >
  >,
): Promise<SuccesNote> {
  const payload = await request<{ note: SuccesNote }>(
    `/v1/succes/notes/${encodeURIComponent(noteId)}`,
    { method: 'PATCH', body: JSON.stringify(patch) },
  );
  return payload.note;
}

export async function deleteSuccesNote(noteId: string): Promise<void> {
  await request(`/v1/succes/notes/${encodeURIComponent(noteId)}`, {
    method: 'DELETE',
    body: JSON.stringify({ confirmed: true }),
  });
}

export function fetchSuccesDashboard(date: string): Promise<SuccesDashboard> {
  return request(`/v1/succes/dashboard?date=${encodeURIComponent(date)}`);
}

export async function listSuccesTemplates(): Promise<SuccesTemplate[]> {
  const payload = await request<{ templates: SuccesTemplate[] }>('/v1/succes/templates');
  return payload.templates;
}

export async function createSuccesTemplate(input: {
  title: string;
  emoji?: string;
  frequency: SuccesTemplateFrequency;
  weeklyDays?: number[];
  monthWeekSlots?: Array<number | 'last'>;
  monthWeekDow?: number;
  projectId?: string;
  priority?: SuccesPriority;
  templateKind?: SuccesTemplateKind;
  startDate: string;
  endDate: string;
  active?: boolean;
}): Promise<SuccesTemplate> {
  const payload = await request<{ template: SuccesTemplate }>('/v1/succes/templates', {
    method: 'POST',
    body: JSON.stringify(input),
  });
  return payload.template;
}

export async function updateSuccesTemplate(
  templateId: string,
  patch: Partial<Omit<SuccesTemplate, 'id' | 'createdAt' | 'updatedAtMs' | 'linkedHabitId'>>,
): Promise<SuccesTemplate> {
  const payload = await request<{ template: SuccesTemplate }>(
    `/v1/succes/templates/${encodeURIComponent(templateId)}`,
    { method: 'PATCH', body: JSON.stringify(patch) },
  );
  return payload.template;
}

export async function deleteSuccesTemplate(templateId: string): Promise<number> {
  const payload = await request<{ tasksDeleted: number }>(
    `/v1/succes/templates/${encodeURIComponent(templateId)}`,
    { method: 'DELETE', body: JSON.stringify({ confirmed: true }) },
  );
  return payload.tasksDeleted;
}

export async function materializeSuccesTemplates(
  startDate: string,
  endDate: string,
): Promise<number> {
  const payload = await request<{ count: number }>('/v1/succes/templates/materialize', {
    method: 'POST',
    body: JSON.stringify({ startDate, endDate }),
  });
  return payload.count;
}

export async function listSuccesQuotes(): Promise<SuccesQuote[]> {
  const payload = await request<{ quotes: SuccesQuote[] }>('/v1/succes/quotes');
  return payload.quotes;
}

export async function createSuccesQuote(input: {
  text: string;
  author?: string;
  category?: string;
}): Promise<SuccesQuote> {
  const payload = await request<{ quote: SuccesQuote }>('/v1/succes/quotes', {
    method: 'POST',
    body: JSON.stringify(input),
  });
  return payload.quote;
}

export async function deleteSuccesQuote(quoteId: string): Promise<void> {
  await request(`/v1/succes/quotes/${encodeURIComponent(quoteId)}`, {
    method: 'DELETE',
    body: JSON.stringify({ confirmed: true }),
  });
}

export function fetchSuccesYearReview(year: number, month?: number): Promise<SuccesYearReview> {
  const query = new URLSearchParams({ year: String(year) });
  if (month) query.set('month', String(month));
  return request(`/v1/succes/year-review?${query}`);
}

export async function downloadSuccesExport(): Promise<void> {
  const payload = await request<Record<string, unknown>>('/v1/succes/export');
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `succes_${new Date().getFullYear()}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}
