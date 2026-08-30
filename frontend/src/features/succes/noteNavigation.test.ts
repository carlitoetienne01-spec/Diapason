import { describe, expect, it } from 'vitest';

import { construireSommaire, debutsDePage, pageDe } from './noteNavigation';

describe('pageDe', () => {
  const bornes = [1000, 2200, 3400];

  it('place une position avant la première coupure en page 1', () => {
    expect(pageDe(0, bornes)).toBe(1);
    expect(pageDe(999, bornes)).toBe(1);
  });

  it('compte une page de plus par coupure franchie', () => {
    expect(pageDe(1000, bornes)).toBe(2);
    expect(pageDe(2200, bornes)).toBe(3);
    expect(pageDe(5000, bornes)).toBe(4);
  });

  it('rend toujours 1 sur un document d’une seule page', () => {
    expect(pageDe(0, [])).toBe(1);
    expect(pageDe(9999, [])).toBe(1);
  });
});

describe('debutsDePage', () => {
  it('la première page commence à zéro', () => {
    expect(debutsDePage([1000, 2200])).toEqual([0, 1000, 2200]);
  });

  it('un document d’une page n’a qu’un début', () => {
    expect(debutsDePage([])).toEqual([0]);
  });
});

describe('construireSommaire', () => {
  const titres = [
    { balise: 'H1', texte: '1. Verdict honnête', haut: 10 },
    { balise: 'H2', texte: '1.1 Budget d’heures', haut: 500 },
    { balise: 'H2', texte: '1.2 Scénarios', haut: 1500 },
    { balise: 'H1', texte: '2. Définition', haut: 2500 },
  ];

  it('garde le texte, le niveau et la page de chaque titre', () => {
    const s = construireSommaire(titres, [1000, 2200]);
    expect(s).toHaveLength(4);
    expect(s[0]).toMatchObject({ titre: '1. Verdict honnête', niveau: 1, page: 1 });
    expect(s[2]).toMatchObject({ niveau: 2, page: 2 });
    expect(s[3]).toMatchObject({ niveau: 1, page: 3 });
  });

  it('écarte les titres vides', () => {
    // Un collage depuis un traitement de texte en produit — un <h2> qui ne
    // porte qu'une ancre. Une ligne vide dans un sommaire ne mène nulle part.
    const s = construireSommaire(
      [...titres, { balise: 'H2', texte: '   ', haut: 3000 }],
      [1000],
    );
    expect(s).toHaveLength(4);
  });

  it('resserre les niveaux : des H2 et H3 seuls s’indentent sur deux crans', () => {
    // Sans cela, un document sans H1 verrait tout son sommaire décalé à
    // droite sans raison.
    const s = construireSommaire(
      [
        { balise: 'H2', texte: 'A', haut: 0 },
        { balise: 'H3', texte: 'B', haut: 10 },
      ],
      [],
    );
    expect(s.map((e) => e.niveau)).toEqual([1, 2]);
  });

  it('garde l’index d’origine pour retrouver le titre dans le document', () => {
    const s = construireSommaire(
      [
        { balise: 'H1', texte: 'A', haut: 0 },
        { balise: 'H2', texte: '', haut: 5 },
        { balise: 'H2', texte: 'C', haut: 10 },
      ],
      [],
    );
    expect(s.map((e) => e.index)).toEqual([0, 2]);
  });
});
