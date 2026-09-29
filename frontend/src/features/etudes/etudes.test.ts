import { describe, expect, it } from 'vitest';
import { bilanEtude, reponseModifiee, type Etude } from './etudes';

const etude = {
  objectives: ['Comprendre', 'Appliquer', 'Transférer'],
  questions: [{ id: 'q1', maxScore: 1, objective: 'Comprendre' }, { id: 'q2', maxScore: 2, objective: 'Appliquer' }],
  responses: { q1: { text: 'A' } }, assisted: ['q1'],
  grades: { q1: { score: 1, maxScore: 1 }, q2: { score: 1, maxScore: 2 } },
} as unknown as Etude;

describe('Le bilan pédagogique ne confond pas aide et autonomie', () => {
  it('compte le barème et garde la notion réussie avec un indice à revoir', () => {
    expect(bilanEtude(etude)).toEqual({ score: 2, maximum: 3, repondues: 1, aRevoir: ['Comprendre', 'Appliquer'], nonEvalues: ['Transférer'] });
  });
  it('ne prétend pas sauvegarder une nouvelle réponse avant retour du serveur', () => {
    expect(reponseModifiee(etude, 'q1', ' B ')).toBe(true);
    expect(reponseModifiee(etude, 'q1', ' A ')).toBe(false);
    expect(reponseModifiee(etude, 'q2', '')).toBe(false);
  });
});
