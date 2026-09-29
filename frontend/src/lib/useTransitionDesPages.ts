import { useEffect, useLayoutEffect, useRef, type RefObject } from 'react';

import { estMobile } from './natif';
import { creerSuiviDesPages, type SuiviDesPages } from './suiviDesPages';

function mouvementReduit(): boolean {
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  } catch {
    return false;
  }
}

/**
 * Les transitions entre pages, au téléphone seulement (lot 2 du chantier
 * « soyeux », 27/09/2026) — lib/transitionPage.ts dit pourquoi et combien,
 * lib/suiviDesPages.ts le fait (sorti d'ici le 27/09/2026 pour que vitest
 * l'exécute).
 *
 * - La page qui ARRIVE glisse de 12 px et se révèle en 180 ms (Web
 *   Animations, transform/opacity : le compositeur seul). C'est la COLONNE
 *   qu'on anime, pas la racine de la page : cette racine est le défileur de
 *   la page, et l'animer fait repeindre tout son contenu — au banc (×4,
 *   trois passes de 14 navigations), la peinture médiane des Notes passe de
 *   39 ms (sans transition) à 97 ms en animant la racine, 46 ms en animant
 *   la colonne ; sur les 42 navigations, 482 → 999 ms de peinture contre
 *   578. La colonne existe aussi sur les pages sans défileur racine (la
 *   Discussion, les Journaux).
 * - La page qui PART n'est pas animée : la garder à l'écran le temps d'un
 *   fondu, c'est la rendre deux fois — au banc, re-poser la page quittée
 *   pour l'estomper fait passer les images abandonnées de 58 à 84 sur les
 *   42 navigations, celles du Planificateur de 2 à 26, et la peinture de
 *   578 à 975 ms.
 * - La position de défilement de la page QUITTÉE est retenue, et rendue au
 *   retour (roue, lien, retour d'Android) : avant, revenir sur les Tâches
 *   ramenait en haut des 726 tâches qu'on venait de descendre.
 *
 * Au bureau et au mini-panneau, rien : aucun écouteur, aucune animation.
 */
export function useTransitionDesPages(colonneRef: RefObject<HTMLElement | null>, chemin: string, directionRoue?: number) {
  const suivi = useRef<SuiviDesPages | null>(null);
  suivi.current ??= creerSuiviDesPages({ mobile: estMobile, mouvementReduit });

  // Retenir : l'événement `scroll` ne remonte pas, mais se capte sur la
  // colonne. Passif — rien sur le chemin du doigt n'attend ce code.
  useEffect(() => {
    const colonne = colonneRef.current;
    if (!estMobile || !colonne) return undefined;
    const surDefilement = (e: Event) => suivi.current?.surDefilement(colonne, e);
    colonne.addEventListener('scroll', surDefilement, { capture: true, passive: true });
    return () => colonne.removeEventListener('scroll', surDefilement, { capture: true });
  }, [colonneRef]);

  // Un effet de MISE EN PAGE : il part après que React a posé la nouvelle
  // page, AVANT sa première peinture — ni l'animation ni la position ne
  // s'appliquent une image trop tard.
  useLayoutEffect(() => {
    if (!estMobile) return undefined;
    return suivi.current?.naviguer(colonneRef.current, chemin, directionRoue);
  }, [chemin, colonneRef, directionRoue]);
}
