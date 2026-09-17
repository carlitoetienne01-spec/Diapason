// Moteur de synchronisation des conversations avec le serveur local.
//
// 16 sept. 2026 : deux origines, deux localStorage — la fenêtre principale
// vit sur tauri://localhost, le mini-panneau sur http://127.0.0.1:8000.
// Chacune croyait détenir l'historique ; une conversation commencée dans le
// mini-panneau n'existait simplement pas dans la fenêtre. Le serveur devient
// la source de vérité, le localStorage reste le cache de travail synchrone
// et le secours hors-ligne.
//
// Deux règles, nées de la revue du même jour :
//
// - Le curseur est un NUMÉRO D'ÉCRITURE serveur (`seq`), jamais une heure.
//   Un premier jet re-tirait « depuis updatedAt - 5 s » : une conversation
//   poussée en retard (vue rouverte après des jours) arrivait avec sa vieille
//   heure et restait invisible à jamais aux vues dont le curseur l'avait
//   dépassée.
// - La fusion se fait au grain du MESSAGE (`fusionnerConversations`), avec
//   la même règle, à la lettre, que conversations_store.py côté serveur. Un
//   dernier-écrit-gagne sur la conversation entière perdait la question et
//   la réponse de la vue A dès que la vue B écrivait le même fil dans la
//   fenêtre de synchronisation.
//
// store.ts n'importe PAS ce module (un cycle d'imports figerait Zustand au
// premier chargement) : le couplage passe par des CustomEvent window que
// saveConversations et deleteConversation émettent, et ce moteur écoute.
//
// Sur le fil, les champs sont ceux du contrat, en camelCase anglais — un
// champ snake_case se lit `undefined` côté TypeScript, en silence.

import type { ChatMessage, Conversation, ConversationStore } from '../types';
import { apiFetch, getApiKey } from './api';
import { estVierge } from './discussions';
import { generateId, loadConversations, saveConversations, useAppStore } from './store';

// ── Types ─────────────────────────────────────────────────────────────

/** Pierre tombale rendue par le serveur : l'id et l'instant de la mort. */
export interface Tombale {
  id: string;
  deletedAt: number;
}

/**
 * L'état persistant du moteur :
 * - `curseur` : le dernier numéro d'écriture serveur reçu ; le prochain
 *   tirage demande tout ce qui a été écrit après.
 * - `suppressions` : ids condamnés localement dont le DELETE n'a pas encore
 *   abouti. Persistée : une suppression faite juste avant de fermer la
 *   fenêtre ressusciterait au prochain tirage si la file ne survivait pas.
 * - `carte` : Record<id, updatedAt> des versions que le serveur connaît. On
 *   ne pousse que ce qui la dépasse — sans elle, chaque rechargement
 *   re-poussait l'historique entier.
 */
export interface EtatSync {
  curseur: number;
  suppressions: string[];
  carte: Record<string, number>;
}

// ── Constantes ────────────────────────────────────────────────────────

export const ETAT_SYNC_KEY = 'diapason-conversations-sync';

// 1200 ms après le dernier événement de modification : pendant un streaming,
// updateLastAssistant sauve à chaque bout de texte — pousser à chaque token
// aurait fait un PUT par mot.
const DEBORDEMENT_MS = 1200;

// 10 s entre deux tirages : assez court pour que le mini-panneau et la
// fenêtre se voient « en direct », assez long pour ne pas peser sur un
// serveur qui fait tourner un modèle local.
const INTERVALLE_MS = 10_000;

// ── Fusion — la même règle que conversations_store.py, à la lettre ────

/**
 * Identité d'un message : son `id`, sinon `role@timestamp`. Les historiques
 * d'avant l'identifiant n'en portent pas ; sans repli, deux copies du même
 * message se seraient dupliquées à chaque fusion.
 */
export function cleMessage(m: ChatMessage): string {
  if (typeof m.id === 'string' && m.id) return m.id;
  return `${m.role ?? ''}@${m.timestamp ?? 0}`;
}

function rangRole(m: ChatMessage): number {
  // Dans une paire écrite à la même milliseconde, la question précède la
  // réponse.
  return m.role === 'user' ? 0 : 1;
}

function nombre(v: unknown): number {
  return typeof v === 'number' && Number.isFinite(v) ? v : 0;
}

/**
 * Entre deux versions du même message, garde la plus complète. Le contenu
 * d'une réponse ne fait que croître pendant le flux — une copie partielle
 * poussée pour que l'autre vue voie la réponse arriver ne doit jamais
 * écraser la copie finale, quelle que soit la vue qui a écrit la
 * conversation en dernier. Puis le nombre de champs (la copie finale porte
 * usage, télémétrie, appels d'outils), puis l'ordre lexicographique du
 * contenu pour que les deux côtés tranchent pareil.
 */
function meilleurMessage(a: ChatMessage, b: ChatMessage): ChatMessage {
  const ca = typeof a.content === 'string' ? a.content : '';
  const cb = typeof b.content === 'string' ? b.content : '';
  if (ca.length !== cb.length) return ca.length > cb.length ? a : b;
  const na = Object.keys(a).length;
  const nb = Object.keys(b).length;
  if (na !== nb) return na > nb ? a : b;
  if (ca !== cb) return ca > cb ? a : b;
  return a;
}

/**
 * Vrai si `a` fournit les métadonnées (titre, épingle, modèle). L'écriture
 * la plus récente gagne ; sur égalité de `updatedAt` (deux vues à la même
 * milliseconde), un ordre total explicite pour que le serveur et chaque
 * client désignent la même copie.
 */
function prime(a: Conversation, b: Conversation): boolean {
  if (a.updatedAt !== b.updatedAt) return a.updatedAt > b.updatedAt;
  if (a.messages.length !== b.messages.length) {
    return a.messages.length > b.messages.length;
  }
  if (a.title !== b.title) return a.title > b.title;
  if (!!a.pinned !== !!b.pinned) return !!a.pinned;
  if (a.model !== b.model) return a.model > b.model;
  return true;
}

/**
 * Union par identité, la version la plus complète par message, dans l'ordre
 * du temps (puis question avant réponse, puis identité). Les objets message
 * sont réutilisés tels quels, jamais recopiés : une fusion sans effet doit
 * rendre exactement les objets locaux, pour qu'on sache qu'elle est sans
 * effet.
 */
export function fusionnerMessages(desA: ChatMessage[], desB: ChatMessage[]): ChatMessage[] {
  const parCle = new Map<string, ChatMessage>();
  for (const m of desB) parCle.set(cleMessage(m), m);
  for (const m of desA) {
    const cle = cleMessage(m);
    const autre = parCle.get(cle);
    parCle.set(cle, autre === undefined ? m : meilleurMessage(m, autre));
  }
  return [...parCle.values()].sort((x, y) => {
    const dt = nombre(x.timestamp) - nombre(y.timestamp);
    if (dt !== 0) return dt;
    const dr = rangRole(x) - rangRole(y);
    if (dr !== 0) return dr;
    const cx = cleMessage(x);
    const cy = cleMessage(y);
    return cx < cy ? -1 : cx > cy ? 1 : 0;
  });
}

/**
 * Jointure commutative et idempotente de deux copies d'une conversation :
 * métadonnées de la copie qui prime, union des messages, `updatedAt` le
 * plus haut, `createdAt` le plus bas.
 */
export function fusionnerConversations(a: Conversation, b: Conversation): Conversation {
  const [gagnante, perdante] = prime(a, b) ? [a, b] : [b, a];
  return {
    ...gagnante,
    createdAt: Math.min(a.createdAt, b.createdAt),
    updatedAt: Math.max(a.updatedAt, b.updatedAt),
    pinned: !!gagnante.pinned,
    messages: fusionnerMessages(gagnante.messages, perdante.messages),
  };
}

function identiques(a: Conversation, b: Conversation): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

// ── Fonctions pures (c'est elles qu'on teste) ─────────────────────────

export function etatSyncInitial(): EtatSync {
  return { curseur: 0, suppressions: [], carte: {} };
}

/**
 * Fusionne l'état local avec ce que le serveur rend. Par id, la
 * conversation locale et la distante sont FUSIONNÉES (jamais remplacées) ;
 * une tombale gagne si `deletedAt >= updatedAt` local (strictement
 * inférieur : la conversation locale survit et sera re-poussée — elle
 * « ressuscite »). `activeId` est conservé, remis à null si sa conversation
 * meurt. Re-fusionner les mêmes données ne change RIEN — sinon chaque
 * tirage redéclencherait une écriture.
 */
export function fusionner(
  local: ConversationStore,
  distantes: Conversation[],
  tombales: Tombale[],
): { store: ConversationStore; changees: string[]; activeSupprimee: boolean } {
  const conversations = { ...local.conversations };
  const changees: string[] = [];

  for (const distante of distantes) {
    const mienne = conversations[distante.id];
    const fusion = mienne ? fusionnerConversations(mienne, distante) : distante;
    if (!mienne || !identiques(fusion, mienne)) {
      conversations[distante.id] = fusion;
      changees.push(distante.id);
    }
  }

  for (const tombale of tombales) {
    const mienne = conversations[tombale.id];
    if (mienne && tombale.deletedAt >= mienne.updatedAt) {
      delete conversations[tombale.id];
      changees.push(tombale.id);
    }
  }

  let activeId = local.activeId;
  let activeSupprimee = false;
  if (activeId && !conversations[activeId]) {
    activeId = null;
    activeSupprimee = true;
  }

  return {
    store: { version: 1, conversations, activeId },
    changees,
    activeSupprimee,
  };
}

/**
 * Ce qui se pousse : les conversations locales que la carte serveur ne
 * connaît pas, ou dont le `updatedAt` dépasse la version connue. Une
 * conversation condamnée (file de suppressions) ne se pousse jamais — le
 * DELETE part à sa place ; une conversation en quarantaine (refusée pour de
 * bon par le serveur) non plus.
 *
 * Une VIERGE (sans message, sans titre, non épinglée) non plus : elle
 * n'existe que localement jusqu'au premier envoi. 17 sept. 2026 : chaque
 * « Nouvelle discussion » abandonnée partait au serveur et réapparaissait
 * « Sans titre » dans l'autre vue — 2 lignes sur 3 dans conversations.db.
 * Dès qu'elle reçoit un message, un titre ou une épingle, elle part comme
 * les autres.
 */
export function choisirAPousser(
  local: ConversationStore,
  carte: Record<string, number>,
  suppressions: string[] = [],
  quarantaine: Iterable<string> = [],
): Conversation[] {
  const exclues = new Set([...suppressions, ...quarantaine]);
  return Object.values(local.conversations).filter(
    (c) =>
      !exclues.has(c.id) &&
      !estVierge(c) &&
      (carte[c.id] === undefined || c.updatedAt > carte[c.id]),
  );
}

/**
 * Ajoute des ids à la file de suppressions (sans doublon — un id supprimé
 * deux fois ne doit produire qu'un DELETE) et les retire de la carte : une
 * conversation condamnée n'a plus de « version connue du serveur ».
 */
export function avecSuppressions(etat: EtatSync, ids: string[]): EtatSync {
  const suppressions = [...etat.suppressions];
  const carte = { ...etat.carte };
  for (const id of ids) {
    if (!suppressions.includes(id)) suppressions.push(id);
    delete carte[id];
  }
  return { ...etat, suppressions, carte };
}

/** Retire un id de la file — appelé quand le DELETE a abouti. */
export function sansSuppression(etat: EtatSync, id: string): EtatSync {
  return { ...etat, suppressions: etat.suppressions.filter((s) => s !== id) };
}

/**
 * Une réponse 4xx (hors 401 et 429) est PERMANENTE : rejouer la même
 * requête toutes les 10 s ne la fera jamais passer, et un premier jet
 * s'arrêtait dessus — toutes les conversations placées après l'élément
 * empoisonné ne se synchronisaient plus jamais. 401 (clé pas encore
 * injectée) et 429 (limiteur) sont transitoires.
 */
export function estRefusPermanent(status: number): boolean {
  return status >= 400 && status < 500 && status !== 401 && status !== 429;
}

/**
 * Rend une sauvegarde importée propre, ou null si elle n'a pas la forme
 * attendue. L'import n'était validé que sur `version === 1` : un fichier
 * sans `conversations` plantait le store à chaque tick, un `pinned: null`
 * ou un `updatedAt: "1000"` faisaient refuser la poussée pour de bon
 * (revue du 16 sept. 2026). Les conversations invalides sont écartées, pas
 * l'import entier ; `activeId` n'est gardé que s'il existe.
 */
export function normaliserImport(data: unknown): ConversationStore | null {
  if (!data || typeof data !== 'object') return null;
  const brut = data as { version?: unknown; conversations?: unknown; activeId?: unknown };
  if (brut.version !== 1) return null;
  if (!brut.conversations || typeof brut.conversations !== 'object') return null;

  const conversations: Record<string, Conversation> = {};
  for (const [cle, valeur] of Object.entries(brut.conversations as Record<string, unknown>)) {
    const c = valeur as Partial<Record<keyof Conversation, unknown>> | null;
    if (!c || typeof c !== 'object') continue;
    const id = typeof c.id === 'string' && c.id ? c.id : cle;
    if (!Number.isFinite(c.updatedAt as number)) continue;
    const updatedAt = c.updatedAt as number;
    const createdAt = Number.isFinite(c.createdAt as number) ? (c.createdAt as number) : updatedAt;
    const messages = Array.isArray(c.messages)
      ? (c.messages as unknown[]).flatMap((m): ChatMessage[] => {
          const b = m as Partial<ChatMessage> | null;
          if (!b || typeof b !== 'object') return [];
          if (b.role !== 'user' && b.role !== 'assistant') return [];
          if (typeof b.content !== 'string') return [];
          return [
            {
              ...(b as ChatMessage),
              id: typeof b.id === 'string' && b.id ? b.id : generateId(),
              timestamp: Number.isFinite(b.timestamp as number) ? (b.timestamp as number) : createdAt,
            },
          ];
        })
      : [];
    conversations[id] = {
      id,
      title: typeof c.title === 'string' ? c.title : '',
      createdAt,
      updatedAt,
      model: typeof c.model === 'string' && c.model ? c.model : 'default',
      pinned: c.pinned === true,
      messages,
    };
  }

  const activeId =
    typeof brut.activeId === 'string' && conversations[brut.activeId] ? brut.activeId : null;
  return { version: 1, conversations, activeId };
}

// ── État du moteur ────────────────────────────────────────────────────

let etat: EtatSync | null = null;

function getEtat(): EtatSync {
  if (etat === null) etat = chargerEtat();
  return etat;
}

function chargerEtat(): EtatSync {
  try {
    const raw = localStorage.getItem(ETAT_SYNC_KEY);
    if (!raw) return etatSyncInitial();
    const parsed = JSON.parse(raw);
    return {
      curseur: typeof parsed.curseur === 'number' ? parsed.curseur : 0,
      suppressions: Array.isArray(parsed.suppressions)
        ? parsed.suppressions.filter((s: unknown): s is string => typeof s === 'string')
        : [],
      carte: parsed.carte && typeof parsed.carte === 'object' ? parsed.carte : {},
    };
  } catch {
    return etatSyncInitial();
  }
}

function persisterEtat(): void {
  try {
    localStorage.setItem(ETAT_SYNC_KEY, JSON.stringify(getEtat()));
  } catch {
    // Quota plein : l'état vit en mémoire pour la session ; au pire, un
    // rechargement re-poussera des conversations que le serveur a déjà —
    // la fusion rend l'opération sans effet.
  }
}

// Ids que le serveur a refusés pour de bon (400/404/422…) dans cette
// session : on ne les rejoue pas, on ne bloque pas les autres, on l'a dit
// une fois. Un rechargement réessaie — le contenu a peut-être changé.
const quarantaine = new Set<string>();

// Vrai pendant qu'on écrit NOUS-MÊMES le localStorage (adoption d'une copie
// serveur). Sans ce drapeau, notre propre écriture émettrait l'événement de
// modification, qui programmerait une poussée, qui re-enverrait au serveur
// ce qu'il vient de nous donner — une boucle inutile à chaque tirage.
let ecritureInterne = false;

// Un seul console.warn à la panne, un au rétablissement — pas un par tick
// (§100 : pas de faux « synchronisé », mais pas de spam non plus).
let enPanne = false;

function signalerPanne(detail: unknown): void {
  if (!enPanne) {
    enPanne = true;
    console.warn('[convSync] serveur injoignable, la synchronisation réessaiera :', detail);
  }
}

function signalerRetablissement(): void {
  if (enPanne) {
    enPanne = false;
    console.warn('[convSync] synchronisation des conversations rétablie');
  }
}

function mettreEnQuarantaine(id: string, detail: string): void {
  if (quarantaine.has(id)) return;
  quarantaine.add(id);
  console.warn(`[convSync] conversation ${id} refusée par le serveur, mise de côté : ${detail}`);
}

// ── Application locale de l'état distant ──────────────────────────────

/**
 * Adopte l'état distant : fusionne dans le localStorage (drapeau levé,
 * donc sans re-déclencher de poussée), rafraîchit Zustand, et ne recharge
 * les messages affichés que hors streaming. La conversation qui REÇOIT un
 * flux est exclue tant qu'il dure — updateLastAssistant écrit dans son
 * dernier message, et une fusion qui y ajouterait la paire d'une autre vue
 * ferait couler le flux dans le mauvais message. Rend les ids exclus : le
 * curseur ne doit pas avancer tant qu'ils n'ont pas été appliqués.
 */
function appliquerDistant(distantes: Conversation[], tombales: Tombale[]): string[] {
  const app = useAppStore.getState();
  const enFlux = app.streamState.isStreaming ? app.streamState.conversationId : null;
  const condamnees = getEtat().suppressions;

  // Une conversation condamnée localement ne ressuscite pas d'un tirage qui
  // aurait couru plus vite que son DELETE.
  let vivantes = distantes.filter((c) => !condamnees.includes(c.id));
  let mortes = tombales;
  const exclues: string[] = [];
  if (enFlux) {
    for (const c of vivantes) if (c.id === enFlux) exclues.push(c.id);
    for (const t of mortes) if (t.id === enFlux) exclues.push(t.id);
    vivantes = vivantes.filter((c) => c.id !== enFlux);
    mortes = mortes.filter((t) => t.id !== enFlux);
  }

  const local = loadConversations();
  const { store, changees, activeSupprimee } = fusionner(local, vivantes, mortes);
  if (changees.length === 0 && !activeSupprimee) return exclues;

  ecritureInterne = true;
  try {
    saveConversations(store);
  } finally {
    ecritureInterne = false;
  }

  app.loadConversations();
  const apres = useAppStore.getState();
  if (!apres.streamState.isStreaming) {
    if (activeSupprimee) {
      apres.loadMessages(null);
    } else if (apres.activeId && changees.includes(apres.activeId)) {
      apres.loadMessages(apres.activeId);
    }
  }
  return exclues;
}

// ── Tirer / pousser ───────────────────────────────────────────────────

/** GET des écritures serveur depuis le curseur, puis fusion locale. */
export async function tirer(): Promise<void> {
  // Sans clé, ne rien tenter et ne rien afficher : le prochain tick
  // réessaiera. Prétendre « synchronisé » ici serait un faux SUCCESS.
  if (!getApiKey()) return;

  const e = getEtat();
  const query = e.curseur > 0 ? `?since=${e.curseur}` : '';

  let distantes: Conversation[];
  let tombales: Tombale[];
  let seq: number;
  try {
    const reponse = await apiFetch(`/v1/conversations${query}`);
    if (!reponse.ok) {
      signalerPanne(`GET /v1/conversations → ${reponse.status}`);
      return;
    }
    const corps = await reponse.json();
    distantes = Array.isArray(corps.conversations) ? corps.conversations : [];
    tombales = Array.isArray(corps.deleted) ? corps.deleted : [];
    seq = typeof corps.seq === 'number' ? corps.seq : e.curseur;
  } catch (err) {
    signalerPanne(err);
    return;
  }
  signalerRetablissement();

  const exclues = appliquerDistant(distantes, tombales);
  for (const c of distantes) {
    if (!exclues.includes(c.id)) e.carte[c.id] = c.updatedAt;
  }
  for (const t of tombales) {
    if (!exclues.includes(t.id)) delete e.carte[t.id];
  }
  // Le curseur n'avance que si TOUT a été appliqué : une conversation
  // exclue parce qu'elle reçoit un flux sera re-tirée au tick suivant (la
  // fusion est idempotente, re-recevoir le reste ne coûte rien).
  if (exclues.length === 0) e.curseur = seq;
  persisterEtat();
}

// Une poussée à la fois : deux flushs entrecroisés (débordement + onglet
// caché) enverraient deux fois les mêmes PUT. Une poussée demandée PENDANT
// le vol est rejouée juste après — un premier jet la jetait, et la dernière
// édition avant fermeture ne partait pas.
let pousseeEnCours = false;
let pousseeDemandee = false;

/**
 * DELETE des suppressions en attente puis PUT des conversations en retard.
 * Le serveur rend sa copie fusionnée (ou une tombale) : on l'adopte — la
 * phrase rendue vient du RÉCEPTEUR, jamais de ce qu'on a envoyé (§100).
 */
export async function pousser(): Promise<void> {
  if (pousseeEnCours) {
    pousseeDemandee = true;
    return;
  }
  if (!getApiKey()) return;
  pousseeEnCours = true;
  try {
    do {
      pousseeDemandee = false;
      const encore = await pousserUneFois();
      if (!encore) break;
    } while (pousseeDemandee);
  } finally {
    pousseeEnCours = false;
  }
}

/** Rend faux quand le serveur est injoignable (inutile de rejouer tout de suite). */
async function pousserUneFois(): Promise<boolean> {
  const e = getEtat();

  for (const id of [...e.suppressions]) {
    try {
      const reponse = await apiFetch(`/v1/conversations/${encodeURIComponent(id)}`, {
        method: 'DELETE',
      });
      if (!reponse.ok) {
        if (estRefusPermanent(reponse.status)) {
          // Un id que le serveur ne peut pas adresser ne le sera jamais : il
          // n'est pas chez lui non plus. On passe.
          mettreEnQuarantaine(id, `DELETE → ${reponse.status}`);
          e.suppressions = sansSuppression(e, id).suppressions;
          persisterEtat();
          continue;
        }
        signalerPanne(`DELETE /v1/conversations/${id} → ${reponse.status}`);
        return false;
      }
      e.suppressions = sansSuppression(e, id).suppressions;
      // Persister à CHAQUE succès : si la fenêtre meurt au milieu de la
      // file, les DELETE déjà faits ne repartent pas au rechargement.
      persisterEtat();
    } catch (err) {
      signalerPanne(err);
      return false;
    }
  }

  const local = loadConversations();
  const enRetard = choisirAPousser(local, e.carte, e.suppressions, quarantaine);
  const copies: Conversation[] = [];
  const tombalesGagnantes: Tombale[] = [];

  for (const conv of enRetard) {
    // Re-vérifier à CHAQUE tour : une suppression arrivée pendant le PUT
    // précédent ne doit pas voir sa conversation repoussée sur le serveur.
    if (e.suppressions.includes(conv.id)) continue;
    try {
      const reponse = await apiFetch(`/v1/conversations/${encodeURIComponent(conv.id)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(conv),
      });
      if (!reponse.ok) {
        if (estRefusPermanent(reponse.status)) {
          mettreEnQuarantaine(conv.id, `PUT → ${reponse.status}`);
          continue;
        }
        signalerPanne(`PUT /v1/conversations/${conv.id} → ${reponse.status}`);
        return false;
      }
      const corps = await reponse.json();
      if (corps.deleted) {
        tombalesGagnantes.push({ id: conv.id, deletedAt: corps.deletedAt });
        delete e.carte[conv.id];
      } else if (corps.conversation) {
        e.carte[conv.id] = corps.conversation.updatedAt;
        copies.push(corps.conversation);
      }
      persisterEtat();
    } catch (err) {
      signalerPanne(err);
      return false;
    }
  }
  signalerRetablissement();

  if (copies.length > 0 || tombalesGagnantes.length > 0) {
    // La copie serveur est la fusion des deux : l'adopter est sans effet
    // quand rien n'a changé, et ramène ce que l'autre vue y avait mis.
    appliquerDistant(copies, tombalesGagnantes);
  }
  return true;
}

// ── Programmation ─────────────────────────────────────────────────────

let minuteurPoussee: ReturnType<typeof setTimeout> | null = null;

function programmerPoussee(): void {
  if (minuteurPoussee !== null) clearTimeout(minuteurPoussee);
  minuteurPoussee = setTimeout(() => {
    minuteurPoussee = null;
    void pousser();
  }, DEBORDEMENT_MS);
}

/**
 * Met des ids en suppression en attente et pousse aussitôt. Exportée pour
 * « effacer les conversations » (SettingsPage) : sans les tombales serveur,
 * l'historique effacé ressusciterait au tirage suivant — un mensonge (§100).
 */
export function programmerSuppressionsServeur(ids: string[]): void {
  if (ids.length === 0) return;
  const e = getEtat();
  // Muter l'objet unique plutôt que le remplacer : pousser() en garde une
  // référence pendant ses await, et un objet remplacé sous ses pieds lui
  // ferait perdre les suppressions ajoutées entre-temps.
  const nouveau = avecSuppressions(e, ids);
  e.suppressions = nouveau.suppressions;
  e.carte = nouveau.carte;
  persisterEtat();
  void pousser();
}

let demarre = false;

/**
 * Démarre le moteur : tir initial, puis toutes les 10 s ; 'focus' → tirer ;
 * onglet caché → flush immédiat des poussées. À appeler une fois — les
 * appels suivants (StrictMode, remontages) sont sans effet.
 */
export function demarrerSyncConversations(): void {
  if (demarre) return;
  demarre = true;
  getEtat();

  window.addEventListener('diapason:conversations-modifiees', () => {
    if (ecritureInterne) return;
    programmerPoussee();
  });

  window.addEventListener('diapason:conversation-supprimee', (event) => {
    const id = (event as CustomEvent<{ id: string }>).detail?.id;
    if (!id) return;
    const e = getEtat();
    const nouveau = avecSuppressions(e, [id]);
    e.suppressions = nouveau.suppressions;
    e.carte = nouveau.carte;
    persisterEtat();
    programmerPoussee();
  });

  window.addEventListener('focus', () => {
    void tirer();
  });

  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) return;
    // L'onglet se cache : pousser tout de suite ce que le débordement
    // retenait — une fenêtre fermée n'aura pas de « 1200 ms plus tard ».
    if (minuteurPoussee !== null) {
      clearTimeout(minuteurPoussee);
      minuteurPoussee = null;
    }
    void pousser();
  });

  void tirer().then(() => pousser());
  setInterval(() => {
    // pousser() après chaque tirage : c'est le réessai silencieux des PUT et
    // DELETE tombés en panne — un no-op quand la carte est à jour.
    void tirer().then(() => pousser());
  }, INTERVALLE_MS);
}
