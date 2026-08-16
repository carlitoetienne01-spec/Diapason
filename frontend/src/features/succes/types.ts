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
  templateId: string;
  groupId: string;
  createdAt: string;
  completedDate: string;
  postponedCount: number;
  updatedAtMs: number;
  subtasks: SuccesSubtask[];
}

export interface SuccesSyncStatus {
  mode: 'local_only' | 'ready' | 'paired' | string;
  role?: 'ready' | 'host' | 'guest' | string;
  configured: boolean;
  deviceId: string;
  localCursor: number;
  peerCount: number;
  pendingPairings: number;
  transport: 'loopback_only' | 'https_relay' | string;
  relayUrl?: string;
  guest?: SuccesSyncGuestSession | null;
  lastSyncAtMs?: number | null;
  lastSyncError?: string | null;
  peers: SuccesSyncPeer[];
  message: string;
  joined?: {
    peerId: string;
    deviceName: string;
    serverDeviceId?: string;
    relayUrl: string;
  };
}

export interface SuccesSyncGuestSession {
  peerId: string;
  deviceName: string;
  serverDeviceId: string;
  pullCursor: number;
  pushCursor: number;
  hasToken: boolean;
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

export interface SuccesSyncRunResult {
  pushed: number;
  pulled: number;
  received: { applied: number; stale: number; duplicate: number };
  pullCursor: number;
  pushCursor: number;
  hasMore: boolean;
  syncedAtMs: number;
  status: SuccesSyncStatus;
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

export type SuccesNotePageFormat =
  | 'a4'
  | 'letter'
  | 'a5'
  | 'wide'
  | 'narrow'
  | 'full'
  | 'reading';

export type SuccesNotePageBackground =
  | 'default'
  | 'lined'
  | 'grid'
  | 'sepia'
  | 'dark';

export type SuccesNoteDocLang = 'fr' | 'ht';

export interface SuccesNote {
  id: string;
  title: string;
  content: string;
  createdAt: string;
  updatedAt: string;
  updatedAtMs: number;
  pageFormat: SuccesNotePageFormat;
  pageBackground: SuccesNotePageBackground;
  fontFamily: string;
  docLang: SuccesNoteDocLang;
  color: string;
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
