// La logique du Planificateur — pure, donc vérifiable sous vitest.
//
// Diagnostic du 13 septembre 2026 (« des points où il n'y a pas de tâches,
// des points où je clique et je ne vois pas les tâches ») : le clic sur un
// jour basculait sur « Terminées de la semaine », aucune vue ne montrait les
// tâches du jour choisi, une tâche en retard posait un point qu'aucune vue
// ne savait expliquer, et les chiffres du jour venaient d'une autre source
// que la liste. Ici, UNE définition de « tâche du jour » sert à tout : la
// vue Jour, les chiffres, et les pastilles de repli — un point sans tâches,
// ou des tâches sans point, est un mensonge.

import type { SuccesTask } from './types';

export type FiltrePlanner = 'day' | 'week' | 'done' | 'high' | 'late';

export interface Pastille {
  open: number;
  done: number;
}

const RANG_PRIORITE: Record<string, number> = { urgent: 0, high: 1, medium: 2, low: 3 };

// ---------------------------------------------------------------------------
// Dates locales — jamais d'UTC : `toISOString` recule d'un jour le soir à
// Toronto, et le calendrier pointerait la veille.
// ---------------------------------------------------------------------------

export function dateIsoLocale(valeur = new Date()): string {
  const annee = valeur.getFullYear();
  const mois = String(valeur.getMonth() + 1).padStart(2, '0');
  const jour = String(valeur.getDate()).padStart(2, '0');
  return `${annee}-${mois}-${jour}`;
}

/** Midi, pas minuit : au changement d'heure, minuit peut ne pas exister. */
export function analyserIso(iso: string): Date {
  const [annee, mois, jour] = iso.split('-').map(Number);
  return new Date(annee, mois - 1, jour, 12);
}

export function deplacerJour(iso: string, jours: number): string {
  const suivant = analyserIso(iso);
  suivant.setDate(suivant.getDate() + jours);
  return dateIsoLocale(suivant);
}

export function lundiDeLaSemaine(ancre: string): string {
  const date = analyserIso(ancre);
  const jour = (date.getDay() + 6) % 7;
  date.setDate(date.getDate() - jour);
  return dateIsoLocale(date);
}

export function dimancheDeLaSemaine(ancre: string): string {
  return deplacerJour(lundiDeLaSemaine(ancre), 6);
}

export interface GrilleMois {
  year: number;
  month: number;
  days: string[];
  label: string;
}

/** La grille du mois : semaines complètes, du lundi au dimanche. */
export function grilleDuMois(ancre: string): GrilleMois {
  const date = analyserIso(ancre);
  const year = date.getFullYear();
  const month = date.getMonth();
  const premier = dateIsoLocale(new Date(year, month, 1, 12));
  const debut = lundiDeLaSemaine(premier);
  const dernierJour = new Date(year, month + 1, 0).getDate();
  const fin = dateIsoLocale(new Date(year, month, dernierJour, 12));
  const dernier = deplacerJour(lundiDeLaSemaine(fin), 6);
  const days: string[] = [];
  let curseur = debut;
  while (curseur <= dernier) {
    days.push(curseur);
    curseur = deplacerJour(curseur, 1);
  }
  return {
    year,
    month,
    days,
    label: new Intl.DateTimeFormat('fr-CA', { month: 'long', year: 'numeric' }).format(date),
  };
}

// ---------------------------------------------------------------------------
// « Les tâches du jour D » — LA définition partagée.
// ---------------------------------------------------------------------------

const comparerOuvertes = (a: SuccesTask, b: SuccesTask): number => {
  const parPriorite = (RANG_PRIORITE[a.priority] ?? 9) - (RANG_PRIORITE[b.priority] ?? 9);
  if (parPriorite) return parPriorite;
  const parHeure = (a.time || '99:99').localeCompare(b.time || '99:99');
  if (parHeure) return parHeure;
  return (a.order ?? 0) - (b.order ?? 0);
};

/**
 * Planifiée ce jour (quel que soit son état), ou sans date et terminée ce
 * jour. Les ouvertes d'abord (priorité, heure), les terminées ensuite : une
 * tâche cochée aujourd'hui reste sous les yeux au lieu de disparaître.
 */
export function tachesDuJour(taches: SuccesTask[], jour: string): SuccesTask[] {
  const duJour = taches.filter(
    (t) => t.date === jour || (!t.date && t.done && t.completedDate === jour),
  );
  const ouvertes = duJour.filter((t) => !t.done).sort(comparerOuvertes);
  const terminees = duJour.filter((t) => t.done).sort(comparerOuvertes);
  return [...ouvertes, ...terminees];
}

/** Les ouvertes dont le jour est passé — celles que rien ne montrait. */
export function enRetard(taches: SuccesTask[], aujourdHui: string): SuccesTask[] {
  return taches
    .filter((t) => !t.done && !!t.date && t.date < aujourdHui)
    .sort((a, b) => a.date.localeCompare(b.date) || comparerOuvertes(a, b));
}

/** Les chiffres du jour — calculés sur la MÊME liste que la vue Jour. */
export function resumeDuJour(
  taches: SuccesTask[],
  jour: string,
): { total: number; open: number; done: number } {
  const duJour = tachesDuJour(taches, jour);
  const done = duJour.filter((t) => t.done).length;
  return { total: duJour.length, open: duJour.length - done, done };
}

/**
 * Les pastilles de repli, quand le serveur ne répond pas : mêmes règles que
 * `tachesDuJour`, sans la projection des récurrences (elle est au serveur).
 */
export function pastillesLocales(taches: SuccesTask[]): Record<string, Pastille> {
  const jours: Record<string, Pastille> = {};
  const case_ = (iso: string) => (jours[iso] ??= { open: 0, done: 0 });
  for (const t of taches) {
    if (t.date) {
      const c = case_(t.date);
      if (t.done) c.done += 1;
      else c.open += 1;
    } else if (t.done && t.completedDate) {
      case_(t.completedDate).done += 1;
    }
  }
  return jours;
}

// ---------------------------------------------------------------------------
// Les filtres de la liste.
// ---------------------------------------------------------------------------

export function filtrer(
  taches: SuccesTask[],
  filtre: FiltrePlanner,
  jourChoisi: string,
  aujourdHui: string,
): SuccesTask[] {
  const debutSemaine = lundiDeLaSemaine(jourChoisi);
  const finSemaine = dimancheDeLaSemaine(jourChoisi);
  if (filtre === 'day') return tachesDuJour(taches, jourChoisi);
  if (filtre === 'late') return enRetard(taches, aujourdHui);
  if (filtre === 'week') {
    return taches
      .filter((t) => !!t.date && !t.done && t.date >= debutSemaine && t.date <= finSemaine)
      .sort((a, b) => a.date.localeCompare(b.date) || comparerOuvertes(a, b));
  }
  if (filtre === 'done') {
    return taches.filter(
      (t) =>
        t.done &&
        !!t.completedDate &&
        t.completedDate >= debutSemaine &&
        t.completedDate <= finSemaine,
    );
  }
  return taches.filter((t) => !t.done && (t.priority === 'high' || t.priority === 'urgent'));
}

/** Le libellé du premier onglet : le jour choisi, ou « Aujourd'hui ». */
export function libelleDuJour(jourChoisi: string, aujourdHui: string): string {
  if (jourChoisi === aujourdHui) return 'Aujourd’hui';
  return new Intl.DateTimeFormat('fr-CA', { day: 'numeric', month: 'short' }).format(
    analyserIso(jourChoisi),
  );
}
