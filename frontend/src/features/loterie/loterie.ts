// La loterie — la logique pure, hors du DOM et hors du réseau.
//
// Ce dépôt n'a aucun test de composant React : ce qui mérite d'être vérifié
// vit donc ici, en fonctions pures.

/** Une grille : cinq numéros parmi 49, un Grand Numéro parmi 7. */
export const NUMEROS_PAR_GRILLE = 5;
export const NUMERO_MAX = 49;
export const GRAND_NUMERO_MAX = 7;

export type Grille = { numeros: number[]; grandNumero: number };

/**
 * Lire une grille tapée à la main.
 *
 * On accepte les espaces, les virgules, les tirets — on ne devine RIEN d'autre.
 * Une saisie ambiguë est refusée avec sa raison, jamais complétée : jouer une
 * grille que l'on n'a pas choisie serait pire que de retaper.
 */
export function lireGrille(texte: string): { grille: Grille | null; erreur: string } {
  const morceaux = String(texte ?? '')
    .split(/[^0-9]+/)
    .filter(Boolean)
    .map(Number);
  if (morceaux.length === 0) return { grille: null, erreur: '' };
  if (morceaux.length !== NUMEROS_PAR_GRILLE + 1) {
    return {
      grille: null,
      erreur: `Il faut ${NUMEROS_PAR_GRILLE} numéros puis le Grand Numéro — ${morceaux.length} nombre(s) lu(s).`,
    };
  }
  const numeros = morceaux.slice(0, NUMEROS_PAR_GRILLE);
  const grandNumero = morceaux[NUMEROS_PAR_GRILLE];
  const horsBornes = numeros.find((n) => n < 1 || n > NUMERO_MAX);
  if (horsBornes !== undefined) {
    return { grille: null, erreur: `Le numéro ${horsBornes} est hors de 1 à ${NUMERO_MAX}.` };
  }
  if (new Set(numeros).size !== numeros.length) {
    return { grille: null, erreur: 'Un numéro revient deux fois.' };
  }
  if (grandNumero < 1 || grandNumero > GRAND_NUMERO_MAX) {
    return {
      grille: null,
      erreur: `Le Grand Numéro doit être entre 1 et ${GRAND_NUMERO_MAX}.`,
    };
  }
  return { grille: { numeros: [...numeros].sort((a, b) => a - b), grandNumero }, erreur: '' };
}

/** « 1 sur 13 348 188 », avec des espaces insécables fines comme en français. */
export function unSur(cote: number): string {
  if (!Number.isFinite(cote) || cote <= 0) return '—';
  return `1 sur ${Math.round(cote).toLocaleString('fr-CA')}`;
}

/**
 * Ce que la valeur p veut dire, en français.
 *
 * Un seuil nu — « p = 0,79 » — ne dit rien à qui ne fait pas de statistiques,
 * et c'est précisément la personne à qui ce module s'adresse.
 */
export function lireLaValeurP(p: number): string {
  if (!Number.isFinite(p)) return 'indéterminé';
  if (p >= 0.05) {
    return 'Aucun écart au hasard. Les tirages se comportent comme un tirage équitable : aucun numéro n’est plus probable qu’un autre.';
  }
  if (p >= 0.01) {
    return 'Un écart inhabituel. Ce n’est pas une preuve de biais — avec 49 numéros, cela arrive une fois sur vingt par pur hasard —, mais cela mérite d’être regardé.';
  }
  return 'Un écart très inhabituel. À vérifier sérieusement avant d’en conclure quoi que ce soit.';
}

/**
 * Combien de tirages représentent N années de jeu.
 *
 * Deux tirages par semaine, lundi et jeudi, soit 104 par année.
 */
export const TIRAGES_PAR_AN = 104;
export function tiragesPourAnnees(annees: number): number {
  return Math.max(1, Math.round(annees * TIRAGES_PAR_AN));
}
