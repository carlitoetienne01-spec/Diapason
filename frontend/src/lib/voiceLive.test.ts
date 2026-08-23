import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const fetchMock = vi.fn<typeof fetch>();

class MemoryStorage {
  private store = new Map<string, string>();
  getItem(key: string): string | null {
    return this.store.get(key) ?? null;
  }
  setItem(key: string, value: string): void {
    this.store.set(key, String(value));
  }
  removeItem(key: string): void {
    this.store.delete(key);
  }
}

beforeEach(() => {
  vi.resetModules();
  fetchMock.mockReset();
  globalThis.fetch = fetchMock;
  (globalThis as unknown as { localStorage: MemoryStorage }).localStorage =
    new MemoryStorage();
  (globalThis as unknown as { sessionStorage: MemoryStorage }).sessionStorage =
    new MemoryStorage();
  (globalThis as unknown as { window: { location: { origin: string } } }).window = {
    location: { origin: 'http://localhost:5173' },
  };
});

afterEach(() => {
  vi.unstubAllEnvs();
  (globalThis as unknown as { localStorage?: MemoryStorage }).localStorage = undefined;
  (globalThis as unknown as { sessionStorage?: MemoryStorage }).sessionStorage = undefined;
  (globalThis as unknown as { window?: unknown }).window = undefined;
});

async function freshVoiceLive() {
  return await import('./voiceLive');
}

describe('voice service readiness', () => {
  it('enables start only for an enabled and configured selected provider', async () => {
    const { canStartVoiceSession } = await freshVoiceLive();
    const health = {
      available: true,
      enabled: true,
      default_provider: 'local',
      providers: {
        local: { configured: true },
        gemini: { configured: false },
        openai: { configured: false },
      },
    };

    expect(canStartVoiceSession(health, 'local')).toBe(true);
    expect(canStartVoiceSession(health, 'gemini')).toBe(false);
    expect(canStartVoiceSession({ ...health, enabled: false }, 'local')).toBe(false);
    expect(canStartVoiceSession(null, 'local')).toBe(false);
  });
});

describe('voice WebSocket URL', () => {
  it('uses the API route and keeps auth out of URL logs', async () => {
    localStorage.setItem(
      'diapason-settings',
      JSON.stringify({ apiUrl: 'http://127.0.0.1:8765' }),
    );
    sessionStorage.setItem('diapason-api-key', 'diapason_sk_secret');
    const { voiceLiveDiagnosticUrl, voiceLiveProtocols, voiceLiveWsUrl } =
      await freshVoiceLive();

    const url = voiceLiveWsUrl({ provider: 'local' });
    expect(url).toContain('ws://127.0.0.1:8765/v1/voice/live');
    expect(url).toContain('provider=local');
    expect(url).not.toContain('diapason_sk_secret');
    expect(url).not.toContain('token=');
    expect(voiceLiveProtocols()).toEqual([
      'diapason',
      'diapason-auth.diapason_sk_secret',
    ]);

    const diagnostic = voiceLiveDiagnosticUrl(url);
    expect(diagnostic).not.toContain('diapason_sk_secret');
    expect(diagnostic).toBe(url);
  });
});

describe('voice health preflight', () => {
  it('uses the authenticated API client before opening a socket', async () => {
    localStorage.setItem(
      'diapason-settings',
      JSON.stringify({ apiUrl: 'http://127.0.0.1:8000' }),
    );
    sessionStorage.setItem('diapason-api-key', 'diapason_sk_local');
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          available: true,
          enabled: true,
          default_provider: 'local',
          providers: { local: { configured: true } },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );
    const { fetchVoiceLiveHealth } = await freshVoiceLive();

    await expect(fetchVoiceLiveHealth()).resolves.toMatchObject({
      default_provider: 'local',
    });
    expect(fetchMock).toHaveBeenCalledWith(
      'http://127.0.0.1:8000/v1/voice/live/health',
      { headers: { Authorization: 'Bearer diapason_sk_local' } },
    );
  });

  it('surfaces the HTTP status for an understandable auth error', async () => {
    fetchMock.mockResolvedValue(new Response('{}', { status: 401 }));
    const { fetchVoiceLiveHealth, VoiceLiveHealthError } = await freshVoiceLive();

    await expect(fetchVoiceLiveHealth()).rejects.toEqual(
      expect.objectContaining<Partial<InstanceType<typeof VoiceLiveHealthError>>>({
        status: 401,
      }),
    );
  });
});
