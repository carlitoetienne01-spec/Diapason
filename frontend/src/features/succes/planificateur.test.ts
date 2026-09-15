import { describe, expect, it } from 'vitest';

import {
  dateIsoLocale,
  deplacerJour,
  dimancheDeLaSemaine,
  enRetard,
  filtrer,
  grilleDuMois,
  libelleDuJour,
  lundiDeLaSemaine,
  pastillesLocales,
  resumeDuJour,
  tachesDuJour,
} from './planificateur';
import type { SuccesTask } from './types';

let compteur = 0;
function tache(partiel: Partial<SuccesTask>): SuccesTask {
  compteur += 1;
  return {
    id: `t${compteur}`,
    title: partiel.title ?? `Tâche ${compteur}`,
    done: false,
    priority: 'medium',
    date: '',
    time: '',
    projectId: '',
    parentTaskId: '',
    category: '',
    notes: '',
    emoji: '',
    templateId: '',
    groupId: '',
    order: 0,
    createdAt: '2026-09-01',
    completedDate: '',
    postponedCount: 0,
    updatedAtMs: 0,
    stage: '',
    cadence: null,
    subtasks: [],
    ...partiel,
  } as SuccesTask;
}

const AUJOURDHUI = '2026-09-13';

describe('les dates', () => {
  it('la grille du mois va du lundi au dimanche, mois voisins compris', () => {
    // Septembre 2026 commence un mardi : la grille remonte au lundi 31 août.
    const grille = grilleDuMois('2026-09-13');
    expect(grille.days[0]).toBe('2026-08-31');
    expect(grille.days[grille.days.length - 1]).toBe('2026-10-04');
    expect(grille.days.length % 7).toBe(0);
    // Février 2027 commence un lundi et finit un dimanche : exactement 4 semaines.
    const fevrier = grilleDuMois('2027-02-10');
    expect(fevrier.days[0]).toBe('2027-02-01');
    expect(fevrier.days[fevrier.days.length - 1]).toBe('2027-02-28');
    expect(fevrier.days.length).toBe(28);
  });

  it('traverse le changement d’heure sans sauter ni doubler un jour', () => {
    // À Toronto, l'heure recule dans la nuit du 1er novembre 2026.
    expect(deplacerJour('2026-10-31', 1)).toBe('2026-11-01');
    expect(deplacerJour('2026-11-01', 1)).toBe('2026-11-02');
    expect(deplacerJour('2026-11-02', -1)).toBe('2026-11-01');
    const grille = grilleDuMois('2026-11-15');
    expect(new Set(grille.days).size).toBe(grille.days.length);
  });

  it('la semaine va du lundi au dimanche', () => {
    expect(lundiDeLaSemaine('2026-09-13')).toBe('2026-09-07'); // un dimanche
    expect(lundiDeLaSemaine('2026-09-07')).toBe('2026-09-07'); // un lundi
    expect(dimancheDeLaSemaine('2026-09-09')).toBe('2026-09-13');
  });

  it('dateIsoLocale écrit la date LOCALE, pas l’UTC', () => {
    // 23 h 30 à Toronto le 12 : toISOString dirait déjà le 13.
    const soir = new Date(2026, 8, 12, 23, 30);
    expect(dateIsoLocale(soir)).toBe('2026-09-12');
  });
});

describe('les tâches du jour — la définition qui répare le clic', () => {
  it('cliquer un jour montre ses tâches : ouvertes d’abord, terminées ensuite', () => {
    const taches = [
      tache({ title: 'Faite', date: '2026-09-10', done: true, completedDate: '2026-09-11' }),
      tache({ title: 'Urgente', date: '2026-09-10', priority: 'urgent' }),
      tache({ title: 'Basse', date: '2026-09-10', priority: 'low' }),
      tache({ title: 'Autre jour', date: '2026-09-11' }),
    ];
    const jour = tachesDuJour(taches, '2026-09-10');
    expect(jour.map((t) => t.title)).toEqual(['Urgente', 'Basse', 'Faite']);
  });

  it('une tâche en retard reste visible sur SON jour — plus de point fantôme', () => {
    const retard = tache({ title: 'Oubliée', date: '2026-08-20' });
    expect(tachesDuJour([retard], '2026-08-20').map((t) => t.title)).toEqual(['Oubliée']);
    expect(enRetard([retard], AUJOURDHUI).map((t) => t.title)).toEqual(['Oubliée']);
  });

  it('une tâche cochée aujourd’hui ne disparaît pas de la vue du jour', () => {
    const faite = tache({ title: 'Cochée', date: AUJOURDHUI, done: true, completedDate: AUJOURDHUI });
    expect(tachesDuJour([faite], AUJOURDHUI)).toHaveLength(1);
  });

  it('une tâche sans date terminée appartient au jour de son achèvement', () => {
    const libre = tache({ title: 'Libre', done: true, completedDate: '2026-09-12' });
    expect(tachesDuJour([libre], '2026-09-12')).toHaveLength(1);
    expect(tachesDuJour([libre], '2026-09-13')).toHaveLength(0);
  });

  it('les chiffres du jour comptent la MÊME liste que la vue', () => {
    const taches = [
      tache({ date: '2026-09-10' }),
      tache({ date: '2026-09-10', done: true, completedDate: '2026-09-10' }),
      tache({ done: true, completedDate: '2026-09-10' }),
    ];
    expect(resumeDuJour(taches, '2026-09-10')).toEqual({ total: 3, open: 1, done: 2 });
    expect(tachesDuJour(taches, '2026-09-10')).toHaveLength(3);
  });
});

describe('les pastilles de repli', () => {
  it('un point existe si et seulement si le jour a des tâches', () => {
    const taches = [
      tache({ date: '2026-09-10' }),
      tache({ date: '2026-09-11', done: true, completedDate: '2026-09-12' }),
      tache({ done: true, completedDate: '2026-09-12' }),
      tache({ title: 'Sans rien' }),
    ];
    const jours = pastillesLocales(taches);
    expect(jours['2026-09-10']).toEqual({ open: 1, done: 0 });
    // Terminée mais PLANIFIÉE le 11 : le point vit sur le 11, comme la vue.
    expect(jours['2026-09-11']).toEqual({ open: 0, done: 1 });
    expect(jours['2026-09-12']).toEqual({ open: 0, done: 1 });
    // Alignement point ↔ clic, la propriété qui manquait :
    for (const [jour, p] of Object.entries(jours)) {
      expect(tachesDuJour(taches, jour).length).toBe(p.open + p.done);
    }
    expect(Object.keys(jours)).toHaveLength(3);
  });
});

describe('les filtres', () => {
  const taches = [
    tache({ title: 'Lundi', date: '2026-09-07' }),
    tache({ title: 'Dimanche urgent', date: '2026-09-13', priority: 'urgent' }),
    tache({ title: 'Hors semaine', date: '2026-09-14' }),
    tache({ title: 'Semaine faite', date: '2026-09-08', done: true, completedDate: '2026-09-09' }),
    tache({ title: 'Vieille ouverte', date: '2026-08-01', priority: 'high' }),
  ];

  it('« Cette semaine » : les ouvertes de la semaine, par jour puis priorité', () => {
    expect(filtrer(taches, 'week', '2026-09-10', AUJOURDHUI).map((t) => t.title)).toEqual([
      'Lundi',
      'Dimanche urgent',
    ]);
  });

  it('« Terminées » : achevées dans la semaine du jour choisi', () => {
    expect(filtrer(taches, 'done', '2026-09-10', AUJOURDHUI).map((t) => t.title)).toEqual([
      'Semaine faite',
    ]);
  });

  it('« En retard » : les ouvertes des jours passés, plus anciennes d’abord', () => {
    // « Lundi » (7 sept.) est aussi passée au 13 : le retard n'épargne
    // pas la semaine courante.
    expect(filtrer(taches, 'late', '2026-09-10', AUJOURDHUI).map((t) => t.title)).toEqual([
      'Vieille ouverte',
      'Lundi',
    ]);
  });

  it('« Priorité haute » : ouvertes high ou urgent', () => {
    expect(new Set(filtrer(taches, 'high', '2026-09-10', AUJOURDHUI).map((t) => t.title))).toEqual(
      new Set(['Dimanche urgent', 'Vieille ouverte']),
    );
  });
});

describe('le libellé du premier onglet', () => {
  it('dit « Aujourd’hui » chez soi, la date ailleurs', () => {
    expect(libelleDuJour(AUJOURDHUI, AUJOURDHUI)).toBe('Aujourd’hui');
    expect(libelleDuJour('2026-09-10', AUJOURDHUI)).toMatch(/10/);
  });
});
