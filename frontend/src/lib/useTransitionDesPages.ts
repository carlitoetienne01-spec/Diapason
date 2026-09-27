import { useEffect, useLayoutEffect, useRef, type RefObject } from 'react';

import { estMobile } from './natif';
import {
  IMAGES_ENTREE,
  OPTIONS_ENTREE,
  SELECTEUR_DEFILEUR_PAGE,
  creerMemoireDefilement,
  decisionRestauration,
  doitAnimerLEntree,
  pageRetientSaPosition,
} from './transitionPage';

function mouvementReduit(): boolean {
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  } catch {
    return false;
  }
}

/** Ce qui annonce que la personne a repris la main sur la page. */
const REPRISES = ['touchstart', 'wheel', 'pointerdown', 'keydown'] as const;

/**
 * Les transitions entre pages, au téléphone seulement (lot 2 du chantier
 * « soyeux », 27/09/2026) — lib/transitionPage.ts dit pourquoi et combien.
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
export function useTransitionDesPages(colonneRef: RefObject<HTMLElement | null>, chemin: string) {
  const memoire = useRef(creerMemoireDefilement());
  const cheminCourant = useRef(chemin);
  const cheminPrecedent = useRef<string | null>(null);
  const entree = useRef<Animation | null>(null);

  // Retenir : l'événement `scroll` ne remonte pas, mais se capte sur la
  // colonne. Passif — rien sur le chemin du doigt n'attend ce code.
  useEffect(() => {
    const colonne = colonneRef.current;
    if (!estMobile || !colonne) return undefined;
    const surDefilement = (e: Event) => {
      const cible = e.target;
      if (cible instanceof HTMLElement && cible.parentElement === colonne) {
        memoire.current.retenir(cheminCourant.current, cible.scrollTop);
      }
    };
    colonne.addEventListener('scroll', surDefilement, { capture: true, passive: true });
    return () => colonne.removeEventListener('scroll', surDefilement, { capture: true });
  }, [colonneRef]);

  // Un effet de MISE EN PAGE : il part après que React a posé la nouvelle
  // page, AVANT sa première peinture — ni l'animation ni la position ne
  // s'appliquent une image trop tard.
  useLayoutEffect(() => {
    if (!estMobile) return undefined;
    const precedent = cheminPrecedent.current;
    cheminPrecedent.current = chemin;
    cheminCourant.current = chemin;
    const colonne = colonneRef.current;
    if (!colonne || precedent === null || precedent === chemin) return undefined;

    // Une navigation arrivée pendant l'entrée de la précédente la remplace :
    // deux entrées empilées finiraient chacune à son heure.
    entree.current?.cancel();
    entree.current = null;
    if (
      typeof colonne.animate === 'function' &&
      doitAnimerLEntree({ mobile: estMobile, mouvementReduit: mouvementReduit(), cheminPrecedent: precedent, chemin })
    ) {
      entree.current = colonne.animate(IMAGES_ENTREE, OPTIONS_ENTREE);
    }

    const cible = pageRetientSaPosition(chemin) ? memoire.current.lire(chemin) : undefined;
    if (!cible) return undefined;
    return reprendrePosition(colonne, cible);
  }, [chemin, colonneRef]);
}

/**
 * Rend `cible` au défileur de la page dès qu'il peut l'atteindre en entier :
 * tout de suite si la liste est déjà là (le cas du retour), sinon à l'image
 * où elle le devient — ou au plus près si la page, plus courte, ne bouge
 * plus —, jusqu'au plafond. Rend la fonction qui abandonne.
 */
function reprendrePosition(colonne: HTMLElement, cible: number): () => void {
  const debut = performance.now();
  let image = 0;
  let fini = false;
  const arreter = () => {
    if (fini) return;
    fini = true;
    cancelAnimationFrame(image);
    for (const type of REPRISES) colonne.removeEventListener(type, arreter, { capture: true });
  };
  let defilablePrecedent = -1;
  let stableDepuis = debut;
  const essayer = () => {
    if (fini) return;
    const maintenant = performance.now();
    const defileur = colonne.querySelector<HTMLElement>(SELECTEUR_DEFILEUR_PAGE);
    const defilable = defileur ? defileur.scrollHeight - defileur.clientHeight : 0;
    if (defilable !== defilablePrecedent) {
      defilablePrecedent = defilable;
      stableDepuis = maintenant;
    }
    const decision = decisionRestauration({
      cible,
      defilable,
      ecouleMs: maintenant - debut,
      stableDepuisMs: maintenant - stableDepuis,
    });
    if (decision.action === 'poser' && defileur) {
      defileur.scrollTop = decision.haut;
      arreter();
    } else if (decision.action === 'renoncer') {
      arreter();
    } else {
      image = requestAnimationFrame(essayer);
    }
  };
  for (const type of REPRISES) colonne.addEventListener(type, arreter, { capture: true, passive: true });
  essayer();
  return arreter;
}
