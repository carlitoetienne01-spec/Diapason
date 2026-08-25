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

export async function armer(): Promise<{ armed: boolean }> {
  const reponse = await apiFetch('/v1/gestures/arm', { method: 'POST' });
  if (!reponse.ok) throw new Error(await reponse.text());
  return reponse.json();
}

export async function desarmer(): Promise<void> {
  await apiFetch('/v1/gestures/disarm', { method: 'POST' });
}

export async function envoyerImage(image: Blob): Promise<ReponseImage | null> {
  const reponse = await apiFetch('/v1/gestures/frame', {
    method: 'POST',
    headers: { 'Content-Type': 'image/jpeg' },
    body: image,
  });
  // 409 : le serveur a désarmé de lui-même (silence ou durée dépassée).
  // Ce n'est pas une panne, c'est le mode qui se referme comme prévu.
  if (reponse.status === 409) return null;
  if (!reponse.ok) throw new Error(await reponse.text());
  return reponse.json();
}
