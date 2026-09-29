import { useLayoutEffect, type ReactNode } from 'react';
import { useLocation } from 'react-router';
import { estMobile } from './natif';
import { releveNavigation } from './mesuresNavigation';

/**
 * Le relevé de fluidité du téléphone (lib/mesuresNavigation.ts,
 * 26/09/2026) : le DÉBUT est noté au premier rendu de la nouvelle adresse,
 * la MONTÉE quand React a posé la page dans le document — l'effet ne part
 * qu'une fois son morceau arrivé et son `Suspense` levé. Depuis le
 * 28/09/2026, il entoure l’Outlet : charger une page ne doit plus démonter
 * la roue pendant le geste. Hors du téléphone, rien n'est relevé.
 */
export function MesureDeRoute({ children }: { children: ReactNode }) {
  const { key, pathname } = useLocation();
  // La clé seule ne suffit pas : une entrée d'historique posée hors du
  // routeur (un `pushState` sans état) garde la clé « default » de
  // l'ouverture, et chaque page suivante passait pour la même navigation.
  const cle = `${key}\u0000${pathname}`;
  if (estMobile) releveNavigation.debut(cle, pathname, performance.now());
  // Un effet de MISE EN PAGE, pas un effet passif : ceux-là partent après
  // ceux de la page, et le banc les a vus attendre derrière 100 à 200 ms de
  // travail des pages déjà peintes (relevé à 136 ms quand le contenu était
  // à l'écran à 21 ms, 26/09/2026).
  useLayoutEffect(() => {
    if (estMobile) releveNavigation.montee(cle);
  }, [cle]);
  return children;
}

