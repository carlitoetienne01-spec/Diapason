import { describe, expect, it } from 'vitest';

import { buildProjectTaskTree } from './ProjectTreeView';
import type { SuccesTask } from './types';

const t = (
  id: string,
  title: string,
  parent: string,
  order: number,
  done = false,
): SuccesTask =>
  ({ id, title, parentTaskId: parent, order, done }) as SuccesTask;

describe('buildProjectTaskTree', () => {
  it('range les branches par rang, pas par ordre alphabétique', () => {
    const roots = buildProjectTaskTree([
      t('c', 'Zéro', '', 2),
      t('a', 'Par où commencer', '', 0),
      t('b', 'Ailleurs', '', 1),
    ]);
    expect(roots.map((n) => n.id)).toEqual(['a', 'b', 'c']);
  });

  it('ne déplace pas une tâche parce qu’elle vient d’être cochée', () => {
    const roots = buildProjectTaskTree([
      t('r', 'Étape', '', 0),
      t('s1', 'Station 1', 'r', 0, true),
      t('s2', 'Station 2', 'r', 1),
    ]);
    expect(roots[0].children.map((n) => n.id)).toEqual(['s1', 's2']);
  });

  it('trie aussi les enfants, à tous les étages', () => {
    const roots = buildProjectTaskTree([
      t('r', 'Étape', '', 0),
      t('c2', 'Cours 2', 'r', 1),
      t('c1', 'Cours 1', 'r', 0),
      t('s2', 'Station 2', 'c1', 1),
      t('s1', 'Station 1', 'c1', 0),
    ]);
    expect(roots[0].children.map((n) => n.id)).toEqual(['c1', 'c2']);
    expect(roots[0].children[0].children.map((n) => n.id)).toEqual(['s1', 's2']);
  });

  it('départage deux rangs égaux par le titre, pour un rendu stable', () => {
    const roots = buildProjectTaskTree([
      t('x', 'Bravo', '', 0),
      t('y', 'Alpha', '', 0),
    ]);
    expect(roots.map((n) => n.title)).toEqual(['Alpha', 'Bravo']);
  });

  it('promeut en racine un enfant dont le parent a disparu', () => {
    const roots = buildProjectTaskTree([t('orphelin', 'Perdu', 'envolé', 0)]);
    expect(roots.map((n) => n.id)).toEqual(['orphelin']);
  });
});
