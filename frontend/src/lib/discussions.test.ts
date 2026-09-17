import { describe, expect, it } from 'vitest';

import type { Conversation } from '../types';
import { TITRE_MAX, titreDiscussion, titreProvisoire } from './discussions';

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
