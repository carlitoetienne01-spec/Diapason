import { describe, expect, it } from 'vitest';

import type { ChatMessage, Conversation, ConversationStore } from '../types';
import {
  avecSuppressions,
  choisirAPousser,
  estRefusPermanent,
  etatSyncInitial,
  fusionner,
  fusionnerConversations,
  fusionnerMessages,
  normaliserImport,
  sansSuppression,
} from './convSync';

function msg(
  id: string,
  role: 'user' | 'assistant',
  content: string,
  timestamp: number,
  extra: Partial<ChatMessage> = {},
): ChatMessage {
  return { id, role, content, timestamp, ...extra };
}

function conv(
  id: string,
  updatedAt: number,
  title = id,
  messages: ChatMessage[] = [],
  extra: Partial<Conversation> = {},
): Conversation {
  return {
    id,
    title,
    createdAt: 1000,
    updatedAt,
    model: 'default',
    messages,
    ...extra,
  };
}

function magasin(
  conversations: Conversation[],
  activeId: string | null = null,
): ConversationStore {
  return {
    version: 1,
    conversations: Object.fromEntries(conversations.map((c) => [c.id, c])),
    activeId,
  };
}

describe('la fusion de deux copies — la même règle que le serveur, à la lettre', () => {
  it('garde les messages des deux copies, dans l’ordre du temps', () => {
    const base = [msg('q1', 'user', 'Bonjour', 100), msg('r1', 'assistant', 'Salut', 101)];
    const deA = conv('x', 2001, 'Titre de A', [
      ...base,
      msg('q2', 'user', 'A ?', 2000),
      msg('r2', 'assistant', 'Ra', 2001),
    ]);
    const deB = conv('x', 3001, 'Titre de B', [
      ...base,
      msg('q3', 'user', 'B ?', 3000),
      msg('r3', 'assistant', 'Rb', 3001),
    ]);

    const fusion = fusionnerConversations(deA, deB);
    expect(
      fusion.messages.map((m) => m.id),
      'aucune paire ne doit être perdue, quel que soit l’ordre des poussées',
    ).toEqual(['q1', 'r1', 'q2', 'r2', 'q3', 'r3']);
    expect(fusion.title, 'les métadonnées viennent de l’écriture la plus récente').toBe(
      'Titre de B',
    );
    expect(fusion.updatedAt).toBe(3001);
  });

  it('est commutative et idempotente', () => {
    const a = conv('x', 10, 'A', [msg('1', 'user', 'a', 1), msg('2', 'assistant', 'ra', 2)]);
    const b = conv('x', 20, 'B', [msg('1', 'user', 'a', 1), msg('3', 'user', 'b', 3)]);
    const ab = fusionnerConversations(a, b);
    expect(fusionnerConversations(b, a), 'commutative').toEqual(ab);
    expect(fusionnerConversations(ab, a), 'idempotente').toEqual(ab);
    expect(fusionnerConversations(ab, b), 'dans les deux sens').toEqual(ab);
  });

  it('ne laisse jamais une copie partielle tronquer la réponse complète', () => {
    const complete = conv('x', 5000, 'x', [
      msg('q', 'user', '?', 1),
      msg('r', 'assistant', 'Bonjour !', 2, {
        usage: { prompt_tokens: 1, completion_tokens: 3, total_tokens: 4 },
      }),
    ]);
    const partielle = conv('x', 6000, 'x', [msg('q', 'user', '?', 1), msg('r', 'assistant', 'Bonj', 2)], {
      pinned: true,
    });
    const fusion = fusionnerConversations(complete, partielle);
    expect(fusion.messages[1].content, 'la plus complète gagne au grain du message').toBe(
      'Bonjour !',
    );
    expect(fusion.messages[1].usage?.total_tokens, 'les champs de la copie complète survivent').toBe(4);
    expect(fusion.pinned, 'l’épingle vient de l’écriture récente').toBe(true);
  });

  it('départage deux copies écrites à la même milliseconde de la même façon des deux côtés', () => {
    const a = conv('x', 1000, 'Alpha', [msg('1', 'user', 'x', 1)]);
    const b = conv('x', 1000, 'Beta', [msg('1', 'user', 'x', 1)]);
    expect(fusionnerConversations(a, b).title).toBe('Beta');
    expect(fusionnerConversations(b, a).title, 'le même vainqueur quel que soit l’ordre').toBe(
      'Beta',
    );
  });

  it('ne duplique pas les messages d’avant l’identifiant', () => {
    const ancien = [{ role: 'user', content: 'salut', timestamp: 5 } as ChatMessage];
    expect(fusionnerMessages(ancien, [...ancien])).toEqual(ancien);
  });

  it('rend exactement les objets locaux quand rien ne change', () => {
    const local = conv('x', 10, 'x', [msg('1', 'user', 'a', 1)], { pinned: false });
    const fusion = fusionnerConversations(local, { ...local, messages: [...local.messages] });
    expect(JSON.stringify(fusion), 'une fusion sans effet doit être détectable').toBe(
      JSON.stringify(local),
    );
  });
});

describe('la fusion du magasin local avec le serveur', () => {
  it('fusionne une distante plus récente et la signale changée', () => {
    const local = magasin([conv('a', 1000, 'vieille')]);
    const { store, changees } = fusionner(local, [conv('a', 2000, 'neuve')], []);
    expect(store.conversations['a'].title).toBe('neuve');
    expect(changees).toEqual(['a']);
  });

  it('ne signale rien quand la distante n’apporte rien', () => {
    const mienne = conv('a', 2000, 'neuve', [msg('1', 'user', 'a', 1)], { pinned: false });
    const local = magasin([mienne]);
    const { changees } = fusionner(local, [{ ...mienne, messages: [...mienne.messages] }], []);
    expect(changees, 're-fusionner les mêmes données ne doit rien changer').toEqual([]);
  });

  it('ajoute une conversation inconnue', () => {
    const { store, changees } = fusionner(magasin([]), [conv('b', 5)], []);
    expect(Object.keys(store.conversations)).toEqual(['b']);
    expect(changees).toEqual(['b']);
  });

  it('supprime la locale quand la tombale est au moins aussi récente', () => {
    const local = magasin([conv('a', 1000)], 'a');
    const { store, changees, activeSupprimee } = fusionner(local, [], [{ id: 'a', deletedAt: 1000 }]);
    expect(store.conversations['a']).toBeUndefined();
    expect(changees).toEqual(['a']);
    expect(store.activeId, 'l’active supprimée doit être annulée').toBeNull();
    expect(activeSupprimee).toBe(true);
  });

  it('laisse ressusciter une locale écrite après la tombale', () => {
    const local = magasin([conv('a', 2000)]);
    const { store, changees } = fusionner(local, [], [{ id: 'a', deletedAt: 1999 }]);
    expect(store.conversations['a'], 'écrite après la suppression : un nouveau choix').toBeDefined();
    expect(changees).toEqual([]);
  });

  it('ignore une tombale d’une conversation inconnue', () => {
    const { store, changees } = fusionner(magasin([]), [], [{ id: 'z', deletedAt: 1 }]);
    expect(store.conversations).toEqual({});
    expect(changees).toEqual([]);
  });
});

describe('ce qui se pousse', () => {
  it('pousse l’inconnu de la carte et ce qui dépasse la version connue', () => {
    const local = magasin([conv('a', 1000), conv('b', 2000), conv('c', 3000)]);
    const carte = { a: 1000, b: 1500 };
    expect(choisirAPousser(local, carte).map((c) => c.id)).toEqual(['b', 'c']);
  });

  it('ne pousse jamais une condamnée ni une mise en quarantaine', () => {
    const local = magasin([conv('a', 1000), conv('b', 2000), conv('c', 3000)]);
    expect(choisirAPousser(local, {}, ['a'], new Set(['c'])).map((c) => c.id)).toEqual(['b']);
  });

  it('une fois datée, une conversation renommée dépasse la carte', () => {
    // Le renommage et l’épingle ne dataient pas leur écriture : à updatedAt
    // égal à la carte, rien ne partait jamais (revue du 16 sept. 2026).
    const local = magasin([conv('a', 1001, 'renommée')]);
    expect(choisirAPousser(local, { a: 1000 }).map((c) => c.id)).toEqual(['a']);
  });
});

describe('la file de suppressions', () => {
  it('ajoute sans doublon et oublie la version connue', () => {
    const etat = avecSuppressions(
      { ...etatSyncInitial(), carte: { a: 1, b: 2 } },
      ['a', 'a', 'z'],
    );
    expect(etat.suppressions).toEqual(['a', 'z']);
    expect(etat.carte).toEqual({ b: 2 });
  });

  it('retire un id quand le DELETE a abouti', () => {
    const etat = sansSuppression({ ...etatSyncInitial(), suppressions: ['a', 'b'] }, 'a');
    expect(etat.suppressions).toEqual(['b']);
  });
});

describe('les refus du serveur', () => {
  it('tient un 4xx pour permanent, sauf la clé absente et le limiteur', () => {
    expect(estRefusPermanent(422)).toBe(true);
    expect(estRefusPermanent(404)).toBe(true);
    expect(estRefusPermanent(400)).toBe(true);
    expect(estRefusPermanent(401), 'la clé arrive peut-être au tick suivant').toBe(false);
    expect(estRefusPermanent(429)).toBe(false);
    expect(estRefusPermanent(500), 'un 5xx se rejoue').toBe(false);
  });
});

describe('l’import d’une sauvegarde', () => {
  it('refuse ce qui n’a pas la forme d’un magasin', () => {
    expect(normaliserImport(null)).toBeNull();
    expect(normaliserImport({ version: 2, conversations: {} })).toBeNull();
    expect(normaliserImport({ version: 1 }), 'sans conversations, rien à importer').toBeNull();
  });

  it('écarte les conversations invalides et garde les autres', () => {
    const propre = normaliserImport({
      version: 1,
      activeId: 'absente',
      conversations: {
        bonne: {
          id: 'bonne',
          title: 'ok',
          createdAt: 1,
          updatedAt: 2,
          model: 'm',
          pinned: null,
          messages: [{ role: 'user', content: 'x' }, { role: 'robot', content: 'y' }, 'bruit'],
        },
        sansDate: { id: 'sansDate', title: 'x', updatedAt: '1000', messages: [] },
      },
    });
    expect(propre).not.toBeNull();
    expect(Object.keys(propre!.conversations)).toEqual(['bonne']);
    expect(propre!.conversations['bonne'].pinned, 'pinned: null devient false').toBe(false);
    expect(propre!.conversations['bonne'].messages).toHaveLength(1);
    expect(propre!.conversations['bonne'].messages[0].id, 'un message reçoit un id').toBeTruthy();
    expect(propre!.activeId, 'un activeId qui ne pointe sur rien est annulé').toBeNull();
  });
});
