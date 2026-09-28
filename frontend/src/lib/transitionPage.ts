/**
 * Les transitions entre pages du téléphone (chantier « soyeux », lot 2).
 *
 * 26/09/2026, retour de Carlito sur l'APK d6052bde : « la navigation est
 * rapide maintenant mais je la veux plus smooth ». Chaque page remplaçait
 * l'autre d'une image à la suivante, et revenir sur les Tâches ramenait tout
 * en haut d'une liste de plusieurs centaines de tâches qu'on venait de
 * descendre. Sa décision : la page qui arrive glisse de ~12 px vers le haut
 * en se révélant, ~180 ms.
 *
 * Ce module ne tient que les décisions, sans DOM : `useTransitionDesPages`
 * (Layout) les applique.
 */

/**
 * 180 ms : la durée qu'a choisie Carlito, la même que le recul de la page
 * sous la roue (roue.css) — ouvrir la roue, toucher un nom et voir la page
 * arriver forment un seul geste, au même tempo. Au-delà de ~250 ms, une
 * transition se fait attendre ; en deçà de ~120, le glissement ne se voit
 * plus.
 */
export const DUREE_ENTREE_MS = 180;

/**
 * 12 px : assez pour que l'œil lise « elle arrive », trop peu pour qu'une
 * ligne de texte (20 px de haut) paraisse sauter d'un rang.
 */
export const GLISSEMENT_ENTREE_PX = 12;

/**
 * Transform et opacity SEULEMENT : les deux propriétés que le compositeur
 * anime sans refaire ni style, ni mise en page, ni peinture de la page.
 */
export const IMAGES_ENTREE: Keyframe[] = [
  { opacity: 0, transform: `translateY(${GLISSEMENT_ENTREE_PX}px)` },
  { opacity: 1, transform: 'translateY(0)' },
];

/**
 * Une décélération (le départ vif, l'arrivée douce) : la page est déjà
 * presque en place au tiers de la durée, et le contenu se lit tôt.
 * `fill` reste à « none » : l'animation finie, la colonne ne garde AUCUN
 * transform — un transform laissé sur elle ferait d'elle le bloc contenant
 * des position:fixed de la page (le volet d'une tâche des Projets). Pendant
 * les 180 ms, aucune page n'en montre (relevé au banc le 27/09/2026 sur les
 * 17 pages de la roue : 0 élément fixe dans la colonne à l'arrivée, à 90 ms
 * ni à 400 ms).
 */
export const OPTIONS_ENTREE: KeyframeAnimationOptions = {
  duration: DUREE_ENTREE_MS,
  easing: 'cubic-bezier(0.2, 0, 0, 1)',
  fill: 'none',
};

/**
 * La page qui arrive s'anime-t-elle ? Au téléphone seulement, jamais à
 * l'ouverture de l'app (rien n'arrive « depuis » une autre page, et la
 * première peinture ne doit pas être retenue à opacité nulle), jamais quand
 * l'adresse ne change pas de page (une requête `?task=…` ouvre un volet dans
 * la même page), et jamais sous « Supprimer les animations » : la page
 * s'affiche d'un coup, sans mouvement ni fondu.
 */
export function doitAnimerLEntree(p: {
  mobile: boolean;
  mouvementReduit: boolean;
  cheminPrecedent: string | null;
  chemin: string;
}): boolean {
  if (!p.mobile || p.mouvementReduit) return false;
  if (p.cheminPrecedent === null) return false;
  return p.cheminPrecedent !== p.chemin;
}

/**
 * La Discussion tient sa propre position (collée au dernier message) : lui
 * rendre une position retenue la décollerait du fil qui continue.
 */
export function pageRetientSaPosition(chemin: string): boolean {
  return chemin !== '/';
}

/**
 * Le défileur principal d'une page : l'enfant direct `.overflow-y-auto` de
 * la colonne — la même convention qu'index.css, où il reçoit la bande de la
 * roue. Relevé au banc le 27/09/2026 : 15 des 17 pages de la roue en ont
 * un ; la Discussion (qui tient sa position) et les Journaux n'en ont pas,
 * et rien n'y est retenu.
 */
export const SELECTEUR_DEFILEUR_PAGE = ':scope > .overflow-y-auto';

/**
 * Combien de temps une position retenue attend que la page soit assez haute
 * pour la reprendre. Au retour, les données sont déjà dans le magasin et la
 * liste est là dès la première image où la page est posée (mesuré au banc le
 * 27/09/2026 : Tâches, Notes, Réglages, par la roue, un lien ou le retour,
 * 27 retours sur 27 à la bonne position dès cette image) ;
 * si elles doivent revenir du Mac, une position posée après 1,2 s ferait
 * sauter une page qu'on lit déjà — on y renonce plutôt. Tout toucher,
 * molette ou touche l'annule aussi.
 */
export const PLAFOND_RESTAURATION_MS = 1200;

/**
 * Une page plus courte qu'à l'aller (des tâches cochées depuis) ne
 * grandira pas : si sa hauteur n'a pas bougé depuis 100 ms — six images —
 * elle est posée, et on la descend au plus près de la position retenue
 * plutôt que de la laisser en haut. Une page vide (hauteur 0) attend : elle
 * charge encore.
 */
export const STABILITE_RESTAURATION_MS = 100;

export type DecisionRestauration =
  | { action: 'poser'; haut: number }
  | { action: 'attendre' }
  | { action: 'renoncer' };

/**
 * Où en est la reprise d'une position retenue : la poser dès que la page
 * peut l'atteindre EN ENTIER (une position à moitié reprise, puis complétée,
 * ferait deux sauts) ; au plus près si la page, plus courte, ne bouge plus ;
 * renoncer au plafond ou sans rien à reprendre.
 */
export function decisionRestauration(p: {
  cible: number;
  defilable: number;
  ecouleMs: number;
  /** Depuis combien de temps `defilable` n'a pas changé. */
  stableDepuisMs?: number;
  plafondMs?: number;
}): DecisionRestauration {
  if (!(p.cible > 0)) return { action: 'renoncer' };
  if (p.defilable >= p.cible) return { action: 'poser', haut: p.cible };
  if (p.ecouleMs >= (p.plafondMs ?? PLAFOND_RESTAURATION_MS)) return { action: 'renoncer' };
  if (p.defilable > 0 && (p.stableDepuisMs ?? 0) >= STABILITE_RESTAURATION_MS) {
    return { action: 'poser', haut: p.defilable };
  }
  return { action: 'attendre' };
}

/**
 * La position de défilement de chaque page, par chemin. Bornée : une page
 * oubliée depuis longtemps cède sa place (ordre d'écriture).
 */
export function creerMemoireDefilement(capacite = 24) {
  const positions = new Map<string, number>();
  return {
    retenir(chemin: string, haut: number) {
      positions.delete(chemin);
      positions.set(chemin, Math.max(0, Math.round(haut)));
      while (positions.size > capacite) {
        const plusAncienne = positions.keys().next().value;
        if (plusAncienne === undefined) break;
        positions.delete(plusAncienne);
      }
    },
    lire(chemin: string): number | undefined {
      return positions.get(chemin);
    },
    taille(): number {
      return positions.size;
    },
  };
}

export type MemoireDefilement = ReturnType<typeof creerMemoireDefilement>;
