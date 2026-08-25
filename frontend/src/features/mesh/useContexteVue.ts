/**
 * Le hook qui publie l'écran courant, et la ressource qu'on y regarde.
 *
 * Deux usages : sans argument dans le shell, pour l'écran ; avec une
 * ressource dans une page qui en sélectionne une.
 */

import { useEffect } from 'react';
import { useLocation } from 'react-router';

import { publierLaVue, type RessourceVue } from './contexte-vue';

export function useContexteVue(ressource?: RessourceVue | null): void {
  const location = useLocation();
  const cle = ressource ? `${ressource.type}:${ressource.id}:${ressource.title ?? ''}` : '';
  useEffect(() => {
    void publierLaVue(location.pathname, ressource ?? null);
    // `cle` sérialise la ressource : sans elle, l'effet ne repartirait pas
    // quand l'utilisateur change de projet sans changer d'écran.
  }, [location.pathname, cle]);
}
