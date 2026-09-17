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
