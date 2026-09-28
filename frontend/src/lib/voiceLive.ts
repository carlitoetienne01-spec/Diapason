/** Helpers for the authenticated realtime voice service. */
import { apiFetch, getApiKey, getBase, isTauri } from '../lib/api';

export type VoiceLiveProviderId = 'gemini' | 'openai' | 'local';

export interface VoiceLiveProviderHealth {
  configured: boolean;
  reason?: string;
}

export interface VoiceLiveHealth {
  defaultVoice?: string;
  voices?: string[];
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

/**
 * Pourquoi le SERVEUR a fermé la voix, dit à l'utilisateur (§78, 26/09/2026).
 *
 * Le Mac coupe seul une séance après deux minutes sans parole ou dix minutes
 * au total (`speech/realtime/bridge.py`). Sans ce motif, l'orbe revenait à
 * « inactif » sans un mot, et une coupure voulue se lisait comme une panne.
 * Un motif inconnu (un serveur plus récent) ne dit rien plutôt que de
 * deviner.
 */
export type FermetureVocale = 'voice-closed-inactivity' | 'voice-closed-max-duration';

export function motifDeFermeture(message: { reason?: unknown }): FermetureVocale | null {
  if (message.reason === 'inactivity') return 'voice-closed-inactivity';
  if (message.reason === 'maxDuration') return 'voice-closed-max-duration';
  return null;
}

/**
 * La garde du CLIENT : quand couper le micro soi-même (§78, 26/09/2026).
 *
 * Contre-épreuve du 26/09/2026 : la coupure du Mac (`bridge.py`) n'atteint
 * pas un téléphone hors réseau — ni la trame « closed » ni la fermeture ne
 * lui arrivent, et son TCP (Tailscale garde son interface montée, Android
 * ne détruit rien) retransmet jusqu'à quinze minutes. Pendant ce temps le
 * micro restait ouvert, le voyant vert allumé, « Listening » à l'écran, et
 * ~43 Ko/s de PCM en base64 s'entassaient dans la file d'envoi. Cette garde
 * ne remplace pas celle du serveur (un client ancien ou planté ne
 * l'appliquerait pas) : elle couvre le cas où le serveur ne peut plus parler.
 */
export type CoupureCliente = 'voice-lost-server' | 'voice-closed-max-duration';

/**
 * 45 s sans AUCUNE trame du Mac : trois battements manqués (`BATTEMENT_S` =
 * 15 s dans `bridge.py`, tenu par le test). Un creux de réseau de trente
 * secondes ne coupe rien ; au-delà, la réponse ne pourrait plus arriver.
 */
export const SERVEUR_MUET_MAX_MS = 45_000;

/**
 * 1 Mo en attente d'envoi : ~23 s de micro (16 kHz, 16 bits, base64 ≈
 * 43 Ko/s) que le réseau n'a pas pris. Whisper ne tirerait rien d'une
 * parole arrivée vingt secondes en retard. Le noyau absorbe d'abord son
 * propre tampon, d'où ce seuil en appoint du battement, pas à sa place.
 */
export const TAMPON_MAX_OCTETS = 1_000_000;

/**
 * Dix minutes (`DUREE_MAX_S` du Mac) plus 30 s pour que sa trame « closed »
 * traverse un réseau lent : au-delà, elle ne viendra plus.
 */
export const DUREE_LOCALE_MAX_MS = 630_000;

export function coupureCliente(etat: {
  maintenantMs: number;
  debutMs: number;
  derniereTrameMs: number;
  /** Le Mac a battu au moins une fois : un serveur plus ancien ne bat pas,
   * et son silence ne doit pas passer pour une mort. */
  battementVu: boolean;
  tamponOctets: number;
}): CoupureCliente | null {
  if (etat.maintenantMs - etat.debutMs >= DUREE_LOCALE_MAX_MS) {
    return 'voice-closed-max-duration';
  }
  if (etat.tamponOctets >= TAMPON_MAX_OCTETS) return 'voice-lost-server';
  if (etat.battementVu && etat.maintenantMs - etat.derniereTrameMs >= SERVEUR_MUET_MAX_MS) {
    return 'voice-lost-server';
  }
  return null;
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
