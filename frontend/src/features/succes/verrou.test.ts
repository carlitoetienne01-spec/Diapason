import { describe, expect, it } from 'vitest';

import type { SuccesTask } from './types';
import { progressionSequentielle, tachesVerrouillees } from './verrou';

const t = (
  id: string,
  parent: string,
  order: number,
  done = false,
): SuccesTask =>
  ({ id, title: id, parentTaskId: parent, order, done }) as SuccesTask;

describe('tachesVerrouillees', () => {
  it('ne verrouille rien quand le projet ne le demande pas', () => {
    const taches = [t('r', '', 0), t('a', 'r', 0), t('b', 'r', 1)];
    expect(tachesVerrouillees(taches, false).size).toBe(0);
  });

  it('laisse la première de la fratrie ouverte et ferme les suivantes', () => {
    const taches = [t('r', '', 0), t('a', 'r', 0), t('b', 'r', 1), t('c', 'r', 2)];
    const verrous = tachesVerrouillees(taches, true);
    expect(verrous.has('a')).toBe(false);
    expect(verrous.get('b')).toBe('a');
    expect(verrous.get('c')).toBe('a');
  });

  it('ouvre la suivante dès que la précédente est cochée', () => {
    const taches = [t('r', '', 0), t('a', 'r', 0, true), t('b', 'r', 1), t('c', 'r', 2)];
    const verrous = tachesVerrouillees(taches, true);
    expect(verrous.has('b')).toBe(false);
    expect(verrous.get('c')).toBe('b');
  });

  it('ne verrouille jamais une racine — les branches avancent en parallèle', () => {
    const taches = [t('r1', '', 0), t('r2', '', 1), t('r3', '', 2)];
    expect(tachesVerrouillees(taches, true).size).toBe(0);
  });

  it('propage le verrou aux stations d’un cours encore fermé', () => {
    const taches = [
      t('etape', '', 0),
      t('cours1', 'etape', 0),
      t('cours2', 'etape', 1),
      t('station', 'cours2', 0),
    ];
    const verrous = tachesVerrouillees(taches, true);
    expect(verrous.get('cours2')).toBe('cours1');
    expect(verrous.get('station')).toBe('cours1');
  });

  it('ne verrouille pas une tâche déjà faite — rouvrir la précédente n’efface rien', () => {
    const taches = [t('r', '', 0), t('a', 'r', 0), t('b', 'r', 1, true)];
    expect(tachesVerrouillees(taches, true).has('b')).toBe(false);
  });

  it('départage deux rangs égaux par identifiant plutôt que par hasard', () => {
    const taches = [t('r', '', 0), t('zzz', 'r', 0), t('aaa', 'r', 0)];
    const verrous = tachesVerrouillees(taches, true);
    expect(verrous.get('zzz')).toBe('aaa');
    expect(verrous.has('aaa')).toBe(false);
  });

  it('survit à un parent absent sans boucler', () => {
    const taches = [t('orphelin', 'disparu', 0), t('suivant', 'disparu', 1)];
    const verrous = tachesVerrouillees(taches, true);
    expect(verrous.get('suivant')).toBe('orphelin');
  });
});

describe('progressionSequentielle', () => {
  it('ne vaut que pour un arbre ou une carte', () => {
    expect(progressionSequentielle('tree', { sequential: true })).toBe(true);
    expect(progressionSequentielle('mindmap', { sequential: true })).toBe(true);
    expect(progressionSequentielle('network', { sequential: true })).toBe(false);
    expect(progressionSequentielle('flat', { sequential: true })).toBe(false);
  });

  it('reste faux sans réglage', () => {
    expect(progressionSequentielle('tree', undefined)).toBe(false);
    expect(progressionSequentielle('tree', {})).toBe(false);
  });
});
