/**
 * Le mode gestes, vu du navigateur.
 *
 * La caméra est ouverte ICI et pas côté serveur : macOS ne pose la question
 * qu'à une application empaquetée, et l'interpréteur Python n'en est pas une
 * (voir docs/spatial-mesh/GESTES.md). L'application capture, le serveur voit.
 */

import { apiFetch } from '../../lib/api';

export type EtatGeste =
  | 'REPOS'
  | 'MAIN_VUE'
  | 'PAUME_STABLE'
  | 'FERMETURE'
  | 'SAISI'
  | 'RELACHEMENT'
  | 'RELACHE'
  | 'PERDU'
  | 'ANNULE';

export type ModeGeste = 'TRANSFER' | 'POINTER';

export type ActionPointeur =
  | 'NONE'
  | 'MOVE'
  | 'CLICK'
  | 'DOUBLE_CLICK'
  | 'SCROLL';

export type LecturePointeur = {
  active: boolean;
  action: ActionPointeur;
  x?: number | null;
  y?: number | null;
  scrollY?: number;
  pinching?: boolean;
  pinchProgress?: number;
};

export type ObjetTenu = {
  type: string;
  id: string;
  title: string;
  screen?: string;
  sizeBytes?: number;
  mimeType?: string;
};

export type Depot = {
  done: boolean;
  reason?: string;
  message?: string;
  target?: string;
  candidates?: string[];
  token?: string;
  object?: ObjetTenu;
  progress?: number;
  sentChunks?: number;
  totalChunks?: number;
  bytes?: number;
  remotePath?: string;
};

export type CandidatDepot = {
  deviceId: string;
  name: string;
  platform?: string;
  deviceType?: string;
};

export type PositionMain = { x: number; y: number };

/**
 * Un dépôt qui attend qu'on tranche (§81).
 *
 * Le `deviceId` vient du serveur et lui revient tel quel : l'interface
 * choisit PARMI ce qui lui a été proposé, elle ne désigne pas une
 * destination. Le serveur refuse tout identifiant absent de sa propre
 * liste — c'est ce qui empêche cette route de devenir un « envoie
 * n'importe quoi à n'importe qui ».
 */
export type DepotEnAttente = {
  token: string;
  object: ObjetTenu;
  candidates: CandidatDepot[];
  secondsLeft: number;
  gestureControlled?: boolean;
  selectedIndex?: number;
  selectedDeviceId?: string;
  handPosition?: PositionMain | null;
};

export type EntreeJournal = {
  at: string;
  what: string;
  detail: string;
  ok: boolean;
};

export async function ecouterLesClaps(actif: boolean): Promise<boolean> {
  const reponse = await apiFetch(`/v1/gestures/clap/${actif ? 'on' : 'off'}`, {
    method: 'POST',
  });
  const corps = await reponse.json().catch(() => null);
  if (!reponse.ok) throw new Error(corps?.detail ?? 'Écoute impossible.');
  return Boolean(corps?.listening);
}

export type PieceMesuree = {
  roomLevel: number;
  roomHigh: number;
  roomLoudest: number;
  disturbed: boolean;
};

export type MesureDesClaps = {
  calibrated: boolean;
  roomLevel: number;
  roomHigh: number;
  roomLoudest: number;
  clapPeaks: number[];
  discarded: number[];
  threshold: number;
};

// La mesure se fait en DEUX temps, et ce n'est pas un détail d'implantation.
// En un seul appel, l'interface devait deviner quand le serveur passait de
// « j'écoute la pièce » à « clape maintenant » : elle armait son minuteur
// avant même que la requête parte, alors que le compte du serveur ne démarre
// qu'une fois le micro ouvert. L'ordre de claper s'affichait donc pendant
// que le serveur écoutait encore le silence, et celui qui obéissait à
// l'écran polluait sa propre mesure. En deux temps, personne ne devine.

/** Premier temps : le serveur écoute la pièce se taire (~3 s). */
export async function mesurerLaPiece(): Promise<PieceMesuree> {
  const reponse = await apiFetch('/v1/gestures/clap/calibrate/room', {
    method: 'POST',
  });
  const corps = await reponse.json().catch(() => null);
  if (!reponse.ok) throw new Error(corps?.detail ?? 'Mesure impossible.');
  return corps as PieceMesuree;
}

/** Second temps : le serveur écoute claper (~6 s). À n'appeler qu'APRÈS
 *  avoir affiché l'ordre de claper. */
export async function mesurerLesClaps(): Promise<MesureDesClaps> {
  const reponse = await apiFetch('/v1/gestures/clap/calibrate/claps', {
    method: 'POST',
  });
  const corps = await reponse.json().catch(() => null);
  if (!reponse.ok) throw new Error(corps?.detail ?? 'Mesure impossible.');
  return corps as MesureDesClaps;
}

export async function oublierLaMesureDesClaps(): Promise<void> {
  const reponse = await apiFetch('/v1/gestures/clap/calibrate/reset', {
    method: 'POST',
  });
  if (!reponse.ok) throw new Error('Le réglage n\'a pas pu être oublié.');
}

export type Diagnostic = {
  armed: boolean;
  mode?: ModeGeste;
  pointer?: LecturePointeur | null;
  clapListening?: boolean;
  clapsHeard?: number;
  clapThreshold?: number;
  clapCalibrated?: boolean;
  clapNoiseFloor?: number;
  clapFailure?: string | null;
  journal?: EntreeJournal[];
  held?: ObjetTenu | null;
  preparedFile?: ObjetTenu | null;
  lastDrop?: Depot | null;
  pendingDrop?: DepotEnAttente | null;
  state?: EtatGeste;
  frames?: number;
  handsSeen?: number;
  grabs?: number;
  releases?: number;
  losses?: number;
  handRatio?: number;
  confidence?: number;
  secondsLeft?: number;
  energy?: EtatEnergie;
  fps?: number;
};

export async function lireDiagnostic(): Promise<Diagnostic> {
  const reponse = await apiFetch('/v1/gestures/state');
  if (!reponse.ok) return { armed: false };
  return reponse.json();
}

/** Trancher : envoyer vers l'un des appareils que le serveur a proposés. */
export async function choisirLAppareil(
  token: string,
  deviceId: string,
): Promise<Depot> {
  const reponse = await apiFetch('/v1/gestures/drop/target', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token, deviceId }),
  });
  const corps = await reponse.json().catch(() => null);
  // 409 : la question a expiré, ou la main s'est vidée entre-temps. Le
  // serveur dit laquelle ; le répéter vaut mieux que « une erreur ».
  if (!reponse.ok) throw new Error(corps?.detail ?? "L'envoi n'a pas eu lieu.");
  return corps as Depot;
}

/** « Laisse tomber » : la main s'ouvre sur rien, et c'est un choix. */
export async function renoncerAuDepot(): Promise<void> {
  await apiFetch('/v1/gestures/drop/cancel', { method: 'POST' });
}

/** Préparer le chemin choisi par le dialogue natif — jamais ses octets. */
export async function preparerFichierPourGeste(
  path: string,
): Promise<ObjetTenu> {
  const reponse = await apiFetch('/v1/gestures/file', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path }),
  });
  const corps = await reponse.json().catch(() => null);
  if (!reponse.ok) {
    throw new Error(corps?.detail ?? "Ce fichier n'a pas pu être préparé.");
  }
  return corps.preparedFile as ObjetTenu;
}

export async function oublierFichierPrepare(): Promise<void> {
  const reponse = await apiFetch('/v1/gestures/file/cancel', { method: 'POST' });
  if (!reponse.ok) throw new Error("Le fichier préparé n'a pas pu être retiré.");
}

export async function mesurerPose(
  pose: 'ouverte' | 'fermee',
): Promise<void> {
  await apiFetch(`/v1/gestures/calibrate/${pose}`, { method: 'POST' });
}

export async function finirLaMesure(
  pose: 'ouverte' | 'fermee',
): Promise<number> {
  const reponse = await apiFetch(`/v1/gestures/calibrate/${pose}/stop`, {
    method: 'POST',
  });
  const corps = await reponse.json();
  if (!reponse.ok) throw new Error(corps?.detail ?? 'Mesure impossible.');
  return corps.value as number;
}

export async function appliquerCalibration(
  ouverte: number,
  fermee: number,
): Promise<void> {
  const reponse = await apiFetch('/v1/gestures/calibrate/apply', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ouverte, fermee }),
  });
  if (!reponse.ok) {
    const corps = await reponse.json().catch(() => null);
    throw new Error(corps?.detail ?? 'Calibration refusée.');
  }
}

export async function oublierCalibration(): Promise<void> {
  await apiFetch('/v1/gestures/calibrate/reset', { method: 'POST' });
}

export type EtatEnergie = 'OFF' | 'READY' | 'ACTIVE' | 'LOW_POWER';

export type ReponseImage = {
  state: EtatGeste;
  changed: boolean;
  hand: boolean;
  frames: number;
  // §83 : la cadence est décidée par le SERVEUR, seul à savoir si une main a
  // été vue. Elle voyage avec chaque image, et pas seulement dans l'état
  // sondé chaque seconde : sans cela l'interface filmerait encore à
  // l'ancienne cadence pendant jusqu'à une seconde après qu'une main est
  // entrée dans le champ — précisément le moment où elle compte.
  energy?: EtatEnergie;
  fps?: number;
  pendingDrop?: DepotEnAttente | null;
  lastDrop?: Depot | null;
  pointer?: LecturePointeur | null;
};

export class EchecGeste extends Error {
  constructor(
    readonly etape: 'armement' | 'caméra' | 'envoi',
    message: string,
  ) {
    super(message);
  }
}

export async function armer(
  mode: ModeGeste = 'TRANSFER',
): Promise<{ armed: boolean; mode?: ModeGeste }> {
  let reponse: Response;
  try {
    reponse = await apiFetch('/v1/gestures/arm', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode }),
    });
  } catch (exc) {
    throw new EchecGeste(
      'armement',
      `Le serveur n'a pas répondu (${exc instanceof Error ? exc.message : exc}).`,
    );
  }
  if (!reponse.ok) throw new EchecGeste('armement', await reponse.text());
  return reponse.json();
}

export async function desarmer(): Promise<void> {
  await apiFetch('/v1/gestures/disarm', { method: 'POST' });
}

export async function envoyerImage(
  imageBase64: string,
): Promise<ReponseImage | null> {
  // L'image voyage en base64 dans du JSON, pas en binaire. WKWebView — le
  // moteur de la fenêtre Diapason — échoue sur un corps de requête binaire
  // avec un « Load failed » opaque, qu'il s'agisse d'un Blob ou d'un
  // ArrayBuffer, alors que la même requête passe en ligne de commande et
  // que le contrôle préalable CORS répond correctement (constaté le
  // 25 août 2026, après avoir écarté le port, CORS et le type de corps).
  // Le JSON est le chemin que toute l'application emprunte déjà.
  let reponse: Response;
  try {
    reponse = await apiFetch('/v1/gestures/frame', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image: imageBase64 }),
    });
  } catch (exc) {
    throw new EchecGeste(
      'envoi',
      `L'image n'a pas pu être envoyée (${exc instanceof Error ? exc.message : exc}).`,
    );
  }
  // 409 : le serveur a désarmé de lui-même (silence ou durée dépassée).
  // Ce n'est pas une panne, c'est le mode qui se referme comme prévu.
  if (reponse.status === 409) return null;
  if (!reponse.ok) throw new EchecGeste('envoi', await reponse.text());
  return reponse.json();
}
