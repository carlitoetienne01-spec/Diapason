/**
 * Les discussions vues depuis le fil — logique pure, sans React.
 *
 * 17 sept. 2026, chantier « discussions dans le mini-panneau ». Le fil se
 * lisait sans jamais dire dans QUELLE discussion on écrivait : la barre
 * latérale seule le savait, et le mini-panneau n'en a pas. Ce module porte
 * les règles que l'en-tête du fil, le store et le moteur de sync partagent,
 * pour qu'elles soient testées une fois et appliquées partout (CLAUDE.md §3 :
 * pas de test de composant — la logique s'extrait).
 */
import type { Conversation } from '../types';

/** Ce que ce module demande au catalogue : rien de plus que ces clés. */
export type TraduireTitre = (key: 'sidebar.newChat') => string;

// Au-delà, ni la pastille réduite du mini-panneau (≈ 200 px de texte) ni un
// onglet n'affichent quoi que ce soit ; un titre collé de 2 000 caractères
// finissait dans `document.title` en entier.
export const TITRE_MAX = 80;

/**
 * Le titre à afficher pour la discussion active : celui de la conversation,
 * sinon « Nouvelle discussion » — quand rien n'est actif OU quand la
 * conversation active n'a pas encore de nom (elle en reçoit un au premier
 * message). Toujours tronqué à TITRE_MAX.
 */
export function titreDiscussion(
  conversations: readonly Conversation[],
  activeId: string | null,
  t: TraduireTitre,
): string {
  const active = activeId ? conversations.find((c) => c.id === activeId) : undefined;
  const brut = active?.title.trim() ?? '';
  if (!brut) return t('sidebar.newChat');
  return brut.length > TITRE_MAX ? `${brut.slice(0, TITRE_MAX - 1)}…` : brut;
}

/** Vrai quand l'en-tête affiche le libellé de repli plutôt qu'un vrai titre. */
export function titreProvisoire(
  conversations: readonly Conversation[],
  activeId: string | null,
): boolean {
  const active = activeId ? conversations.find((c) => c.id === activeId) : undefined;
  return !active || !active.title.trim();
}

/**
 * Une discussion VIERGE : aucun message, pas de titre, pas épinglée. Une
 * conversation vide que l'on a renommée ou épinglée est du travail préparé,
 * pas une page blanche à recycler.
 *
 * La règle vivait en ligne dans Sidebar.handleNewChat — inaccessible au
 * mini-panneau, et au moteur de sync qui poussait chaque vierge abandonnée au
 * serveur : elles réapparaissaient « Sans titre » dans l'autre vue (2 lignes
 * sur 3 dans conversations.db le 17 sept. 2026).
 */
export function estVierge(c: Conversation): boolean {
  return c.messages.length === 0 && !c.title.trim() && !c.pinned;
}

/** La vierge la plus récente à réutiliser, ou null s'il faut en créer une. */
export function trouverDiscussionVierge(
  conversations: readonly Conversation[],
): Conversation | null {
  let meilleure: Conversation | null = null;
  for (const c of conversations) {
    if (estVierge(c) && (!meilleure || c.updatedAt > meilleure.updatedAt)) meilleure = c;
  }
  return meilleure;
}

/**
 * La conversation à réactiver quand l'active disparaît : la plus récente
 * par `updatedAt`. `deleteConversation` prenait `Object.keys(...)[0]` — l'ordre
 * d'insertion d'un objet JSON, c'est-à-dire un fil arbitraire.
 */
export function plusRecente(conversations: readonly Conversation[]): Conversation | null {
  let meilleure: Conversation | null = null;
  for (const c of conversations) {
    if (!meilleure || c.updatedAt > meilleure.updatedAt) meilleure = c;
  }
  return meilleure;
}

/**
 * Plie un texte pour la recherche : sans accents, sans casse, sans blancs
 * aux extrémités. « Permis » et « permis », « Cité » et « cite » se valent —
 * dans le mini-panneau on tape vite, souvent sans accent.
 */
export function plierTexte(texte: string): string {
  return texte
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .trim();
}

// Un caractère de mot : lettre (accentuée ou non, une fois pliée) ou chiffre.
// Tout le reste — espace, tiret, ponctuation, « — » — sépare deux mots.
const CARACTERE_DE_MOT = /[\p{L}\p{N}]/u;

/**
 * La requête commence-t-elle un MOT du titre ? « per » trouve « La Cité —
 * permis » ; « mis » ne le trouve qu'en simple sous-chaîne, classée après.
 */
export function debutDeMot(titrePlie: string, requetePliee: string): boolean {
  if (!requetePliee) return false;
  let depuis = 0;
  for (;;) {
    const i = titrePlie.indexOf(requetePliee, depuis);
    if (i < 0) return false;
    if (i === 0 || !CARACTERE_DE_MOT.test(titrePlie[i - 1])) return true;
    depuis = i + 1;
  }
}

/**
 * Le classement du sauteur (⌘J) : les épinglées d'abord, puis, à requête
 * non vide, les titres où elle commence un mot avant ceux où elle n'est
 * qu'une sous-chaîne, puis la plus récente en premier. Sans requête, c'est
 * l'ordre de la barre latérale — épinglées puis récence — et rien n'est
 * écarté ; avec, seules les discussions dont le titre plié contient la
 * requête pliée restent.
 *
 * `now` borne la récence : un `updatedAt` dans le futur (horloge qui a
 * reculé après une écriture, sync depuis l'autre vue) se lit « à
 * l'instant », pas « en tête pour toujours » — et l'ordre est une fonction
 * pure de ses entrées, testable avec une horloge fixe.
 *
 * Une discussion sans titre (pas encore nommée par son premier message)
 * n'a rien où chercher : elle ne répond à aucune requête, mais figure dans
 * la liste sans requête, à sa place de récence.
 */
export function classerDiscussions(
  requete: string,
  conversations: readonly Conversation[],
  now: number,
): Conversation[] {
  const q = plierTexte(requete);
  const recence = (c: Conversation) => Math.min(c.updatedAt, now);
  const rang = (c: Conversation): number => {
    if (!q) return 0;
    const titre = plierTexte(c.title);
    if (debutDeMot(titre, q)) return 0;
    return titre.includes(q) ? 1 : 2;
  };
  return conversations
    .map((c) => ({ c, rang: rang(c) }))
    .filter((e) => e.rang < 2)
    .sort((a, b) => {
      const ea = a.c.pinned ? 0 : 1;
      const eb = b.c.pinned ? 0 : 1;
      if (ea !== eb) return ea - eb;
      if (a.rang !== b.rang) return a.rang - b.rang;
      return recence(b.c) - recence(a.c);
    })
    .map((e) => e.c);
}

// ── Recherche dans les messages ──────────────────────────────────────────
//
// 17 sept. 2026, chantier « discussions dans le mini-panneau ». Le titre est
// les 50 premiers caractères de la première question (store.ts) : « la
// discussion où il m'a donné la date du permis » était introuvable, le mot
// « date » n'étant jamais dans un titre. Les messages sont déjà dans le
// store ; à trois conversations, un index FTS côté serveur serait une
// promesse sans usage (§5). La recherche est donc ici, pure, et le même
// résultat se lit pareil sous le titre du fil et dans la barre latérale.

/** Un segment de l'extrait : `avant` et `apres` sont du texte nu, `terme`
 * est l'occurrence telle qu'elle est écrite (accents et casse d'origine),
 * à surligner. Le module ne rend pas de <mark> : il n'a pas de DOM. */
export interface Extrait {
  avant: string;
  terme: string;
  apres: string;
}

export interface ResultatRecherche {
  conversation: Conversation;
  /** null quand seul le titre correspond : il est déjà affiché. */
  extrait: Extrait | null;
  /** Qui a écrit le message extrait ; null pour une correspondance de titre. */
  role: 'user' | 'assistant' | null;
  /** Le message d'où vient l'extrait, pour y défiler ; null sur le titre. */
  messageId: string | null;
  /** Occurrences dans le titre et tous les messages — le second critère de tri. */
  occurrences: number;
}

// 24 caractères avant le terme, 40 après. La ligne d'extrait (11 px) porte
// ≈ 55 caractères à 320 px, la largeur du sauteur ; elle est tronquée à
// droite, et « Vous : » (7) + une ellipse + 24 laissent le terme visible
// avant la coupe — avec 40 devant, un terme au milieu d'un long message
// était tronqué hors de la ligne, et l'extrait ne montrait que du contexte
// (vu dans le banc à 800 px, 17 sept. 2026). Après, 40 : de quoi lire la
// suite de la phrase quand la ligne est plus large.
export const RAYON_AVANT = 24;
export const RAYON_APRES = 40;

// Sous deux caractères, presque tout correspond (« e » est dans chaque
// message) et l'extrait ne dit rien ; on reste alors sur les titres.
export const LONGUEUR_MIN_RECHERCHE = 2;

interface TextePlie {
  plie: string;
  /** Pour chaque unité de code du texte plié, l'index d'origine de son caractère. */
  debut: number[];
  /** … et l'index d'origine juste APRÈS ce caractère. */
  fin: number[];
}

/**
 * Plie caractère par caractère en gardant la correspondance des index :
 * `plierTexte` seul déplace tout ce qui suit un accent (« é » NFD fait deux
 * unités, dont une est retirée), et l'extrait tombait un caractère trop tôt
 * par accent précédent.
 */
function plierAvecIndex(texte: string): TextePlie {
  let plie = '';
  const debut: number[] = [];
  const fin: number[] = [];
  let i = 0;
  for (const car of texte) {
    const p = plierCaractere(car);
    for (let k = 0; k < p.length; k++) {
      debut.push(i);
      fin.push(i + car.length);
    }
    plie += p;
    i += car.length;
  }
  return { plie, debut, fin };
}

function plierCaractere(car: string): string {
  return car
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase();
}

/** Occurrences non chevauchantes de `q` dans `plie` (q non vide). */
function compterOccurrences(plie: string, q: string): number {
  let n = 0;
  let depuis = 0;
  for (;;) {
    const i = plie.indexOf(q, depuis);
    if (i < 0) return n;
    n += 1;
    depuis = i + q.length;
  }
}

/** Les retours à la ligne d'un message deviennent des espaces : l'extrait
 * est une ligne, et un « \n\n » de Markdown y ferait un trou. */
function aplatir(texte: string): string {
  return texte.replace(/\s+/g, ' ');
}

function extraire(contenu: string, texte: TextePlie, q: string): Extrait | null {
  const i = texte.plie.indexOf(q);
  if (i < 0) return null;
  const debut = texte.debut[i];
  const fin = texte.fin[i + q.length - 1];
  const depuis = Math.max(0, debut - RAYON_AVANT);
  const jusqua = Math.min(contenu.length, fin + RAYON_APRES);
  return {
    avant: (depuis > 0 ? '…' : '') + aplatir(contenu.slice(depuis, debut)),
    terme: aplatir(contenu.slice(debut, fin)),
    apres: aplatir(contenu.slice(fin, jusqua)) + (jusqua < contenu.length ? '…' : ''),
  };
}

/**
 * Cherche `requete` dans le titre puis dans `messages[].content` de chaque
 * conversation, accents et casse pliés. Le résultat porte un extrait
 * (RAYON_AVANT caractères avant, RAYON_APRES après) de la PREMIÈRE
 * occurrence dans un message (le premier qui contient la requête) ; quand seul le
 * titre correspond, pas d'extrait — il est déjà affiché. Tri : épinglées,
 * puis nombre d'occurrences (titre et messages confondus), puis la plus
 * récente, `now` bornant la récence comme dans `classerDiscussions`.
 *
 * Une requête vide ou blanche ne rend RIEN : le catalogue entier n'est pas
 * un résultat de recherche, l'appelant montre alors l'ordre du sauteur. Un
 * message sans texte (appel d'outil seul, audio) n'est pas une erreur : il
 * ne correspond simplement pas.
 */
export function filtrerDiscussions(
  conversations: readonly Conversation[],
  requete: string,
  now: number = Date.now(),
): ResultatRecherche[] {
  const q = plierTexte(requete);
  if (!q) return [];
  const resultats: ResultatRecherche[] = [];
  for (const c of conversations) {
    let occurrences = compterOccurrences(plierTexte(c.title), q);
    let extrait: Extrait | null = null;
    let role: ResultatRecherche['role'] = null;
    let messageId: string | null = null;
    for (const m of c.messages) {
      const contenu = typeof m.content === 'string' ? m.content : '';
      if (!contenu) continue;
      const texte = plierAvecIndex(contenu);
      const n = compterOccurrences(texte.plie, q);
      if (n === 0) continue;
      occurrences += n;
      if (!extrait) {
        extrait = extraire(contenu, texte, q);
        role = m.role;
        messageId = m.id;
      }
    }
    if (occurrences > 0) resultats.push({ conversation: c, extrait, role, messageId, occurrences });
  }
  const recence = (c: Conversation) => Math.min(c.updatedAt, now);
  return resultats.sort((a, b) => {
    const ea = a.conversation.pinned ? 0 : 1;
    const eb = b.conversation.pinned ? 0 : 1;
    if (ea !== eb) return ea - eb;
    if (a.occurrences !== b.occurrences) return b.occurrences - a.occurrences;
    return recence(b.conversation) - recence(a.conversation);
  });
}

/**
 * Ce que le sauteur ET la barre latérale affichent pour une requête : sous
 * LONGUEUR_MIN_RECHERCHE caractères, les titres seuls (`classerDiscussions`,
 * sans extrait) ; à partir de deux, titres et messages avec extrait. Une
 * seule fonction pour que les deux vues ne divergent jamais.
 */
export function rechercherDiscussions(
  conversations: readonly Conversation[],
  requete: string,
  now: number,
): ResultatRecherche[] {
  if (plierTexte(requete).length >= LONGUEUR_MIN_RECHERCHE) {
    return filtrerDiscussions(conversations, requete, now);
  }
  return classerDiscussions(requete, conversations, now).map((conversation) => ({
    conversation,
    extrait: null,
    role: null,
    messageId: null,
    occurrences: 0,
  }));
}

// ── L'atterrissage du mini-panneau ───────────────────────────────────────
//
// 17 sept. 2026, chantier « discussions dans le mini-panneau ». `activeId`
// n'est jamais synchronisé (convSync.ts, fusionner) et le localStorage est
// cloisonné par origine : le mini-panneau rouvrait TOUJOURS la conversation
// où on l'avait laissé — la question rapide posée depuis Xcode se collait
// au fil d'avant-hier, et la longue discussion commencée dans la fenêtre
// dix minutes plus tôt restait hors de portée. La règle est celle d'Apple
// Notes (Quick Note rouvre la dernière note si elle est récente, sinon en
// crée une) et de Raycast AI (« Continue last chat » sous une heure).

// 20 minutes : la durée d'une pause entre deux relances d'un même sujet —
// on lit une réponse, on retourne dans Xcode, on revient avec la suite. À
// 5 minutes, un simple aller-retour dans l'éditeur suffisait à perdre le
// fil ; à une heure (Raycast), on a presque toujours changé de sujet et la
// nouvelle question se collait à l'ancien.
export const FENETRE_CHAUDE_MS = 20 * 60_000;

export type Atterrissage =
  | { type: 'rester' }
  | { type: 'reprendre'; id: string }
  | { type: 'vierge' };

/** La récence bornée par `now` : un `updatedAt` dans le futur se lit « à l'instant ». */
function recenceBornee(c: Conversation, now: number): number {
  return Math.min(c.updatedAt, now);
}

/**
 * Où atterrir à l'ouverture du panneau. (a) La conversation la plus
 * récemment modifiée — fenêtre ou mini confondus, elles sont synchronisées —
 * si elle l'a été il y a moins de `fenetreChaudeMs` ET porte au moins un
 * message : on la reprend (« rester » si c'est déjà l'active locale). (b)
 * Sinon une vierge : « rester » si l'active locale en est une, « vierge »
 * (à créer ou à réutiliser par la règle commune) autrement. Deux
 * conversations chaudes à égalité : l'active locale gagne, on ne change
 * pas de fil sans raison.
 */
export function choisirAtterrissage(
  conversations: readonly Conversation[],
  activeIdLocal: string | null,
  now: number,
  fenetreChaudeMs: number = FENETRE_CHAUDE_MS,
): Atterrissage {
  let chaude: Conversation | null = null;
  for (const c of conversations) {
    if (c.messages.length === 0) continue;
    const recence = recenceBornee(c, now);
    if (now - recence >= fenetreChaudeMs) continue;
    if (
      !chaude ||
      recence > recenceBornee(chaude, now) ||
      (recence === recenceBornee(chaude, now) && c.id === activeIdLocal)
    ) {
      chaude = c;
    }
  }
  if (chaude) return chaude.id === activeIdLocal ? { type: 'rester' } : { type: 'reprendre', id: chaude.id };
  const active = activeIdLocal ? conversations.find((c) => c.id === activeIdLocal) : undefined;
  if (active && estVierge(active)) return { type: 'rester' };
  return { type: 'vierge' };
}

export interface Occupation {
  /** Une réponse est en cours de réception. */
  enFlux: boolean;
  /** Ce que le compositeur porte — un espace seul n'est pas un brouillon. */
  brouillon: string;
}

/**
 * L'utilisateur tient-il le fil ? Alors on n'atterrit PAS, quel que soit le
 * fil chaud. Contre-revue du 17 sept. 2026 : le panneau se dépliait sur
 * « La Cité » (chaude) alors qu'on avait tapé « et la suite du plan ? » dans
 * « Zéro à Héro » — le brouillon restait dans le champ sous le mauvais titre
 * et serait parti dans le mauvais fil (§100). Une réponse en cours tient le
 * fil de la même façon : on ne quitte pas ce qu'on est en train de lire.
 */
export function tientLeFil({ enFlux, brouillon }: Occupation): boolean {
  return enFlux || brouillon.trim() !== '';
}

/**
 * Le fil `conversationId` est-il celui que la vue affiche ? Contre-revue du
 * 17 sept. 2026 : le store réaffichait les messages du fil en flux quel que
 * soit l'actif — ⌘N pendant une réponse montrait les jetons du fil A sous le
 * titre « Nouvelle discussion », bulle vivante comprise, alors que la vierge
 * était vide sur disque. Le fil en flux continue d'être ÉCRIT dans son
 * propre objet ; seule la vue est réservée à l'actif.
 */
export function doitAfficherLeFil(conversationId: string, activeId: string | null): boolean {
  return conversationId === activeId;
}

/**
 * Le titre à commettre après un renommage, ou null s'il n'y a rien à
 * commettre : vide ou blanc (le titre ne se perd pas sur un champ effacé),
 * ou identique à l'actuel (une écriture datée pour rien serait poussée vers
 * l'autre vue par convSync).
 */
export function titreARenommer(saisie: string, actuel: string): string | null {
  const suivant = saisie.trim();
  return suivant && suivant !== actuel ? suivant : null;
}

export interface Accueil {
  /** Le dernier fil qui a des messages, hors l'active — à reprendre d'un ↩. */
  reprendre: Conversation | null;
  /** Les suivants, par récence, au plus `n`. */
  autres: Conversation[];
}

/**
 * Ce que la page vide propose en compact : le dernier fil à reprendre, puis
 * les `n` suivants. Seules les conversations qui ont des messages comptent
 * (une vierge n'a rien à reprendre) et l'active est exclue (on y est). Par
 * récence bornée — les épinglées ne passent pas devant : « reprendre »
 * parle du dernier fil, pas du préféré.
 */
export function recentesPourAccueil(
  conversations: readonly Conversation[],
  activeId: string | null,
  now: number,
  n = 3,
): Accueil {
  const triees = conversations
    .filter((c) => c.messages.length > 0 && c.id !== activeId)
    .sort((a, b) => recenceBornee(b, now) - recenceBornee(a, now));
  return { reprendre: triees[0] ?? null, autres: triees.slice(1, 1 + n) };
}

// ── Fil précédent / suivant ──────────────────────────────────────────────

export type SensVoisine = 'precedente' | 'suivante';

/**
 * Le fil voisin de `activeId` dans l'ordre exact du sauteur (épinglées puis
 * récence, `classerDiscussions` sans requête) : « precedente » remonte
 * vers le plus récent, « suivante » descend vers le plus ancien — comme
 * ⌘⇧[ et ⌘⇧] entre les onglets de Safari. Aux extrémités, null : pas de
 * bouclage, car dans une liste par récence sauter du plus ancien au plus
 * récent surprend au lieu de dire « c'est le bout ». Sans active, ou active
 * inconnue (supprimée dans l'autre vue) : le premier de la liste dans les
 * deux sens — on entre dans la liste par le haut. Liste vide : null.
 */
export function discussionVoisine(
  conversations: readonly Conversation[],
  activeId: string | null,
  sens: SensVoisine,
  now: number,
): Conversation | null {
  const ordre = classerDiscussions('', conversations, now);
  if (ordre.length === 0) return null;
  const i = activeId ? ordre.findIndex((c) => c.id === activeId) : -1;
  if (i < 0) return ordre[0];
  const j = sens === 'precedente' ? i - 1 : i + 1;
  return j >= 0 && j < ordre.length ? ordre[j] : null;
}
