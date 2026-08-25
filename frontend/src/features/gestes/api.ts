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

export type ObjetTenu = {
  type: string;
  id: string;
  title: string;
  screen?: string;
};

export type Depot = {
  done: boolean;
  reason?: string;
  message?: string;
  target?: string;
  candidates?: string[];
  object?: ObjetTenu;
};

export type Diagnostic = {
  armed: boolean;
  held?: ObjetTenu | null;
  lastDrop?: Depot | null;
  state?: EtatGeste;
  frames?: number;
  handsSeen?: number;
  grabs?: number;
  releases?: number;
  losses?: number;
  handRatio?: number;
  confidence?: number;
  secondsLeft?: number;
};

export async function lireDiagnostic(): Promise<Diagnostic> {
  const reponse = await apiFetch('/v1/gestures/state');
  if (!reponse.ok) return { armed: false };
  return reponse.json();
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

export type ReponseImage = {
  state: EtatGeste;
  changed: boolean;
  hand: boolean;
  frames: number;
};

export class EchecGeste extends Error {
  constructor(
    readonly etape: 'armement' | 'caméra' | 'envoi',
    message: string,
  ) {
    super(message);
  }
}

export async function armer(): Promise<{ armed: boolean }> {
  let reponse: Response;
  try {
    reponse = await apiFetch('/v1/gestures/arm', { method: 'POST' });
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
