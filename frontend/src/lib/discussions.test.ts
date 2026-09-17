import { describe, expect, it } from 'vitest';

import type { ChatMessage, Conversation } from '../types';
import {
  LONGUEUR_MIN_RECHERCHE,
  RAYON_APRES,
  RAYON_AVANT,
  TITRE_MAX,
  classerDiscussions,
  debutDeMot,
  filtrerDiscussions,
  plierTexte,
  plusRecente,
  rechercherDiscussions,
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

describe('plierTexte', () => {
  it('retire les accents et la casse — au mini-panneau on tape vite, sans accent', () => {
    expect(plierTexte('  La Cité — Permis ')).toBe('la cite — permis');
    expect(plierTexte('Élève')).toBe('eleve');
  });
});

describe('debutDeMot', () => {
  it('trouve la requête au début d’un mot, séparé par espace, tiret ou ponctuation', () => {
    expect(debutDeMot('la cite — permis', 'per')).toBe(true);
    expect(debutDeMot('la cite — permis', 'la')).toBe(true);
    expect(debutDeMot('zero-a-heros', 'her')).toBe(true);
    expect(debutDeMot('bilan (mars)', 'mar')).toBe(true);
  });

  it('ne compte pas une sous-chaîne au milieu d’un mot, même si elle apparaît deux fois', () => {
    expect(debutDeMot('la cite — permis', 'mis')).toBe(false);
    expect(debutDeMot('permis permis', 'mis'), 'deux occurrences, aucune en tête de mot').toBe(
      false,
    );
  });

  it('une requête vide ne commence aucun mot', () => {
    expect(debutDeMot('permis', '')).toBe(false);
  });
});

describe('classerDiscussions', () => {
  const NOW = 100_000;
  const permis = conv('permis', 'La Cité — permis', { updatedAt: 90_000 });
  const anglais = conv('anglais', 'English Mastery', { updatedAt: 95_000 });
  const bilan = conv('bilan', 'Bilan du permis', { updatedAt: 80_000, pinned: true });
  const compromis = conv('compromis', 'Un compromis', { updatedAt: 99_000 });
  const sansTitre = conv('vide', '', { updatedAt: 99_500 });

  it('sans requête, rend l’ordre de la barre latérale : épinglées puis récence, rien d’écarté', () => {
    const ids = classerDiscussions('', [permis, anglais, bilan, compromis, sansTitre], NOW).map(
      (c) => c.id,
    );
    expect(ids).toEqual(['bilan', 'vide', 'compromis', 'anglais', 'permis']);
  });

  it('avec une requête, écarte ce qui ne contient pas la requête — et la vide, qui n’a rien à chercher', () => {
    const ids = classerDiscussions('perm', [permis, anglais, bilan, compromis, sansTitre], NOW).map(
      (c) => c.id,
    );
    expect(ids).not.toContain('anglais');
    expect(ids).not.toContain('vide');
    expect(ids).toHaveLength(2);
  });

  it('classe : épinglées, puis début de mot, puis simple sous-chaîne, puis récence', () => {
    // « compromis » est plus récent que « permis » mais n'a « mis » qu'au
    // milieu d'un mot ; « Bilan du permis » est épinglée et passe devant tout.
    const ids = classerDiscussions('mis', [permis, anglais, bilan, compromis], NOW).map(
      (c) => c.id,
    );
    expect(ids).toEqual(['bilan', 'compromis', 'permis']);
    const ids2 = classerDiscussions('per', [permis, anglais, bilan, compromis], NOW).map(
      (c) => c.id,
    );
    expect(ids2, 'début de mot dans les deux, épinglée d’abord').toEqual(['bilan', 'permis']);
  });

  it('ignore accents et casse dans la requête comme dans le titre', () => {
    expect(classerDiscussions('CITE', [permis, anglais], NOW).map((c) => c.id)).toEqual(['permis']);
    expect(classerDiscussions('cité', [permis, anglais], NOW).map((c) => c.id)).toEqual(['permis']);
  });

  it('un updatedAt dans le futur se lit « à l’instant », pas « en tête pour toujours »', () => {
    // Horloge qui a reculé, ou stamp venu de l'autre vue : sans borne, cette
    // conversation resterait première quoi qu'on fasse ensuite.
    const futur = conv('futur', 'Futur', { updatedAt: NOW + 500_000 });
    const present = conv('present', 'Présent', { updatedAt: NOW });
    const ids = classerDiscussions('', [futur, present], NOW).map((c) => c.id);
    // Les deux valent `now` : l'ordre d'entrée est conservé (tri stable).
    expect(ids).toEqual(['futur', 'present']);
    expect(classerDiscussions('', [present, futur], NOW).map((c) => c.id)).toEqual([
      'present',
      'futur',
    ]);
  });

  it('ne modifie pas la liste reçue', () => {
    const liste = [permis, anglais];
    classerDiscussions('', liste, NOW);
    expect(liste.map((c) => c.id)).toEqual(['permis', 'anglais']);
  });
});

describe('filtrerDiscussions', () => {
  const NOW = 100_000;
  const msg = (id: string, role: ChatMessage['role'], content: string): ChatMessage => ({
    id,
    role,
    content,
    timestamp: 1,
  });
  const permis = conv('permis', 'La Cité — permis', {
    updatedAt: 90_000,
    messages: [
      msg('q1', 'user', 'Quelle est la date limite pour le permis haïtien ?'),
      msg('r1', 'assistant', 'La date limite est le 27 octobre 2026, puis le 6 novembre 2027.'),
    ],
  });
  const anglais = conv('anglais', 'English Mastery', {
    updatedAt: 95_000,
    messages: [msg('q2', 'user', 'Comment dit-on « permis » en anglais ?')],
  });
  const bilan = conv('bilan', 'Bilan du permis', { updatedAt: 80_000, pinned: true });
  const muet = conv('muet', 'Appel d’outil', {
    updatedAt: 99_000,
    messages: [{ id: 'o', role: 'assistant', content: '', timestamp: 1, toolCalls: [] }],
  });

  it('trouve une discussion par un mot qui n’est que dans ses messages — le titre ne dit pas tout', () => {
    // « la discussion où il m'a donné la date du permis » : « date » n'est
    // dans aucun titre, seulement dans les messages.
    const res = filtrerDiscussions([permis, anglais, bilan], 'date', NOW);
    expect(res.map((r) => r.conversation.id)).toEqual(['permis']);
    expect(res[0].messageId, 'le PREMIER message qui contient le terme').toBe('q1');
    expect(res[0].role).toBe('user');
    expect(res[0].occurrences, 'deux messages, une occurrence chacun').toBe(2);
  });

  it('rend l’extrait autour de la première occurrence, le terme écrit comme dans le message', () => {
    const res = filtrerDiscussions([permis], 'DATE', NOW);
    const ex = res[0].extrait!;
    expect(ex.terme, 'accents et casse d’origine, pas ceux de la requête').toBe('date');
    expect(ex.avant).toBe('Quelle est la ');
    expect(ex.apres).toBe(' limite pour le permis haïtien ?');
    expect(ex.avant + ex.terme + ex.apres).toBe(permis.messages[0].content);
  });

  it('borne l’extrait à RAYON_AVANT / RAYON_APRES caractères et marque les coupes d’une ellipse', () => {
    // Asymétrique : la ligne est tronquée à droite, le terme doit rester
    // visible avant la coupe à 320 px.
    expect(RAYON_AVANT).toBeLessThan(RAYON_APRES);
    const long = conv('long', 'Long', {
      messages: [msg('m', 'assistant', 'a'.repeat(100) + ' cible ' + 'b'.repeat(100))],
    });
    const ex = filtrerDiscussions([long], 'cible', NOW)[0].extrait!;
    expect(ex.avant.startsWith('…')).toBe(true);
    expect(ex.apres.endsWith('…')).toBe(true);
    expect(ex.avant.length, 'ellipse + 24').toBe(RAYON_AVANT + 1);
    expect(ex.apres.length, '40 + ellipse').toBe(RAYON_APRES + 1);
  });

  it('place l’extrait au bon endroit malgré des accents AVANT le terme', () => {
    // Plier le texte entier déplace tout ce qui suit un « é » (NFD fait deux
    // unités, l'une retirée) : sans index par caractère, l'extrait tombait
    // un caractère trop tôt par accent précédent.
    const accents = conv('acc', 'Été', {
      messages: [msg('m', 'user', 'Élève éméché à Nîmes : réserver la salle')],
    });
    const ex = filtrerDiscussions([accents], 'reserver', NOW)[0].extrait!;
    expect(ex.terme).toBe('réserver');
    expect(ex.avant).toBe('Élève éméché à Nîmes : ');
    expect(ex.apres).toBe(' la salle');
  });

  it('aplatit les retours à la ligne dans l’extrait — c’est une ligne, pas un paragraphe', () => {
    const md = conv('md', 'Md', { messages: [msg('m', 'assistant', 'Un.\n\nDeux cible\ntrois.')] });
    const ex = filtrerDiscussions([md], 'cible', NOW)[0].extrait!;
    expect(ex.avant).toBe('Un. Deux ');
    expect(ex.apres).toBe(' trois.');
  });

  it('une correspondance de titre seul n’a ni extrait ni message — le titre est déjà affiché', () => {
    const res = filtrerDiscussions([bilan], 'bilan', NOW);
    expect(res).toHaveLength(1);
    expect(res[0].extrait).toBeNull();
    expect(res[0].messageId).toBeNull();
    expect(res[0].role).toBeNull();
    expect(res[0].occurrences).toBe(1);
  });

  it('trie : épinglées, puis nombre d’occurrences, puis récence', () => {
    // « permis » : titre + 2 messages = 3 occurrences ; « anglais » : 1, plus
    // récente ; « bilan » : 1 mais épinglée — devant tout.
    const ids = filtrerDiscussions([permis, anglais, bilan], 'permis', NOW).map(
      (r) => r.conversation.id,
    );
    expect(ids).toEqual(['bilan', 'permis', 'anglais']);
  });

  it('une requête vide ou blanche ne rend rien — le catalogue n’est pas un résultat', () => {
    expect(filtrerDiscussions([permis, anglais], '', NOW)).toEqual([]);
    expect(filtrerDiscussions([permis, anglais], '   ', NOW)).toEqual([]);
  });

  it('un message sans texte (appel d’outil seul) ne correspond pas et ne plante pas', () => {
    expect(filtrerDiscussions([muet], 'outil', NOW).map((r) => r.conversation.id)).toEqual([
      'muet',
    ]);
    expect(filtrerDiscussions([muet], 'zzz', NOW)).toEqual([]);
    const casse = conv('casse', 'Casse', {
      messages: [{ ...msg('m', 'user', ''), content: undefined as unknown as string }],
    });
    expect(filtrerDiscussions([casse], 'zzz', NOW)).toEqual([]);
  });

  it('ignore accents et casse dans la requête comme dans les messages', () => {
    expect(filtrerDiscussions([permis], 'HAITIEN', NOW).map((r) => r.conversation.id)).toEqual([
      'permis',
    ]);
    expect(filtrerDiscussions([permis], 'haïtien', NOW)[0].extrait!.terme).toBe('haïtien');
  });
});

describe('rechercherDiscussions', () => {
  const NOW = 100_000;
  const permis = conv('permis', 'Permis', {
    messages: [{ id: 'm', role: 'user', content: 'la date limite', timestamp: 1 }],
  });

  it('sous LONGUEUR_MIN_RECHERCHE caractères, ne fouille que les titres, sans extrait', () => {
    expect(LONGUEUR_MIN_RECHERCHE).toBe(2);
    const res = rechercherDiscussions([permis], 'd', NOW);
    expect(res, '« d » est dans « date » mais pas dans le titre').toEqual([]);
    const titre = rechercherDiscussions([permis], 'p', NOW);
    expect(titre).toHaveLength(1);
    expect(titre[0].extrait).toBeNull();
  });

  it('dès deux caractères, fouille les messages avec extrait', () => {
    const res = rechercherDiscussions([permis], 'da', NOW);
    expect(res).toHaveLength(1);
    expect(res[0].extrait?.terme).toBe('da');
    expect(res[0].messageId).toBe('m');
  });

  it('sans requête, rend l’ordre du sauteur en entier', () => {
    expect(rechercherDiscussions([permis], '', NOW).map((r) => r.conversation.id)).toEqual([
      'permis',
    ]);
  });
});
