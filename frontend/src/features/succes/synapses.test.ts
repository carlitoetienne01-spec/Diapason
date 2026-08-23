import { describe, expect, it } from 'vitest';

import {
  dureeImpulsion,
  longueurApprochee,
  planifierRafale,
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

describe('planifierRafale', () => {
  it('rend vide quand il n’y a aucune arête — rien à allumer', () => {
    expect(planifierRafale([], de())).toEqual([]);
  });

  it('propage de proche en proche : chaque impulsion part d’un nœud atteint', () => {
    const rafale = planifierRafale(ARBRE, de(0, 0));
    expect(rafale.length).toBeGreaterThan(1);
    const atteints = new Set<string>();
    for (const imp of rafale.slice(0, 1)) atteints.add(imp.arriveeId);
    for (const imp of rafale.slice(1)) {
      const source = ARBRE.find((a) => a.id === imp.areteId)!;
      const depart = imp.descend ? source.parentId : source.id;
      expect(atteints.has(depart)).toBe(true);
      atteints.add(imp.arriveeId);
    }
  });

  it('ne repasse jamais deux fois sur la même arête', () => {
    for (const graine of [0, 0.3, 0.6, 0.99]) {
      const rafale = planifierRafale(ARBRE, de(graine, 0.9, 0.5, 0.5, 0.5, 0.5, 0.5));
      const ids = rafale.map((i) => i.areteId);
      expect(new Set(ids).size).toBe(ids.length);
    }
  });

  it('les départs respectent l’arrivée du relais précédent', () => {
    const rafale = planifierRafale(ARBRE, de(0, 0));
    for (const imp of rafale.slice(1)) {
      const relais = rafale.find(
        (autre) =>
          autre !== imp &&
          autre.departMs + autre.dureeMs < imp.departMs &&
          autre.arriveeId ===
            (imp.descend
              ? ARBRE.find((a) => a.id === imp.areteId)!.parentId
              : imp.areteId),
      );
      expect(relais).toBeDefined();
    }
  });

  it('se contente d’une seule impulsion sur un arbre à une arête', () => {
    const rafale = planifierRafale([arete('seule', 'r')], de(0, 0));
    expect(rafale).toHaveLength(1);
    expect(rafale[0].departMs).toBe(0);
  });

  it('cinq impulsions au grand maximum — une rafale, pas un orage', () => {
    const large = [
      arete('a', 'r'), arete('b', 'r'), arete('c', 'r'),
      arete('a1', 'a'), arete('a2', 'a'), arete('a3', 'a'),
      arete('b1', 'b'), arete('b2', 'b'), arete('c1', 'c'),
    ];
    for (const graine of [0, 0.2, 0.5, 0.8]) {
      expect(
        planifierRafale(large, de(graine, 0.1, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9)).length,
      ).toBeLessThanOrEqual(5);
    }
  });

  it('sait remonter : une impulsion peut aller vers le parent', () => {
    // graine = a1 (index 2 sur 4), sens montant (rng ≥ 0.7)
    const rafale = planifierRafale(ARBRE, de(0.5, 0.95, 0, 0, 0, 0));
    expect(rafale[0].descend).toBe(false);
    expect(rafale[0].arriveeId).toBe('a');
  });
});

describe('durées', () => {
  it('vitesse constante mais bornée', () => {
    expect(dureeImpulsion(10)).toBe(500);
    expect(dureeImpulsion(300)).toBe(720);
    expect(dureeImpulsion(9999)).toBe(1300);
  });

  it('la longueur approchée suit l’hypoténuse', () => {
    expect(longueurApprochee({ x1: 0, y1: 0, x2: 30, y2: 40 })).toBeCloseTo(55);
  });
});
