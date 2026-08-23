// La Ligne — les aides pures du panneau d'étape.
//
// Demandé le 23 août 2026 : cliquer une étape déroule ses cours en stations
// reliées, comme une ligne de métro — cochée pleine, courante pulsante, à
// venir creuse. Séparé du composant pour être vérifiable sous node, la
// convention de ce dépôt.

import type { SuccesTask } from './types';

export interface Station {
  tache: SuccesTask;
  profondeur: 0 | 1; // 0 = enfant de l'étape, 1 = petit-enfant
}

/** Les stations d'une étape : enfants puis petits-enfants, dans l'ordre. */
export function construireStations(
  etapeId: string,
  taches: SuccesTask[],
): Station[] {
  const parRang = (a: SuccesTask, b: SuccesTask) =>
    (a.order ?? 0) - (b.order ?? 0);
  const enfantsDe = (id: string) =>
    taches.filter((t) => t.parentTaskId === id).sort(parRang);
  const stations: Station[] = [];
  for (const enfant of enfantsDe(etapeId)) {
    stations.push({ tache: enfant, profondeur: 0 });
    for (const petit of enfantsDe(enfant.id)) {
      stations.push({ tache: petit, profondeur: 1 });
    }
  }
  return stations;
}

/** La station COURANTE : la première non cochée — c'est là qu'on en est. */
export function stationCourante(stations: Station[]): string | null {
  const courante = stations.find((s) => !s.tache.done);
  return courante ? courante.tache.id : null;
}

export interface Segment {
  type: 'texte' | 'lien';
  valeur: string;
}

const LIEN_RE = /(https?:\/\/[^\s<>"')\]]+)/g;

/** Découpe un texte en segments, les URL devenant des liens cliquables. */
export function linkifier(texte: string): Segment[] {
  const segments: Segment[] = [];
  let reste = String(texte ?? '');
  let m: RegExpExecArray | null;
  LIEN_RE.lastIndex = 0;
  let position = 0;
  while ((m = LIEN_RE.exec(reste)) !== null) {
    if (m.index > position) {
      segments.push({ type: 'texte', valeur: reste.slice(position, m.index) });
    }
    // La ponctuation finale appartient à la phrase, pas au lien.
    let url = m[0];
    while (/[.,;:!?]$/.test(url)) url = url.slice(0, -1);
    segments.push({ type: 'lien', valeur: url });
    position = m.index + url.length;
    LIEN_RE.lastIndex = position;
  }
  if (position < reste.length) {
    segments.push({ type: 'texte', valeur: reste.slice(position) });
  }
  return segments;
}

/** L'étape voisine dans l'ordre des racines — pour les flèches ← →. */
export function etapeVoisine(
  etapeId: string,
  taches: SuccesTask[],
  sens: -1 | 1,
): string | null {
  const racines = taches
    .filter((t) => !t.parentTaskId)
    .sort((a, b) => (a.order ?? 0) - (b.order ?? 0));
  const i = racines.findIndex((t) => t.id === etapeId);
  if (i < 0) return null;
  const voisin = racines[i + sens];
  return voisin ? voisin.id : null;
}
