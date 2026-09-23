import { describe, expect, it } from 'vitest';

import { TOURS_D_AVANT, fusionnerLesSources, historiqueDeRecherche, remplacerLesSources } from './historiqueDeRecherche';

describe('historiqueDeRecherche', () => {
  it("écarte la demande courante et garde les tours d'avant", () => {
    const messages = [
      { role: 'user', content: 'Fais-moi une recherche de sites de jeux de programmation' },
      { role: 'assistant', content: 'CodinGame, Codewars…' },
      { role: 'user', content: 'Donne-moi les liens de ces sites' },
    ];
    expect(historiqueDeRecherche(messages)).toEqual(messages.slice(0, 2));
  });

  it('écarte les messages vides et ceux qui ne sont ni user ni assistant', () => {
    const messages = [
      { role: 'system', content: 'x' },
      { role: 'user', content: 'a' },
      { role: 'assistant', content: '' },
      { role: 'user', content: 'b' },
    ];
    expect(historiqueDeRecherche(messages)).toEqual([{ role: 'user', content: 'a' }]);
  });

  it('garde les six derniers tours seulement', () => {
    const messages = Array.from({ length: 12 }, (_, i) => ({
      role: i % 2 ? 'assistant' : 'user',
      content: `m${i}`,
    }));
    const h = historiqueDeRecherche(messages);
    expect(h).toHaveLength(TOURS_D_AVANT);
    expect(h[0].content).toBe('m5');
    expect(h[h.length - 1].content).toBe('m10');
  });

  it('rend vide sans tour d\'avant', () => {
    expect(historiqueDeRecherche([{ role: 'user', content: 'seul' }])).toEqual([]);
  });
});

describe('remplacerLesSources', () => {
  it('la liste renumérotée du serveur remplace les numéros d\'origine', () => {
    const parRef = new Map<number, { ref: number; url: string }>();
    parRef.set(1, { ref: 1, url: 'https://mail.google.com/#inbox/aaa' });
    parRef.set(2, { ref: 2, url: 'https://mail.google.com/#inbox/bbb' });
    parRef.set(3, { ref: 3, url: 'https://www.codingame.com/' });
    parRef.set(4, { ref: 4, url: 'https://www.codewars.com/' });
    remplacerLesSources(parRef, [
      { ref: 1, url: 'https://www.codingame.com/' },
      { ref: 2, url: 'https://www.codewars.com/' },
    ]);
    expect([...parRef.values()].map((s) => s.url)).toEqual([
      'https://www.codingame.com/',
      'https://www.codewars.com/',
    ]);
    expect(parRef.get(1)?.url).toBe('https://www.codingame.com/');
  });

  it('sans liste finale, rien ne change', () => {
    const parRef = new Map<number, { ref: number }>([[1, { ref: 1 }]]);
    remplacerLesSources(parRef, undefined);
    expect(parRef.size).toBe(1);
  });

  it('une liste vide vide la carte : le texte ne cite rien', () => {
    const parRef = new Map<number, { ref: number }>([[1, { ref: 1 }]]);
    remplacerLesSources(parRef, []);
    expect(parRef.size).toBe(0);
  });
});

describe('fusionnerLesSources', () => {
  // 22/09/2026 : les deux sites qui recevaient un lot écartaient toute
  // pastille DÉJÀ connue. Sans effet tant qu'aucun émetteur ne réémettait un
  // numéro — puis le serveur a voulu dire « cette source est officielle, lue
  // aujourd'hui » sur une page que la recherche avait déjà rendue, et la
  // mise à jour se perdait en silence.
  type Source = { ref: number; title?: string; url?: string; snippet?: string; official?: boolean; date?: string };

  it('ajoute ce qui est nouveau', () => {
    const parRef = new Map<number, Source>();
    fusionnerLesSources(parRef, [{ ref: 1, title: 'Banque du Canada' }]);
    expect(parRef.get(1)).toEqual({ ref: 1, title: 'Banque du Canada' });
  });

  it('met à jour une pastille déjà connue au lieu de l’ignorer', () => {
    const parRef = new Map<number, Source>([[1, { ref: 1, title: 'Taux directeur', date: '2025-03-12' }]]);
    fusionnerLesSources(parRef, [{ ref: 1, official: true, date: '2026-09-22' }]);
    expect(parRef.get(1)?.official).toBe(true);
    expect(parRef.get(1)?.date).toBe('2026-09-22');
  });

  it('FUSIONNE : une carte partielle n’efface pas ce qu’on avait déjà', () => {
    // Une carte officielle ne porte que six champs, une source de recherche
    // en porte davantage.
    const parRef = new Map<number, Source>([[1, { ref: 1, title: 'x', snippet: 'à garder' }]]);
    fusionnerLesSources(parRef, [{ ref: 1, official: true }]);
    expect(parRef.get(1)?.snippet).toBe('à garder');
  });

  it('ignore ce qui n’a pas la forme attendue, sans faire tomber la réception', () => {
    const parRef = new Map<number, Source>();
    fusionnerLesSources(parRef, [null, 'texte', { pas: 'de ref' }, { ref: '2' }, { ref: 3 }]);
    expect([...parRef.keys()]).toEqual([3]);
  });

  it('ne casse pas sur un lot qui n’est pas un tableau', () => {
    const parRef = new Map<number, Source>([[1, { ref: 1 }]]);
    fusionnerLesSources(parRef, null);
    fusionnerLesSources(parRef, { ref: 9 });
    expect([...parRef.keys()]).toEqual([1]);
  });
});
