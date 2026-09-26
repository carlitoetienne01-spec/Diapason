import { useEffect, useRef } from 'react';

/** Le strict nécessaire d'une cible d'événements, pour pouvoir la doubler. */
type Cible = {
  addEventListener: (type: string, handler: () => void) => void;
  removeEventListener: (type: string, handler: () => void) => void;
};

type Options = {
  /** Lue à chaque déclenchement : une fermeture périmée rappellerait l'ancien état. */
  getRefresh: () => () => void;
  minIntervalMs: number;
  estVisible: () => boolean;
  maintenant: () => number;
  fenetre: Cible;
  document: Cible;
};

/**
 * Branche le rafraîchissement au retour du focus. Rend la fonction de retrait.
 *
 * Séparée du crochet pour être vérifiable sans navigateur : la suite de tests
 * de ce dépôt tourne sous node avec des doublures, sans jsdom.
 */
export function brancherRafraichissement(options: Options): () => void {
  const { getRefresh, minIntervalMs, estVisible, maintenant, fenetre } = options;
  let derniereFois = 0;

  const relire = () => {
    const t = maintenant();
    // Étouffe la rafale : macOS émet plusieurs focus d'affilée quand on
    // clique dans une fenêtre, et chacun aurait lancé une salve de requêtes.
    if (t - derniereFois < minIntervalMs) return;
    derniereFois = t;
    getRefresh()();
  };

  const surVisibilite = () => {
    // Le focus et la visibilité ne coïncident pas : changer d'onglet modifie
    // la seconde sans toucher au premier.
    if (estVisible()) relire();
  };

  fenetre.addEventListener('focus', relire);
  options.document.addEventListener('visibilitychange', surVisibilite);
  return () => {
    fenetre.removeEventListener('focus', relire);
    options.document.removeEventListener('visibilitychange', surVisibilite);
  };
}

/**
 * Relit les données quand la fenêtre redevient active.
 *
 * Constaté le 22 août 2026 : dans l'application de bureau, une page ouverte
 * gardait son état indéfiniment. Des tâches créées ailleurs n'apparaissaient
 * pas, et un projet supprimé restait affiché — l'écran vieillissait sans rien
 * dire, ce qui se lit comme un bogue. Ce n'est pas propre aux projets : toute
 * page Succès peut être dépassée par le téléphone, par une autre fenêtre, ou
 * par l'assistant.
 */
export function useRefreshOnFocus(refresh: () => void, minIntervalMs = 2000): void {
  // La référence garde la dernière fonction sans réabonner l'écouteur à chaque
  // rendu : un `refresh` recréé à chaque passage ferait autrement ajouter et
  // retirer l'écouteur en boucle, et rappellerait une fermeture périmée.
  const dernier = useRef(refresh);
  dernier.current = refresh;

  useEffect(
    () =>
      brancherRafraichissement({
        getRefresh: () => dernier.current,
        minIntervalMs,
        estVisible: () => document.visibilityState === 'visible',
        maintenant: () => Date.now(),
        fenetre: window,
        document,
      }),
    [minIntervalMs],
  );
}
