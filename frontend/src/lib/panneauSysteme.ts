// Le panneau « Système » de la Discussion, au premier lancement.
//
// 26/09/2026 : sans choix mémorisé, le panneau s'ouvrait partout. Sous `sm`
// il n'est plus une colonne mais une superposition de 280 px (SystemPanel.tsx,
// 16 sept. 2026) : sur un téléphone de 375 px, la première chose vue était un
// tableau de jetons et de watts posé sur les trois quarts de la Discussion,
// le compositeur coupé derrière le voile. Un choix mémorisé reste un choix ;
// seul le défaut suit la largeur, lue en CSS par une requête média.

/** Le point `sm` de Tailwind 4 (40rem), écrit en `min-width` pour les vieux WebKit. */
export const REQUETE_PANNEAU_SYSTEME_EN_COLONNE = '(min-width: 40rem)';

type MatchMedia = (requete: string) => { matches: boolean };

export function panneauSystemeOuvertAuDemarrage(
  memoire: string | null,
  matchMedia: MatchMedia | undefined,
): boolean {
  if (memoire === 'false') return false;
  if (memoire === 'true') return true;
  if (!matchMedia) return true;
  try {
    return matchMedia(REQUETE_PANNEAU_SYSTEME_EN_COLONNE).matches;
  } catch {
    return true;
  }
}
