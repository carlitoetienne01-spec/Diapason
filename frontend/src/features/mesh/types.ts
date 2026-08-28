/**
 * Wire shapes for the device mesh, mirroring `src/diapason/mesh/*` 1:1.
 *
 * camelCase throughout — the mesh routes serialise that way, like Succès and
 * unlike the older core `/v1` surface. Nothing converts between the two, so
 * a snake_case field here would simply read undefined.
 */

export type MeshTrustLevel = 'UNTRUSTED' | 'PENDING' | 'TRUSTED' | 'REVOKED';

export type MeshDeviceType =
  | 'DESKTOP'
  | 'LAPTOP'
  | 'PHONE'
  | 'TABLET'
  | 'BROWSER';

export type MeshPresenceState = 'ONLINE' | 'IDLE' | 'BACKGROUND' | 'OFFLINE';

export interface MeshIdentity {
  deviceId: string;
  publicKey: string;
  name: string;
  platform: string;
  createdAtMs: number;
  ownerId: string;
}

export interface MeshDevice {
  deviceId: string;
  publicKey: string;
  name: string;
  platform: string;
  deviceType: MeshDeviceType;
  trustLevel: MeshTrustLevel;
  /** What the device claims it can do. */
  declaredCapabilities: string[];
  /**
   * What it is actually granted, after the platform ceiling is applied.
   * Both lists are exposed on purpose: the gap between them is what explains
   * to the user why a phone cannot do something it advertises.
   */
  capabilities: string[];
  appVersion: string;
  createdAtMs: number;
  lastSeenAtMs: number | null;
  revokedAtMs: number | null;
  appState: string | null;
  transport: string | null;
  address: string | null;
}

export interface MeshPresence {
  deviceId: string;
  state: MeshPresenceState;
  appState: string | null;
  transport: string | null;
  lastSeenAtMs: number | null;
  /** null when the device was never seen, or has been revoked. */
  ageMs: number | null;
  heartbeatIntervalMs: number;
}

export type MeshDeviceWithPresence = MeshDevice & { presence: MeshPresence };

export interface MeshPairingInvitation {
  pairingToken: string;
  deviceName: string;
  expiresAtMs: number;
  expiresInSeconds: number;
}

export interface MeshFileReceived {
  fileName: string;
  sizeBytes: number;
  mimeType: string;
  sourceDeviceId: string;
  sourceDeviceName: string;
}

/**
 * One thing another device caused this one to show. The shapes are
 * distinguished by their optional payload — notifications and verified file
 * arrivals carry no route.
 */
export interface MeshInboxEntry {
  commandId: string;
  originDeviceId: string;
  receivedAtMs: number;
  route?: string;
  focus?: boolean;
  resourceType?: string;
  resourceId?: string;
  notification?: { title: string; body: string };
  fileReceived?: MeshFileReceived;
}

export interface MeshAnnounceResult {
  reached: number;
  skipped: number;
}
