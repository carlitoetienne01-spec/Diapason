// La règle de fusion vit deux fois — conversations_store.py côté serveur,
// convSync.ts ici. L'instantané tests/contract/fusion_conversations.json est
// calculé par le Python (scripts/gen_fusion_fixture.py) ; ce test vérifie
// que le TypeScript rend exactement la même chose, cas par cas. Si les deux
// divergeaient d'un cheveu, chaque vue « convergerait » vers son propre
// résultat en se croyant synchronisée (§100).

import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import type { Conversation } from '../types';
import { fusionnerConversations } from './convSync';

interface Cas {
  nom: string;
  a: Conversation;
  b: Conversation;
  fusion: Conversation;
}

const ici = dirname(fileURLToPath(import.meta.url));
const instantane = resolve(ici, '../../../tests/contract/fusion_conversations.json');
const { cas } = JSON.parse(readFileSync(instantane, 'utf-8')) as { cas: Cas[] };

describe('l’instantané de la fusion, partagé avec le serveur', () => {
  it('n’est pas vide', () => {
    expect(cas.length).toBeGreaterThan(0);
  });

  for (const c of cas) {
    it(`rend la même fusion que le Python : ${c.nom}`, () => {
      expect(
        fusionnerConversations(c.a, c.b),
        'la règle TypeScript diverge du serveur — régénérer ou corriger',
      ).toEqual(c.fusion);
      expect(fusionnerConversations(c.b, c.a), 'commutative').toEqual(c.fusion);
    });
  }
});
