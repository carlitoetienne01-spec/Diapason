import type { ResearchEvent, SSEEvent } from '../types';
import { getBase, authHeaders } from './api';

export interface ChatRequest {
  model: string;
  // 22/09/2026 : `images` porte du base64 avec son en-tête `data:` ; le
  // serveur la retire et vérifie le format dans les octets. JSON base64 et
  // jamais multipart : la fenêtre Tauri est une WKWebView, qui échoue sur
  // un corps binaire avec un « Load failed » opaque (CLAUDE.md).
  messages: Array<{
    role: string;
    content: string;
    images?: string[];
    documents?: Array<{ nom: string; texte: string; pages?: number; tronque?: boolean }>;
  }>;
  stream: true;
  temperature?: number;
  max_tokens?: number;
  action_mode?: 'off' | 'auto';
  interactiveQuestions?: boolean;
  // 21/09/2026 : le bouton « Vérifier en ligne » force la recherche web sur
  // ce tour, quelle que soit la forme de la question.
  verifyOnline?: boolean;
}

export async function* streamChat(
  request: ChatRequest,
  signal?: AbortSignal,
  recevoir?: (octets: Uint8Array) => void,
): AsyncGenerator<SSEEvent> {
  const base = getBase();
  const response = await fetch(`${base}/v1/chat/completions`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(request),
    signal,
  });

  if (!response.ok) {
    throw new Error(`Chat request failed: ${response.status}`);
  }

  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let currentEvent: string | undefined;

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      recevoir?.(value);

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (line.startsWith('event: ')) {
          currentEvent = line.slice(7).trim();
        } else if (line.startsWith('data: ')) {
          const data = line.slice(6);
          if (data === '[DONE]') return;
          yield { event: currentEvent, data };
          currentEvent = undefined;
        } else if (line.trim() === '') {
          currentEvent = undefined;
        }
      }
    }
  } finally {
    // 19/09/2026 : sortir au finish_reason relâchait seulement le verrou,
    // laissant le fournisseur travailler après la fermeture du consommateur.
    try { await reader.cancel(); } catch { /* Déjà interrompu par AbortSignal. */ }
    reader.releaseLock();
  }
}

export async function* streamResearch(
  query: string,
  model?: string,
  signal?: AbortSignal,
  // 22/09/2026 : « Donne-moi les liens de ces sites web » partait seul —
  // sans les tours d'avant, « ces sites » n'avait pas de référent et la
  // recherche rendait des liens tirés des courriels.
  history: Array<{ role: string; content: string }> = [],
  recevoir?: (octets: Uint8Array) => void,
): AsyncGenerator<ResearchEvent> {
  // /api/research is mounted at the server root — strip any trailing /v1
  // from the base so configurations like "http://host:8000/v1" still resolve.
  const base = getBase().replace(/\/v1\/?$/, '');
  const response = await fetch(`${base}/api/research`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ query, history, ...(model ? { model } : {}) }),
    signal,
  });

  if (!response.ok) {
    throw new Error(`Research request failed: ${response.status}`);
  }

  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      recevoir?.(value);

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const data = line.slice(6);
        if (data === '[DONE]') return;
        try {
          const parsed = JSON.parse(data) as ResearchEvent;
          yield parsed;
          if (parsed.type === 'done') return;
        } catch {
          // skip malformed chunks
        }
      }
    }
  } finally {
    // 19/09/2026 : sortir au finish_reason relâchait seulement le verrou,
    // laissant le fournisseur travailler après la fermeture du consommateur.
    try { await reader.cancel(); } catch { /* Déjà interrompu par AbortSignal. */ }
    reader.releaseLock();
  }
}
