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

export interface SuccesProject {
  id: string;
  name: string;
  description: string;
  color: string;
  icon: string;
  startDate: string;
  endDate: string;
  createdAt: string;
  updatedAtMs: number;
  taskTotal: number;
  taskCompleted: number;
}

export type SuccesHabitFrequency = 'daily' | 'weekly' | 'monthly';

export interface SuccesHabit {
  id: string;
  name: string;
  icon: string;
  color: string;
  frequency: SuccesHabitFrequency;
  createdAt: string;
  startDate: string;
  endDate: string;
  weeklyDays: number[];
  monthWeekSlots: Array<number | 'last'>;
  monthWeekDay: number;
  reminderTime: string;
  updatedAtMs: number;
  date: string;
  due: boolean;
  done: boolean;
  streak: number;
}

export interface SuccesNote {
  id: string;
  title: string;
  content: string;
  createdAt: string;
  updatedAt: string;
  updatedAtMs: number;
}

export interface SuccesDashboard {
  date: string;
  tasks: { total: number; completed: number };
  habits: { due: number; completed: number };
  projects: number;
  notes: number;
}
