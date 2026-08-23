import { describe, expect, it } from 'vitest';

import {
  construireStations,
  etapeVoisine,
  linkifier,
  stationCourante,
} from './ligne';
import type { SuccesTask } from './types';

const t = (
  id: string,
  parent: string,
  order: number,
  done = false,
): SuccesTask =>
  ({ id, title: id, parentTaskId: parent, order, done }) as SuccesTask;

describe('construireStations', () => {
  it('déroule enfants puis petits-enfants, dans le rang', () => {
    const taches = [
      t('etape', '', 0),
      t('b', 'etape', 1),
      t('a', 'etape', 0),
      t('a1', 'a', 0),
      t('autre', '', 1),
    ];
    const s = construireStations('etape', taches);
    expect(s.map((x) => x.tache.id)).toEqual(['a', 'a1', 'b']);
    expect(s.map((x) => x.profondeur)).toEqual([0, 1, 0]);
  });
});

describe('stationCourante', () => {
  it('pointe la première non cochée — là où on en est', () => {
    const s = construireStations('e', [
      t('e', '', 0),
      t('x', 'e', 0, true),
      t('y', 'e', 1),
      t('z', 'e', 2),
    ]);
    expect(stationCourante(s)).toBe('y');
  });

  it('rend null quand tout est fait — l’étape est conquise', () => {
    const s = construireStations('e', [t('e', '', 0), t('x', 'e', 0, true)]);
    expect(stationCourante(s)).toBeNull();
  });
});

describe('linkifier', () => {
  it('rend les URL cliquables et garde la ponctuation à la phrase', () => {
    const s = linkifier('Lien : https://openclassrooms.com/fr/courses/1. Voilà.');
    expect(s).toEqual([
      { type: 'texte', valeur: 'Lien : ' },
      { type: 'lien', valeur: 'https://openclassrooms.com/fr/courses/1' },
      { type: 'texte', valeur: '. Voilà.' },
    ]);
  });

  it('un texte sans lien reste un seul segment', () => {
    expect(linkifier('rien à voir ici')).toEqual([
      { type: 'texte', valeur: 'rien à voir ici' },
    ]);
  });
});

describe('etapeVoisine', () => {
  const taches = [t('e1', '', 0), t('e2', '', 1), t('e3', '', 2), t('fils', 'e1', 0)];
  it('avance et recule dans l’ordre des racines', () => {
    expect(etapeVoisine('e2', taches, 1)).toBe('e3');
    expect(etapeVoisine('e2', taches, -1)).toBe('e1');
  });
  it('s’arrête net aux extrémités', () => {
    expect(etapeVoisine('e1', taches, -1)).toBeNull();
    expect(etapeVoisine('e3', taches, 1)).toBeNull();
  });
});
