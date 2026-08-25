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
  image: ArrayBuffer,
): Promise<ReponseImage | null> {
  // Un ArrayBuffer et non un Blob : WebKit échoue sur un corps Blob répété
  // avec un « Load failed » opaque qui ne dit ni pourquoi ni où (constaté
  // le 25 août 2026 dans la fenêtre Diapason, alors que la même requête
  // passait en ligne de commande).
  let reponse: Response;
  try {
    reponse = await apiFetch('/v1/gestures/frame', {
      method: 'POST',
      headers: { 'Content-Type': 'image/jpeg' },
      body: image,
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
