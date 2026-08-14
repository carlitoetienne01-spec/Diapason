import { apiFetch } from '../../lib/api';
import type { PlannerResponse, SuccesPriority, SuccesSyncStatus, SuccesTask } from './types';

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await apiFetch(path, {
    ...init,
    headers: {
      ...(init.body ? { 'Content-Type': 'application/json' } : {}),
      ...((init.headers as Record<string, string> | undefined) ?? {}),
    },
  });
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
}): Promise<SuccesTask> {
  const payload = await request<{ task: SuccesTask }>('/v1/succes/tasks', {
    method: 'POST',
    body: JSON.stringify(input),
  });
  return payload.task;
}

export async function updateSuccesTask(
  taskId: string,
  patch: Partial<Pick<SuccesTask, 'title' | 'date' | 'time' | 'priority' | 'notes'>>,
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

export async function importLegacySuccesSnapshot(snapshot: unknown): Promise<{
  summary: { tasksImported: number; projectsImported: number; alreadyImported: boolean };
  message: string;
}> {
  return request('/v1/succes/import/legacy', {
    method: 'POST',
    body: JSON.stringify({ snapshot, source: 'Sauvegarde Life OS importée depuis Diapason' }),
  });
}
