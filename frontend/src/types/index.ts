// --- SSE Event Types ---

export interface SSEEvent {
  event?: string;
  data: string;
}

export interface AgentTurnStartEvent {
  agent: string;
  input: string;
}

export interface InferenceStartEvent {
  model: string;
  engine: string;
  turn: number;
}

export interface InferenceEndEvent {
  model: string;
  engine: string;
  turn: number;
}

export interface ToolCallStartEvent {
  tool: string;
  arguments: string;
}

export interface ToolCallEndEvent {
  tool: string;
  success: boolean;
  latency: number;
}

// --- Chat Types ---

export interface ToolCallInfo {
  id: string;
  tool: string;
  arguments: string;
  status: 'running' | 'success' | 'error';
  result?: string;
  latency?: number;
  // 21/09/2026 : le serveur lit lui-même la page d'un poste après une
  // recherche. La carte le dit : ce que le modèle n'a pas demandé se voit.
  auto?: boolean;
}

export interface TokenUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

export interface MessageTelemetry {
  engine?: string;
  model_id?: string;
  // Le modèle demandé quand un tour léger est parti sur le modèle léger (20/09/2026).
  routed_from?: string;
  tokens_per_sec?: number;
  ttft_ms?: number;
  total_ms?: number;
  complexity_score?: number;
  complexity_tier?: string;
  suggested_max_tokens?: number;
}

export interface TimeRange {
  start?: string;
  end?: string;
}

export interface ResearchSource {
  ref: number;
  title?: string;
  sender?: string;
  date?: string;
  url?: string;
}

export interface ResearchSearchTrace {
  id: string;
  query: string;
  person?: string;
  timeRange?: TimeRange | string;
  status: 'pending' | 'complete';
  numHits?: number;
  topTitles?: string[];
}

export type ResearchEvent =
  | {
      type: 'search_call';
      arguments: {
        query: string;
        person?: string;
        time_range?: TimeRange | string;
      };
    }
  | {
      type: 'search_result';
      num_hits: number;
      top_titles?: string[];
      sources?: ResearchSource[];
    }
  | { type: 'synthesis'; text: string }
  | {
      type: 'system_metrics';
      power_w: number;
      energy_j: number;
      duration_s: number;
    }
  | { type: 'done'; usage?: TokenUsage }
  | { type: 'error'; message: string };

export interface LiveEnergyMetrics {
  power_w: number;
  energy_j: number;
  duration_s: number;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
  toolCalls?: ToolCallInfo[];
  researchTraces?: ResearchSearchTrace[];
  researchSources?: ResearchSource[];
  isResearch?: boolean;
  usage?: TokenUsage;
  telemetry?: MessageTelemetry;
  audio?: { url: string };
  questions?: import('../lib/questionsChat').QuestionsChat;
  questionReply?: import('../lib/questionsChat').ReponsesQuestions;
  // 20/09/2026 : ce que la réponse affirme et que ses sources ne portent pas
  // (années, valeurs, noms) — un signal du serveur, jamais dans le texte.
  // 21/09 : plus le titulaire que les sources désignent quand la réponse en
  // nomme un autre, et la date des sources quand elles sont trop vieilles.
  verification?: {
    nonRetrouves: string[];
    sourcesDatees?: string;
    desaccord?: { reponse: string; sources: string[] };
  };
}

export interface Conversation {
  id: string;
  // Empty until the first user message names it (or the user renames it):
  // a hardcoded "New chat" cannot be translated after the fact.
  title: string;
  createdAt: number;
  updatedAt: number;
  model: string;
  /** Pinned conversations surface in their own section, above the dated ones. */
  pinned?: boolean;
  messages: ChatMessage[];
}

export interface ConversationStore {
  version: 1;
  conversations: Record<string, Conversation>;
  activeId: string | null;
}

// --- Stream State ---

export interface StreamState {
  isStreaming: boolean;
  /**
   * La conversation dans laquelle le flux écrit — PAS forcément l'active :
   * on peut changer de conversation pendant qu'une réponse arrive. Le
   * moteur de sync la protège de toute fusion distante tant que le flux
   * dure (16 sept. 2026 : la garde visait `activeId`, et cliquer une autre
   * conversation la retirait à celle qui recevait la réponse).
   */
  conversationId: string | null;
  phase: string;
  elapsedMs: number;
  activeToolCalls: ToolCallInfo[];
  content: string;
}

// --- API Types ---

export interface ModelInfo {
  id: string;
  object: string;
  created: number;
  owned_by: string;
  /** Max context window when known (catalog or Ollama /api/show). */
  context_length?: number | null;
}

export interface ProviderSavings {
  provider: string;
  label: string;
  input_cost: number;
  output_cost: number;
  total_cost: number;
  energy_wh: number;
  energy_joules: number;
  flops: number;
}

export interface SavingsData {
  total_calls: number;
  total_prompt_tokens: number;
  total_completion_tokens: number;
  total_tokens: number;
  local_cost: number;
  per_provider: ProviderSavings[];
  token_counting_version?: number;
}

export interface ServerInfo {
  model: string;
  agent: string | null;
  engine: string;
  /** Effective Ollama context window sent on every local call. */
  num_ctx?: number;
}

// --- Log Types ---

export interface LogEntry {
  timestamp: number;
  level: 'info' | 'warn' | 'error';
  category: 'server' | 'model' | 'chat' | 'tool' | 'succes' | 'mesh';
  message: string;
}
