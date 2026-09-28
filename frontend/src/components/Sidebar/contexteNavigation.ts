import { useLayoutEffect, useRef } from 'react';
import { create } from 'zustand';

export type ChoixNavigation = {
  id: string;
  libelle: string;
  actif?: boolean;
  choisir: () => void;
};
export type ContexteNavigation = {
  chemin: string;
  groupes: { titre: string; choix: ChoixNavigation[] }[];
  date?: { valeur: string; choisir: (valeur: string) => void };
};

type Etat = { proprietaire: symbol | null; contexte: ContexteNavigation | null };
export const useContexteNavigation = create<Etat>(() => ({ proprietaire: null, contexte: null }));

export function retirerContexte(proprietaire: symbol) {
  if (useContexteNavigation.getState().proprietaire === proprietaire) {
    useContexteNavigation.setState({ proprietaire: null, contexte: null });
  }
}

/**
 * 28/09/2026 : le panneau montrait les autres modules au lieu des vues de
 * la page. La page publie ses vrais contrôles : pas de second filtre qui
 * pourrait diverger. Seul le panneau s'abonne, pour éviter une boucle de rendu.
 */
export function usePublierNavigation(contexte: ContexteNavigation) {
  const proprietaire = useRef(Symbol('page'));
  useLayoutEffect(() => {
    useContexteNavigation.setState({ proprietaire: proprietaire.current, contexte });
  });
  useLayoutEffect(() => {
    const id = proprietaire.current;
    return () => retirerContexte(id);
  }, []);
}
