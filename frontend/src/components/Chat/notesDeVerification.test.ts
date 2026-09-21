import { describe, expect, it } from 'vitest';

import { lireVerification, notesDeVerification } from './notesDeVerification';

const t = (key: string, vars?: Record<string, string | number>): string =>
  `${key}${vars ? ' ' + JSON.stringify(vars) : ''}`;

describe("lireVerification — ce que le serveur a établi, rien d'autre", () => {
  it('rend undefined quand rien n’est signalé', () => {
    expect(lireVerification({})).toBeUndefined();
    expect(lireVerification({ nonRetrouves: [] })).toBeUndefined();
    expect(lireVerification(null)).toBeUndefined();
    expect(lireVerification({ desaccord: { reponse: 'X', sources: [] } })).toBeUndefined();
  });

  it('lit les trois constats et ignore un désaccord mal formé', () => {
    expect(
      lireVerification({
        nonRetrouves: ['2015', 42],
        sourcesDatees: '2024-03-01',
        desaccord: { reponse: 'Justin Trudeau', sources: ['Mark Carney'] },
      }),
    ).toEqual({
      nonRetrouves: ['2015', '42'],
      sourcesDatees: '2024-03-01',
      desaccord: { reponse: 'Justin Trudeau', sources: ['Mark Carney'] },
    });
    expect(lireVerification({ desaccord: 'oui', nonRetrouves: ['x'] })).toEqual({
      nonRetrouves: ['x'],
    });
  });
});

describe('notesDeVerification — une ligne par constat, le plus grave d’abord', () => {
  it('le désaccord sur le titulaire passe avant tout', () => {
    const lignes = notesDeVerification(
      {
        nonRetrouves: ['2015'],
        sourcesDatees: '2024-03-01',
        desaccord: { reponse: 'Justin Trudeau', sources: ['Mark Carney'] },
      },
      t,
    );
    expect(lignes).toEqual([
      'chat.verification.desaccord {"sources":"Mark Carney","reponse":"Justin Trudeau"}',
      'chat.verification.sourcesDatees {"date":"1 mars 2024"}',
      'chat.verification.nonRetrouves 2015',
    ]);
  });

  it('ne dit rien sans constat', () => {
    expect(notesDeVerification(undefined, t)).toEqual([]);
    expect(notesDeVerification({ nonRetrouves: [] }, t)).toEqual([]);
  });

  it('une date illisible est montrée telle quelle plutôt que perdue', () => {
    expect(notesDeVerification({ nonRetrouves: [], sourcesDatees: 'hier' }, t)).toEqual([
      'chat.verification.sourcesDatees {"date":"hier"}',
    ]);
  });
});
