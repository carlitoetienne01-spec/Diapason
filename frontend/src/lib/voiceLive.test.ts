import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

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

describe('la coupure dite par le serveur (§78, 26/09/2026)', () => {
  it('traduit les deux motifs de fermeture du Mac en message pour l’orbe', async () => {
    const { motifDeFermeture } = await freshVoiceLive();
    // Sans ce motif, l'orbe revenait à « inactif » sans un mot : une coupure
    // voulue se lisait comme une panne.
    expect(motifDeFermeture({ reason: 'inactivity' }), 'deux minutes sans parole').toBe(
      'voice-closed-inactivity',
    );
    expect(motifDeFermeture({ reason: 'maxDuration' }), 'dix minutes au plus').toBe(
      'voice-closed-max-duration',
    );
  });

  it('ne dit rien d’une fermeture demandée par l’utilisateur ou d’un motif inconnu', async () => {
    const { motifDeFermeture } = await freshVoiceLive();
    expect(motifDeFermeture({}), '« Terminer » n’est pas une coupure du serveur').toBeNull();
    expect(motifDeFermeture({ reason: 'autreChose' }), 'un motif inconnu ne se devine pas').toBeNull();
    expect(motifDeFermeture({ reason: 42 })).toBeNull();
  });
});

describe('la garde du client quand le Mac ne répond plus (§78, 26/09/2026)', () => {
  // Contre-épreuve du 26/09/2026 : la coupure du Mac n'atteint pas un
  // téléphone hors réseau ; son micro restait armé jusqu'à quinze minutes.
  const T0 = 1_790_400_000_000;
  const vivant = {
    maintenantMs: T0 + 60_000,
    debutMs: T0,
    derniereTrameMs: T0 + 50_000,
    battementVu: true,
    tamponOctets: 0,
  };

  it('ne coupe pas une séance dont le Mac parle encore', async () => {
    const { coupureCliente } = await freshVoiceLive();
    expect(coupureCliente(vivant), 'une trame il y a 10 s : le Mac est là').toBeNull();
  });

  it('coupe après 45 s sans aucune trame d’un Mac qui battait', async () => {
    const { coupureCliente, SERVEUR_MUET_MAX_MS } = await freshVoiceLive();
    const derniere = T0 + 10_000;
    expect(
      coupureCliente({ ...vivant, derniereTrameMs: derniere, maintenantMs: derniere + SERVEUR_MUET_MAX_MS - 1 }),
      'un creux de réseau court ne coupe rien',
    ).toBeNull();
    expect(
      coupureCliente({ ...vivant, derniereTrameMs: derniere, maintenantMs: derniere + SERVEUR_MUET_MAX_MS }),
      'trois battements manqués : le micro se ferme ici',
    ).toBe('voice-lost-server');
  });

  it('ne prend jamais pour mort un serveur plus ancien, qui ne bat pas', async () => {
    const { coupureCliente } = await freshVoiceLive();
    expect(
      coupureCliente({ ...vivant, battementVu: false, derniereTrameMs: T0, maintenantMs: T0 + 300_000 }),
      'sans battement vu, le silence du serveur ne prouve rien',
    ).toBeNull();
  });

  it('coupe quand l’envoi n’avance plus, même sans battement vu', async () => {
    const { coupureCliente, TAMPON_MAX_OCTETS } = await freshVoiceLive();
    expect(coupureCliente({ ...vivant, battementVu: false, tamponOctets: TAMPON_MAX_OCTETS - 1 })).toBeNull();
    expect(
      coupureCliente({ ...vivant, battementVu: false, tamponOctets: TAMPON_MAX_OCTETS }),
      '~23 s de micro que le réseau n’a pas pris',
    ).toBe('voice-lost-server');
  });

  it('coupe au plafond local, dix minutes et demie après le début', async () => {
    const { coupureCliente, DUREE_LOCALE_MAX_MS } = await freshVoiceLive();
    expect(
      coupureCliente({ ...vivant, maintenantMs: T0 + DUREE_LOCALE_MAX_MS - 1, derniereTrameMs: T0 + DUREE_LOCALE_MAX_MS - 1 }),
    ).toBeNull();
    expect(
      coupureCliente({ ...vivant, maintenantMs: T0 + DUREE_LOCALE_MAX_MS, derniereTrameMs: T0 + DUREE_LOCALE_MAX_MS }),
      'la trame « closed » du Mac ne viendra plus',
    ).toBe('voice-closed-max-duration');
  });

  it('tient ses seuils contre le battement et la durée maximale du Mac', async () => {
    const { SERVEUR_MUET_MAX_MS, DUREE_LOCALE_MAX_MS } = await freshVoiceLive();
    const pont = readFileSync(
      join(process.cwd(), '..', 'src', 'diapason', 'speech', 'realtime', 'bridge.py'),
      'utf-8',
    );
    const battement = Number(/^BATTEMENT_S = ([\d.]+)$/m.exec(pont)?.[1]);
    const dureeMax = Number(/^DUREE_MAX_S = ([\d.]+)$/m.exec(pont)?.[1]);
    expect(battement, 'BATTEMENT_S introuvable dans bridge.py').toBeGreaterThan(0);
    expect(SERVEUR_MUET_MAX_MS, 'trois battements manqués au moins').toBeGreaterThanOrEqual(3 * battement * 1000);
    expect(dureeMax, 'DUREE_MAX_S introuvable dans bridge.py').toBeGreaterThan(0);
    expect(DUREE_LOCALE_MAX_MS, 'le plafond local vient APRÈS celui du Mac').toBeGreaterThan(dureeMax * 1000);
  });
});
