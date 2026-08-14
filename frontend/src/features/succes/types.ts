export type SuccesPriority = 'low' | 'medium' | 'high' | 'urgent';

export interface SuccesSubtask {
  id: string;
  title: string;
  done: boolean;
  isGroup: boolean;
  updatedAtMs: number;
  children: SuccesSubtask[];
}

export interface SuccesTask {
  id: string;
  title: string;
  done: boolean;
  priority: SuccesPriority;
  date: string;
  time: string;
  projectId: string;
  category: string;
  notes: string;
  emoji: string;
  createdAt: string;
  completedDate: string;
  postponedCount: number;
  updatedAtMs: number;
  subtasks: SuccesSubtask[];
}

export interface SuccesSyncStatus {
  mode: 'local_only' | string;
  configured: boolean;
  deviceId: string;
  localCursor: number;
  message: string;
}

export interface PlannerResponse {
  date: string;
  tasks: SuccesTask[];
  summary: { total: number; completed: number; open: number };
}
