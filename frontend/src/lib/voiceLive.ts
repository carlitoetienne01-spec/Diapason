/** Helpers for the authenticated realtime voice service. */
import { apiFetch, getApiKey, getBase, isTauri } from '../lib/api';

export type VoiceLiveProviderId = 'gemini' | 'openai' | 'local';

export interface VoiceLiveProviderHealth {
  configured: boolean;
  reason?: string;
}

export interface VoiceLiveHealth {
  available: boolean;
  enabled: boolean;
  default_provider: string;
  providers: Record<string, VoiceLiveProviderHealth>;
}

export class VoiceLiveHealthError extends Error {
  constructor(public readonly status: number) {
    super(`voice live health ${status}`);
    this.name = 'VoiceLiveHealthError';
  }
}

export function canStartVoiceSession(
  health: VoiceLiveHealth | null,
  provider: VoiceLiveProviderId,
): boolean {
  return !!health?.enabled && health.providers?.[provider]?.configured === true;
}

export function voiceLiveWsUrl(extraQuery: Record<string, string> = {}): string {
  const base = getBase() || window.location.origin;
  const u = new URL(base);
  u.protocol = u.protocol === 'https:' ? 'wss:' : 'ws:';
  u.pathname = '/v1/voice/live';
  u.search = '';
  for (const [k, v] of Object.entries(extraQuery)) {
    if (v) u.searchParams.set(k, v);
  }
  return u.toString();
}

/** Authenticate without putting the local credential in Uvicorn's URL logs. */
export function voiceLiveProtocols(): string[] {
  const key = getApiKey();
  return key ? ['diapason', `diapason-auth.${key}`] : ['diapason'];
}

/** Remove credentials before writing a WebSocket URL to developer logs. */
export function voiceLiveDiagnosticUrl(url: string): string {
  const safe = new URL(url);
  if (safe.searchParams.has('token')) safe.searchParams.set('token', '[redacted]');
  return safe.toString();
}

export async function fetchVoiceLiveHealth(): Promise<VoiceLiveHealth> {
  // Native builds use Rust's authenticated client. This avoids making
  // desktop readiness depend on WebKit's cross-origin preflight lifecycle.
  if (isTauri()) {
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      return await invoke<VoiceLiveHealth>('get_voice_live_health');
    } catch (err) {
      console.error('[voice-live] native health check failed', err);
      throw err;
    }
  }

  // apiFetch retries a 401 once after refreshing the desktop-generated key.
  // This is important during startup: the Python backend can create its key
  // after the WebView has rendered, and a direct fetch would remain stale.
  const res = await apiFetch('/v1/voice/live/health');
  if (!res.ok) throw new VoiceLiveHealthError(res.status);
  return res.json();
}
