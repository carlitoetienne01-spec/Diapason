import { describe, expect, it } from 'vitest';

import { TOURS_D_AVANT, historiqueDeRecherche, remplacerLesSources } from './historiqueDeRecherche';

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
