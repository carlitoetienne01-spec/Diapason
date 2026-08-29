/** Appliquer l'intention du serveur dans le paquet Tauri, jamais ailleurs. */

import { invoke } from '@tauri-apps/api/core';

import type { LecturePointeur } from './api';

export function pointeurNatifDisponible(): boolean {
  return typeof window !== 'undefined' && Boolean(window.__TAURI_INTERNALS__);
}

export async function appliquerPointeur(
  lecture: LecturePointeur | null | undefined,
): Promise<void> {
  if (!lecture?.active || lecture.action === 'NONE') return;
  if (!pointeurNatifDisponible()) {
    throw new Error(
      'Le contrôle du curseur exige l’application de bureau Diapason.',
    );
  }
  await invoke('apply_pointer_event', { event: lecture });
}
