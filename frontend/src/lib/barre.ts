// La barre latérale sur un écran étroit — phase 3, étape 5
// (docs/development/diapason-mobile.md).
//
// 26/09/2026 : la barre démarrait OUVERTE partout. Sous `md` elle n'est plus
// une colonne mais un tiroir `fixed` de 260 px posé sur la page : à 390 px de
// large, elle cachait les deux tiers de la Discussion à chaque lancement, et
// ne se refermait jamais après un choix — toucher « Tâches » laissait le
// tiroir par-dessus la page des tâches, qu'il fallait deviner derrière le
// voile. Ce module ne décide que de l'ÉTAT ; la largeur reste au CSS
// (`fixed md:relative` dans Sidebar.tsx), et ce que le JS en sait vient d'une
// requête média lue une fois, jamais de `innerWidth` (règle 2 de
// docs/development/mini-panneau-responsive.md).

/**
 * La requête du point de rupture `md` de Tailwind 4 (48rem). Au-dessus, la
 * barre est une colonne à côté de la page ; au-dessous, un tiroir par-dessus.
 * Écrite en `min-width` plutôt qu'en syntaxe d'intervalle (`width < 48rem`),
 * que les WKWebView antérieures à Safari 16.4 ne comprennent pas.
 */
export const REQUETE_BARRE_EN_COLONNE = '(min-width: 48rem)';

/** Les pages que le tiroir des Réglages dessert : y entrer l'ouvre. */
export const CHEMINS_DES_REGLAGES = [
  '/settings',
  '/get-started',
  '/data-sources',
  '/agents',
  '/logs',
  '/vie/sync',
  '/devices',
  '/dashboard',
] as const;

export function estCheminDesReglages(chemin: string): boolean {
  return (CHEMINS_DES_REGLAGES as readonly string[]).includes(chemin);
}

type MatchMedia = (requete: string) => { matches: boolean };

/**
 * La barre est-elle un tiroir posé sur la page ? Faux quand on ne peut pas le
 * savoir (jsdom, rendu serveur) : c'est l'ancien comportement, sans surprise.
 */
export function barreSuperposee(matchMedia: MatchMedia | undefined): boolean {
  if (!matchMedia) return false;
  try {
    return !matchMedia(REQUETE_BARRE_EN_COLONNE).matches;
  } catch {
    return false;
  }
}

/** Ouverte au lancement seulement là où elle ne couvre pas la page. */
export function barreOuverteAuDemarrage(matchMedia: MatchMedia | undefined): boolean {
  return !barreSuperposee(matchMedia);
}

/**
 * L'état de la barre après une navigation.
 *
 * Sur une colonne (bureau, mini-panneau large), rien ne change. En tiroir,
 * une navigation est un CHOIX fait dans le tiroir — la seule chose qu'on
 * puisse toucher tant que le voile couvre la page — et le tiroir se retire
 * pour montrer ce qu'on a choisi. Deux exceptions, qui ne sont pas des
 * choix mais le tiroir qui change de contenu : entrer dans les Réglages
 * (« Réglages » remplace la liste par les onglets d'administration) et en
 * sortir par « Retour » (la liste revient). Refermer là aurait obligé à
 * rouvrir le tiroir pour voir les onglets qu'on venait de demander.
 */
export function barreApresNavigation(entree: {
  ouverte: boolean;
  superposee: boolean;
  avant: string;
  apres: string;
}): boolean {
  const { ouverte, superposee, avant, apres } = entree;
  if (!ouverte || !superposee) return ouverte;
  const entreDansLesReglages = !estCheminDesReglages(avant) && estCheminDesReglages(apres);
  const sortDesReglages = estCheminDesReglages(avant) && !estCheminDesReglages(apres);
  if (entreDansLesReglages || sortDesReglages) return true;
  return false;
}

/**
 * Le bouton retour d'Android, demandé par la coquille (verbe `retour`) :
 * un tiroir ouvert se ferme d'abord, comme dans toute app Android. Une
 * colonne (téléphone à l'horizontale, au-delà de 768 px) n'est pas un tiroir :
 * le retour revient alors à la page précédente, sans toucher à la barre.
 * Rend `true` quand le retour a été consommé.
 */
export function retourFermeLaBarre(ouverte: boolean, superposee: boolean): boolean {
  return ouverte && superposee;
}
