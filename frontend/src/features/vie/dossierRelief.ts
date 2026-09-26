// Le relief des dossiers (Notes et Projets) — ou son absence au téléphone.
//
// 26/09/2026, chantier de la fluidité (lot 3) : au téléphone, le dossier
// des Notes était posé à plat — 371 → 35 calques composés, 9,1 → 4,7
// millions de pixels de textures sur la page des Notes. Mais le dossier
// des Projets en était une COPIE (VieProjectsPage.tsx) que le lot n'avait
// pas touchée : contre-épreuve du même jour, 20 éléments en `preserve-3d`,
// 149 calques dont 86 dessinés (4,03 Mpx), et 16 transitions de 320 à
// 460 ms, pour un survol qu'un doigt ne fait jamais. Les deux dossiers
// passent maintenant par ces fonctions : une troisième copie ne pourrait
// plus oublier le téléphone sans que dossierRelief.test.ts le voie.

import type { CSSProperties } from 'react';

import { estMobile } from '../../lib/natif';

/** Au téléphone : ni perspective, ni `preserve-3d`, ni `will-change`, ni
 *  couche en `translateZ`, ni inclinaison au pointeur, ni transition de
 *  survol. Le Mac garde son dossier en relief. */
export const DOSSIER_PLAT = estMobile;

export type Inclinaison = { x: number; y: number };

/** La boîte qui porte la perspective. */
export function perspectiveDuDossier(plat: boolean): string | undefined {
  return plat ? undefined : '760px';
}

/** Le corps du dossier : incliné et grossi au survol, en relief — ou rien. */
export function reliefDuDossier(plat: boolean, tilt: Inclinaison, active: boolean, grossi: number): CSSProperties {
  if (plat) return {};
  return {
    transform: `rotateX(${tilt.y}deg) rotateY(${tilt.x}deg) scale(${active ? grossi : 1})`,
    transformStyle: 'preserve-3d',
    transition: active ? 'transform 90ms linear' : 'transform 460ms cubic-bezier(.2,.8,.2,1)',
    willChange: 'transform',
  };
}

/** Une couche avancée de `px` pixels vers l'œil — à plat, à sa place. */
export function profondeur(plat: boolean, px: number): string | undefined {
  return plat ? undefined : `translateZ(${px}px)`;
}

/** Une transition de survol : au téléphone, aucune (rien n'y survole). */
export function transitionDeSurvol(plat: boolean, valeur: string): string | undefined {
  return plat ? undefined : valeur;
}

/** Les gestionnaires du survol, ou aucun au téléphone. */
export function survolDuDossier<T>(plat: boolean, gestionnaires: T): Partial<T> {
  return plat ? {} : gestionnaires;
}
