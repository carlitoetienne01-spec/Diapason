/**
 * Le mode gestes vit AU-DESSUS des pages, pas dans l'une d'elles.
 *
 * Constaté le 25 août 2026 : le panneau vivait dans la page Appareils, donc
 * quitter cette page démontait le composant et éteignait la caméra. Or le
 * geste sert justement à attraper ce qu'on regarde — un projet, une note —
 * ce qui suppose d'être sur la page qui l'affiche. Le mode s'éteignait
 * exactement au moment où il devenait utile.
 *
 * L'état vit donc dans un contexte monté une fois pour toute l'application.
 * Le §78 tient toujours : la caméra ne s'allume que sur activation
 * explicite, et les quatre chemins d'extinction demeurent — le bouton, le
 * silence, la durée maximale, et la fermeture de l'application.
 */

import { createContext, useContext, type ReactNode } from 'react';

import { useModeGestes, type ModeGestes } from './useModeGestes';

const Contexte = createContext<ModeGestes | null>(null);

export function ModeGestesProvider({ children }: { children: ReactNode }) {
  const mode = useModeGestes();
  return <Contexte.Provider value={mode}>{children}</Contexte.Provider>;
}

export function useModeGestesPartage(): ModeGestes {
  const mode = useContext(Contexte);
  if (mode === null) {
    throw new Error(
      'useModeGestesPartage doit être utilisé sous ModeGestesProvider.',
    );
  }
  return mode;
}
