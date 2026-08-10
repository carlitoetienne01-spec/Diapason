/** Build a WebSocket URL for `/v1/voice/live` with optional API token. */
import { getApiKey, getBase } from '../lib/api';

export function voiceLiveWsUrl(extraQuery: Record<string, string> = {}): string {
  const base = getBase() || window.location.origin;
  const u = new URL(base);
  u.protocol = u.protocol === 'https:' ? 'wss:' : 'ws:';
  u.pathname = '/v1/voice/live';
  u.search = '';
  const key = getApiKey();
  if (key) u.searchParams.set('token', key);
  for (const [k, v] of Object.entries(extraQuery)) {
    if (v) u.searchParams.set(k, v);
  }
  return u.toString();
}

export async function fetchVoiceLiveHealth(): Promise<{
  available: boolean;
  enabled: boolean;
  default_provider: string;
  providers: Record<string, { configured: boolean }>;
}> {
  const { getBase, authHeaders } = await import('../lib/api');
  const res = await fetch(`${getBase()}/v1/voice/live/health`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`voice live health ${res.status}`);
  return res.json();
}
