import { apiFetch } from '../../lib/api';
import type {
  MeshAnnounceResult,
  MeshDevice,
  MeshDeviceWithPresence,
  MeshIdentity,
  MeshInboxEntry,
  MeshPairingInvitation,
} from './types';

/**
 * Same wrapper as Succès, with one deliberate difference: network failures
 * are retried only for reads.
 *
 * The Succès version retries any request four times, which is right for
 * idempotent CRUD and wrong here — a dropped response on POST /pairings
 * would mint up to four live invitations, each of which lets a device in.
 * A retry that can hand out extra keys is not a retry.
 */
async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const requestInit = {
    ...init,
    headers: {
      ...(init.body ? { 'Content-Type': 'application/json' } : {}),
      ...((init.headers as Record<string, string> | undefined) ?? {}),
    },
  };
  const idempotent = !init.method || init.method === 'GET';

  let lastError: unknown = null;
  for (let attempt = 0; attempt < 4; attempt += 1) {
    let response: Response;
    try {
      response = await apiFetch(path, requestInit);
    } catch (error) {
      lastError = error;
      // WebKit reports aborted/network races as "Load failed".
      if (idempotent && attempt < 3) {
        await new Promise((resolve) => window.setTimeout(resolve, 250 * (attempt + 1)));
        continue;
      }
      const raw = error instanceof Error ? error.message : String(error);
      throw new Error(
        /load failed|failed to fetch|networkerror/i.test(raw)
          ? 'Connexion locale interrompue. Réessayez.'
          : /did not match the expected pattern|invalid url|failed to construct/i.test(raw)
            ? "L'URL de l'API est invalide. Vérifiez Réglages → Connexion → URL de l'API."
            : raw || 'Connexion locale impossible.',
      );
    }

    // A 429 means the request never ran, so retrying it is safe whatever
    // the method — nothing was created on the other side.
    if (response.status === 429) {
      const retrySeconds = Number(response.headers.get('Retry-After') || attempt + 1);
      const delay = Math.min(2500, Math.max(300, retrySeconds * 1000));
      if (attempt < 3) {
        await new Promise((resolve) => window.setTimeout(resolve, delay));
        continue;
      }
      throw new Error('Trop de requêtes. Réessayez dans un instant.');
    }

    if (!response.ok) {
      let message = `Erreur appareils (${response.status})`;
      try {
        const payload = await response.json();
        const detail = payload?.detail;
        // Mesh errors are already written for the user, in French — pass
        // them through rather than paraphrasing them into something vaguer.
        message = typeof detail === 'string' ? detail : detail?.message || message;
      } catch {
        // Keep the stable user-facing fallback; technical details stay in logs.
      }
      throw new Error(message);
    }

    return response.json() as Promise<T>;
  }

  throw lastError instanceof Error ? lastError : new Error('Connexion locale impossible.');
}

/** This installation's own identity. It never appears in the device list. */
export function fetchMeshIdentity(): Promise<MeshIdentity> {
  return request('/v1/mesh/me');
}

export async function listMeshDevices(
  options: { includeRevoked?: boolean } = {},
): Promise<MeshDeviceWithPresence[]> {
  const query = new URLSearchParams();
  if (options.includeRevoked) query.set('includeRevoked', 'true');
  const suffix = query.toString() ? `?${query}` : '';
  const payload = await request<{ devices: MeshDeviceWithPresence[]; count: number }>(
    `/v1/mesh/devices${suffix}`,
  );
  return payload.devices;
}

/**
 * Mint a single-use invitation. The token is a credential: it is what lets a
 * new device into the fleet, so it must never be logged or sent anywhere.
 */
export function createMeshPairing(deviceName: string): Promise<MeshPairingInvitation> {
  return request('/v1/mesh/pairings', {
    method: 'POST',
    body: JSON.stringify({ deviceName }),
  });
}

export function renameMeshDevice(deviceId: string, name: string): Promise<MeshDevice> {
  return request(`/v1/mesh/devices/${encodeURIComponent(deviceId)}`, {
    method: 'PATCH',
    body: JSON.stringify({ name }),
  });
}

/** Terminal: the only way back from revocation is to forget the device. */
export function revokeMeshDevice(deviceId: string): Promise<MeshDevice> {
  return request(`/v1/mesh/devices/${encodeURIComponent(deviceId)}/revoke`, {
    method: 'POST',
  });
}

export async function forgetMeshDevice(deviceId: string): Promise<void> {
  // No body: the route declares none, unlike the Succès delete convention.
  await request<{ ok: boolean; deviceId: string }>(
    `/v1/mesh/devices/${encodeURIComponent(deviceId)}`,
    { method: 'DELETE' },
  );
}

/**
 * What another device asked this one to open. Draining is the default and is
 * the point: a screen should open once, not on every poll. Exactly one caller
 * may poll this, or entries vanish into whichever poller won the race.
 */
export async function fetchMeshInbox(drain = true): Promise<MeshInboxEntry[]> {
  const payload = await request<{ pending: MeshInboxEntry[] }>(
    `/v1/mesh/inbox?drain=${drain}`,
  );
  return payload.pending;
}

export function announceMeshPresence(appState: string): Promise<MeshAnnounceResult> {
  // appState travels in the query string: the FastAPI route declares it as a
  // scalar parameter, so a JSON body would be ignored in silence.
  return request(`/v1/mesh/announce?appState=${encodeURIComponent(appState)}`, {
    method: 'POST',
  });
}
