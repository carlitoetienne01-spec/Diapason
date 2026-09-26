import { describe, expect, it } from 'vitest';

import {
  dureeImpulsion,
  impulsionAleatoire,
  longueurApprochee,
  plafondImpulsions,
  relaisDepuis,
  type AreteSynapse,
} from './synapses';

const arete = (id: string, parentId: string, y2 = 200): AreteSynapse => ({
  id,
  parentId,
  x1: 100,
  y1: 100,
  x2: 100,
  y2,
});

// r1 -> a -> a1, a2 ; r1 -> b
const ARBRE = [arete('a', 'r1'), arete('b', 'r1'), arete('a1', 'a'), arete('a2', 'a')];

/** Un dé truqué qui rend les valeurs données puis 0. */
const de = (...valeurs: number[]) => {
  let i = 0;
  return () => valeurs[i++] ?? 0;
};

describe('impulsionAleatoire', () => {
  it('rend null quand il n’y a rien à allumer', () => {
    expect(impulsionAleatoire([], new Set(), de())).toBeNull();
  });

  it('ne choisit jamais une arête déjà allumée', () => {
    const occupees = new Set(['a', 'a1', 'a2']);
    for (const graine of [0, 0.4, 0.99]) {
      const imp = impulsionAleatoire(ARBRE, occupees, de(graine, 0));
      expect(imp?.areteId).toBe('b');
    }
  });

  it('rend null quand tout est allumé — le plafond, pas l’orage', () => {
    expect(
      impulsionAleatoire(ARBRE, new Set(['a', 'b', 'a1', 'a2']), de()),
    ).toBeNull();
  });

  it('descend le plus souvent, mais sait remonter', () => {
    const descend = impulsionAleatoire(ARBRE, new Set(), de(0, 0.3));
    expect(descend).toMatchObject({ areteId: 'a', descend: true, arriveeId: 'a' });
    const remonte = impulsionAleatoire(ARBRE, new Set(), de(0, 0.9));
    expect(remonte).toMatchObject({ areteId: 'a', descend: false, arriveeId: 'r1' });
  });
});

describe('relaisDepuis', () => {
  it('repart du nœud atteint vers une voisine libre, dans le bon sens', () => {
    // depuis « a » : descentes vers a1/a2, remontée par l'arête « a » elle-même
    const imp = relaisDepuis('a', ARBRE, new Set(['a']), de(0));
    expect(imp).toMatchObject({ descend: true });
    expect(['a1', 'a2']).toContain(imp?.areteId);
  });

  it('sait remonter quand c’est la seule voie libre', () => {
    const imp = relaisDepuis('a', ARBRE, new Set(['a1', 'a2']), de(0));
    expect(imp).toMatchObject({ areteId: 'a', descend: false, arriveeId: 'r1' });
  });

  it('rend null dans un cul-de-sac tout occupé', () => {
    expect(relaisDepuis('a', ARBRE, new Set(['a', 'a1', 'a2']), de())).toBeNull();
    expect(relaisDepuis('a1', ARBRE, new Set(['a1']), de())).toBeNull();
  });
});

describe('cadence', () => {
  it('les durées sont lentes et bornées — le reproche était « trop rapide »', () => {
    expect(dureeImpulsion(10)).toBe(1600);
    expect(dureeImpulsion(400)).toBe(2400);
    expect(dureeImpulsion(9999)).toBe(3600);
  });

  it('le plafond grandit avec l’arbre sans jamais tourner à l’orage', () => {
    expect(plafondImpulsions(2)).toBe(3);
    expect(plafondImpulsions(27)).toBe(9);
    expect(plafondImpulsions(400)).toBe(9);
  });

  it('la longueur approchée suit l’hypoténuse', () => {
    expect(longueurApprochee({ x1: 0, y1: 0, x2: 30, y2: 40 })).toBeCloseTo(55);
  });
});
