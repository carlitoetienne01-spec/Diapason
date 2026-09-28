// Quand la CONNEXION lâche pendant une réponse du chat — et ce qu'on en dit.
//
// 26/09/2026, 19:44, Discussion du téléphone : « Erreur : network error ».
// Les en-têtes 200 étaient arrivés ; `reader.read()` a échoué au milieu du
// corps SSE (TypeError « network error » de la WebView Chromium), pendant les
// ~16 s du remplissage du prompt — une reprise d'app ou un changement de
// réseau (rafale de connexions neuves au même instant dans le journal).
// InputArea collait ce nom brut dans « Erreur : {message} » : rien ne disait
// que c'était le réseau, ni quoi faire, et un statut non OK aurait donné
// « Chat request failed: N » (lib/sse.ts). Le mini-panneau et la fenêtre
// Tauri peuvent perdre le serveur de la même façon (redémarrage, veille).
//
// Ce module reconnaît la coupure, choisit la phrase, et prépare le renvoi du
// MÊME message. Il ne relance jamais rien seul : un tour peut avoir déjà
// exécuté des outils avant de se couper, et le rejouer sans qu'on le demande
// les ferait agir deux fois.

import type { ChatMessage } from '../types';
import type { MessageKey, Vars } from '../i18n/translate';

export type ConnexionPerdue = NonNullable<ChatMessage['connectionLost']>;

/** Le nom brut d'une erreur, tel qu'on l'affiche en petit sous la phrase. */
export function nomBrut(erreur: unknown): string {
  if (erreur instanceof CoupureDuFlux) return erreur.brut;
  if (erreur && typeof erreur === 'object') {
    const e = erreur as { name?: unknown; message?: unknown };
    const nom = typeof e.name === 'string' && e.name ? e.name : 'Error';
    const message = typeof e.message === 'string' ? e.message : '';
    return message ? `${nom}: ${message}` : nom;
  }
  return String(erreur);
}

/** Un arrêt demandé (bouton Arrêter, changement de modèle) n'est pas une coupure. */
export function estAbandon(erreur: unknown): boolean {
  return !!erreur && typeof erreur === 'object' && (erreur as { name?: unknown }).name === 'AbortError';
}

/**
 * Levée par `streamChat` / `streamResearch` quand `reader.read()` échoue : le
 * corps s'est interrompu APRÈS les en-têtes, quel que soit le mot du moteur
 * (« network error » chez Chromium, « Load failed » ou « The network
 * connection was lost. » chez WebKit, « Error in body stream » chez Firefox).
 * Garder la cause évite de deviner à partir d'un message.
 */
export class CoupureDuFlux extends Error {
  readonly brut: string;

  constructor(cause: unknown) {
    const brut = nomBrut(cause);
    super(brut);
    this.name = 'CoupureDuFlux';
    this.brut = brut;
  }
}

/**
 * `reader.read()`, dont l'échec devient une `CoupureDuFlux` — sauf un arrêt
 * demandé, qui reste un `AbortError` et garde son texte « (Génération
 * interrompue) ».
 */
export async function lireLeCorps<T>(lecteur: {
  read(): Promise<ReadableStreamReadResult<T>>;
}): Promise<ReadableStreamReadResult<T>> {
  try {
    return await lecteur.read();
  } catch (erreur) {
    if (estAbandon(erreur)) throw erreur;
    throw new CoupureDuFlux(erreur);
  }
}

// Les mots des moteurs pour une requête que le réseau a fait échouer, sans
// statut HTTP. Ancrés : « Chat request failed: 502 » (un Mac arrêté derrière
// `tailscale serve`) est une réponse, pas une coupure, et garde sa phrase.
//
// « Load failed » avant toute réponse ne veut dire « injoignable » que si
// chaque refus du serveur reste LISIBLE par la fenêtre Tauri, qui l'appelle
// en cross-origin. Revue du 28/09/2026 : un 401 d'AuthMiddleware ou une 500
// partaient sans en-tête CORS, et une clé périmée se lisait « serveur
// arrêté » ; server/app.py pose désormais CORS en dernier et sur la 500
// (tests/server/test_app_refus_lisibles.py).
const MOTS_DU_TRANSPORT: ReadonlyArray<{ motif: RegExp; pendant: ConnexionPerdue['during'] }> = [
  // Chromium (la WebView d'Android, Chrome) : le corps s'est interrompu.
  { motif: /^network error$/i, pendant: 'response' },
  // Firefox : le corps s'est interrompu.
  { motif: /^error in body stream$/i, pendant: 'response' },
  // WebKit (la WKWebView de Tauri, Safari) : NSURLErrorNetworkConnectionLost.
  { motif: /^the network connection was lost\.?$/i, pendant: 'response' },
  // Chromium : la requête n'a jamais abouti.
  { motif: /^failed to fetch$/i, pendant: 'request' },
  // WebKit : la requête n'a jamais abouti.
  { motif: /^load failed$/i, pendant: 'request' },
  // Firefox : la requête n'a jamais abouti.
  { motif: /^networkerror when attempting to fetch resource\.?$/i, pendant: 'request' },
];

/**
 * La coupure que cette erreur décrit, ou `null` si c'est autre chose (un
 * refus du serveur, un arrêt demandé, un bug). `parLeTailnet` dit de quel
 * côté on était — la phrase n'est pas la même au téléphone et au Mac.
 */
export function lireCoupure(erreur: unknown, parLeTailnet: boolean): ConnexionPerdue | null {
  if (estAbandon(erreur)) return null;
  if (erreur instanceof CoupureDuFlux) {
    return { detail: erreur.brut, during: 'response', overTailnet: parLeTailnet };
  }
  const message =
    erreur && typeof erreur === 'object' && typeof (erreur as { message?: unknown }).message === 'string'
      ? ((erreur as { message: string }).message).trim()
      : '';
  if (!message) return null;
  const mot = MOTS_DU_TRANSPORT.find(({ motif }) => motif.test(message));
  if (!mot) return null;
  return { detail: nomBrut(erreur), during: mot.pendant, overTailnet: parLeTailnet };
}

type Traduire = (cle: MessageKey, vars?: Vars) => string;

/** Ce que la bulle garde quand le flux lève une erreur. */
export interface IssueDuFlux {
  texte: string;
  coupure: ConnexionPerdue | null;
  statut: 'interrupted' | 'error';
}

/**
 * La fin d'un flux interrompu, pour InputArea. Une coupure garde le texte
 * déjà reçu TEL QUEL — même vide : la phrase et « Renvoyer » viennent de
 * `connectionLost` à l'affichage, jamais du texte, que le modèle relirait au
 * tour suivant comme s'il l'avait écrit. Le reste ne change pas : un arrêt
 * demandé dit « (Génération interrompue) », une autre erreur « Erreur : … ».
 */
export function issueDuFlux(
  erreur: unknown,
  recu: string,
  parLeTailnet: boolean,
  t: Traduire,
): IssueDuFlux {
  if (estAbandon(erreur)) {
    return { texte: recu || t('chat.input.generationStopped'), coupure: null, statut: 'interrupted' };
  }
  const coupure = lireCoupure(erreur, parLeTailnet);
  if (coupure) return { texte: recu, coupure, statut: 'error' };
  const message = (erreur as { message?: unknown } | null)?.message;
  return {
    texte: recu || t('chat.input.error', { message: typeof message === 'string' && message ? message : String(erreur) }),
    coupure: null,
    statut: 'error',
  };
}

/** Le texte final : « Aucune réponse… » seulement si rien n'explique le vide. */
export function texteFinal(recu: string, coupure: ConnexionPerdue | null, t: Traduire): string {
  if (recu || coupure) return recu;
  return t('chat.input.noResponse');
}

/** La phrase à dire : au téléphone ou au Mac, pendant la réponse ou avant. */
export function cleDeCoupure(coupure: ConnexionPerdue): MessageKey {
  if (coupure.overTailnet) {
    return coupure.during === 'response' ? 'chat.coupure.telephoneReponse' : 'chat.coupure.telephoneEnvoi';
  }
  return coupure.during === 'response' ? 'chat.coupure.bureauReponse' : 'chat.coupure.bureauEnvoi';
}

/** Ce que le bouton « Renvoyer » envoie. */
export interface Renvoi {
  /** La question, telle qu'elle est déjà dans le fil — jamais recopiée. */
  question: ChatMessage;
  /** Le fil jusqu'à la question incluse : ce que le modèle relit. */
  historique: ChatMessage[];
  /** Une recherche approfondie coupée se renvoie en recherche approfondie. */
  recherche: boolean;
}

/**
 * Le renvoi de la réponse coupée `messageId`, ou `null` s'il n'a pas de sens.
 *
 * Seulement depuis la DERNIÈRE bulle du fil, et seulement si rien n'a
 * répondu à la question depuis : entre elle et la fin, il n'y a que des
 * réponses coupées (un deuxième renvoi coupé à son tour se renvoie encore).
 * La question n'est pas ajoutée une seconde fois ; la bulle coupée reste,
 * avec son texte partiel et sa phrase — la fusion des conversations est une
 * union au grain du message, une bulle retirée ici reviendrait au tirage
 * suivant (docs/development/conversations-sync.md).
 */
export function preparerRenvoi(messages: ChatMessage[], messageId: string): Renvoi | null {
  const derniere = messages[messages.length - 1];
  if (!derniere || derniere.id !== messageId || derniere.role !== 'assistant') return null;
  let i = messages.length - 1;
  while (i >= 0 && messages[i].role === 'assistant') {
    if (!messages[i].connectionLost) return null;
    i -= 1;
  }
  if (i < 0) return null;
  return {
    question: messages[i],
    historique: messages.slice(0, i + 1),
    recherche: derniere.isResearch === true,
  };
}

/** Le bouton « Renvoyer » d'une bulle demande le renvoi ; InputArea écoute. */
export interface DemandeDeRenvoi { conversationId: string; messageId: string }
export const EVENEMENT_RENVOYER = 'diapason:renvoyer-message';
