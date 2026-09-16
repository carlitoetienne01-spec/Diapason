import { create } from 'zustand';

import { modeleInitial } from './modelePrefere';
import type {
  Conversation,
  ChatMessage,
  LiveEnergyMetrics,
  LogEntry,
  ModelInfo,
  MessageTelemetry,
  ResearchSearchTrace,
  ResearchSource,
  SavingsData,
  ServerInfo,
  StreamState,
  ToolCallInfo,
  TokenUsage,
} from '../types';
import type { ManagedAgent } from './api';

export interface CachedConnector {
  connector_id: string;
  display_name: string;
  connected: boolean;
  chunks: number;
}

export interface AgentEvent {
  type: string;
  timestamp: number;
  data: Record<string, unknown>;
}

// ── localStorage persistence ──────────────────────────────────────────

const CONVERSATIONS_KEY = 'diapason-conversations';
const SETTINGS_KEY = 'diapason-settings';
const SYSTEM_PANEL_KEY = 'diapason-system-panel-open';

/** Drop leftover contest / leaderboard keys from older installs. */
function wipeLegacyLeaderboardKeys() {
  if (typeof localStorage === 'undefined') return;
  for (const key of [
    'diapason-optin',
    'diapason-display-name',
    'diapason-email',
    'diapason-anon-id',
    'diapason-optin-seen',
    'diapason-desktop-optin',
    'diapason-desktop-display-name',
    'diapason-desktop-email',
    'diapason-desktop-anon-id',
  ]) {
    localStorage.removeItem(key);
  }
}
wipeLegacyLeaderboardKeys();

interface ConversationStore {
  version: 1;
  conversations: Record<string, Conversation>;
  activeId: string | null;
}

function generateId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}

/** Absent on a fresh install, so the panel opens by default and stays shut only
 * once the user has actually shut it. */
function loadSystemPanelOpen(): boolean {
  try {
    return localStorage.getItem(SYSTEM_PANEL_KEY) !== 'false';
  } catch {
    return true;
  }
}

function saveSystemPanelOpen(open: boolean): void {
  try {
    localStorage.setItem(SYSTEM_PANEL_KEY, open ? 'true' : 'false');
  } catch {
    /* private mode or quota: the panel simply won't be remembered */
  }
}

function loadConversations(): ConversationStore {
  try {
    const raw = localStorage.getItem(CONVERSATIONS_KEY);
    if (!raw) return { version: 1, conversations: {}, activeId: null };
    const parsed = JSON.parse(raw);
    if (parsed.version === 1) return parsed;
    return { version: 1, conversations: {}, activeId: null };
  } catch {
    return { version: 1, conversations: {}, activeId: null };
  }
}

function saveConversations(store: ConversationStore): void {
  try {
    localStorage.setItem(CONVERSATIONS_KEY, JSON.stringify(store));
  } catch {
    // 16 sept. 2026 : un QuotaExceededError se propageait nu jusqu'au
    // gestionnaire d'événement appelant — l'envoi du message plantait alors
    // que la conversation, elle, existait bien en mémoire.
  }
  // Toujours émettre, même quand l'écriture a échoué : le moteur de sync
  // (convSync.ts, qui écoute — jamais importé d'ici, sens unique) pousse
  // alors vers le serveur, devenu le seul exemplaire fiable.
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('diapason:conversations-modifiees'));
  }
}

export type ThemeMode = 'light' | 'dark' | 'system' | 'terminal';

/**
 * Screen types within the terminal theme. They swap the palette only — the
 * pixel type, square corners and panel grammar are the theme's, not the
 * screen's. `ardechine` is the odd one: a reflective LCD, so it is the single
 * light member of the family and is applied alongside `.light`.
 */
export type TerminalSkin = 'phosphor' | 'ardechine' | 'oxblood' | 'sage';

export const TERMINAL_SKINS: TerminalSkin[] = [
  'phosphor',
  'ardechine',
  'oxblood',
  'sage',
];

/** The one screen that is dark ink on a pale panel rather than light on black. */
export function isLightTerminalSkin(skin: TerminalSkin): boolean {
  return skin === 'ardechine';
}

interface Settings {
  theme: ThemeMode;
  terminalSkin: TerminalSkin;
  apiUrl: string;
  // Local server API key (DIAPASON_API_KEY). Sent as a Bearer token on
  // /v1 + /api requests so a key-protected `diapason serve` doesn't 401 the
  // frontend. It is kept in sessionStorage, never persisted in this object.
  apiKey: string;
  fontSize: 'small' | 'default' | 'large';
  /** Le zoom du webview (1 = 100 %), voir lib/zoom.ts. Il agrandit tout,
   *  pixels compris — là où fontSize ne touche que les unités relatives. */
  zoom: number;
  defaultModel: string;
  defaultAgent: string;
  temperature: number;
  maxTokens: number;
  speechEnabled: boolean;
}

function loadSettings(): Settings {
  const defaults: Settings = {
    theme: 'system',
    terminalSkin: 'phosphor',
    apiUrl: '',
    apiKey: '',
    fontSize: 'default',
    zoom: 1,
    defaultModel: '',
    defaultAgent: '',
    temperature: 0.7,
    maxTokens: 4096,
    speechEnabled: false,
  };
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (!raw) return defaults;
    const parsed = JSON.parse(raw);
    if (parsed.apiKey) {
      try {
        sessionStorage.setItem('diapason-api-key', String(parsed.apiKey));
      } catch {}
      delete parsed.apiKey;
      // Remove credentials left by older application builds now,
      // instead of waiting for the next settings update.
      localStorage.setItem(SETTINGS_KEY, JSON.stringify(parsed));
    }
    return { ...defaults, ...parsed, apiKey: sessionStorage.getItem('diapason-api-key') || '' };
  } catch {
    return defaults;
  }
}

function saveSettings(settings: Settings): void {
  const { apiKey, ...persisted } = settings;
  try {
    if (apiKey) sessionStorage.setItem('diapason-api-key', apiKey);
    else sessionStorage.removeItem('diapason-api-key');
  } catch {}
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(persisted));
}

// ── Store ─────────────────────────────────────────────────────────────

const INITIAL_STREAM: StreamState = {
  isStreaming: false,
  conversationId: null,
  phase: '',
  elapsedMs: 0,
  activeToolCalls: [],
  content: '',
};

interface AppState {
  // Conversations
  conversations: Conversation[];
  activeId: string | null;
  messages: ChatMessage[];
  streamState: StreamState;

  // Models & server
  models: ModelInfo[];
  modelsLoading: boolean;
  selectedModel: string;
  serverInfo: ServerInfo | null;
  savings: SavingsData | null;

  // Settings
  settings: Settings;

  // Command palette
  commandPaletteOpen: boolean;

  // Sidebar
  sidebarOpen: boolean;

  // System panel
  systemPanelOpen: boolean;

  // Actions: conversations
  loadConversations: () => void;
  importOverlayConversation: () => Promise<void>;
  createConversation: (model?: string) => string;
  selectConversation: (id: string) => void;
  deleteConversation: (id: string) => void;
  renameConversation: (id: string, title: string) => void;
  togglePinConversation: (id: string) => void;
  /** Copy id's history into a fresh conversation named newTitle; returns its id. */
  duplicateConversation: (id: string, newTitle: string) => string | null;
  loadMessages: (conversationId: string | null) => void;
  addMessage: (conversationId: string, message: ChatMessage) => void;
  updateLastAssistant: (
    conversationId: string,
    content: string,
    toolCalls?: ToolCallInfo[],
    usage?: TokenUsage,
    telemetry?: MessageTelemetry,
    audio?: { url: string },
    researchTraces?: ResearchSearchTrace[],
    researchSources?: ResearchSource[],
  ) => void;
  setStreamState: (state: Partial<StreamState>) => void;
  resetStream: () => void;

  // Deep Research toggle
  deepResearch: boolean;
  setDeepResearch: (on: boolean) => void;

  // Actions: models & server
  setModels: (models: ModelInfo[]) => void;
  setModelsLoading: (loading: boolean) => void;
  setSelectedModel: (model: string) => void;
  /** Choix de l'utilisateur : sélectionne ET retient la préférence. */
  chooseModel: (model: string) => void;
  setServerInfo: (info: ServerInfo | null) => void;
  setSavings: (data: SavingsData | null) => void;
  incrementSavings: (usage: TokenUsage) => void;

  // Live GPU metrics — streamed from /api/research system_metrics events.
  // When non-null, the System panel renders this instead of polled values
  // so Power (W) and Energy (kJ) update in real time during a research run.
  liveEnergy: LiveEnergyMetrics | null;
  setLiveEnergy: (data: LiveEnergyMetrics | null) => void;

  // Actions: settings
  updateSettings: (partial: Partial<Settings>) => void;

  // Actions: UI
  setCommandPaletteOpen: (open: boolean) => void;
  toggleSidebar: () => void;
  setSidebarOpen: (open: boolean) => void;
  toggleSystemPanel: () => void;
  setSystemPanelOpen: (open: boolean) => void;

  // Data sources (cached between visits to avoid empty-state flicker)
  cachedConnectors: CachedConnector[] | null;
  setCachedConnectors: (list: CachedConnector[] | null) => void;

  // Agents
  managedAgents: ManagedAgent[];
  managedAgentsLoading: boolean;
  selectedAgentId: string | null;

  // Actions: agents
  setManagedAgents: (agents: ManagedAgent[]) => void;
  setManagedAgentsLoading: (loading: boolean) => void;
  setSelectedAgentId: (id: string | null) => void;

  // Agent events (live stream)
  agentEvents: AgentEvent[];
  addAgentEvent: (event: AgentEvent) => void;
  clearAgentEvents: () => void;

  // Logs
  logEntries: LogEntry[];
  addLogEntry: (entry: LogEntry) => void;
  clearLogs: () => void;

  // Mesh
  /**
   * Ressource qu'un autre appareil demande d'ouvrir, consommée au montage de
   * la page cible : le routeur ne transporte pas de sélection. Jamais
   * persistée — une demande d'hier ne doit pas rouvrir un écran aujourd'hui.
   */
  pendingMeshSelection: { kind: 'project' | 'note'; id: string } | null;
  setPendingMeshSelection: (
    selection: { kind: 'project' | 'note'; id: string } | null,
  ) => void;

  // Model loading
  modelLoading: boolean;
  setModelLoading: (loading: boolean) => void;
}

export const useAppStore = create<AppState>((set, get) => {
  const initial = loadConversations();
  const convList = Object.values(initial.conversations).sort(
    (a, b) => b.updatedAt - a.updatedAt,
  );

  return {
    conversations: convList,
    activeId: initial.activeId,
    messages:
      initial.activeId && initial.conversations[initial.activeId]
        ? initial.conversations[initial.activeId].messages
        : [],
    streamState: INITIAL_STREAM,

    models: [],
    modelsLoading: true,
    selectedModel: '',
    serverInfo: null,
    savings: null,

    settings: loadSettings(),

    commandPaletteOpen: false,
    sidebarOpen: true,
    systemPanelOpen: loadSystemPanelOpen(),

    // ── Conversations ───────────────────────────────────────────────

    loadConversations: () => {
      const store = loadConversations();
      set({
        conversations: Object.values(store.conversations).sort(
          (a, b) => b.updatedAt - a.updatedAt,
        ),
        activeId: store.activeId,
      });
    },

    importOverlayConversation: async () => {
      try {
        const { invoke } = await import('@tauri-apps/api/core');
        const raw = await invoke<string>('get_overlay_conversation');
        if (!raw || raw === '[]') return;
        const overlay = JSON.parse(raw);
        if (!overlay.id || !overlay.messages?.length) return;
        const store = loadConversations();
        const existing = store.conversations[overlay.id];
        // Only update if the overlay has newer/more messages
        if (existing && existing.messages.length >= overlay.messages.length) return;
        // Track first use of overlay for this conversation
        if (!existing) {
          import('../lib/analytics').then(({ track }) => {
            track('feature_used', { feature_name: 'overlay' });
          });
        }
        store.conversations[overlay.id] = {
          id: overlay.id,
          title: overlay.title || 'Overlay chat',
          createdAt: overlay.createdAt || Date.now(),
          updatedAt: overlay.updatedAt || Date.now(),
          model: overlay.model || 'default',
          messages: overlay.messages,
        };
        saveConversations(store);
        set({
          conversations: Object.values(store.conversations).sort(
            (a, b) => b.updatedAt - a.updatedAt,
          ),
        });
      } catch {
        // Overlay command unavailable (non-Tauri or no overlay data)
      }
    },

    createConversation: (model?: string) => {
      const store = loadConversations();
      const conv: Conversation = {
        id: generateId(),
        title: '',
        createdAt: Date.now(),
        updatedAt: Date.now(),
        model: model || get().selectedModel || 'default',
        messages: [],
      };
      store.conversations[conv.id] = conv;
      store.activeId = conv.id;
      saveConversations(store);
      set({
        conversations: Object.values(store.conversations).sort(
          (a, b) => b.updatedAt - a.updatedAt,
        ),
        activeId: conv.id,
        messages: [],
      });
      return conv.id;
    },

    selectConversation: (id: string) => {
      const store = loadConversations();
      store.activeId = id;
      saveConversations(store);
      const conv = store.conversations[id];
      set({
        activeId: id,
        messages: conv ? conv.messages : [],
      });
    },

    deleteConversation: (id: string) => {
      const store = loadConversations();
      delete store.conversations[id];
      if (store.activeId === id) {
        const remaining = Object.keys(store.conversations);
        store.activeId = remaining.length > 0 ? remaining[0] : null;
      }
      saveConversations(store);
      // Le retrait local ne suffit pas : sans pierre tombale côté serveur,
      // la conversation ressusciterait au tirage suivant. Le moteur de sync
      // écoute cet événement et met l'id en file de suppression.
      if (typeof window !== 'undefined') {
        window.dispatchEvent(
          new CustomEvent('diapason:conversation-supprimee', { detail: { id } }),
        );
      }
      const convList = Object.values(store.conversations).sort(
        (a, b) => b.updatedAt - a.updatedAt,
      );
      const activeConv = store.activeId
        ? store.conversations[store.activeId]
        : null;
      set({
        conversations: convList,
        activeId: store.activeId,
        messages: activeConv ? activeConv.messages : [],
      });
    },

    renameConversation: (id: string, title: string) => {
      const store = loadConversations();
      const conv = store.conversations[id];
      const trimmed = title.trim();
      if (!conv || !trimmed) return;
      conv.title = trimmed;
      // Dater l'écriture : le moteur de sync ne pousse que ce qui dépasse la
      // version connue du serveur, et un renommage non daté n'atteignait
      // jamais l'autre vue — puis se faisait écraser par sa prochaine
      // écriture (revue du 16 sept. 2026).
      conv.updatedAt = Date.now();
      saveConversations(store);
      set({
        conversations: Object.values(store.conversations).sort(
          (a, b) => b.updatedAt - a.updatedAt,
        ),
      });
    },

    togglePinConversation: (id: string) => {
      const store = loadConversations();
      const conv = store.conversations[id];
      if (!conv) return;
      conv.pinned = !conv.pinned;
      // Même raison que le renommage : une épingle non datée ne se
      // synchronise jamais.
      conv.updatedAt = Date.now();
      saveConversations(store);
      set({
        conversations: Object.values(store.conversations).sort(
          (a, b) => b.updatedAt - a.updatedAt,
        ),
      });
    },

    duplicateConversation: (id: string, newTitle: string) => {
      const store = loadConversations();
      const orig = store.conversations[id];
      if (!orig) return null;
      const copy: Conversation = {
        ...orig,
        id: generateId(),
        title: newTitle,
        createdAt: Date.now(),
        updatedAt: Date.now(),
        pinned: false,
        // Deep copy: edits to the duplicate must never leak into the
        // original's message objects.
        messages: JSON.parse(JSON.stringify(orig.messages)),
      };
      store.conversations[copy.id] = copy;
      store.activeId = copy.id;
      saveConversations(store);
      set({
        conversations: Object.values(store.conversations).sort(
          (a, b) => b.updatedAt - a.updatedAt,
        ),
        activeId: copy.id,
        messages: [...copy.messages],
      });
      return copy.id;
    },

    loadMessages: (conversationId: string | null) => {
      if (!conversationId) {
        set({ messages: [] });
        return;
      }
      const store = loadConversations();
      const conv = store.conversations[conversationId];
      set({ messages: conv ? conv.messages : [] });
    },

    addMessage: (conversationId: string, message: ChatMessage) => {
      const store = loadConversations();
      const conv = store.conversations[conversationId];
      if (!conv) return;
      conv.messages.push(message);
      conv.updatedAt = Date.now();
      if (message.role === 'user' && (!conv.title || conv.title === 'New chat')) {
        conv.title =
          message.content.slice(0, 50) +
          (message.content.length > 50 ? '...' : '');
      }
      saveConversations(store);
      set({
        messages: [...conv.messages],
        conversations: Object.values(store.conversations).sort(
          (a, b) => b.updatedAt - a.updatedAt,
        ),
      });
    },

    updateLastAssistant: (
      conversationId: string,
      content: string,
      toolCalls?: ToolCallInfo[],
      usage?: TokenUsage,
      telemetry?: MessageTelemetry,
      audio?: { url: string },
      researchTraces?: ResearchSearchTrace[],
      researchSources?: ResearchSource[],
    ) => {
      const store = loadConversations();
      const conv = store.conversations[conversationId];
      if (!conv) return;
      const lastMsg = conv.messages[conv.messages.length - 1];
      if (lastMsg && lastMsg.role === 'assistant') {
        lastMsg.content = content;
        if (toolCalls) lastMsg.toolCalls = toolCalls;
        if (usage) lastMsg.usage = usage;
        if (telemetry) lastMsg.telemetry = telemetry;
        if (audio) lastMsg.audio = audio;
        if (researchTraces) lastMsg.researchTraces = researchTraces;
        if (researchSources) lastMsg.researchSources = researchSources;
        conv.updatedAt = Date.now();
        saveConversations(store);
        set({ messages: [...conv.messages] });
      }
    },

    setStreamState: (partial: Partial<StreamState>) => {
      set((s) => ({ streamState: { ...s.streamState, ...partial } }));
    },

    resetStream: () => {
      set({ streamState: INITIAL_STREAM });
    },

    // ── Deep Research ─────────────────────────────────────────────
    deepResearch: false,
    setDeepResearch: (on: boolean) => set({ deepResearch: on }),

    // ── Models & server ────────────────────────────────────────────

    setModels: (models: ModelInfo[]) =>
      set((state) => {
        if (state.selectedModel) return { models };
        const choix = modeleInitial(state.settings.defaultModel, models);
        return choix ? { models, selectedModel: choix } : { models };
      }),
    setModelsLoading: (loading: boolean) => set({ modelsLoading: loading }),
    setSelectedModel: (model: string) => set({ selectedModel: model }),
    // Un modèle CHOISI est une préférence (23 août 2026) : elle survit au
    // redémarrage (réglages locaux) et même à un stockage effacé — la config
    // serveur la relit au démarrage et la remet en tête de /v1/models.
    chooseModel: (model: string) => {
      set({ selectedModel: model });
      get().updateSettings({ defaultModel: model });
      void import('./api')
        .then(({ setServerConfigKey }) =>
          setServerConfigKey('intelligence.default_model', model),
        )
        .catch(() => undefined);
    },
    setServerInfo: (info: ServerInfo | null) => set({ serverInfo: info }),
    setSavings: (data: SavingsData | null) => set({ savings: data }),
    incrementSavings: (usage: TokenUsage) => {
      const cur = get().savings;
      const prompt = usage.prompt_tokens ?? 0;
      const completion = usage.completion_tokens ?? 0;
      const total = usage.total_tokens ?? prompt + completion;
      set({
        savings: {
          total_calls: (cur?.total_calls ?? 0) + 1,
          total_prompt_tokens: (cur?.total_prompt_tokens ?? 0) + prompt,
          total_completion_tokens: (cur?.total_completion_tokens ?? 0) + completion,
          total_tokens: (cur?.total_tokens ?? 0) + total,
          local_cost: cur?.local_cost ?? 0,
          per_provider: cur?.per_provider ?? [],
          token_counting_version: cur?.token_counting_version,
        },
      });
    },

    liveEnergy: null,
    setLiveEnergy: (data: LiveEnergyMetrics | null) => set({ liveEnergy: data }),

    cachedConnectors: null,
    setCachedConnectors: (list) => set({ cachedConnectors: list }),

    // ── Settings ───────────────────────────────────────────────────

    updateSettings: (partial: Partial<Settings>) => {
      const updated = { ...get().settings, ...partial };
      saveSettings(updated);
      set({ settings: updated });
    },

    // ── UI ──────────────────────────────────────────────────────────

    setCommandPaletteOpen: (open: boolean) => set({ commandPaletteOpen: open }),
    toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
    setSidebarOpen: (open: boolean) => set({ sidebarOpen: open }),
    toggleSystemPanel: () =>
      set((s) => {
        const systemPanelOpen = !s.systemPanelOpen;
        saveSystemPanelOpen(systemPanelOpen);
        return { systemPanelOpen };
      }),
    setSystemPanelOpen: (open: boolean) => {
      saveSystemPanelOpen(open);
      set({ systemPanelOpen: open });
    },

    // ── Agents ─────────────────────────────────────────────────────

    managedAgents: [],
    managedAgentsLoading: false,
    selectedAgentId: null,

    setManagedAgents: (agents) => set({ managedAgents: agents }),
    setManagedAgentsLoading: (loading) => set({ managedAgentsLoading: loading }),
    setSelectedAgentId: (id) => set({ selectedAgentId: id }),

    agentEvents: [],
    addAgentEvent: (event) => set((s) => ({
      agentEvents: [...s.agentEvents.slice(-99), event],
    })),
    clearAgentEvents: () => set({ agentEvents: [] }),

    // ── Logs ────────────────────────────────────────────────────────
    logEntries: [],
    addLogEntry: (entry) => set((s) => ({
      logEntries: [...s.logEntries.slice(-499), entry],
    })),
    clearLogs: () => set({ logEntries: [] }),

    // ── Mesh ────────────────────────────────────────────────────────
    pendingMeshSelection: null,
    setPendingMeshSelection: (selection) => set({ pendingMeshSelection: selection }),

    // ── Model loading ───────────────────────────────────────────────
    modelLoading: false,
    setModelLoading: (loading) => set({ modelLoading: loading }),
  };
});

// Le moteur de sync (lib/convSync.ts) et l'import des réglages passent par
// ces mêmes lecture/écriture pour que l'événement de modification parte de
// TOUS les chemins d'écriture — un setItem direct court-circuitait la
// poussée vers le serveur.
export { generateId, loadConversations, saveConversations, CONVERSATIONS_KEY };
