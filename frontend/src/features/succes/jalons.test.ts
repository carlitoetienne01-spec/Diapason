import { describe, expect, it } from 'vitest';

import {
  estJalonEnAttente,
  jalonSuivant,
  jalonsEnAttente,
  projetsAJalons,
  tachesDuJour,
} from './jalons';
import type { SuccesProject, SuccesTask } from './types';

const projet = (id: string, structure: string, name = id): SuccesProject =>
  ({ id, name, structure }) as SuccesProject;

const tache = (
  id: string,
  projectId: string,
  extra: Partial<SuccesTask> = {},
): SuccesTask =>
  ({ id, title: id, projectId, done: false, date: '', order: 0, ...extra }) as SuccesTask;

const PROJETS = [
  projet('parcours', 'tree', 'Zéro à Héro'),
  projet('anglais', 'tree', 'English'),
  projet('maison', 'flat', 'Maison'),
];

describe('projetsAJalons', () => {
  it('tout ce qui n’est pas plat porte des jalons', () => {
    expect(projetsAJalons(PROJETS)).toEqual(new Set(['parcours', 'anglais']));
  });
});

describe('tachesDuJour', () => {
  it('les jalons sans date restent sur leur carte', () => {
    const taches = [
      tache('etape1', 'parcours'),
      tache('etape2', 'parcours', { date: '2026-08-25' }),
      tache('courses', 'maison'),
      tache('libre', ''),
    ];
    expect(tachesDuJour(taches, PROJETS).map((t) => t.id)).toEqual([
      'etape2',
      'courses',
      'libre',
    ]);
  });

  it('dater un jalon, c’est décider de le faire', () => {
    const jalon = tache('etape1', 'parcours');
    expect(tachesDuJour([jalon], PROJETS)).toHaveLength(0);
    expect(tachesDuJour([{ ...jalon, date: '2026-08-25' }], PROJETS)).toHaveLength(1);
  });

  it('sans projet à jalons, rien n’est masqué', () => {
    const taches = [tache('a', 'maison'), tache('b', '')];
    expect(tachesDuJour(taches, PROJETS)).toHaveLength(2);
  });
});

describe('jalonsEnAttente', () => {
  it('compte par projet, du plus gros au plus petit, sans les faits', () => {
    const taches = [
      tache('e1', 'parcours'),
      tache('e2', 'parcours'),
      tache('e3', 'parcours', { done: true }),
      tache('a1', 'anglais'),
      tache('date', 'parcours', { date: '2026-08-25' }),
    ];
    expect(
      jalonsEnAttente(taches, PROJETS).map((x) => [x.projet.name, x.total]),
    ).toEqual([
      ['Zéro à Héro', 2],
      ['English', 1],
    ]);
  });
});

describe('jalonSuivant', () => {
  const taches = [
    tache('a', 'parcours', { order: 0, done: true }),
    tache('b', 'parcours', { order: 1 }),
    tache('c', 'parcours', { order: 2 }),
  ];

  it('après une étape cochée, propose celle d’après dans l’ordre', () => {
    const suivant = jalonSuivant(taches, 'parcours', taches[0]);
    expect(suivant?.id).toBe('b');
  });

  it('sans référence, propose la première non faite', () => {
    expect(jalonSuivant(taches, 'parcours')?.id).toBe('b');
  });

  it('rend null quand le projet est fini', () => {
    const finis = [tache('a', 'parcours', { done: true })];
    expect(jalonSuivant(finis, 'parcours')).toBeNull();
  });
});
