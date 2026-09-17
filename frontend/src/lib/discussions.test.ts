import { describe, expect, it } from 'vitest';

import type { Conversation } from '../types';
import {
  TITRE_MAX,
  plusRecente,
  titreDiscussion,
  titreProvisoire,
  trouverDiscussionVierge,
} from './discussions';

function conv(id: string, title: string, extra: Partial<Conversation> = {}): Conversation {
  return {
    id,
    title,
    createdAt: 1000,
    updatedAt: 1000,
    model: 'm',
    messages: [],
    ...extra,
  };
}

const t = (key: 'sidebar.newChat') => (key === 'sidebar.newChat' ? 'Nouvelle discussion' : key);

describe('titreDiscussion', () => {
  it('sans discussion active, l’en-tête dit « Nouvelle discussion »', () => {
    // Un mini-panneau neuf n'a aucune conversation : l'en-tête ne doit pas
    // rester vide, ni inventer un nom.
    expect(titreDiscussion([], null, t)).toBe('Nouvelle discussion');
    expect(titreDiscussion([conv('a', 'Permis')], null, t)).toBe('Nouvelle discussion');
  });

  it('un titre vide (pas encore nommée par son premier message) donne le même repli', () => {
    expect(titreDiscussion([conv('a', '')], 'a', t)).toBe('Nouvelle discussion');
    expect(titreDiscussion([conv('a', '   ')], 'a', t), 'les blancs ne sont pas un titre').toBe(
      'Nouvelle discussion',
    );
  });

  it('rend le titre de la conversation active, pas celui de la première', () => {
    const liste = [conv('a', 'La Cité — permis'), conv('b', 'English Mastery')];
    expect(titreDiscussion(liste, 'b', t)).toBe('English Mastery');
  });

  it('un id inconnu (conversation supprimée dans l’autre vue) retombe sur le repli', () => {
    expect(titreDiscussion([conv('a', 'Permis')], 'zz', t)).toBe('Nouvelle discussion');
  });

  it('tronque un titre long à TITRE_MAX avec une ellipse — document.title ne doit pas tout avaler', () => {
    const long = 'x'.repeat(TITRE_MAX + 40);
    const titre = titreDiscussion([conv('a', long)], 'a', t);
    expect(titre.length).toBe(TITRE_MAX);
    expect(titre.endsWith('…')).toBe(true);
    const juste = 'y'.repeat(TITRE_MAX);
    expect(titreDiscussion([conv('a', juste)], 'a', t), 'à la limite exacte, rien n’est coupé').toBe(
      juste,
    );
  });
});

describe('titreProvisoire', () => {
  it('est vrai sans active, sur un titre vide, faux sur un titre réel', () => {
    expect(titreProvisoire([], null)).toBe(true);
    expect(titreProvisoire([conv('a', '')], 'a')).toBe(true);
    expect(titreProvisoire([conv('a', 'Permis')], 'a')).toBe(false);
  });
});

describe('trouverDiscussionVierge', () => {
  it('réutilise une conversation vide, sans titre, non épinglée', () => {
    const vierge = conv('v', '');
    expect(trouverDiscussionVierge([conv('a', 'Permis'), vierge])).toBe(vierge);
  });

  it('prend la vierge la plus récente quand il y en a plusieurs', () => {
    const vieille = conv('v1', '', { updatedAt: 10 });
    const recente = conv('v2', '', { updatedAt: 20 });
    expect(trouverDiscussionVierge([vieille, recente])).toBe(recente);
  });

  it('ne recycle ni une vide renommée ni une vide épinglée — c’est du travail préparé', () => {
    const renommee = conv('r', 'Idées pour le bilan');
    const epinglee = conv('e', '', { pinned: true });
    expect(trouverDiscussionVierge([renommee, epinglee])).toBeNull();
  });

  it('ne recycle pas une conversation qui a des messages, même sans titre', () => {
    const avecMessage = conv('m', '', {
      messages: [{ id: 'x', role: 'user', content: 'salut', timestamp: 1 }],
    });
    expect(trouverDiscussionVierge([avecMessage])).toBeNull();
  });

  it('rend null sans aucune conversation', () => {
    expect(trouverDiscussionVierge([])).toBeNull();
  });
});

describe('plusRecente', () => {
  it('rend la conversation au updatedAt le plus grand, pas la première de la liste', () => {
    // deleteConversation prenait Object.keys[0] : l'ordre d'insertion du
    // JSON, c'est-à-dire un fil arbitraire après une suppression.
    const ancienne = conv('a', 'A', { updatedAt: 5 });
    const recente = conv('b', 'B', { updatedAt: 50 });
    const moyenne = conv('c', 'C', { updatedAt: 20 });
    expect(plusRecente([ancienne, recente, moyenne])).toBe(recente);
  });

  it('rend null quand il ne reste rien', () => {
    expect(plusRecente([])).toBeNull();
  });
});
