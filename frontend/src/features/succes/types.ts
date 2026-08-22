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
  parentTaskId: string;
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
  structure: 'flat' | 'tree';
  createdAt: string;
  updatedAtMs: number;
  taskTotal: number;
  taskCompleted: number;
}

export interface SuccesProjectKit {
  id: string;
  name: string;
  description: string;
  icon: string;
  nodeCount: number;
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

export type FinancePeriod = 'day' | 'week' | 'month' | 'year';
export type FinanceAccountType = 'checking' | 'savings' | 'cash' | 'credit' | 'other';
export type FinanceCategoryKind = 'income' | 'expense';
export type FinanceTxnType = 'income' | 'expense' | 'transfer';
export type FinanceSubCadence = 'weekly' | 'monthly' | 'yearly';
export type FinanceBudgetScope = 'global' | 'category';

export interface FinanceAccount {
  id: string;
  name: string;
  type: FinanceAccountType;
  currency: string;
  openingBalance: number;
  balance?: number;
  color: string;
  icon: string;
  archived: boolean;
  updatedAtMs: number;
}

export interface FinanceCategory {
  id: string;
  name: string;
  kind: FinanceCategoryKind;
  color: string;
  icon: string;
  system: boolean;
  updatedAtMs: number;
}

export interface FinanceTransaction {
  id: string;
  accountId: string;
  categoryId: string;
  type: FinanceTxnType;
  amount: number;
  currency: string;
  date: string;
  payee: string;
  notes: string;
  transferAccountId: string;
  subscriptionId: string;
  updatedAtMs: number;
}

export interface FinanceSubscription {
  id: string;
  name: string;
  amount: number;
  currency: string;
  cadence: FinanceSubCadence;
  nextDueDate: string;
  accountId: string;
  categoryId: string;
  active: boolean;
  reminderDays: number;
  notes: string;
  updatedAtMs: number;
}

export interface FinanceBudget {
  id: string;
  scope: FinanceBudgetScope;
  categoryId: string;
  yearMonth: string;
  limit: number;
  currency: string;
  updatedAtMs: number;
  spent?: number;
  remaining?: number;
  pct?: number;
  over?: boolean;
}

export interface FinanceGoal {
  id: string;
  name: string;
  target: number;
  current: number;
  currency: string;
  accountId: string;
  deadline: string;
  color: string;
  icon: string;
  updatedAtMs: number;
}

export interface FinanceCategoryBreakdown {
  categoryId: string;
  name: string;
  icon: string;
  color: string;
  amount: number;
}

export interface FinanceSeriesPoint {
  date: string;
  income: number;
  expense: number;
}

export interface FinanceOverview {
  period: FinancePeriod;
  from: string;
  to: string;
  currency: string;
  income: number;
  expense: number;
  net: number;
  prevIncome: number;
  prevExpense: number;
  prevNet: number;
  categoryBreakdown: FinanceCategoryBreakdown[];
  series: FinanceSeriesPoint[];
  forecastExpense: number;
  forecastRemaining: number;
  budgets: FinanceBudget[];
  accounts: FinanceAccount[];
  upcomingSubscriptions: FinanceSubscription[];
  goals: FinanceGoal[];
  transactionCount: number;
}

export interface FinanceCsvImportSummary {
  created: number;
  skipped: number;
  errors: string[];
}
