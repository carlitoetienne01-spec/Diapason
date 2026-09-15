import { apiFetch } from '../../lib/api';
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
  SuccesDashboard,
  SuccesHabit,
  SuccesHabitFrequency,
  SuccesNote,
  SuccesPairingInvitation,
  SuccesPriority,
  SuccesProject,
  SuccesProjectKit,
  SuccesQuote,
  SuccesSyncRunResult,
  SuccesSyncStatus,
  SuccesTask,
  SuccesTemplate,
  SuccesTemplateFrequency,
  SuccesTemplateKind,
  SuccesYearReview,
  SuccesCadence,
  SuccesProjectStructure,
  SuccesStructureConfig,
  SuccesStructureInfo,
  SuccesTaskEdge,
  SuccesAnnotation,
  SuccesCadre,
  SuccesPhoto,
  SuccesPhotoContenu,
  SuccesPhotoEnvoi,
  SuccesPhotoPile,
  SuccesPhotoPiles,
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
        } else if (detail?.message) {
          message = detail.message;
        }
      } catch {
        // Keep the stable user-facing fallback; technical details stay in logs.
      }
      throw new Error(message);
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
  journal?: string;
  projectId?: string;
  parentTaskId?: string;
  category?: string;
  emoji?: string;
  stage?: string;
  cadence?: SuccesCadence | null;
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
    Pick<
      SuccesTask,
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
    >
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

export interface PlannerPastilles {
  startDate: string;
  endDate: string;
  days: Record<string, { open: number; done: number }>;
}

/** Les points du petit calendrier — exacts, récurrences projetées comprises. */
export function fetchPlannerPastilles(start: string, end: string): Promise<PlannerPastilles> {
  return request(
    `/v1/succes/planner/pastilles?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`,
  );
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

export async function listSuccesProjectKits(): Promise<SuccesProjectKit[]> {
  const payload = await request<{ kits: SuccesProjectKit[] }>('/v1/succes/project-kits');
  return payload.kits;
}

export async function listSuccesProjectStructures(): Promise<SuccesStructureInfo[]> {
  const payload = await request<{ structures: SuccesStructureInfo[] }>(
    '/v1/succes/project-structures',
  );
  return payload.structures;
}

export async function createSuccesProject(input: {
  name: string;
  description?: string;
  color?: string;
  icon?: string;
  startDate?: string;
  endDate?: string;
  structure?: SuccesProjectStructure;
  structureConfig?: SuccesStructureConfig;
  kitId?: string;
}): Promise<SuccesProject> {
  const payload = await request<{ project: SuccesProject }>('/v1/succes/projects', {
    method: 'POST',
    body: JSON.stringify(input),
  });
  return payload.project;
}

export async function updateSuccesProject(
  projectId: string,
  patch: Partial<
    Pick<
      SuccesProject,
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
): Promise<SuccesProject> {
  const payload = await request<{ project: SuccesProject }>(
    `/v1/succes/projects/${encodeURIComponent(projectId)}`,
    { method: 'PATCH', body: JSON.stringify(patch) },
  );
  return payload.project;
}

export async function listSuccesTaskEdges(projectId: string): Promise<SuccesTaskEdge[]> {
  const payload = await request<{ edges: SuccesTaskEdge[] }>(
    `/v1/succes/projects/${encodeURIComponent(projectId)}/edges`,
  );
  return payload.edges;
}

export async function createSuccesTaskEdge(
  projectId: string,
  fromTaskId: string,
  toTaskId: string,
): Promise<SuccesTaskEdge> {
  const payload = await request<{ edge: SuccesTaskEdge }>(
    `/v1/succes/projects/${encodeURIComponent(projectId)}/edges`,
    { method: 'POST', body: JSON.stringify({ fromTaskId, toTaskId }) },
  );
  return payload.edge;
}

export async function deleteSuccesTaskEdge(
  projectId: string,
  fromTaskId: string,
  toTaskId: string,
): Promise<void> {
  await request(
    `/v1/succes/projects/${encodeURIComponent(projectId)}/edges/${encodeURIComponent(fromTaskId)}/${encodeURIComponent(toTaskId)}`,
    { method: 'DELETE' },
  );
}

export async function resetSuccesProjectCycle(
  projectId: string,
): Promise<{ project: SuccesProject; reopened: number }> {
  return request<{ project: SuccesProject; reopened: number }>(
    `/v1/succes/projects/${encodeURIComponent(projectId)}/cycle/reset`,
    { method: 'POST', body: JSON.stringify({}) },
  );
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
  pageSize?: SuccesNote['pageSize'];
  pageOrientation?: SuccesNote['pageOrientation'];
  pageMargins?: SuccesNote['pageMargins'];
  pageBackground?: SuccesNote['pageBackground'];
  fontFamily?: string;
  docLang?: SuccesNote['docLang'];
  color?: string;
  readingMark?: number;
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
      | 'pageSize'
      | 'pageOrientation'
      | 'pageMargins'
      | 'pageBackground'
      | 'fontFamily'
      | 'docLang'
      | 'color'
      | 'readingMark'
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

// ── Finances ─────────────────────────────────────────────────────────

export async function listFinanceAccounts(includeArchived = false): Promise<FinanceAccount[]> {
  const payload = await request<{ accounts: FinanceAccount[] }>(
    `/v1/succes/finances/accounts?includeArchived=${includeArchived}`,
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
  const payload = await request<{ account: FinanceAccount }>('/v1/succes/finances/accounts', {
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
    `/v1/succes/finances/accounts/${encodeURIComponent(accountId)}`,
    { method: 'PATCH', body: JSON.stringify(patch) },
  );
  return payload.account;
}

export async function deleteFinanceAccount(accountId: string): Promise<void> {
  await request(`/v1/succes/finances/accounts/${encodeURIComponent(accountId)}`, {
    method: 'DELETE',
    body: JSON.stringify({ confirmed: true }),
  });
}

export async function listFinanceCategories(kind?: FinanceCategoryKind): Promise<FinanceCategory[]> {
  const query = kind ? `?kind=${encodeURIComponent(kind)}` : '';
  const payload = await request<{ categories: FinanceCategory[] }>(
    `/v1/succes/finances/categories${query}`,
  );
  return payload.categories;
}

export async function createFinanceCategory(input: {
  name: string;
  kind?: FinanceCategoryKind;
  color?: string;
  icon?: string;
}): Promise<FinanceCategory> {
  const payload = await request<{ category: FinanceCategory }>('/v1/succes/finances/categories', {
    method: 'POST',
    body: JSON.stringify(input),
  });
  return payload.category;
}

export async function deleteFinanceCategory(categoryId: string): Promise<void> {
  await request(`/v1/succes/finances/categories/${encodeURIComponent(categoryId)}`, {
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
    `/v1/succes/finances/transactions${suffix}`,
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
    '/v1/succes/finances/transactions',
    { method: 'POST', body: JSON.stringify(input) },
  );
  return payload.transaction;
}

export async function deleteFinanceTransaction(txnId: string): Promise<void> {
  await request(`/v1/succes/finances/transactions/${encodeURIComponent(txnId)}`, {
    method: 'DELETE',
    body: JSON.stringify({ confirmed: true }),
  });
}

export async function listFinanceSubscriptions(activeOnly = false): Promise<FinanceSubscription[]> {
  const payload = await request<{ subscriptions: FinanceSubscription[] }>(
    `/v1/succes/finances/subscriptions?activeOnly=${activeOnly}`,
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
    '/v1/succes/finances/subscriptions',
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
    `/v1/succes/finances/subscriptions/${encodeURIComponent(subId)}`,
    { method: 'PATCH', body: JSON.stringify(patch) },
  );
  return payload.subscription;
}

export async function deleteFinanceSubscription(subId: string): Promise<void> {
  await request(`/v1/succes/finances/subscriptions/${encodeURIComponent(subId)}`, {
    method: 'DELETE',
    body: JSON.stringify({ confirmed: true }),
  });
}

export async function materializeFinanceSubscriptions(
  onDate?: string,
): Promise<{ created: FinanceTransaction[]; count: number }> {
  const query = onDate ? `?onDate=${encodeURIComponent(onDate)}` : '';
  return request(`/v1/succes/finances/subscriptions/materialize${query}`, {
    method: 'POST',
  });
}

export async function listFinanceBudgets(yearMonth?: string): Promise<FinanceBudget[]> {
  const query = yearMonth ? `?yearMonth=${encodeURIComponent(yearMonth)}` : '';
  const payload = await request<{ budgets: FinanceBudget[] }>(
    `/v1/succes/finances/budgets${query}`,
  );
  return payload.budgets;
}

export async function upsertFinanceBudget(input: {
  scope?: FinanceBudgetScope;
  categoryId?: string;
  yearMonth?: string;
  limit: number;
}): Promise<FinanceBudget> {
  const payload = await request<{ budget: FinanceBudget }>('/v1/succes/finances/budgets', {
    method: 'POST',
    body: JSON.stringify(input),
  });
  return payload.budget;
}

export async function deleteFinanceBudget(budgetId: string): Promise<void> {
  await request(`/v1/succes/finances/budgets/${encodeURIComponent(budgetId)}`, {
    method: 'DELETE',
    body: JSON.stringify({ confirmed: true }),
  });
}

export async function listFinanceGoals(): Promise<FinanceGoal[]> {
  const payload = await request<{ goals: FinanceGoal[] }>('/v1/succes/finances/goals');
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
  const payload = await request<{ goal: FinanceGoal }>('/v1/succes/finances/goals', {
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
    `/v1/succes/finances/goals/${encodeURIComponent(goalId)}`,
    { method: 'PATCH', body: JSON.stringify(patch) },
  );
  return payload.goal;
}

export async function deleteFinanceGoal(goalId: string): Promise<void> {
  await request(`/v1/succes/finances/goals/${encodeURIComponent(goalId)}`, {
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
  return request(`/v1/succes/finances/overview?${query}`);
}

export async function importFinanceCsv(input: {
  csvText: string;
  accountId: string;
  mapping?: Record<string, string>;
}): Promise<FinanceCsvImportSummary> {
  const payload = await request<{ summary: FinanceCsvImportSummary }>(
    '/v1/succes/finances/import/csv',
    { method: 'POST', body: JSON.stringify(input) },
  );
  return payload.summary;
}

// ── Piles de photos ──────────────────────────────────────────────────
// Tout passe en JSON base64 : la fenêtre Tauri refuse les corps binaires.

export async function listSuccesPhotoPiles(projectId: string): Promise<SuccesPhotoPiles> {
  const payload = await request<SuccesPhotoPiles>(
    `/v1/succes/projects/${encodeURIComponent(projectId)}/photo-piles`,
  );
  return { piles: payload.piles, parTache: payload.parTache ?? {} };
}

export async function createSuccesPhotoPile(
  projectId: string,
  name: string,
): Promise<SuccesPhotoPile> {
  const payload = await request<{ pile: SuccesPhotoPile }>(
    `/v1/succes/projects/${encodeURIComponent(projectId)}/photo-piles`,
    { method: 'POST', body: JSON.stringify({ name }) },
  );
  return payload.pile;
}

export async function updateSuccesPhotoPile(
  pileId: string,
  patch: { name?: string; coverPhotoId?: string },
): Promise<SuccesPhotoPile> {
  const payload = await request<{ pile: SuccesPhotoPile }>(
    `/v1/succes/photo-piles/${encodeURIComponent(pileId)}`,
    { method: 'PATCH', body: JSON.stringify(patch) },
  );
  return payload.pile;
}

export async function deleteSuccesPhotoPile(pileId: string): Promise<number> {
  const payload = await request<{ photos: number }>(
    `/v1/succes/photo-piles/${encodeURIComponent(pileId)}`,
    { method: 'DELETE', body: JSON.stringify({ confirmed: true }) },
  );
  return payload.photos;
}

export async function listSuccesPhotos(
  pileId: string,
): Promise<{ pile: SuccesPhotoPile; photos: SuccesPhoto[] }> {
  return request(`/v1/succes/photo-piles/${encodeURIComponent(pileId)}/photos`);
}

export async function addSuccesPhoto(
  pileId: string,
  envoi: SuccesPhotoEnvoi,
): Promise<SuccesPhoto> {
  const payload = await request<{ photo: SuccesPhoto }>(
    `/v1/succes/photo-piles/${encodeURIComponent(pileId)}/photos`,
    { method: 'POST', body: JSON.stringify(envoi) },
  );
  return payload.photo;
}

/** Ranger les photos d'une pile dans cet ordre ; les absentes suivent. */
export async function reorderSuccesPhotos(
  pileId: string,
  photoIds: string[],
): Promise<SuccesPhoto[]> {
  const payload = await request<{ photos: SuccesPhoto[] }>(
    `/v1/succes/photo-piles/${encodeURIComponent(pileId)}/ordre`,
    { method: 'PUT', body: JSON.stringify({ photoIds }) },
  );
  return payload.photos;
}

export async function getSuccesPhotoContenu(photoId: string): Promise<SuccesPhotoContenu> {
  return request(`/v1/succes/photos/${encodeURIComponent(photoId)}/contenu`);
}

export interface SuccesPhotoPatch {
  caption?: string;
  taskId?: string;
  pileId?: string;
  rotation?: number;
  crop?: SuccesCadre;
  /** Effacer le cadre : un `crop: null` se perdrait dans le JSON. */
  effacerCadre?: boolean;
  annotations?: SuccesAnnotation[];
  /** L'aperçu redessiné après une retouche, en JPEG base64. */
  thumbBase64?: string;
}

export async function updateSuccesPhoto(
  photoId: string,
  patch: SuccesPhotoPatch,
): Promise<SuccesPhoto> {
  const payload = await request<{ photo: SuccesPhoto }>(
    `/v1/succes/photos/${encodeURIComponent(photoId)}`,
    { method: 'PATCH', body: JSON.stringify(patch) },
  );
  return payload.photo;
}

/** Lire le texte de la photo avec Vision et le garder (macOS seulement). */
export async function ocrSuccesPhoto(photoId: string): Promise<SuccesPhoto> {
  const payload = await request<{ photo: SuccesPhoto }>(
    `/v1/succes/photos/${encodeURIComponent(photoId)}/ocr`,
    { method: 'POST', body: JSON.stringify({}) },
  );
  return payload.photo;
}

export async function rechercherSuccesPhotos(
  projectId: string,
  q: string,
): Promise<Array<SuccesPhoto & { pileName: string }>> {
  const payload = await request<{ photos: Array<SuccesPhoto & { pileName: string }> }>(
    `/v1/succes/projects/${encodeURIComponent(projectId)}/photos/recherche?q=${encodeURIComponent(q)}`,
  );
  return payload.photos;
}

/** Écrire un export (PDF) à l'emplacement choisi dans le dialogue de l'app. */
export async function exporterSuccesFichier(
  path: string,
  dataBase64: string,
): Promise<{ path: string; bytes: number }> {
  return request('/v1/succes/photos/exporter', {
    method: 'POST',
    body: JSON.stringify({ path, dataBase64 }),
  });
}

export async function deleteSuccesPhoto(photoId: string): Promise<void> {
  await request(`/v1/succes/photos/${encodeURIComponent(photoId)}`, {
    method: 'DELETE',
    body: JSON.stringify({ confirmed: true }),
  });
}
