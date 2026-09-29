/**
 * Le suivi des pages du téléphone : l'entrée animée de la page qui arrive et
 * la position retenue de celle qu'on quitte (chantier « soyeux », lot 2).
 * `useTransitionDesPages` (Layout) ne fait que le brancher sur la colonne.
 *
 * 27/09/2026, contre-épreuve du chantier : tout ceci vivait dans le corps du
 * crochet React, que vitest n'exécute pas (aucun test de composant dans ce
 * dépôt). Cinq mutations y survivaient à la suite complète : supprimer la
 * ligne qui pose la position, rendre celle de la page QUITTÉE, laisser un
 * défileur imbriqué écraser celle de la page, ne plus annuler la reprise au
 * toucher, ne plus suivre le chemin courant — et une sixième, ne plus
 * transmettre « Supprimer les animations ». Les « 27 retours sur 27 » du
 * banc ne tenaient à aucun test. Sorti du crochet, le même code s'exécute
 * sous jsdom avec une horloge et des images injectées (suiviDesPages.test.ts).
 */
import {
  IMAGES_ENTREE,
  OPTIONS_ENTREE,
  SELECTEUR_DEFILEUR_PAGE,
  creerMemoireDefilement,
  decisionRestauration,
  doitAnimerLEntree,
  pageRetientSaPosition,
  type MemoireDefilement,
} from './transitionPage';

/** Ce qui annonce que la personne a repris la main sur la page. */
export const REPRISES = ['touchstart', 'wheel', 'pointerdown', 'keydown'] as const;

/** Le temps et les images, injectables : `performance` et `requestAnimationFrame` au vrai. */
export type Horloge = {
  maintenant(): number;
  demanderImage(suite: () => void): number;
  annulerImage(id: number): void;
};

export const HORLOGE_DU_NAVIGATEUR: Horloge = {
  maintenant: () => performance.now(),
  demanderImage: (suite) => requestAnimationFrame(() => suite()),
  annulerImage: (id) => cancelAnimationFrame(id),
};

/**
 * Retient la position du défileur PRINCIPAL de la page — l'enfant direct de
 * la colonne, le même que vise index.css — sous le chemin courant. Un
 * défileur imbriqué (une liste dans un volet, un tableau large) défile aussi,
 * et l'événement `scroll` capté sur la colonne le signale : il ne doit jamais
 * écraser la position de la page.
 */
export function retenirSiDefileurDePage(
  colonne: HTMLElement,
  cible: EventTarget | null,
  chemin: string,
  memoire: MemoireDefilement,
): boolean {
  if (!(cible instanceof HTMLElement) || cible.parentElement !== colonne) return false;
  memoire.retenir(chemin, cible.scrollTop);
  return true;
}

/**
 * Rend `cible` au défileur de la page dès qu'il peut l'atteindre en entier :
 * tout de suite si la liste est déjà là (le cas du retour), sinon à l'image
 * où elle le devient — ou au plus près si la page, plus courte, ne bouge
 * plus —, jusqu'au plafond. Tout toucher, molette, pointeur ou touche
 * l'annule : la reprise ne doit jamais sauter sous un doigt qui lit déjà.
 * Rend la fonction qui abandonne.
 */
export function reprendrePosition(colonne: HTMLElement, cible: number, horloge: Horloge = HORLOGE_DU_NAVIGATEUR): () => void {
  const debut = horloge.maintenant();
  let image = 0;
  let fini = false;
  const arreter = () => {
    if (fini) return;
    fini = true;
    horloge.annulerImage(image);
    for (const type of REPRISES) colonne.removeEventListener(type, arreter, { capture: true });
  };
  let defilablePrecedent = -1;
  let stableDepuis = debut;
  const essayer = () => {
    if (fini) return;
    const maintenant = horloge.maintenant();
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
      image = horloge.demanderImage(essayer);
    }
  };
  for (const type of REPRISES) colonne.addEventListener(type, arreter, { capture: true, passive: true });
  essayer();
  return arreter;
}

/**
 * L'état du suivi, d'une navigation à l'autre. `naviguer` est appelé à
 * chaque chemin, AVANT la première peinture de la nouvelle page (effet de
 * mise en page) : ni l'animation ni la position ne s'appliquent une image
 * trop tard.
 */
export function creerSuiviDesPages(o: { mobile: boolean; mouvementReduit: () => boolean; horloge?: Horloge }) {
  const memoire = creerMemoireDefilement();
  let cheminCourant: string | null = null;
  let entree: Animation | null = null;

  return {
    memoire,
    /** Le chemin sous lequel les défilements sont retenus. */
    chemin: () => cheminCourant,
    /** L'écouteur `scroll` de la colonne (capture, passif). */
    surDefilement(colonne: HTMLElement, e: Event): void {
      if (cheminCourant === null) return;
      retenirSiDefileurDePage(colonne, e.target, cheminCourant, memoire);
    },
    /** Rend de quoi abandonner la reprise en cours, s'il y en a une. */
    naviguer(colonne: HTMLElement | null, chemin: string, directionRoue?: number): (() => void) | undefined {
      const precedent = cheminCourant;
      cheminCourant = chemin;
      if (!colonne || precedent === null || precedent === chemin) return undefined;

      // Une navigation arrivée pendant l'entrée de la précédente la remplace :
      // deux entrées empilées finiraient chacune à son heure.
      entree?.cancel();
      entree = null;
      if (
        typeof colonne.animate === 'function' &&
        doitAnimerLEntree({ mobile: o.mobile, mouvementReduit: o.mouvementReduit(), cheminPrecedent: precedent, chemin })
      ) {
        entree = colonne.animate(directionRoue ? [
          { opacity: 0.92, transform: `translateY(${directionRoue > 0 ? 12 : -12}px)` },
          { opacity: 1, transform: 'translateY(0)' },
        ] : IMAGES_ENTREE, directionRoue ? { ...OPTIONS_ENTREE, duration: 160 } : OPTIONS_ENTREE);
      }

      const cible = pageRetientSaPosition(chemin) ? memoire.lire(chemin) : undefined;
      if (!cible) return undefined;
      return reprendrePosition(colonne, cible, o.horloge);
    },
  };
}

export type SuiviDesPages = ReturnType<typeof creerSuiviDesPages>;
