/** Appliquer l'intention du serveur dans le paquet Tauri, jamais ailleurs. */

import { invoke } from '@tauri-apps/api/core';

import type { ActionPointeur, LecturePointeur } from './api';

export function pointeurNatifDisponible(): boolean {
  return typeof window !== 'undefined' && Boolean(window.__TAURI_INTERNALS__);
}

// 60 im/s max côté JS : évite d'inonder Tauri quand la caméra envoie vite
// (30 août 2026).
const MOVE_MIN_MS = 16;
const MOVE_MIN_DELTA = 0.002;

let dernierMove: { x: number; y: number; t: number } | null = null;

function actionEffective(lecture: LecturePointeur): ActionPointeur {
  if (
    lecture.action === 'NONE' &&
    lecture.x != null &&
    lecture.y != null
  ) {
    return 'MOVE';
  }
  return lecture.action;
}

function moveRedondant(x: number, y: number, maintenant: number): boolean {
  if (dernierMove === null) return false;
  if (maintenant - dernierMove.t >= MOVE_MIN_MS) return false;
  return (
    Math.abs(x - dernierMove.x) < MOVE_MIN_DELTA &&
    Math.abs(y - dernierMove.y) < MOVE_MIN_DELTA
  );
}

export async function notifierSessionGestes(active: boolean): Promise<void> {
  if (!pointeurNatifDisponible()) return;
  await invoke('gestes_session_active', { active });
}

export async function appliquerPointeur(
  lecture: LecturePointeur | null | undefined,
): Promise<void> {
  if (!lecture?.active) return;
  const action = actionEffective(lecture);
  if (action === 'NONE') return;
  if (!pointeurNatifDisponible()) {
    throw new Error(
      'Le contrôle du curseur exige l’application de bureau Diapason.',
    );
  }
  const event = { ...lecture, action };
  if (action === 'MOVE') {
    if (lecture.x == null || lecture.y == null) return;
    const maintenant = performance.now();
    if (moveRedondant(lecture.x, lecture.y, maintenant)) return;
    dernierMove = { x: lecture.x, y: lecture.y, t: maintenant };
    // Retour immédiat : le plafond de pas est appliqué côté Rust.
    void invoke('apply_pointer_event', { event });
    return;
  }
  dernierMove = null;
  await invoke('apply_pointer_event', { event });
}
