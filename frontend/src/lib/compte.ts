/**
 * Le compte chiffré, vu de l'interface — logique pure, sans React.
 *
 * Conception : docs/development/compte-chiffre.md §2.7, §3.8, §3.11, §4.11.
 *
 * Le bundle ne voit JAMAIS une clé : le serveur Python local fait toute la
 * cryptographie et parle seul au serveur de comptes. La seule exception est
 * la clé de récupération, montrée une fois pour qu'on la note — d'où les
 * fonctions de format et d'extrait ci-dessous, qui ne dérivent rien.
 *
 * Tout ce qui décide d'un texte ou d'une étape vit ici et se teste en
 * vitest (compte.test.ts) : ce dépôt n'a aucun test de composant React.
 */

import type { MessageKey, Vars } from '../i18n/translate';
import type { Locale } from '../i18n/locale';

// ---------------------------------------------------------------------------
// Le statut rendu par GET /v1/account/status (§3.8)
// ---------------------------------------------------------------------------

export const ETATS_COMPTE = [
  'none',
  'signupInProgress',
  'locked',
  'unlocked',
  'sessionExpired',
  'resetPending',
  'accountReset',
  // Le serveur local ne l'émet plus (service.py, 24/09/2026) : un compte
  // supprimé ailleurs se lit `sessionExpired`. Gardé ici parce que le §4.11
  // le nomme ; un état inconnu, lui, rendrait le statut illisible.
  'accountDeleted',
  'serverRolledBack',
  'serverLost',
] as const;
export type EtatCompte = (typeof ETATS_COMPTE)[number];

export const ETATS_SYNCHRO = [
  'disabled',
  'paused',
  'needsConsent',
  'syncing',
  'upToDate',
  'pending',
  'offline',
  'quarantined',
  'repaired',
  'quotaExceeded',
  'serverFull',
  'sessionExpired',
  'resetPending',
  'accountReset',
  'accountDeleted',
  'serverRolledBack',
  'serverLost',
] as const;
export type EtatSynchro = (typeof ETATS_SYNCHRO)[number];

export type Protecteur = 'keychain' | 'dpapi' | 'file' | 'memory';

export interface StatutSynchro {
  state: EtatSynchro;
  serverSeq: number | null;
  lastConfirmedAt: number | null;
  pendingCount: number | null;
  quarantinedCount: number | null;
  repairedCount: number | null;
  errorCode: string | null;
}

export interface StatutCompte {
  state: EtatCompte;
  unlocked: boolean;
  email: string | null;
  remembered: boolean;
  protector: Protecteur;
  rememberAllowed: boolean;
  rememberRefusal: string | null;
  recoveryConfigured: boolean;
  backupMeans: { recoveryKey: boolean; rememberedDevices: number | null };
  onboarding: 'pending' | 'done';
  localConversations: number | null;
  sync: StatutSynchro;
  clockSkewMs: number | null;
  pendingResetAt: number | null;
  serverOrigin: string | null;
  serverOriginAllowed: boolean;
  /** Faux tant que les comptes ne sont pas ouverts (service.COMPTES_OUVERTS,
   *  24/09/2026) : ni écran d'accueil, ni inscription, ni connexion. */
  accountsOpen: boolean;
  lastKeyChangeAt: number | null;
}

const estObjet = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v);

/** Un nombre fini, ou null. `undefined` (champ absent) n'est PAS null. */
function nombreOuNull(v: unknown): number | null | undefined {
  if (v === null) return null;
  if (typeof v === 'number' && Number.isFinite(v)) return v;
  return undefined;
}

function texteOuNull(v: unknown): string | null | undefined {
  if (v === null) return null;
  if (typeof v === 'string') return v;
  return undefined;
}

/**
 * Lecture STRICTE du statut. Un champ absent ou mal typé rend `null` — la
 * vue dit alors « état du compte illisible » au lieu d'inventer.
 *
 * 24/09/2026 : les champs sur le fil sont en camelCase ; un champ renommé
 * en snake_case côté Python se serait lu `undefined`, en silence, et
 * `backupMeans.recoveryKey` absent aurait compté zéro moyen de secours chez
 * quelqu'un qui en a un. Refuser tout le statut est la seule lecture honnête.
 */
export function lireStatut(brut: unknown): StatutCompte | null {
  if (!estObjet(brut)) return null;
  const state = brut.state;
  if (typeof state !== 'string' || !(ETATS_COMPTE as readonly string[]).includes(state)) return null;
  const booleens = ['unlocked', 'remembered', 'rememberAllowed', 'recoveryConfigured'] as const;
  for (const b of booleens) if (typeof brut[b] !== 'boolean') return null;
  const protector = brut.protector;
  if (protector !== 'keychain' && protector !== 'dpapi' && protector !== 'file' && protector !== 'memory') return null;
  const onboarding = brut.onboarding;
  if (onboarding !== 'pending' && onboarding !== 'done') return null;
  const moyens = brut.backupMeans;
  if (!estObjet(moyens) || typeof moyens.recoveryKey !== 'boolean') return null;
  const appareils = nombreOuNull(moyens.rememberedDevices);
  if (appareils === undefined) return null;
  const sync = brut.sync;
  if (!estObjet(sync)) return null;
  const etatSynchro = sync.state;
  if (typeof etatSynchro !== 'string' || !(ETATS_SYNCHRO as readonly string[]).includes(etatSynchro)) return null;
  const nombresSynchro = ['serverSeq', 'lastConfirmedAt', 'pendingCount', 'quarantinedCount', 'repairedCount'] as const;
  const lusSynchro: Record<string, number | null> = {};
  for (const n of nombresSynchro) {
    const v = nombreOuNull(sync[n]);
    if (v === undefined) return null;
    lusSynchro[n] = v;
  }
  const errorCode = texteOuNull(sync.errorCode);
  if (errorCode === undefined) return null;
  const email = texteOuNull(brut.email);
  const refus = texteOuNull(brut.rememberRefusal);
  const conversations = nombreOuNull(brut.localConversations);
  const decalage = nombreOuNull(brut.clockSkewMs);
  const attente = nombreOuNull(brut.pendingResetAt);
  const origine = texteOuNull(brut.serverOrigin);
  const changement = nombreOuNull(brut.lastKeyChangeAt);
  // Exigé comme tout autre champ : un serveur local plus ancien que l'app
  // rend un statut illisible (« Réessayer ») jusqu'à son redémarrage, et
  // l'écran d'accueil ne s'affiche pas sur un statut illisible. Le lire
  // absent comme « fermé » aurait été sûr ici, mais aurait fait exception à
  // la règle qui rend visible un champ renommé.
  const ouverts = brut.accountsOpen;
  if (typeof ouverts !== 'boolean') return null;
  if (
    email === undefined ||
    refus === undefined ||
    conversations === undefined ||
    decalage === undefined ||
    attente === undefined ||
    origine === undefined ||
    changement === undefined ||
    typeof brut.serverOriginAllowed !== 'boolean'
  ) {
    return null;
  }
  return {
    state: state as EtatCompte,
    unlocked: brut.unlocked as boolean,
    email,
    remembered: brut.remembered as boolean,
    protector,
    rememberAllowed: brut.rememberAllowed as boolean,
    rememberRefusal: refus,
    recoveryConfigured: brut.recoveryConfigured as boolean,
    backupMeans: { recoveryKey: moyens.recoveryKey, rememberedDevices: appareils },
    onboarding,
    localConversations: conversations,
    sync: {
      state: etatSynchro as EtatSynchro,
      serverSeq: lusSynchro.serverSeq,
      lastConfirmedAt: lusSynchro.lastConfirmedAt,
      pendingCount: lusSynchro.pendingCount,
      quarantinedCount: lusSynchro.quarantinedCount,
      repairedCount: lusSynchro.repairedCount,
      errorCode,
    },
    clockSkewMs: decalage,
    pendingResetAt: attente,
    serverOrigin: origine,
    serverOriginAllowed: brut.serverOriginAllowed as boolean,
    lastKeyChangeAt: changement,
    accountsOpen: ouverts,
  };
}

/** Un compte est-il enregistré sur cet appareil (quel que soit son état) ? */
export function aUnCompte(statut: StatutCompte | null): boolean {
  return !!statut && statut.state !== 'none' && statut.state !== 'signupInProgress';
}

/**
 * `local_only` refuse l'origine configurée : tout geste qui joindrait le
 * serveur de comptes est grisé AVANT d'être fait (§3.12, condition 2).
 *
 * 24/09/2026 : seuls l'accueil et la connexion le lisaient. L'adresse
 * (ouverte directement par « Créer un compte » des Réglages), la
 * récupération et la réinitialisation laissaient partir la demande, que le
 * serveur local refusait ensuite (`localOnly`) — après le geste.
 */
export function destinationBloquee(statut: StatutCompte): boolean {
  return !!statut.serverOrigin && !statut.serverOriginAllowed;
}

export type LectureAffichee = 'chargement' | 'erreur' | 'perime' | 'frais';

/**
 * Ce que la vue peut affirmer du statut qu'elle tient.
 *
 * 24/09/2026 : `useStatutCompte` garde le dernier statut quand le serveur
 * local ne répond plus — c'est voulu, un redémarrage ne doit pas faire
 * croire qu'il n'y a plus de compte. Mais la section des Réglages l'affichait
 * alors comme frais : « Déverrouillé », pastille verte, serveur arrêté.
 * `perime` impose de le dire (`compte.statutPerime`).
 */
export function lectureAffichee(statut: StatutCompte | null, lu: boolean, erreur: unknown): LectureAffichee {
  if (!statut) return lu ? 'erreur' : 'chargement';
  return erreur ? 'perime' : 'frais';
}

// ---------------------------------------------------------------------------
// Adresse et mot de passe (§2.4, D5)
// ---------------------------------------------------------------------------

export const MOT_DE_PASSE_MIN = 12;
export const MOT_DE_PASSE_MAX = 1024;

/** Le même `NFKC`, `strip`, `lower` que `cles.normaliser_courriel`. */
export function normaliserCourriel(courriel: string): string {
  return courriel.normalize('NFKC').trim().toLowerCase();
}

/** 3 à 254 caractères, un seul @, aucun espace (§2.4). Le serveur local
 * juge en dernier ; ceci évite seulement un aller-retour pour une faute
 * visible. */
export function courrielValide(courriel: string): boolean {
  const e = normaliserCourriel(courriel);
  const longueur = [...e].length;
  if (longueur < 3 || longueur > 254) return false;
  if (e.split('@').length !== 2) return false;
  return !/\s/u.test(e);
}

export type BlocageAdresse = 'adresse' | 'conditions' | null;

/**
 * Pourquoi l'envoi de l'adresse n'a pas lieu — dit, jamais muet.
 *
 * 24/09/2026 : le bouton était grisé tant que la case des conditions
 * n'était pas cochée. Or un bouton d'envoi grisé annule l'envoi implicite
 * d'un formulaire : Entrée dans le champ ne faisait rien, et dans WKWebView
 * avec les réglages macOS par défaut, Tab ne visite ni cases ni boutons — on
 * ne pouvait pas finir l'inscription sans souris, sans qu'aucun mot le dise
 * (§82).
 */
export function blocageAdresse(courriel: string, conditions: boolean): BlocageAdresse {
  if (!courrielValide(courriel)) return 'adresse';
  if (!conditions) return 'conditions';
  return null;
}

export type DefautMotDePasse = 'tropCourt' | 'tropLong' | 'contientAdresse' | 'differents';

export interface JugementMotDePasse {
  /** Caractères comptés comme Python les compte : points de code, après NFKC. */
  longueur: number;
  defauts: DefautMotDePasse[];
  valide: boolean;
}

/**
 * Les règles D5, dans l'ordre où `cles.verifier_mot_de_passe` les applique :
 * 12 à 1 024 caractères après NFKC (sans `strip`), et pas la partie locale
 * de l'adresse.
 *
 * 24/09/2026 : compter `motDePasse.length` aurait compté des unités UTF-16
 * — un émoji vaut 2 — et laissé passer ici un mot de passe que le serveur
 * refuse ensuite, après 0,5 s d'Argon2id et un écran de plus.
 */
export function reglesMotDePasse(
  motDePasse: string,
  courriel: string | null,
  confirmation?: string,
): JugementMotDePasse {
  const p = motDePasse.normalize('NFKC');
  const longueur = [...p].length;
  const defauts: DefautMotDePasse[] = [];
  if (longueur < MOT_DE_PASSE_MIN) defauts.push('tropCourt');
  if (longueur > MOT_DE_PASSE_MAX) defauts.push('tropLong');
  if (courriel) {
    const e = normaliserCourriel(courriel);
    const morceaux = e.split('@');
    const partieLocale = morceaux.length === 2 ? morceaux[0] : '';
    // Une partie locale vide est « contenue » dans toute chaîne : sans ce
    // test, tout mot de passe serait refusé (même garde qu'en Python).
    if (partieLocale && p.toLowerCase().includes(partieLocale)) defauts.push('contientAdresse');
  }
  if (confirmation !== undefined && confirmation !== motDePasse) defauts.push('differents');
  return { longueur, defauts, valide: defauts.length === 0 };
}

// ---------------------------------------------------------------------------
// La clé de récupération (§2.7)
// ---------------------------------------------------------------------------

export const ALPHABET_CROCKFORD = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';
export const CLE_LONGUEUR = 32;
export const CLE_GROUPES = 8;
export const CLE_TAILLE_GROUPE = 4;

/**
 * La saisie tolérante de `recuperation.lire_cle_recuperation` : NFKC,
 * majuscules, O lu 0, I et L lus 1, tirets et espaces ignorés. Le U n'est
 * pas pardonné — il n'est pas dans l'alphabet.
 */
export function normaliserSaisieCle(saisie: string): string {
  return saisie
    .normalize('NFKC')
    .toUpperCase()
    .replace(/O/g, '0')
    .replace(/[IL]/g, '1')
    .replace(/[-\s]/gu, '');
}

export type FormeCle = 'vide' | 'incomplete' | 'caractereInconnu' | 'tropLongue' | 'complete';

/**
 * La forme de ce qui est tapé. `complete` ne dit PAS que la clé est juste :
 * les 4 octets de contrôle (SHA-256) se vérifient dans le serveur local,
 * avant tout appel réseau (§2.7) — c'est lui qui répond `recoveryKeyInvalid`.
 */
export function formeCle(saisie: string): FormeCle {
  const n = normaliserSaisieCle(saisie);
  if (!n) return 'vide';
  for (const c of n) if (!ALPHABET_CROCKFORD.includes(c)) return 'caractereInconnu';
  if (n.length < CLE_LONGUEUR) return 'incomplete';
  if (n.length > CLE_LONGUEUR) return 'tropLongue';
  return 'complete';
}

/** « XXXX-XXXX-… » pendant la frappe, pour qu'on voie où l'on en est. */
export function mettreEnGroupes(saisie: string): string {
  const n = normaliserSaisieCle(saisie);
  const groupes: string[] = [];
  for (let i = 0; i < n.length; i += CLE_TAILLE_GROUPE) groupes.push(n.slice(i, i + CLE_TAILLE_GROUPE));
  return groupes.join('-');
}

/** Les huit groupes d'une clé telle que le serveur local la rend. */
export function groupesDeLaCle(cle: string): string[] {
  const n = normaliserSaisieCle(cle);
  if (n.length !== CLE_LONGUEUR) return [];
  const groupes: string[] = [];
  for (let i = 0; i < CLE_LONGUEUR; i += CLE_TAILLE_GROUPE) groupes.push(n.slice(i, i + CLE_TAILLE_GROUPE));
  return groupes;
}

/**
 * Les numéros de groupe à ressaisir (`confirmGroups`), validés : deux
 * numéros distincts entre 1 et 8. Le serveur les tire au hasard ; l'interface
 * ne les choisit jamais — sinon la preuve deviendrait toujours « 1 et 2 ».
 */
export function lireGroupesDemandes(brut: unknown): [number, number] | null {
  if (!Array.isArray(brut) || brut.length !== 2) return null;
  const [a, b] = brut;
  const valide = (n: unknown) => Number.isInteger(n) && (n as number) >= 1 && (n as number) <= CLE_GROUPES;
  if (!valide(a) || !valide(b) || a === b) return null;
  return [a as number, b as number];
}

/** Ce que la personne doit recopier, dans l'ordre de `confirmGroups`. */
export function extraitAttendu(cle: string, groupes: [number, number]): [string, string] | null {
  const tous = groupesDeLaCle(cle);
  if (tous.length !== CLE_GROUPES) return null;
  return [tous[groupes[0] - 1], tous[groupes[1] - 1]];
}

/**
 * Preuve de sauvegarde (§2.7) : les deux groupes ressaisis correspondent-ils ?
 * Vérifiée ICI d'abord pour dire « le groupe 3 ne correspond pas » sans
 * aller-retour ; le serveur local la revérifie (`recoveryExcerptMismatch`).
 */
export function extraitConcorde(cle: string, groupes: [number, number], saisies: [string, string]): boolean {
  const attendu = extraitAttendu(cle, groupes);
  if (!attendu) return false;
  return normaliserSaisieCle(saisies[0]) === attendu[0] && normaliserSaisieCle(saisies[1]) === attendu[1];
}

// ---------------------------------------------------------------------------
// Moyens de secours (§3.11, D4)
// ---------------------------------------------------------------------------

export interface MoyensDeSecours {
  /** La clé de récupération confirmée au serveur. */
  cle: boolean;
  /** CET appareil garde la clé du compte (« Garder cet appareil déverrouillé »). */
  cetAppareil: boolean;
  total: number;
  /** Zéro moyen : l'avertissement reste affiché (D4). */
  avertir: boolean;
}

/**
 * Les moyens RÉELS de choisir un nouveau mot de passe après un oubli.
 *
 * Seul CET appareil est compté : le serveur ignore quels appareils gardent
 * la clé (§2.9), et un autre appareil « connecté » mais verrouillé ne sauve
 * rien (encadré de l'étape 3, texte corrigé). Compter ce qu'on ne sait pas
 * aurait affiché un secours qui n'existe peut-être pas (§100).
 *
 * `null` sans compte : il n'y a rien à secourir.
 *
 * 24/09/2026 : un `rememberedDevices` à `null` chez un compte rendait `null`
 * — donc AUCUN avertissement, alors que D4 veut qu'il reste. Ne pas savoir
 * si cet appareil garde la clé, c'est ne pas pouvoir compter dessus : il
 * vaut zéro, et l'on avertit.
 */
export function moyensDeSecours(statut: StatutCompte | null): MoyensDeSecours | null {
  if (!aUnCompte(statut) || !statut) return null;
  const appareils = statut.backupMeans.rememberedDevices ?? 0;
  const cle = statut.backupMeans.recoveryKey;
  const cetAppareil = appareils > 0;
  const total = (cle ? 1 : 0) + (cetAppareil ? 1 : 0);
  return { cle, cetAppareil, total, avertir: total === 0 };
}

/**
 * Le conseil de l'avertissement « 0 moyen de secours ».
 *
 * 24/09/2026 : il conseillait de cocher « Garder cet appareil
 * déverrouillé » même là où la case est grisée (Linux, Windows sans mot de
 * passe, protecteur en mémoire) — un conseil qu'on ne peut pas suivre (§34).
 */
export function texteAucunSecours(statut: StatutCompte): MessageKey {
  return statut.rememberAllowed ? 'compte.secours.aucun' : 'compte.secours.aucunSansCase';
}

// ---------------------------------------------------------------------------
// Heures et jours
// ---------------------------------------------------------------------------

/** « 14 h 02 » en français, « 2:02 PM » en anglais — l'heure de l'appareil. */
export function formaterHeure(ms: number, locale: Locale): string {
  const d = new Date(ms);
  const minutes = String(d.getMinutes()).padStart(2, '0');
  if (locale === 'fr') return `${d.getHours()} h ${minutes}`;
  // Écrit à la main : `toLocaleTimeString('en-US')` met, selon la version
  // d'ICU, une espace fine insécable (U+202F) avant « PM » — la même heure
  // ne s'écrivait pas pareil dans la fenêtre et dans le banc de test.
  const h = d.getHours();
  return `${h % 12 === 0 ? 12 : h % 12}:${minutes} ${h < 12 ? 'AM' : 'PM'}`;
}

/** L'heure seule le jour même, sinon la date et l'heure. */
export function formaterMoment(ms: number, maintenant: number, locale: Locale): string {
  const d = new Date(ms);
  const m = new Date(maintenant);
  const memeJour =
    d.getFullYear() === m.getFullYear() && d.getMonth() === m.getMonth() && d.getDate() === m.getDate();
  if (memeJour) return formaterHeure(ms, locale);
  const options: Intl.DateTimeFormatOptions = { day: 'numeric', month: 'long' };
  if (d.getFullYear() !== m.getFullYear()) options.year = 'numeric';
  const date = d.toLocaleDateString(locale === 'fr' ? 'fr-CA' : 'en-US', options);
  return `${date}, ${formaterHeure(ms, locale)}`;
}

/** Une date seule (réinitialisation prévue, dernier changement de clé). */
export function formaterDate(ms: number, locale: Locale): string {
  return new Date(ms).toLocaleDateString(locale === 'fr' ? 'fr-CA' : 'en-US', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  });
}

/**
 * `createdDay` et `lastSeenDay` du serveur de comptes : un numéro de jour
 * UTC (ms // 86 400 000). Le serveur ne garde aucune heure par session
 * (§3.3) ; afficher une heure serait l'inventer.
 */
export function formaterJour(jour: number, locale: Locale): string {
  return new Date(jour * 86_400_000).toLocaleDateString(locale === 'fr' ? 'fr-CA' : 'en-US', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    timeZone: 'UTC',
  });
}

// ---------------------------------------------------------------------------
// Le libellé de synchronisation (§4.11, §100)
// ---------------------------------------------------------------------------

export type Ton = 'ok' | 'neutre' | 'attente' | 'alerte';

export interface Libelle {
  cle: MessageKey;
  vars?: Vars;
  ton: Ton;
}

/**
 * LA SEULE fonction qui a le droit d'écrire « Synchronisé à 14 h 02 » (§4.11).
 *
 * Et seulement quand les trois preuves y sont : un `serverSeq` rendu par le
 * serveur, une date de confirmation, une file sortante VIDE (`pendingCount`
 * à 0, pas `null`). Il en manque une → « état inconnu », jamais « à jour ».
 * Le 24/09/2026, l'étape 8 rend tous ces nombres à `null` (aucun moteur de
 * synchronisation) : un 0 supposé ici aurait affiché « Synchronisé » chez
 * quelqu'un dont rien n'est jamais parti.
 */
export function libelleSynchro(sync: StatutSynchro, maintenant: number, locale: Locale = 'fr'): Libelle {
  const moment = (ms: number) => formaterMoment(ms, maintenant, locale);
  switch (sync.state) {
    case 'upToDate':
      if (sync.serverSeq !== null && sync.lastConfirmedAt !== null && sync.pendingCount === 0) {
        return {
          cle: 'compte.synchro.aJour',
          vars: { moment: moment(sync.lastConfirmedAt), seq: sync.serverSeq },
          ton: 'ok',
        };
      }
      return { cle: 'compte.synchro.inconnu', ton: 'attente' };
    case 'pending':
      if (sync.pendingCount !== null && sync.pendingCount > 0) {
        return { cle: 'compte.synchro.enAttente', vars: { count: sync.pendingCount }, ton: 'attente' };
      }
      return { cle: 'compte.synchro.inconnu', ton: 'attente' };
    case 'offline':
      if (sync.pendingCount !== null && sync.lastConfirmedAt !== null) {
        return {
          cle: 'compte.synchro.horsLigneDepuis',
          vars: { moment: moment(sync.lastConfirmedAt), count: sync.pendingCount },
          ton: 'attente',
        };
      }
      return { cle: 'compte.synchro.horsLigne', ton: 'attente' };
    case 'syncing':
      return { cle: 'compte.synchro.enCours', ton: 'attente' };
    case 'disabled':
    // 24/09/2026 : « En pause tant que cet appareil est verrouillé »
    // promettait une reprise qu'aucun moteur ne fera avant l'étape 10 — et le
    // service rend `paused` pour TOUT compte verrouillé. Même vérité que
    // `disabled` tant que rien ne part ; l'étape 10 les séparera.
    case 'paused':
      return { cle: 'compte.synchro.inactive', ton: 'neutre' };
    case 'needsConsent':
      return { cle: 'compte.synchro.accord', ton: 'attente' };
    case 'quarantined':
      if (sync.quarantinedCount !== null && sync.quarantinedCount > 0) {
        return { cle: 'compte.synchro.quarantaine', vars: { count: sync.quarantinedCount }, ton: 'alerte' };
      }
      return { cle: 'compte.synchro.inconnu', ton: 'alerte' };
    case 'repaired':
      if (sync.repairedCount !== null && sync.repairedCount > 0) {
        return { cle: 'compte.synchro.repare', vars: { count: sync.repairedCount }, ton: 'attente' };
      }
      return { cle: 'compte.synchro.inconnu', ton: 'attente' };
    case 'quotaExceeded':
      return { cle: 'compte.synchro.quota', ton: 'alerte' };
    case 'serverFull':
      return { cle: 'compte.synchro.serveurPlein', ton: 'alerte' };
    case 'sessionExpired':
      return { cle: 'compte.synchro.sessionExpiree', ton: 'alerte' };
    case 'resetPending':
      return { cle: 'compte.synchro.reinitPrevue', ton: 'alerte' };
    case 'accountReset':
      return { cle: 'compte.synchro.compteReinitialise', ton: 'alerte' };
    case 'accountDeleted':
      return { cle: 'compte.synchro.compteSupprime', ton: 'alerte' };
    case 'serverRolledBack':
      return { cle: 'compte.synchro.retourArriere', ton: 'alerte' };
    case 'serverLost':
      return { cle: 'compte.synchro.serveurPerdu', ton: 'alerte' };
    default:
      return { cle: 'compte.synchro.inconnu', ton: 'attente' };
  }
}

// ---------------------------------------------------------------------------
// Les messages d'erreur, par code (§3.8)
// ---------------------------------------------------------------------------

export interface ErreurLue {
  code: string;
  champ?: string;
  raison?: string;
  attenteS?: number;
}

const MESSAGES_PAR_CODE: Record<string, MessageKey> = {
  accountLocked: 'compte.erreur.accountLocked',
  invalidPassword: 'compte.erreur.invalidPassword',
  invalidCredentials: 'compte.erreur.invalidCredentials',
  invalidProof: 'compte.erreur.invalidPassword',
  recoveryExcerptMismatch: 'compte.erreur.recoveryExcerptMismatch',
  invalidCode: 'compte.erreur.invalidCode',
  invalidToken: 'compte.erreur.invalidToken',
  emailInvalid: 'compte.erreur.emailInvalid',
  passwordRejected: 'compte.erreur.passwordRejected',
  passwordTooShort: 'compte.erreur.passwordTooShort',
  passwordTooLong: 'compte.erreur.passwordTooLong',
  passwordContainsEmail: 'compte.erreur.passwordContainsEmail',
  recoveryKeyInvalid: 'compte.erreur.recoveryKeyInvalid',
  mailUnavailable: 'compte.erreur.mailUnavailable',
  signupClosed: 'compte.erreur.signupClosed',
  accountsNotOpen: 'compte.erreur.accountsNotOpen',
  serverUnreachable: 'compte.erreur.serverUnreachable',
  serverBusy: 'compte.erreur.serverBusy',
  serverFull: 'compte.erreur.serverFull',
  quotaExceeded: 'compte.erreur.quotaExceeded',
  serverError: 'compte.erreur.serverError',
  serverRejected: 'compte.erreur.serverRejected',
  sessionExpired: 'compte.erreur.sessionExpired',
  localOnly: 'compte.erreur.localOnly',
  notConnected: 'compte.erreur.notConnected',
  alreadyConnected: 'compte.erreur.alreadyConnected',
  alreadyUnlocked: 'compte.erreur.alreadyUnlocked',
  noPendingSignup: 'compte.erreur.noPendingSignup',
  noPendingRecoveryKey: 'compte.erreur.noPendingRecoveryKey',
  currentDevice: 'compte.erreur.currentDevice',
  rememberNotAllowed: 'compte.erreur.rememberNotAllowed',
  resetNeedsKnownAccount: 'compte.erreur.resetNeedsKnownAccount',
  resetNotDue: 'compte.erreur.resetNotDue',
  syncUnavailable: 'compte.erreur.syncUnavailable',
  kdfDowngrade: 'compte.erreur.kdfDowngrade',
  serverKeyStale: 'compte.erreur.serverKeyStale',
  serverKeyInvalid: 'compte.erreur.serverKeyInvalid',
  serverRolledBack: 'compte.erreur.serverRolledBack',
  envelopeUnreadable: 'compte.erreur.envelopeUnreadable',
  keychainUnavailable: 'compte.erreur.protectorUnavailable',
  keychainCorrupt: 'compte.erreur.protectorUnavailable',
  protectedFileUnavailable: 'compte.erreur.protectorUnavailable',
  protectorUnavailable: 'compte.erreur.protectorUnavailable',
  // 24/09/2026 : émis par gardien.py (Windows, fichier protégé, chemin
  // refusé) mais absents d'ici, ils s'affichaient « Refus inattendu » alors
  // que leurs voisins macOS étaient traduits.
  dpapiUnavailable: 'compte.erreur.protectorUnavailable',
  protectedFileCorrupt: 'compte.erreur.protectorUnavailable',
  unsafePath: 'compte.erreur.protectorUnavailable',
  keyringInvalid: 'compte.erreur.serverKeyInvalid',
  keyEpochUnknown: 'compte.erreur.serverKeyInvalid',
  objectPermuted: 'compte.erreur.donneesIllisibles',
  plaintextInvalid: 'compte.erreur.donneesIllisibles',
  unknownVersion: 'compte.erreur.donneesIllisibles',
  plaintextRefused: 'compte.erreur.defautInterne',
  accountError: 'compte.erreur.defautInterne',
  accountIdInvalid: 'compte.erreur.defautInterne',
  elementInvalid: 'compte.erreur.defautInterne',
  secretInvalid: 'compte.erreur.defautInterne',
  serviceInvalid: 'compte.erreur.defautInterne',
  // Relayés tels quels depuis le serveur de comptes (transport._erreur_de).
  sessionRevoked: 'compte.erreur.sessionExpired',
  notFound: 'compte.erreur.serveurIncompatible',
  methodNotAllowed: 'compte.erreur.serveurIncompatible',
  invalidEnvelope: 'compte.erreur.serverRejected',
  payloadTooLarge: 'compte.erreur.payloadTooLarge',
  objectTooLarge: 'compte.erreur.payloadTooLarge',
  pieceUnreadable: 'compte.erreur.pieceUnreadable',
  internal: 'compte.erreur.serverError',
  serverBehind: 'compte.erreur.vaultConflict',
  keyEpochChanged: 'compte.erreur.vaultConflict',
  reclaimed: 'compte.erreur.vaultConflict',
  incarnationChanged: 'compte.erreur.compteReinitialise',
  backupExclusionFailed: 'compte.erreur.backupExclusionFailed',
  accountExists: 'compte.erreur.accountExists',
  termsOutdated: 'compte.erreur.termsOutdated',
  vaultConflict: 'compte.erreur.vaultConflict',
  localServerUnreachable: 'compte.erreur.localServerUnreachable',
  localUnauthorized: 'compte.erreur.localUnauthorized',
  accountRoutesMissing: 'compte.erreur.accountRoutesMissing',
  responseUnreadable: 'compte.erreur.responseUnreadable',
};

/**
 * La phrase d'un refus. Le code seul la choisit — le serveur local ne rend
 * jamais de message (il pourrait citer un chemin ou une valeur), et
 * l'interface n'en invente pas : un code inconnu est NOMMÉ, pas maquillé en
 * « une erreur est survenue ».
 */
export function messageErreur(erreur: ErreurLue): { cle: MessageKey; vars?: Vars } {
  if (erreur.code === 'tooManyAttempts') {
    if (erreur.attenteS && erreur.attenteS > 0) {
      return { cle: 'compte.erreur.tooManyAttemptsDelai', vars: { secondes: erreur.attenteS } };
    }
    return { cle: 'compte.erreur.tooManyAttempts' };
  }
  if (erreur.code === 'invalidCredentials' && erreur.raison === 'changedElsewhere') {
    // 24/09/2026 (service.py) : après une révocation, « mot de passe
    // incorrect » laissait croire à une faute de frappe alors que le mot de
    // passe a pu changer — ou le compte disparaître — ailleurs.
    return { cle: 'compte.erreur.changedElsewhere' };
  }
  if (erreur.code === 'resetNeedsKnownAccount' && erreur.raison === 'incarnationUnconfirmed') {
    return { cle: 'compte.erreur.resetIncarnationUnconfirmed' };
  }
  if (erreur.code === 'invalidRequest') {
    return erreur.champ
      ? { cle: 'compte.erreur.invalidRequestChamp', vars: { champ: erreur.champ } }
      : { cle: 'compte.erreur.invalidRequest' };
  }
  if (erreur.code === 'rememberNotAllowed' && erreur.raison) {
    const motif = MOTIFS_REFUS_MEMORISATION[erreur.raison];
    if (motif) return { cle: motif };
  }
  const cle = MESSAGES_PAR_CODE[erreur.code];
  if (cle === 'compte.erreur.defautInterne') return { cle, vars: { code: erreur.code } };
  if (cle) return { cle };
  return { cle: 'compte.erreur.inconnue', vars: { code: erreur.code } };
}

/** Pourquoi « Garder cet appareil déverrouillé » est grisé (`rememberRefusal`). */
export const MOTIFS_REFUS_MEMORISATION: Record<string, MessageKey> = {
  noPersistentProtector: 'compte.memoriser.refus.aucunProtecteur',
  windowsAccountWithoutPassword: 'compte.memoriser.refus.windowsSansMotDePasse',
  windowsPasswordUndetermined: 'compte.memoriser.refus.windowsIndetermine',
  notOnThisPlatform: 'compte.memoriser.refus.plateforme',
  backupExclusionFailed: 'compte.memoriser.refus.sauvegarde',
};

export function motifRefusMemorisation(refus: string | null): MessageKey | null {
  if (!refus) return null;
  return MOTIFS_REFUS_MEMORISATION[refus] ?? 'compte.memoriser.refus.aucunProtecteur';
}

/** Ce que la mémorisation protège vraiment (§2.11), selon le protecteur. */
export function texteMemorisation(protecteur: Protecteur): MessageKey {
  if (protecteur === 'keychain') return 'compte.memoriser.aide.trousseau';
  if (protecteur === 'dpapi') return 'compte.memoriser.aide.windows';
  if (protecteur === 'file') return 'compte.memoriser.aide.fichier';
  return 'compte.memoriser.aide.memoire';
}

// ---------------------------------------------------------------------------
// L'écran d'activation : quelle étape montrer (§3.11)
// ---------------------------------------------------------------------------

/** Le chemin que la personne a choisi, gardé par la vue (pas par le serveur). */
export type Parcours = 'accueil' | 'inscription' | 'connexion' | 'oubli' | 'recuperation' | 'reinitialisation';

export type SousEtapeInscription = 'adresse' | 'code' | 'motDePasse';

export interface CleMontree {
  cle: string;
  groupes: [number, number];
  /** `inscription` : `/signup/complete` ; `remplacement` : `/recovery-key/confirm`. */
  origine: 'inscription' | 'remplacement';
}

export interface EtatVue {
  parcours: Parcours;
  inscription?: SousEtapeInscription;
  /** Une clé de récupération à l'écran, qui attend sa preuve de sauvegarde. */
  cle?: CleMontree | null;
  /** « Ce qui se synchronise » a été lu (étape 5). */
  synchroVue?: boolean;
}

export type EtapeActivation =
  | 'chargement'
  | 'illisible'
  | 'accueil'
  | 'adresse'
  | 'code'
  | 'motDePasse'
  | 'cle'
  | 'nouvelleCle'
  | 'consentement'
  | 'synchro'
  | 'termine'
  | 'connexion'
  | 'deverrouillage'
  | 'oubli'
  | 'recuperation'
  | 'reinitialisation'
  | 'reinitPrevue'
  | 'compteReinitialise'
  | 'retourArriere'
  | 'serveurPerdu'
  | 'fermee';

const PARCOURS_DE_SECOURS: Parcours[] = ['oubli', 'recuperation', 'reinitialisation'];

/**
 * L'étape de l'écran d'activation, déduite du statut du SERVEUR LOCAL et du
 * chemin choisi dans la vue. Le serveur fait foi sur l'état du compte : un
 * `sessionExpired` posé pendant que l'écran était ouvert l'emporte sur ce
 * que la vue croyait.
 *
 * P2 (code interrompu) : rien n'existe sur le VPS avant `signup/complete`,
 * et la vue perd sa sous-étape en se rechargeant ; `signupInProgress` sans
 * sous-étape reprend donc au code.
 */
export function etapeActivation(statut: StatutCompte | null | 'illisible', vue: EtatVue): EtapeActivation {
  if (statut === 'illisible') return 'illisible';
  if (!statut) return 'chargement';
  const etat = statut.state;
  // 24/09/2026 : les comptes ne sont pas encore ouverts. Sans compte sur cet
  // appareil, chaque parcours (inscription, connexion, récupération,
  // réinitialisation) contacterait un serveur qui n'existe pas : l'écran le
  // dit au lieu d'en ouvrir un qui échouerait au premier appel.
  if (!statut.accountsOpen && etat === 'none') return 'fermee';

  // Une clé montrée attend sa preuve : on ne quitte pas l'écran qui la
  // montre pour un autre — elle n'est gardée nulle part ailleurs.
  //
  // Sauf si le serveur local l'a oubliée. 24/09/2026 : `none` gardait
  // l'étape de la clé, alors qu'une inscription expirée (30 min) ou un
  // serveur local redémarré a effacé R — « C'est noté » comme « Continuer
  // sans clé » répondaient `noPendingSignup`, sans Retour ni croix, et
  // l'écran d'accueil plein écran bloquait toute l'app.
  if (vue.cle) {
    if (vue.cle.origine === 'inscription' && (etat === 'signupInProgress' || etat === 'serverLost')) {
      return 'cle';
    }
    if (vue.cle.origine === 'remplacement' && statut.unlocked) return 'nouvelleCle';
  }
  if (inscriptionExpiree(statut, vue)) return 'adresse';

  const sousEtapeInscription = (): EtapeActivation =>
    vue.inscription ?? (etat === 'signupInProgress' ? 'code' : 'adresse');

  const secours = (): EtapeActivation | null => {
    if (vue.parcours === 'oubli') return 'oubli';
    if (vue.parcours === 'recuperation') return 'recuperation';
    if (vue.parcours === 'reinitialisation') return 'reinitialisation';
    return null;
  };

  switch (etat) {
    case 'none':
      if (vue.parcours === 'inscription') return sousEtapeInscription();
      if (vue.parcours === 'connexion') return 'connexion';
      // Depuis un appareil qui n'a jamais ouvert ce compte, la
      // réinitialisation est refusée (`resetNeedsKnownAccount`) : l'écran
      // d'oubli le dit au lieu d'ouvrir un parcours qui échouerait au bout.
      if (vue.parcours === 'reinitialisation') return 'oubli';
      if (vue.parcours === 'oubli' || vue.parcours === 'recuperation') return vue.parcours;
      return 'accueil';
    case 'signupInProgress':
      if (vue.parcours === 'connexion') return 'connexion';
      if (vue.parcours === 'oubli' || vue.parcours === 'recuperation') return vue.parcours;
      if (vue.parcours === 'accueil') return 'accueil';
      return sousEtapeInscription();
    case 'locked':
      // 24/09/2026 : `connexion` était ignoré ici. Après un changement de
      // mot de passe fait sur un autre appareil (P4 chemin 2, P5), le
      // déverrouillage — hors ligne, contre l'enveloppe locale — refuse le
      // NOUVEAU mot de passe, et rien ne menait à `/login`, que le serveur
      // local accepte pourtant sur un appareil verrouillé (§34).
      if (vue.parcours === 'connexion') return 'connexion';
      return secours() ?? 'deverrouillage';
    case 'unlocked':
      if (statut.sync.state === 'needsConsent') return 'consentement';
      if (!vue.synchroVue) return 'synchro';
      return 'termine';
    case 'sessionExpired':
      return secours() ?? 'connexion';
    case 'resetPending':
      return 'reinitPrevue';
    case 'accountReset':
    case 'accountDeleted':
      return secours() ?? 'compteReinitialise';
    case 'serverRolledBack':
      if (vue.parcours === 'recuperation') return 'recuperation';
      return 'retourArriere';
    case 'serverLost':
      if (vue.parcours === 'inscription') return sousEtapeInscription();
      return 'serveurPerdu';
  }
  return PARCOURS_DE_SECOURS.includes(vue.parcours) ? 'oubli' : 'chargement';
}

/**
 * Le serveur local a oublié l'inscription que la vue croyait en cours.
 *
 * `none` alors que la vue est au code, au mot de passe ou à la clé
 * d'inscription : l'attente en mémoire a expiré (30 min, `DUREE_EN_ATTENTE_S`)
 * ou le serveur a redémarré. L'écran revient à l'adresse et le DIT, au lieu
 * de garder une étape dont chaque bouton répond `noPendingSignup`.
 */
export function inscriptionExpiree(statut: StatutCompte | null, vue: EtatVue): boolean {
  if (!statut || statut.state !== 'none') return false;
  if (vue.cle?.origine === 'inscription') return true;
  return vue.parcours === 'inscription' && (vue.inscription === 'code' || vue.inscription === 'motDePasse');
}

/**
 * L'écran d'accueil plein écran (D13) garde une sortie à chaque étape :
 * c'est une question posée une fois, jamais une porte (App.tsx).
 *
 * 24/09/2026 : seules l'étape d'accueil (« Plus tard ») et l'écran
 * « illisible » en avaient une ; au mot de passe, sans Retour ni croix ni
 * Échap, un `/signup/prepare` qui échouait enfermait l'app jusqu'au
 * redémarrage. Exceptions : une clé à l'écran, qui n'est gardée nulle part
 * ailleurs, et les étapes qui ont déjà leur propre bouton de sortie.
 */
export function sortieAccueil(etape: EtapeActivation): boolean {
  return !(['accueil', 'illisible', 'cle', 'nouvelleCle', 'termine'] as EtapeActivation[]).includes(etape);
}

export type ActionEchap = 'fermer' | 'plusTard' | null;

/**
 * Ce que fait Échap sur l'écran du compte.
 *
 * - une clé à l'écran ne se ferme pas d'une touche ;
 * - une autre fenêtre modale au-dessus (la confirmation) le consomme
 *   seule. 24/09/2026 : l'écouteur du voile, inscrit sur `window` AVANT
 *   celui de ConfirmModal, partait le premier — l'Échap qui voulait dire
 *   « Garder » fermait aussi le voile et perdait le code saisi ;
 * - en plein écran (D13), Échap vaut « Plus tard » : sans lui, l'écran
 *   d'accueil n'avait aucune sortie au clavier dans WKWebView, où Tab ne
 *   visite pas les boutons avec les réglages macOS par défaut (§82).
 */
export function actionEchap(args: {
  contexte: 'accueil' | 'reglages';
  cleAffichee: boolean;
  autreModale: boolean;
  dejaConsomme: boolean;
  etape: EtapeActivation;
}): ActionEchap {
  if (args.dejaConsomme || args.cleAffichee || args.autreModale) return null;
  if (args.contexte === 'reglages') return 'fermer';
  if (args.etape === 'termine') return null;
  return 'plusTard';
}

/**
 * L'indice du prochain élément focalisable quand Tab boucle dans la carte
 * (fenêtre modale : le clavier ne doit pas atterrir derrière elle).
 * `courant` vaut -1 quand le focus est hors de la carte.
 */
export function indiceFocusSuivant(n: number, courant: number, arriere: boolean): number {
  if (n <= 0) return -1;
  if (courant < 0) return arriere ? n - 1 : 0;
  return arriere ? (courant - 1 + n) % n : (courant + 1) % n;
}

export type ActionSection = 'resoudre' | 'consentir' | null;

const ETATS_ALERTE: readonly EtatCompte[] = ['sessionExpired', 'accountReset', 'accountDeleted', 'serverRolledBack', 'serverLost'];

/**
 * Le geste que la section des Réglages propose pour rouvrir l'écran du
 * compte.
 *
 * 24/09/2026 : `needsConsent` n'en avait aucun. Une fois le voile fermé
 * sans répondre, la section disait « En attente de votre accord… » sans
 * rien pour le donner — une question qu'on ne peut plus répondre (§34).
 */
export function actionSection(statut: StatutCompte): ActionSection {
  if (ETATS_ALERTE.includes(statut.state)) return 'resoudre';
  if (statut.state === 'unlocked' && statut.sync.state === 'needsConsent') return 'consentir';
  return null;
}

/** La pastille d'état de la section : rouge, orange, verte — ou grise quand le statut est périmé. */
export function estEtatAlerte(etat: EtatCompte): boolean {
  return ETATS_ALERTE.includes(etat);
}

/**
 * « Imprimer » la clé n'est proposé que là où l'impression a été vérifiée.
 *
 * 24/09/2026 : sous macOS, Tauri 2 remplace `window.print` par
 * `invoke('plugin:webview|print')`, qui exige `core:webview:allow-print` —
 * absent des capabilities de la fenêtre. L'appel était refusé en silence :
 * le bouton ne faisait rien. Sous Windows (WebView2), l'aperçu est
 * asynchrone et le retrait des règles d'impression, une seconde après,
 * aurait imprimé la fenêtre entière derrière la clé. Tant que ni l'un ni
 * l'autre n'est vérifié dans la vraie fenêtre, pas de bouton : Copier reste.
 *
 * 26/09/2026 : la WebView d'Android n'imprime pas — `window.print()` y est
 * un appel sans effet, sans erreur. Dans le téléphone, pas de bouton non plus.
 */
export function impressionDisponible(dansTauri: boolean, surTelephone = false): boolean {
  return !dansTauri && !surTelephone;
}

export type IconeEncadre = 'alerte' | 'ok' | null;

/**
 * L'icône d'un encadré ne dépend QUE de son ton.
 *
 * 24/09/2026 : elle n'était posée qu'avec un titre. Sur la peau ardéchine,
 * succès, avertissement et erreur valent tous l'encre (#14120e) : un
 * encadré danger sans titre ne se distinguait d'un encadré d'attente par
 * rien — la gravité doit survivre à une peau monochrome.
 */
export function iconeEncadre(ton: string): IconeEncadre {
  if (ton === 'danger' || ton === 'alerte') return 'alerte';
  if (ton === 'ok') return 'ok';
  return null;
}

/**
 * L'écran d'activation s'affiche une fois après l'installation (D13) :
 * dans la fenêtre de bureau, hors du mini-panneau, tant que le drapeau
 * `onboarding` du serveur local dit `pending`, et seulement pour quelqu'un
 * qui n'a pas de compte. Un statut illisible ne bloque JAMAIS l'app.
 */
export function doitAfficherAccueil(statut: StatutCompte | null, dansLaFenetre: boolean): boolean {
  if (!dansLaFenetre || !statut) return false;
  // Rien à accueillir tant que les comptes ne sont pas ouverts : l'écran
  // plein écran proposerait un compte qu'aucun serveur ne peut créer.
  if (!statut.accountsOpen) return false;
  if (statut.onboarding !== 'pending') return false;
  return statut.state === 'none' || statut.state === 'signupInProgress';
}

// ---------------------------------------------------------------------------
// Le bandeau (Layout, §3.11 « Place dans l'interface »)
// ---------------------------------------------------------------------------

export type ActionBandeau = 'deverrouiller' | 'reconnecter' | 'annulerReinit' | 'ouvrir';

export interface Bandeau extends Libelle {
  action: ActionBandeau;
}

/**
 * Ce que le bandeau dit, ou `null` quand il n'a rien à dire : sans compte,
 * pendant une inscription, et sur un appareil ouvert. Les six états du
 * §3.11 — `locked`, `sessionExpired`, `resetPending`, `accountReset`,
 * `serverRolledBack`, `serverLost` — et `accountDeleted`, que le §4.11 nomme.
 */
export function bandeauCompte(statut: StatutCompte | null, locale: Locale): Bandeau | null {
  if (!statut) return null;
  switch (statut.state) {
    case 'locked':
      return { cle: 'compte.bandeau.verrouille', ton: 'attente', action: 'deverrouiller' };
    case 'sessionExpired':
      return { cle: 'compte.bandeau.sessionExpiree', ton: 'alerte', action: 'reconnecter' };
    case 'resetPending':
      // `resetPending` n'est rendu que pour une date À VENIR (service.py) :
      // sans date, c'est une contradiction du serveur, dite comme telle.
      if (statut.pendingResetAt === null) {
        return { cle: 'compte.bandeau.reinitPrevueSansDate', ton: 'alerte', action: 'annulerReinit' };
      }
      return {
        cle: 'compte.bandeau.reinitPrevue',
        vars: { date: formaterDate(statut.pendingResetAt, locale) },
        ton: 'alerte',
        action: 'annulerReinit',
      };
    case 'accountReset':
    case 'accountDeleted':
      return { cle: 'compte.bandeau.compteReinitialise', ton: 'alerte', action: 'reconnecter' };
    case 'serverRolledBack':
      return { cle: 'compte.bandeau.retourArriere', ton: 'alerte', action: 'reconnecter' };
    case 'serverLost':
      return { cle: 'compte.bandeau.serveurPerdu', ton: 'alerte', action: 'ouvrir' };
    default:
      return null;
  }
}

/** Le nom court de l'état, pour la ligne d'état des Réglages. */
export function libelleEtat(etat: EtatCompte): MessageKey {
  const cles: Record<EtatCompte, MessageKey> = {
    none: 'compte.etat.none',
    signupInProgress: 'compte.etat.signupInProgress',
    locked: 'compte.etat.locked',
    unlocked: 'compte.etat.unlocked',
    sessionExpired: 'compte.etat.sessionExpired',
    resetPending: 'compte.etat.resetPending',
    accountReset: 'compte.etat.accountReset',
    accountDeleted: 'compte.etat.accountDeleted',
    serverRolledBack: 'compte.etat.serverRolledBack',
    serverLost: 'compte.etat.serverLost',
  };
  return cles[etat];
}

// ---------------------------------------------------------------------------
// Réinitialisation (§3.6)
// ---------------------------------------------------------------------------

export type EtapeReinitialisation = 'programmer' | 'attente' | 'terminer';

/**
 * `reset/request` sert deux fois : avant l'attente (code pour `confirm`) et
 * après son échéance (code pour `complete`). Pendant l'attente, un code ne
 * servirait à rien — le VPS n'en envoie pas.
 */
export function etapeReinitialisation(pendingResetAt: number | null, maintenant: number): EtapeReinitialisation {
  if (pendingResetAt === null) return 'programmer';
  return pendingResetAt > maintenant ? 'attente' : 'terminer';
}

// ---------------------------------------------------------------------------
// La phrase de passe proposée (D5, D6)
// ---------------------------------------------------------------------------

/**
 * Les mots d'une liste au format EFF (« 11111\tabacus ») ou d'un mot par
 * ligne. Seuls les mots faits de lettres sont gardés, sans doublon : un mot
 * à tiret (« t-shirt ») se confondrait avec le séparateur, et un doublon
 * gonflerait l'entropie annoncée.
 */
export function lireListeMots(texte: string): string[] {
  const vus = new Set<string>();
  for (const ligne of texte.split(/\r?\n/)) {
    const morceaux = ligne.trim().split(/\s+/);
    const mot = (morceaux.length > 1 ? morceaux[morceaux.length - 1] : morceaux[0] ?? '').toLowerCase();
    if (mot && /^\p{L}+$/u.test(mot)) vus.add(mot);
  }
  return [...vus];
}

/** En dessous, une phrase de six mots ne vaut plus ce qu'on en dit. */
export const LISTE_MOTS_MIN = 2048;
/** L'entropie visée : au-delà de ce qu'un GPU défait en années à 256 Mio par essai (A5). */
export const PHRASE_BITS_VISES = 70;

export function listeUtilisable(mots: readonly string[]): boolean {
  return mots.length >= LISTE_MOTS_MIN;
}

/** Le nombre de mots pour atteindre `bits` avec une liste de `n` mots. */
export function motsNecessaires(n: number, bits = PHRASE_BITS_VISES): number {
  if (n < 2) return Infinity;
  return Math.ceil(bits / Math.log2(n));
}

/** Un tirage uint32 ; `crypto.getRandomValues` en production. */
export type Tirage = () => number;

export const tirageCrypto: Tirage = () => {
  const t = new Uint32Array(1);
  crypto.getRandomValues(t);
  return t[0];
};

/**
 * Un indice uniforme dans [0, n), par rejet. `tirage() % n` seul favorise
 * les premiers mots dès que 2^32 n'est pas un multiple de n — le biais est
 * faible, mais une phrase de passe qui dit « 77 bits » doit les avoir.
 */
export function indiceUniforme(n: number, tirage: Tirage): number {
  if (!Number.isInteger(n) || n < 1 || n > 2 ** 32) throw new RangeError('n hors bornes');
  const limite = Math.floor(2 ** 32 / n) * n;
  for (let essais = 0; essais < 1000; essais += 1) {
    const x = tirage() >>> 0;
    if (x < limite) return x % n;
  }
  throw new Error('tirage défaillant');
}

export interface Phrase {
  texte: string;
  mots: number;
  bits: number;
}

/**
 * Une phrase de passe : des mots tirés uniformément, séparés par des tirets.
 * Rien d'inventé : sans liste utilisable, aucune phrase (D6) — l'interface
 * masque alors la suggestion.
 */
export function genererPhrase(
  mots: readonly string[],
  tirage: Tirage = tirageCrypto,
  bits = PHRASE_BITS_VISES,
): Phrase | null {
  if (mots.length < 2) return null;
  const nombre = motsNecessaires(mots.length, bits);
  const tires: string[] = [];
  for (let i = 0; i < nombre; i += 1) tires.push(mots[indiceUniforme(mots.length, tirage)]);
  return {
    texte: tires.join('-'),
    mots: nombre,
    bits: Math.floor(nombre * Math.log2(mots.length)),
  };
}
