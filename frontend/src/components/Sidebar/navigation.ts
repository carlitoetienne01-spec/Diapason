import { estCheminDesReglages } from '../../lib/barre';

export type Rubrique = 'discussion' | 'projets' | 'notes' | 'taches' | 'agenda' | 'tableau' | 'finances' | 'habitudes' | 'bilan' | 'reglages';

/** Le panneau est réservé à Discussion et Réglages ; le choix de repli est conservé. */
export function panneauDisponible(chemin: string): boolean {
  return estCheminDesReglages(chemin) || chemin === '/';
}

export function panneauVisible(ouvert: boolean, chemin: string): boolean {
  return ouvert && panneauDisponible(chemin);
}

export function rubriqueDuChemin(chemin: string): Rubrique {
  if (estCheminDesReglages(chemin)) return 'reglages';
  if (chemin === '/') return 'discussion';
  if (chemin === '/vie/projects') return 'projets';
  if (chemin === '/vie/notes') return 'notes';
  if (chemin === '/vie/tasks') return 'taches';
  if (chemin === '/vie/planner') return 'agenda';
  if (chemin === '/vie/dashboard') return 'tableau';
  if (chemin === '/vie/finances') return 'finances';
  if (chemin === '/vie/habits') return 'habitudes';
  if (chemin === '/vie/year-review') return 'bilan';
  return 'discussion';
}

export function correspondALaRecherche(texte: string, recherche: string): boolean {
  const normaliser = (valeur: string) => valeur.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase().trim();
  return normaliser(texte).includes(normaliser(recherche));
}

export type EtapeNavigation = { chemin: string; discussion: string | null };
export type HistoriqueNavigation = { etapes: EtapeNavigation[]; position: number };

export function memeEtape(a: EtapeNavigation, b: EtapeNavigation): boolean {
  return a.chemin === b.chemin && a.discussion === b.discussion;
}

/** §82 : revenir à une discussion doit restaurer son ID, pas seulement « / ». */
export function ajouterEtape(historique: HistoriqueNavigation, etape: EtapeNavigation): HistoriqueNavigation {
  if (memeEtape(historique.etapes[historique.position], etape)) return historique;
  const etapes = [...historique.etapes.slice(0, historique.position + 1), etape];
  return { etapes, position: etapes.length - 1 };
}
