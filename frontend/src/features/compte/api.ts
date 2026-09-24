/**
 * Les routes locales du compte, `/v1/account/*` (compte-chiffre.md §3.8).
 *
 * C'est tout ce que le bundle appelle : le serveur Python local fait la
 * cryptographie et parle seul au serveur de comptes (§2.1). Aucune clé ne
 * transite ici, sauf la clé de récupération rendue une fois pour être notée.
 *
 * Le mot de passe part dans un corps JSON, jamais dans l'URL : uvicorn
 * journalise chemin et requête (§2.1). Les corps sont du JSON texte — la
 * fenêtre WKWebView refuse les corps binaires (CLAUDE.md §5).
 */

import { apiFetch } from '../../lib/api';
import { lireGroupesDemandes, lireStatut, type ErreurLue, type StatutCompte } from '../../lib/compte';

export interface Appareil {
  sessionId: string;
  /** `null` quand le nom a été scellé sous une AMK d'avant une rotation. */
  name: string | null;
  createdDay: number;
  lastSeenDay: number;
  current: boolean;
}

export interface CleRendue {
  cle: string;
  groupes: [number, number];
}

/** Un refus du serveur local, lu de `{error:{code, field?, reason?, retryAfterS?}}`. */
export class ErreurCompteApi extends Error implements ErreurLue {
  code: string;
  champ?: string;
  raison?: string;
  attenteS?: number;
  statutHttp: number;

  constructor(statutHttp: number, lue: ErreurLue) {
    super(lue.code);
    this.name = 'ErreurCompteApi';
    this.code = lue.code;
    this.champ = lue.champ;
    this.raison = lue.raison;
    this.attenteS = lue.attenteS;
    this.statutHttp = statutHttp;
  }
}

export function estErreurCompte(e: unknown): e is ErreurCompteApi {
  return e instanceof ErreurCompteApi;
}

// Une seule rumeur pour toutes les vues du compte : le bandeau, la section
// des Réglages et l'écran d'activation relisent le statut après chaque
// geste, au lieu d'attendre leur prochaine sonde (30 s) en affichant
// « verrouillé » juste après un déverrouillage réussi.
const EVENEMENT = 'diapason:compte-change';

export function signalerChangementCompte(statut?: StatutCompte | null): void {
  window.dispatchEvent(new CustomEvent(EVENEMENT, { detail: statut ?? null }));
}

export function surChangementCompte(rappel: (statut: StatutCompte | null) => void): () => void {
  const ecoute = (e: Event) => rappel((e as CustomEvent<StatutCompte | null>).detail ?? null);
  window.addEventListener(EVENEMENT, ecoute);
  return () => window.removeEventListener(EVENEMENT, ecoute);
}

function lireRefus(statutHttp: number, corps: unknown, entetes: Headers): ErreurLue {
  const enTete = Number.parseInt(entetes.get('Retry-After') ?? '', 10);
  const attenteEnTete = Number.isFinite(enTete) && enTete > 0 ? enTete : undefined;
  const erreur = (corps as { error?: unknown } | null)?.error;
  if (erreur && typeof erreur === 'object' && typeof (erreur as { code?: unknown }).code === 'string') {
    const e = erreur as { code: string; field?: unknown; reason?: unknown; retryAfterS?: unknown };
    return {
      code: e.code,
      champ: typeof e.field === 'string' ? e.field : undefined,
      raison: typeof e.reason === 'string' ? e.reason : undefined,
      attenteS: typeof e.retryAfterS === 'number' && e.retryAfterS > 0 ? e.retryAfterS : attenteEnTete,
    };
  }
  // Le seau du middleware local rend `{"detail": …}` sans code.
  if (statutHttp === 429) return { code: 'tooManyAttempts', attenteS: attenteEnTete };
  // Les routes du compte ne rendent JAMAIS 401 (compte_routes._statut_de) :
  // un 401 ici vient de la clé d'API locale, après le rejeu d'apiFetch.
  if (statutHttp === 401) return { code: 'localUnauthorized' };
  if (statutHttp === 404) return { code: 'accountRoutesMissing' };
  return { code: `http${statutHttp}` };
}

async function appeler(chemin: string, corps?: Record<string, unknown>, signal?: AbortSignal): Promise<unknown> {
  let reponse: Response;
  try {
    reponse = await apiFetch(`/v1/account${chemin}`, {
      method: corps === undefined ? 'GET' : 'POST',
      headers: corps === undefined ? {} : { 'Content-Type': 'application/json' },
      body: corps === undefined ? undefined : JSON.stringify(corps),
      signal,
    });
  } catch (e) {
    if (signal?.aborted) throw e;
    throw new ErreurCompteApi(0, { code: 'localServerUnreachable' });
  }
  // 24/09/2026, constaté sur le serveur launchd d'avant l'étape 8 : sans
  // les routes du compte, `/v1/account/status` tombe dans le repli de la
  // page unique et répond 200 avec index.html. Lu comme JSON, cela donnait
  // « forme inattendue » ; c'est en vérité un serveur qui ne connaît pas
  // encore les comptes, et il faut le dire ainsi.
  const type = reponse.headers.get('content-type') ?? '';
  if (reponse.ok && !type.includes('json')) {
    throw new ErreurCompteApi(reponse.status, { code: 'accountRoutesMissing' });
  }
  let json: unknown = null;
  try {
    json = await reponse.json();
  } catch {
    json = null;
  }
  if (!reponse.ok) throw new ErreurCompteApi(reponse.status, lireRefus(reponse.status, json, reponse.headers));
  return json;
}

/** Les routes de mutation rendent `{…, status}` : on le lit et on le diffuse. */
async function muter(chemin: string, corps: Record<string, unknown> = {}): Promise<{ brut: Record<string, unknown>; statut: StatutCompte | null }> {
  const brut = ((await appeler(chemin, corps)) ?? {}) as Record<string, unknown>;
  const statut = lireStatut(brut.status);
  signalerChangementCompte(statut);
  return { brut, statut };
}

function lireCle(brut: Record<string, unknown>, champ: 'recoveryKey' | 'newRecoveryKey'): CleRendue | null {
  const cle = brut[champ];
  const groupes = lireGroupesDemandes(brut.confirmGroups);
  if (typeof cle !== 'string' || !groupes) return null;
  return { cle, groupes };
}

/** `null` : statut illisible (champ manquant, forme inattendue). */
export async function lireStatutCompte(signal?: AbortSignal): Promise<StatutCompte | null> {
  return lireStatut(await appeler('/status', undefined, signal));
}

// --- P1 : inscription -------------------------------------------------------

export const commencerInscription = (email: string, termsAccepted: boolean) =>
  muter('/signup/start', { email, termsAccepted });

export const verifierCodeInscription = (code: string) => muter('/signup/verify', { code });

export async function preparerInscription(password: string, remember: boolean): Promise<CleRendue> {
  const { brut } = await muter('/signup/prepare', { password, remember });
  const cle = lireCle(brut, 'recoveryKey');
  if (!cle) throw new ErreurCompteApi(200, { code: 'responseUnreadable' });
  return cle;
}

export const terminerInscription = (choix: { recoveryExcerpt: [string, string] } | { skipRecovery: true }) =>
  muter('/signup/complete', choix);

// --- P3 : connexion, déverrouillage -----------------------------------------

export const connecter = (email: string, password: string, remember: boolean) =>
  muter('/login', { email, password, remember });

export const deverrouiller = (password: string, remember: boolean) => muter('/unlock', { password, remember });

export const verrouiller = () => muter('/lock');

// --- P5, P4 -------------------------------------------------------------------

export const changerMotDePasse = (currentPassword: string, newPassword: string) =>
  muter('/password', { currentPassword, newPassword });

export const demanderCodeOubliIci = () => muter('/password/forgotten-here/code');

export const oubliIci = (code: string, newPassword: string) => muter('/password/forgotten-here', { code, newPassword });

/** P4 chemin 1. Rend la clé NEUVE à confirmer (D22), sauf si l'on garde l'ancienne. */
export async function recuperer(args: {
  email: string;
  recoveryKey: string;
  newPassword: string;
  remember: boolean;
  keepRecoveryKey: boolean;
}): Promise<CleRendue | null> {
  const { brut } = await muter('/recover', { ...args });
  return lireCle(brut, 'newRecoveryKey');
}

// --- Clé de récupération -------------------------------------------------------

export async function nouvelleCle(password: string): Promise<CleRendue> {
  const { brut } = await muter('/recovery-key', { password });
  const cle = lireCle(brut, 'recoveryKey');
  if (!cle) throw new ErreurCompteApi(200, { code: 'responseUnreadable' });
  return cle;
}

export const confirmerCle = (recoveryExcerpt: [string, string]) => muter('/recovery-key/confirm', { recoveryExcerpt });

export const retirerCle = (password: string) => muter('/recovery-key/remove', { password });

// --- Réinitialisation (§3.6) ---------------------------------------------------

export const reinitDemander = (email: string) => muter('/reset/request', { email });

export async function reinitConfirmer(email: string, code: string): Promise<number | null> {
  const { brut } = await muter('/reset/confirm', { email, code });
  return typeof brut.effectiveAt === 'number' ? brut.effectiveAt : null;
}

export const reinitAnnuler = () => muter('/reset/cancel');

export async function reinitTerminer(email: string, code: string, newPassword: string, remember: boolean): Promise<CleRendue | null> {
  const { brut } = await muter('/reset/complete', { email, code, newPassword, remember });
  return lireCle(brut, 'newRecoveryKey');
}

// --- P6 : appareils -----------------------------------------------------------

export async function listerAppareils(): Promise<Appareil[]> {
  const brut = (await appeler('/devices')) as { devices?: unknown } | null;
  const liste = Array.isArray(brut?.devices) ? brut.devices : [];
  return liste.filter(
    (a): a is Appareil =>
      !!a &&
      typeof a === 'object' &&
      typeof (a as Appareil).sessionId === 'string' &&
      ((a as Appareil).name === null || typeof (a as Appareil).name === 'string') &&
      typeof (a as Appareil).createdDay === 'number' &&
      typeof (a as Appareil).lastSeenDay === 'number' &&
      typeof (a as Appareil).current === 'boolean',
  );
}

export const deconnecterAppareil = (sessionId: string, password: string) =>
  muter(`/devices/${encodeURIComponent(sessionId)}/disconnect`, { password });

// --- P7, P8 ---------------------------------------------------------------------

/** `false` : la session n'a pas pu être refermée sur le serveur de comptes. */
export async function seDeconnecter(): Promise<boolean> {
  const { brut } = await muter('/logout', { eraseLocalData: false });
  return brut.serverSessionClosed === true;
}

export const supprimerCompte = (password: string) => muter('/delete', { password, eraseLocalData: false });

// --- Consentement, premier lancement ---------------------------------------------

export const consentir = () => muter('/sync/consent');

export const accueilTermine = () => muter('/onboarding/done');
