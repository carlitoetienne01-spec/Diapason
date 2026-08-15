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
  mode: 'local_only' | 'ready' | 'paired' | string;
  configured: boolean;
  deviceId: string;
  localCursor: number;
  peerCount: number;
  pendingPairings: number;
  transport: 'loopback_only' | string;
  peers: SuccesSyncPeer[];
  message: string;
}

export interface SuccesSyncPeer {
  id: string;
  deviceName: string;
  createdAtMs: number;
  lastSeenAtMs: number | null;
  lastPullCursor: number;
  lastPushAtMs: number | null;
}

export interface SuccesPairingInvitation {
  pairingToken: string;
  deviceName: string;
  expiresAtMs: number;
  expiresInSeconds: number;
}

export interface PlannerResponse {
  date: string;
  tasks: SuccesTask[];
  quote: SuccesQuote | null;
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
  tasks: {
    todayTotal: number;
    todayOpen: number;
    weekTotal: number;
    weekCompleted: number;
    weeklyCounts: number[];
  };
  habits: { due: number; completed: number; items: SuccesHabit[] };
  projects: SuccesProject[];
  notes: number;
  quote: SuccesQuote | null;
}

export type SuccesTemplateFrequency = 'daily' | 'weekly' | 'monthly';
export type SuccesTemplateKind = 'task' | 'habit';

export interface SuccesTemplate {
  id: string;
  title: string;
  emoji: string;
  frequency: SuccesTemplateFrequency;
  daysOfWeek: number[];
  weeklyDays: number[];
  monthWeekSlots: Array<number | 'last'>;
  monthWeekDow: number;
  projectId: string;
  priority: SuccesPriority;
  templateKind: SuccesTemplateKind;
  startDate: string;
  endDate: string;
  active: boolean;
  linkedHabitId: string;
  createdAt: string;
  updatedAtMs: number;
}

export interface SuccesQuote {
  id: string;
  text: string;
  author: string;
  category: string;
  updatedAtMs: number;
}

export interface SuccesYearReview {
  year: number;
  month: number | null;
  activityByMonth: number[];
  summary: {
    tasksCreated: number;
    tasksCompleted: number;
    habitsCompleted: number;
    projectsCreated: number;
    projectsCompleted: number;
  };
  catalog: {
    tasksCompletedAllTime: number;
    projects: number;
    habits: number;
    longestHabitStreak: number;
  };
}
