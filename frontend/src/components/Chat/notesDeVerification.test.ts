import { describe, expect, it } from 'vitest';

import {
  badgeDeVerification,
  lireVerification,
  notesDeVerification,
  peutVerifierEnLigne,
} from './notesDeVerification';

const t = (key: string, vars?: Record<string, string | number>): string =>
  `${key}${vars ? ' ' + JSON.stringify(vars) : ''}`;

describe("lireVerification — ce que le serveur a établi, rien d'autre", () => {
  it('rend undefined quand rien n’est signalé', () => {
    expect(lireVerification({})).toBeUndefined();
    expect(lireVerification({ notFound: [] })).toBeUndefined();
    expect(lireVerification(null)).toBeUndefined();
    expect(lireVerification({ disagreement: { answer: 'X', sources: [] } })).toBeUndefined();
    expect(lireVerification({ level: 'unknown' })).toBeUndefined();
  });

  it('lit le niveau, la recherche tentée et les trois constats', () => {
    expect(
      lireVerification({
        level: 'partial',
        searchTried: true,
        notFound: ['2015', 42],
        sourcesDatedAt: '2024-03-01',
        disagreement: { answer: 'Justin Trudeau', sources: ['Mark Carney'] },
      }),
    ).toEqual({
      level: 'partial',
      searchTried: true,
      notFound: ['2015', '42'],
      sourcesDatedAt: '2024-03-01',
      disagreement: { answer: 'Justin Trudeau', sources: ['Mark Carney'] },
    });
    expect(lireVerification({ disagreement: 'oui', notFound: ['x'] })).toEqual({
      notFound: ['x'],
    });
    expect(lireVerification({ level: 'verified', searchTried: true })).toEqual({
      level: 'verified',
      searchTried: true,
      notFound: [],
    });
  });

  it('lit encore les clés françaises des messages enregistrés le 20/09', () => {
    expect(
      lireVerification({
        nonRetrouves: ['2015'],
        sourcesDatees: '2024-03-01',
        desaccord: { reponse: 'Justin Trudeau', sources: ['Mark Carney'] },
      }),
    ).toEqual({
      notFound: ['2015'],
      sourcesDatedAt: '2024-03-01',
      disagreement: { answer: 'Justin Trudeau', sources: ['Mark Carney'] },
    });
  });
});

describe('notesDeVerification — une ligne par constat, le plus grave d’abord', () => {
  it('le désaccord sur le titulaire passe avant tout', () => {
    const lignes = notesDeVerification(
      {
        notFound: ['2015'],
        sourcesDatedAt: '2024-03-01',
        disagreement: { answer: 'Justin Trudeau', sources: ['Mark Carney'] },
      },
      t,
    );
    expect(lignes).toEqual([
      'chat.verification.desaccord {"sources":"Mark Carney","reponse":"Justin Trudeau"}',
      'chat.verification.sourcesDatees {"date":"1 mars 2024"}',
      'chat.verification.nonRetrouves 2015',
    ]);
  });

  it('ne dit rien sans constat — un niveau seul ne fait pas une ligne', () => {
    expect(notesDeVerification(undefined, t)).toEqual([]);
    expect(notesDeVerification({ notFound: [], level: 'verified' }, t)).toEqual([]);
  });

  it('un message enregistré aux clés françaises du 20/09 ne plante pas', () => {
    const ancien = { nonRetrouves: ['2015'] } as unknown as Parameters<typeof notesDeVerification>[0];
    expect(notesDeVerification(ancien, t)).toEqual(['chat.verification.nonRetrouves 2015']);
    expect(badgeDeVerification(ancien)).toBeNull();
  });

  it('une date illisible est montrée telle quelle plutôt que perdue', () => {
    expect(notesDeVerification({ notFound: [], sourcesDatedAt: 'hier' }, t)).toEqual([
      'chat.verification.sourcesDatees {"date":"hier"}',
    ]);
  });
});

describe('badgeDeVerification — l’état, jamais déclaré par le modèle', () => {
  it('rien sans niveau (question qui ne dépend pas du moment)', () => {
    expect(badgeDeVerification(undefined)).toBeNull();
    expect(badgeDeVerification({ notFound: ['x'] })).toBeNull();
  });

  it('trois niveaux, et la recherche sans résultat dite telle quelle', () => {
    expect(badgeDeVerification({ notFound: [], level: 'verified' })).toEqual({
      cle: 'chat.verification.niveau.verifie',
      ton: 'ok',
    });
    expect(badgeDeVerification({ notFound: [], level: 'partial' })).toEqual({
      cle: 'chat.verification.niveau.partiel',
      ton: 'warn',
    });
    expect(badgeDeVerification({ notFound: [], level: 'memory' })).toEqual({
      cle: 'chat.verification.niveau.memoire',
      ton: 'warn',
    });
    expect(badgeDeVerification({ notFound: [], level: 'memory', searchTried: true })).toEqual({
      cle: 'chat.verification.niveau.memoireSansResultat',
      ton: 'warn',
    });
  });
});

describe('peutVerifierEnLigne — le bouton, seulement quand il peut changer quelque chose', () => {
  it('de mémoire, partiel ou sans niveau : oui ; vérifié : non', () => {
    expect(peutVerifierEnLigne({ notFound: [], level: 'memory' })).toBe(true);
    expect(peutVerifierEnLigne({ notFound: [], level: 'partial', searchTried: true })).toBe(true);
    expect(peutVerifierEnLigne({ notFound: [], level: 'verified', searchTried: true })).toBe(false);
    // Le cas pour lequel le bouton existe : le lexique a raté la question,
    // aucun niveau n'est venu (revue du 21/09).
    expect(peutVerifierEnLigne(undefined)).toBe(true);
    expect(peutVerifierEnLigne({ notFound: ['x'] })).toBe(true);
  });

  it('pas après une recherche qui n’a rien rendu : relancer la même boucle sur Ollama pour rien', () => {
    expect(peutVerifierEnLigne({ notFound: [], level: 'memory', searchTried: true })).toBe(false);
  });
});
