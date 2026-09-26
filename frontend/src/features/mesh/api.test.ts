import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const reseau = vi.hoisted(() => vi.fn());
vi.mock('../../lib/api', () => ({ apiFetch: reseau }));

let api: typeof import('./api');
// Relue après chaque `resetModules`, comme l'api : une classe d'avant ne
// serait pas celle que le module rechargé lève.
let SondeNonEnvoyee: typeof import('../../lib/tailnet').SondeNonEnvoyee;

beforeEach(async () => {
  vi.resetModules();
  reseau.mockReset();
  api = await import('./api');
  ({ SondeNonEnvoyee } = await import('../../lib/tailnet'));
});
afterEach(() => vi.useRealTimers());

describe('Une lecture que la passerelle refuse ne se relance pas', () => {
  it('SondeNonEnvoyee sort au premier essai, sans les trois réessais réseau', async () => {
    // 26/09/2026, contre-épreuve (mutant V8) : la relancer ne ferait que la
    // retenir trois fois de plus, 250 + 500 + 750 ms plus tard, et la page
    // attendrait 1,5 s pour dire ce qu'elle savait tout de suite.
    vi.useFakeTimers();
    reseau.mockRejectedValue(new SondeNonEnvoyee('GET /v1/mesh/inbox'));
    const lecture = api.fetchMeshIdentity();
    const verdict = expect(lecture).rejects.toBeInstanceOf(SondeNonEnvoyee);
    await vi.advanceTimersByTimeAsync(2000);
    await verdict;
    expect(reseau).toHaveBeenCalledTimes(1);
  });

  it('une vraie panne de lecture, elle, se réessaie', async () => {
    vi.useFakeTimers();
    reseau.mockRejectedValueOnce(new Error('Load failed')).mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers(),
      json: async () => ({ deviceId: 'mac' }),
    });
    const lecture = api.fetchMeshIdentity();
    await vi.advanceTimersByTimeAsync(250);
    await expect(lecture).resolves.toMatchObject({ deviceId: 'mac' });
    expect(reseau).toHaveBeenCalledTimes(2);
  });
});
