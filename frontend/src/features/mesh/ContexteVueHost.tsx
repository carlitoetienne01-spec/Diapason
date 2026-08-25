/**
 * Publie l'écran courant, monté une fois pour toute l'application.
 *
 * Les pages qui sélectionnent une ressource (Projets, Notes) appellent en
 * plus `useContexteVue({...})` : le hook le plus précis gagne, puisqu'il
 * s'exécute après.
 */

import { useContexteVue } from './useContexteVue';

export function ContexteVueHost(): null {
  useContexteVue();
  return null;
}
