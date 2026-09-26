export type ViePriority = 'low' | 'medium' | 'high' | 'urgent';

/** Les cinq formes qu'un projet peut prendre, plus la liste simple. */
export type VieProjectStructure =
  | 'flat'
  | 'tree'
  | 'mindmap'
  | 'pipeline'
  | 'network'
  | 'cycle';

/** Réglages propres à une forme : étages nommés de l'arbre, étapes du pipeline. */
export interface VieStructureConfig {
  levelLabels?: string[];
  stages?: string[];
  /**
   * Arbre et carte : les tâches d'une même fratrie s'ouvrent une par une.
   * Le magasin refuse de cocher une tâche verrouillée ; ce drapeau ne sert
   * qu'à l'afficher avant le clic (voir `verrou.ts`).
   */
  sequential?: boolean;
}

/** La cadence d'une tâche de cycle : jour = 0..6 (semaine) ou 1..28 (mois). */
export interface VieCadence {
  every: 'day' | 'week' | 'month';
  day?: number;
}

/** Une synapse du réseau : « from débloque to ». */
export interface VieTaskEdge {
  projectId: string;
  fromTaskId: string;
  toTaskId: string;
  updatedAtMs: number;
}

/** Une entrée du catalogue de formes, pour le sélecteur de création. */
export interface VieStructureInfo {
  id: VieProjectStructure;
  name: string;
  icon: string;
  description: string;
}

export interface VieSubtask {
  id: string;
  title: string;
  done: boolean;
  isGroup: boolean;
  updatedAtMs: number;
  children: VieSubtask[];
}

export interface VieTask {
  id: string;
  title: string;
  done: boolean;
  priority: ViePriority;
  date: string;
  time: string;
  projectId: string;
  parentTaskId: string;
  category: string;
  /** La consigne de l'étape : objectif, lien, ce qui vient ensuite. Lue AVANT. */
  notes: string;
  /**
   * Le CARNET de la tâche, distinct de `notes`. Écrit PENDANT : ce qu'on a
   * compris, où l'on bloque, ce qu'on a essayé. Les mélanger obligerait à
   * effacer la consigne pour noter un doute.
   */
  journal?: string;
  emoji: string;
  templateId: string;
  groupId: string;
  /** Rang d'affichage parmi les sœurs — l'API l'a toujours envoyé, le type l'ignorait. */
  order: number;
  createdAt: string;
  completedDate: string;
  postponedCount: number;
  updatedAtMs: number;
  stage: string;
  cadence: VieCadence | null;
  /**
   * La durée estimée en jours, un ENTIER (18 sept. 2026) — jamais un
   * flottant, le client Dart signe des enveloppes canoniques où `1e-07`
   * et `1e-7` divergent. 0 = pas d'estimation : le réseau ne parle de
   * « chemin critique » que lorsqu'une durée existe (§5).
   */
  estimateDays: number;
  subtasks: VieSubtask[];
}

export interface VieSyncStatus {
  mode: 'local_only' | 'ready' | 'paired' | string;
  role?: 'ready' | 'host' | 'guest' | string;
  configured: boolean;
  deviceId: string;
  localCursor: number;
  peerCount: number;
  pendingPairings: number;
  transport: 'loopback_only' | 'https_relay' | string;
  relayUrl?: string;
  guest?: VieSyncGuestSession | null;
  lastSyncAtMs?: number | null;
  lastSyncError?: string | null;
  peers: VieSyncPeer[];
  message: string;
  joined?: {
    peerId: string;
    deviceName: string;
    serverDeviceId?: string;
    relayUrl: string;
  };
}

export interface VieSyncGuestSession {
  peerId: string;
  deviceName: string;
  serverDeviceId: string;
  pullCursor: number;
  pushCursor: number;
  hasToken: boolean;
}

export interface VieSyncPeer {
  id: string;
  deviceName: string;
  createdAtMs: number;
  lastSeenAtMs: number | null;
  lastPullCursor: number;
  lastPushAtMs: number | null;
}

export interface ViePairingInvitation {
  pairingToken: string;
  deviceName: string;
  expiresAtMs: number;
  expiresInSeconds: number;
}

export interface VieSyncRunResult {
  pushed: number;
  pulled: number;
  received: { applied: number; stale: number; duplicate: number };
  pullCursor: number;
  pushCursor: number;
  hasMore: boolean;
  syncedAtMs: number;
  status: VieSyncStatus;
}

export interface PlannerResponse {
  date: string;
  tasks: VieTask[];
  quote: VieQuote | null;
  summary: { total: number; completed: number; open: number };
}

export interface VieProject {
  id: string;
  name: string;
  description: string;
  color: string;
  icon: string;
  startDate: string;
  endDate: string;
  structure: VieProjectStructure;
  structureConfig: VieStructureConfig;
  createdAt: string;
  updatedAtMs: number;
  /** Le rang manuel du projet dans la grille. */
  order?: number;
  taskTotal: number;
  taskCompleted: number;
}

export interface VieProjectKit {
  id: string;
  name: string;
  description: string;
  icon: string;
  structure: VieProjectStructure;
  nodeCount: number;
}

export type VieHabitFrequency = 'daily' | 'weekly' | 'monthly';

export interface VieHabit {
  id: string;
  name: string;
  icon: string;
  color: string;
  frequency: VieHabitFrequency;
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

export type VieNotePageFormat =
  | 'a4'
  | 'letter'
  | 'a5'
  | 'wide'
  | 'narrow'
  | 'full'
  | 'reading';

/**
 * Les trois axes de « Mise en page » de Word, séparés comme chez lui.
 *
 * `VieNotePageFormat` ci-dessus reste : c'est la colonne héritée, et les
 * notes déjà enregistrées la portent. Elle se décompose en ces trois-ci à la
 * lecture — voir `decomposeLegacyFormat` dans `noteFormats.ts`.
 *
 * Les CHAMPS voyagent en anglais camelCase (`pageSize`, `pageOrientation`,
 * `pageMargins`) ; les VALEURS sont des libellés produit, donc en français,
 * comme `pageBackground: 'sepia'` l'est déjà.
 */
export type VieNotePageSize = 'a4' | 'letter' | 'legal' | 'a5' | 'executive';

export type VieNotePageOrientation = 'portrait' | 'paysage';

export type VieNotePageMargins = 'normales' | 'etroites' | 'moderees' | 'larges';

export type VieNotePageBackground =
  | 'default'
  | 'lined'
  | 'grid'
  | 'sepia'
  | 'dark';

export type VieNoteDocLang = 'fr' | 'ht';

export interface VieNote {
  contentHash?: string;
  id: string;
  title: string;
  content: string;
  createdAt: string;
  updatedAt: string;
  updatedAtMs: number;
  pageFormat: VieNotePageFormat;
  pageSize?: VieNotePageSize;
  pageOrientation?: VieNotePageOrientation;
  pageMargins?: VieNotePageMargins;
  pageBackground: VieNotePageBackground;
  fontFamily: string;
  docLang: VieNoteDocLang;
  color: string;
  /**
   * La page où l'on s'est arrêté de lire. Zéro : aucun marqueur.
   *
   * Une DONNÉE de la note, pas un état d'affichage : il doit survivre à la
   * fermeture de l'application et suivre la note, pas la machine.
   */
  readingMark?: number;
  /** Le classement choisi par l'utilisateur ; vide : « sans catégorie ». */
  category?: string;
  /** Le projet auquel la note est rattachée ; vide : aucun. */
  projectId?: string;
  /** Le rang manuel dans sa section ; le mode « Mon ordre » s'en sert. */
  order?: number;
}

/** Le cartable ne possède pas le document : il faut le lire avant d'éditer. */
export type VieNoteResume = Omit<VieNote, 'content'> & { pageCountEstimate: number };

export interface VieDashboard {
  date: string;
  tasks: {
    todayTotal: number;
    todayOpen: number;
    weekTotal: number;
    weekCompleted: number;
    weeklyCounts: number[];
  };
  habits: { due: number; completed: number; items: VieHabit[] };
  projects: VieProject[];
  notes: number;
  quote: VieQuote | null;
}

export type VieTemplateFrequency = 'daily' | 'weekly' | 'monthly';
export type VieTemplateKind = 'task' | 'habit';

export interface VieTemplate {
  id: string;
  title: string;
  emoji: string;
  frequency: VieTemplateFrequency;
  daysOfWeek: number[];
  weeklyDays: number[];
  monthWeekSlots: Array<number | 'last'>;
  monthWeekDow: number;
  projectId: string;
  priority: ViePriority;
  templateKind: VieTemplateKind;
  startDate: string;
  endDate: string;
  active: boolean;
  linkedHabitId: string;
  createdAt: string;
  updatedAtMs: number;
}

export interface VieQuote {
  id: string;
  text: string;
  author: string;
  category: string;
  updatedAtMs: number;
}

export interface VieYearReview {
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

/** Une photo d'une pile, telle que le serveur la décrit. `thumb` est une URL de données JPEG. */
export interface ViePhoto {
  id: string;
  pileId: string;
  projectId: string;
  fileName: string;
  mime: string;
  bytes: number;
  width: number;
  height: number;
  /** `#rrggbb` extrait de l'image par le navigateur à l'import, ou vide. */
  tint: string;
  caption: string;
  /** La tâche du projet vers laquelle la photo pointe, ou vide. */
  taskId: string;
  /** Le rang rangé à la main ; 0 si jamais rangée, négatif si ajoutée après. */
  position: number;
  /** Retouche non destructive : rotation (0/90/180/270) puis cadre, en fractions. */
  rotation: number;
  crop: VieCadre | null;
  /** Le calque d'annotations, coordonnées en fractions de l'image retouchée. */
  annotations: VieAnnotation[];
  /** Le texte lu par Vision, ou vide. */
  ocrText: string;
  thumb: string;
  createdAtMs: number;
  updatedAtMs: number;
}

/** Un cadre de recadrage en fractions [0,1] de l'image (après rotation). */
export interface VieCadre {
  x: number;
  y: number;
  w: number;
  h: number;
}

export type VieAnnotationType = 'arrow' | 'rect' | 'ellipse' | 'text' | 'highlight' | 'pen';

/** Une forme posée sur la photo ; `points` en fractions de l'image affichée. */
export interface VieAnnotation {
  id: string;
  type: VieAnnotationType;
  color: string;
  points: Array<[number, number]>;
  text?: string;
  width: number;
}

/** Une catégorie de photos : la pile fermée, avec ses trois aperçus. */
export interface ViePhotoPile {
  id: string;
  projectId: string;
  name: string;
  coverPhotoId: string;
  tint: string;
  count: number;
  /** La couverture d'abord, puis les premières de l'ordre — au plus trois. */
  apercus: ViePhoto[];
  createdAtMs: number;
  updatedAtMs: number;
}

export interface ViePhotoPiles {
  piles: ViePhotoPile[];
  /** Combien de photos pointent vers chaque tâche du projet. */
  parTache: Record<string, number>;
}

/** Ce que le navigateur prépare avant l'envoi : l'original et son aperçu. */
export interface ViePhotoEnvoi {
  fileName: string;
  dataBase64: string;
  thumbBase64: string;
  width: number;
  height: number;
  tint: string;
  caption?: string;
  taskId?: string;
}

export interface ViePhotoContenu {
  id: string;
  mime: string;
  fileName: string;
  dataBase64: string;
}
