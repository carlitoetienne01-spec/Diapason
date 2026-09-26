// Les pages que la roue du téléphone dessert, dans l'ordre de la roue.
//
// 26/09/2026, chantier de la fluidité (lot 3) : au téléphone, la barre
// latérale du bureau n'était qu'un tiroir de 260 px posé sur la page — deux
// touchers et un voile pour changer d'écran. Carlito a choisi « la roue »
// (proposition A) : toutes les pages sur un arc, tournées au pouce. Cette
// liste vit ici, sans React, pour qu'un test la confronte aux routes de
// l'app : une page ajoutée à la barre et oubliée ici serait devenue
// inatteignable au téléphone (§82), sans un mot.

import type { MessageKey } from '../../i18n/translate';

/** Une destination de la roue : son chemin et la clé de son nom. */
export type PageRoue = {
  chemin: string;
  cle: MessageKey;
};

/**
 * L'ordre décidé par Carlito : la Discussion, puis les pages de la vie dans
 * l'ordre de la barre, puis Réglages et Appareils, puis le reste de
 * l'administration dans l'ordre de ses groupes (bureau, Sidebar.tsx).
 */
export const PAGES_ROUE: readonly PageRoue[] = [
  { chemin: '/', cle: 'nav.chat' },
  { chemin: '/vie/dashboard', cle: 'nav.vieDashboard' },
  { chemin: '/vie/planner', cle: 'nav.viePlanner' },
  { chemin: '/vie/tasks', cle: 'nav.vieTasks' },
  { chemin: '/vie/projects', cle: 'nav.vieProjects' },
  { chemin: '/vie/finances', cle: 'nav.vieFinances' },
  { chemin: '/vie/habits', cle: 'nav.vieHabits' },
  { chemin: '/vie/notes', cle: 'nav.vieNotes' },
  { chemin: '/vie/year-review', cle: 'nav.vieYearReview' },
  { chemin: '/settings', cle: 'nav.settings' },
  { chemin: '/devices', cle: 'nav.devices' },
  { chemin: '/get-started', cle: 'nav.getStarted' },
  { chemin: '/data-sources', cle: 'nav.dataSources' },
  { chemin: '/agents', cle: 'nav.agents' },
  { chemin: '/vie/sync', cle: 'nav.vieSync' },
  { chemin: '/dashboard', cle: 'nav.dashboard' },
  { chemin: '/logs', cle: 'nav.logs' },
];

/**
 * L'élément allumé à l'ouverture : la page où l'on est. Une adresse que la
 * roue ne connaît pas (une route future, un chemin avec sous-partie) allume
 * le plus long préfixe connu, sinon la Discussion — jamais rien.
 */
export function indexDeLaPage(chemin: string, pages: readonly PageRoue[] = PAGES_ROUE): number {
  const exact = pages.findIndex((p) => p.chemin === chemin);
  if (exact >= 0) return exact;
  let meilleur = 0;
  let longueur = 0;
  pages.forEach((p, i) => {
    if (p.chemin !== '/' && chemin.startsWith(`${p.chemin}/`) && p.chemin.length > longueur) {
      meilleur = i;
      longueur = p.chemin.length;
    }
  });
  return meilleur;
}
