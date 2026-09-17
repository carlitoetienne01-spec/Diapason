import { describe, expect, it } from 'vitest';

import type { ChatMessage, Conversation } from '../types';
import {
  FENETRE_CHAUDE_MS,
  LONGUEUR_MIN_RECHERCHE,
  RAYON_APRES,
  RAYON_AVANT,
  TITRE_MAX,
  choisirAtterrissage,
  classerDiscussions,
  debutDeMot,
  discussionVoisine,
  doitAfficherLeFil,
  filtrerDiscussions,
  plierTexte,
  plusRecente,
  nombreDeRecentesQuiTiennent,
  recentesPourAccueil,
  rechercherDiscussions,
  tientLeFil,
  titreARenommer,
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

describe('choisirAtterrissage', () => {
  const NOW = 10_000_000;
  const MIN = 60_000;
  const avec = (id: string, title: string, ilYA: number, extra: Partial<Conversation> = {}) =>
    conv(id, title, {
      updatedAt: NOW - ilYA,
      messages: [{ id: `${id}-m`, role: 'user', content: 'salut', timestamp: 1 }],
      ...extra,
    });

  it('la fenêtre chaude vaut 20 minutes — une pause entre deux relances, pas un changement de sujet', () => {
    expect(FENETRE_CHAUDE_MS).toBe(20 * MIN);
  });

  it('reprend le fil modifié il y a moins de 20 min, même si l’active locale est un autre', () => {
    // La longue discussion commencée dans la fenêtre dix minutes plus tôt ;
    // le mini était resté sur le fil d'avant-hier.
    const fenetre = avec('fenetre', 'Dans la fenêtre', 10 * MIN);
    const vieux = avec('vieux', 'Avant-hier', 48 * 60 * MIN);
    expect(choisirAtterrissage([vieux, fenetre], 'vieux', NOW)).toEqual({
      type: 'reprendre',
      id: 'fenetre',
    });
  });

  it('reste quand le fil chaud est déjà l’active locale', () => {
    const ici = avec('ici', 'Ici', 3 * MIN);
    expect(choisirAtterrissage([ici], 'ici', NOW)).toEqual({ type: 'rester' });
  });

  it('atterrit sur une vierge quand tout a plus de 20 min — la question rapide ne se colle pas au fil d’avant-hier', () => {
    const vieux = avec('vieux', 'Avant-hier', 48 * 60 * MIN);
    expect(choisirAtterrissage([vieux], 'vieux', NOW)).toEqual({ type: 'vierge' });
    const limite = avec('limite', 'Pile 20 min', 20 * MIN);
    expect(choisirAtterrissage([limite], null, NOW), 'à 20 min exactement, c’est froid').toEqual({
      type: 'vierge',
    });
    const juste = avec('juste', 'Juste avant', 20 * MIN - 1);
    expect(choisirAtterrissage([juste], null, NOW)).toEqual({ type: 'reprendre', id: 'juste' });
  });

  it('reste sur l’active locale quand elle est déjà vierge — rien de visible', () => {
    const vierge = conv('v', '', { updatedAt: NOW - MIN });
    const vieux = avec('vieux', 'Vieux', 48 * 60 * MIN);
    expect(choisirAtterrissage([vieux, vierge], 'v', NOW)).toEqual({ type: 'rester' });
  });

  it('une vierge récente n’est pas « chaude » : sans message, rien à reprendre', () => {
    // Créée dans l'autre vue à l'instant : ce n'est pas un sujet en cours.
    const vierge = conv('v', '', { updatedAt: NOW - MIN });
    expect(choisirAtterrissage([vierge], null, NOW)).toEqual({ type: 'vierge' });
  });

  it('entre deux chaudes, prend la plus récente ; à égalité, l’active locale', () => {
    const a = avec('a', 'A', 5 * MIN);
    const b = avec('b', 'B', 2 * MIN);
    expect(choisirAtterrissage([a, b], 'a', NOW)).toEqual({ type: 'reprendre', id: 'b' });
    const c = avec('c', 'C', 2 * MIN);
    expect(choisirAtterrissage([b, c], 'c', NOW), 'égalité : on ne change pas de fil sans raison').toEqual({
      type: 'rester',
    });
    expect(choisirAtterrissage([c, b], 'b', NOW)).toEqual({ type: 'rester' });
  });

  it('un updatedAt dans le futur se lit « à l’instant » : chaud, mais pas éternel', () => {
    const futur = avec('futur', 'Futur', -30 * MIN);
    expect(choisirAtterrissage([futur], null, NOW)).toEqual({ type: 'reprendre', id: 'futur' });
    expect(
      choisirAtterrissage([futur], null, NOW + 51 * MIN),
      '21 min après le stamp, froid — il n’est pas « chaud » tant qu’il est dans le futur',
    ).toEqual({ type: 'vierge' });
  });

  it('respecte une fenêtre passée en paramètre', () => {
    const c = avec('c', 'C', 2 * MIN);
    expect(choisirAtterrissage([c], null, NOW, MIN)).toEqual({ type: 'vierge' });
  });

  it('sans aucune conversation, une vierge', () => {
    expect(choisirAtterrissage([], null, NOW)).toEqual({ type: 'vierge' });
  });

  it('un fil choisi exprès n’est pas « chaud » : la règle seule l’abandonnerait — d’où la garde de l’appelant', () => {
    // Contre-revue du 17 sept. 2026 : selectConversation ne date pas
    // `updatedAt`, donc « Zéro à Héro » ouvert par ⌘J il y a une seconde
    // pèse un jour, et « La Cité » (6 min) gagne. La règle est juste pour une
    // VRAIE ouverture ; c'est à l'appelant de ne la rejouer qu'alors, et
    // jamais quand on tient le fil (tientLeFil).
    const laCite = avec('lacite', 'La Cité', 6 * MIN);
    const zero = avec('zero', 'Zéro à Héro', 24 * 60 * MIN);
    expect(choisirAtterrissage([laCite, zero], 'zero', NOW)).toEqual({
      type: 'reprendre',
      id: 'lacite',
    });
  });
});

describe('tientLeFil', () => {
  it('un brouillon tient le fil — il partirait dans le mauvais fil (§100)', () => {
    expect(tientLeFil({ enFlux: false, brouillon: 'et la suite du plan ?' })).toBe(true);
  });

  it('une réponse en cours tient le fil', () => {
    expect(tientLeFil({ enFlux: true, brouillon: '' })).toBe(true);
  });

  it('rien ne tient le fil quand le compositeur est vide ou blanc', () => {
    // Une espace oubliée n'est pas un brouillon : elle bloquerait
    // l'atterrissage sans que rien ne soit visible dans le champ.
    expect(tientLeFil({ enFlux: false, brouillon: '' })).toBe(false);
    expect(tientLeFil({ enFlux: false, brouillon: '   \n' })).toBe(false);
  });
});

describe('doitAfficherLeFil', () => {
  it('seul le fil actif est affiché ; le fil en flux écrit sans s’afficher', () => {
    // ⌘N pendant une réponse : les jetons du fil A s'affichaient sous le
    // titre « Nouvelle discussion », bulle vivante comprise.
    expect(doitAfficherLeFil('a', 'a')).toBe(true);
    expect(doitAfficherLeFil('a', 'b')).toBe(false);
    expect(doitAfficherLeFil('a', null)).toBe(false);
  });
});

describe('titreARenommer', () => {
  it('commet un titre nouveau, sans ses blancs', () => {
    expect(titreARenommer('  Permis haïtien ', 'Ancien')).toBe('Permis haïtien');
  });

  it('ne commet ni un champ vidé ni un titre inchangé', () => {
    // Inchangé : une écriture datée pour rien serait poussée vers l'autre
    // vue (convSync). Vide : le titre ne se perd pas sur un champ effacé.
    expect(titreARenommer('', 'Ancien')).toBeNull();
    expect(titreARenommer('   ', 'Ancien')).toBeNull();
    expect(titreARenommer('Ancien', 'Ancien')).toBeNull();
    expect(titreARenommer(' Ancien ', 'Ancien')).toBeNull();
  });
});

describe('recentesPourAccueil', () => {
  const NOW = 10_000_000;
  const avec = (id: string, ilYA: number, extra: Partial<Conversation> = {}) =>
    conv(id, id, {
      updatedAt: NOW - ilYA,
      messages: [{ id: `${id}-m`, role: 'user', content: 'x', timestamp: 1 }],
      ...extra,
    });

  it('propose le dernier fil à reprendre, puis les trois suivants par récence', () => {
    const liste = [avec('c', 3), avec('a', 1), avec('e', 5), avec('b', 2), avec('d', 4)];
    const accueil = recentesPourAccueil(liste, null, NOW);
    expect(accueil.reprendre?.id).toBe('a');
    expect(accueil.autres.map((c) => c.id)).toEqual(['b', 'c', 'd']);
  });

  it('exclut l’active (on y est) et les vierges (rien à reprendre)', () => {
    const active = avec('active', 0);
    const vierge = conv('v', '', { updatedAt: NOW });
    const autre = avec('autre', 10);
    const accueil = recentesPourAccueil([active, vierge, autre], 'active', NOW);
    expect(accueil.reprendre?.id).toBe('autre');
    expect(accueil.autres).toEqual([]);
  });

  it('les épinglées ne passent pas devant : « reprendre » parle du dernier fil, pas du préféré', () => {
    const epinglee = avec('ep', 100, { pinned: true });
    const recente = avec('rec', 1);
    expect(recentesPourAccueil([epinglee, recente], null, NOW).reprendre?.id).toBe('rec');
  });

  it('rend null sans rien à reprendre', () => {
    expect(recentesPourAccueil([], null, NOW)).toEqual({ reprendre: null, autres: [] });
  });
});

describe('nombreDeRecentesQuiTiennent', () => {
  it('à la taille minimale du mini (fil de 122 px), aucune récente : seul « Reprendre » tient', () => {
    /* §5 : l'invitation que le ↩ à vide promet doit être visible sans
       défiler ; une liste qui déborde la repoussait hors champ. */
    expect(nombreDeRecentesQuiTiennent(122)).toBe(0);
  });

  it('une récente avec son libellé dès qu’ils tiennent, trois au préréglage S', () => {
    expect(nombreDeRecentesQuiTiennent(123)).toBe(0);
    expect(nombreDeRecentesQuiTiennent(124)).toBe(1);
    expect(nombreDeRecentesQuiTiennent(200)).toBe(2);
    expect(nombreDeRecentesQuiTiennent(262)).toBe(3);
  });

  it('ne dépasse jamais le plafond, même avec une grande fenêtre', () => {
    expect(nombreDeRecentesQuiTiennent(2000)).toBe(3);
    expect(nombreDeRecentesQuiTiennent(2000, 5)).toBe(5);
  });

  it('un fil sans hauteur (pas encore mesuré, ou nul) ne rend rien de négatif', () => {
    expect(nombreDeRecentesQuiTiennent(0)).toBe(0);
    expect(nombreDeRecentesQuiTiennent(-10)).toBe(0);
  });
});

describe('discussionVoisine', () => {
  const NOW = 100_000;
  const epinglee = conv('ep', 'Épinglée', { updatedAt: 10_000, pinned: true });
  const recente = conv('rec', 'Récente', { updatedAt: 90_000 });
  const moyenne = conv('moy', 'Moyenne', { updatedAt: 50_000 });
  const vieille = conv('vie', 'Vieille', { updatedAt: 20_000 });
  // Ordre du sauteur : ep, rec, moy, vie — l'ordre d'ENTRÉE est brouillé.
  const liste = [moyenne, vieille, recente, epinglee];

  it('suit l’ordre du sauteur : épinglées d’abord, puis récence, quel que soit l’ordre d’entrée', () => {
    expect(discussionVoisine(liste, 'rec', 'precedente', NOW)?.id).toBe('ep');
    expect(discussionVoisine(liste, 'rec', 'suivante', NOW)?.id).toBe('moy');
    expect(discussionVoisine(liste, 'moy', 'suivante', NOW)?.id).toBe('vie');
  });

  it('aux extrémités, rend null — pas de bouclage', () => {
    expect(discussionVoisine(liste, 'ep', 'precedente', NOW)).toBeNull();
    expect(discussionVoisine(liste, 'vie', 'suivante', NOW)).toBeNull();
  });

  it('sans active, ou active supprimée dans l’autre vue, entre par le haut', () => {
    expect(discussionVoisine(liste, null, 'suivante', NOW)?.id).toBe('ep');
    expect(discussionVoisine(liste, null, 'precedente', NOW)?.id).toBe('ep');
    expect(discussionVoisine(liste, 'zz', 'suivante', NOW)?.id).toBe('ep');
  });

  it('liste vide : null dans les deux sens', () => {
    expect(discussionVoisine([], null, 'suivante', NOW)).toBeNull();
    expect(discussionVoisine([], 'x', 'precedente', NOW)).toBeNull();
  });

  it('ne modifie pas la liste reçue', () => {
    const copie = [...liste];
    discussionVoisine(liste, 'rec', 'suivante', NOW);
    expect(liste).toEqual(copie);
  });
});
