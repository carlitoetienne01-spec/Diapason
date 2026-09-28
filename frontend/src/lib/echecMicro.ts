// Le micro qui ne s'ouvre pas : pourquoi, et ce qu'il faut en dire.
//
// 28/09/2026, constat de Carlito sur son téléphone (Nothing Phone, « Diapason
// dev ») : toucher « Parler » affichait « L'accès au microphone est bloqué.
// Autorisez Diapason dans Réglages Système › Confidentialité et sécurité ›
// Microphone. » — le message du MAC, sans qu'Android ait rien demandé.
// `useVoiceLive` n'avait qu'un `try` autour de getUserMedia, de l'AudioContext,
// de la capture et de `resume()`, et TOUTE exception y devenait
// `microphone-denied`. Le nom de l'erreur n'allait qu'en console : la capture
// d'écran ne disait rien de la cause (§5).
//
// L'audit du même jour tient pour la cause la plus probable un
// `NotReadableError « Could not start audio source »` : sans la permission
// MODIFY_AUDIO_SETTINGS, que l'APK n'a jamais déclarée, le Chromium de la
// WebView refuse de créer le flux d'entrée sur un téléphone, RECORD_AUDIO
// accordé ou non. Ce n'est pas un refus, et le dire en est un mensonge.
//
// Deux fonctions pures, testées seules (aucun test de composant dans ce
// dépôt) : `classerEchecMicro` dit ce qui a échoué, `messageDuMicro` choisit
// la phrase et le bouton. Le hook de la voix et la dictée s'en servent tous
// les deux, pour qu'un même échec ne se dise pas de deux façons.

import type { MessageKey } from '../i18n/translate';
import type { ReponseNatif } from './natif';

/**
 * Avant ou après l'obtention du flux. Une `AbortError` levée par
 * l'AudioContext ou la capture n'a rien d'un micro occupé : le micro s'était
 * ouvert. Classer par ÉTAPE avant de classer par NOM.
 */
export type EtapeDuMicro = 'avantLeFlux' | 'apresLeFlux';

export type ClasseEchecMicro =
  /** Le navigateur, la coquille ou le système a dit non. */
  | 'refus'
  /** Le micro existe mais n'a pas démarré : occupé, ou la WebView n'a pas pu ouvrir son flux. */
  | 'indisponible'
  /** Aucun périphérique d'entrée ne répond aux contraintes. */
  | 'aucunMicro'
  /** La page n'a pas accès au micro du tout : contexte non sécurisé, `mediaDevices` absent. */
  | 'pageSansMicro'
  /** Le flux était obtenu ; c'est la préparation du son qui a échoué. */
  | 'echecAudio'
  /** Un nom qu'aucune de ces familles ne connaît : on l'affiche, on ne devine pas. */
  | 'inconnu';

export interface EchecMicro {
  classe: ClasseEchecMicro;
  /** « NotReadableError · Could not start audio source », tronqué. */
  technique: string;
}

/**
 * La longueur du détail technique affiché. Le message de Chromium distingue
 * les sous-cas (« Permission denied by system », « Could not start audio
 * source », « Timeout starting video source ») en moins de 60 signes ; 120
 * garde le nom ET le message entiers sur deux lignes d'un écran de 360 px,
 * sans laisser une trace de pile envahir l'écran.
 */
export const TECHNIQUE_MAX = 120;

// Les noms de Blink (user_media_request.cc), plus les anciens noms que
// Chrome rendait avant la normalisation (PermissionDeniedError,
// TrackStartError, DevicesNotFoundError, ConstraintNotSatisfiedError).
const REFUS = new Set(['NotAllowedError', 'PermissionDeniedError']);
const INDISPONIBLE = new Set([
  'NotReadableError',
  'TrackStartError',
  // START_TIMEOUT chez Chromium : le micro n'a pas démarré à temps.
  'AbortError',
  'NotSupportedError',
  'InvalidStateError',
]);
const AUCUN_MICRO = new Set([
  'NotFoundError',
  'DevicesNotFoundError',
  'OverconstrainedError',
  'ConstraintNotSatisfiedError',
]);
// `SecurityError` n'est pas un refus : Chrome ne la rend que pour une origine
// non sécurisée (INVALID_SECURITY_ORIGIN, seul cas de UserMediaRequest::Fail,
// relu le 28/09/2026) ; un refus de la coquille ou d'Android arrive en
// NotAllowedError. La ranger avec le refus renverrait la personne vers des
// réglages qui n'y peuvent rien. Écart assumé au contrat du 28/09, écrit au
// §6 de docs/development/diapason-mobile.md.
const PAGE_SANS_MICRO = new Set(['TypeError', 'SecurityError']);

function lireNomEtMessage(erreur: unknown): { nom: string; message: string } {
  if (erreur && typeof erreur === 'object') {
    const e = erreur as { name?: unknown; message?: unknown };
    const nom = typeof e.name === 'string' ? e.name.trim() : '';
    const message = typeof e.message === 'string' ? e.message.trim() : '';
    if (nom || message) return { nom, message };
  }
  if (typeof erreur === 'string') return { nom: '', message: erreur.trim() };
  return { nom: '', message: String(erreur) };
}

/** « Nom · message », sur une ligne, borné à `TECHNIQUE_MAX` signes. */
export function detailTechnique(erreur: unknown): string {
  const { nom, message } = lireNomEtMessage(erreur);
  const morceaux = [nom, message && message !== nom ? message : ''].filter(Boolean);
  const texte = morceaux.join(' · ').replace(/\s+/g, ' ').trim() || 'Error';
  return texte.length > TECHNIQUE_MAX ? `${texte.slice(0, TECHNIQUE_MAX - 1)}…` : texte;
}

export function classerEchecMicro(erreur: unknown, etape: EtapeDuMicro): EchecMicro {
  const technique = detailTechnique(erreur);
  if (etape === 'apresLeFlux') return { classe: 'echecAudio', technique };
  const { nom } = lireNomEtMessage(erreur);
  const classe: ClasseEchecMicro = REFUS.has(nom)
    ? 'refus'
    : INDISPONIBLE.has(nom)
      ? 'indisponible'
      : AUCUN_MICRO.has(nom)
        ? 'aucunMicro'
        : PAGE_SANS_MICRO.has(nom)
          ? 'pageSansMicro'
          : 'inconnu';
  return { classe, technique };
}

// ---------------------------------------------------------------------------
// Le verbe `micro` de la coquille (contrat du 28/09/2026, identique en Dart).

/** Ce que la coquille rend à `micro/etat`, lu par permission_handler sans rien demander. */
export const ETATS_MICRO = ['accorde', 'aDemander', 'refuse', 'refuseDefinitivement', 'restreint'] as const;
export type EtatMicroAndroid = (typeof ETATS_MICRO)[number];

/**
 * Ce que la page sait de l'état d'Android : l'état lui-même, une coquille
 * trop ancienne pour le dire (`verbeInconnu` — donc, vérifié sur les trois
 * APK construits avant ce contrat, sans MODIFY_AUDIO_SETTINGS), ou rien
 * (pas de pont, délai, réponse illisible).
 */
export type EtatMicroLu = EtatMicroAndroid | 'verbeInconnu' | 'inconnu';

/** Les données du verbe `micro` : une action, rien d'autre ne voyage. */
export type ChargeMicro = { action: 'etat' | 'reglages' };

export type DemanderMicro = (verbe: 'micro', donnees: ChargeMicro) => Promise<ReponseNatif>;

/**
 * Faut-il demander l'état d'Android ? Seulement après un refus ou un micro
 * indisponible, et jamais au montage ni en boucle : `Permission.microphone
 * .status` n'affiche rien, mais peut écrire la préférence « déjà refusé » de
 * permission_handler.
 */
export function doitLireEtatAndroid(classe: ClasseEchecMicro): boolean {
  return classe === 'refus' || classe === 'indisponible';
}

/** `micro/etat` ; ne lève jamais. */
export async function lireEtatDuMicro(demander: DemanderMicro): Promise<EtatMicroLu> {
  let reponse: ReponseNatif;
  try {
    reponse = await demander('micro', { action: 'etat' });
  } catch {
    return 'inconnu';
  }
  if (!reponse.ok) return reponse.erreur === 'verbeInconnu' ? 'verbeInconnu' : 'inconnu';
  // L'état voyage DANS `donnees` : les deux lecteurs du pont (natif.ts,
  // pont_natif.dart) jettent tout autre champ du premier niveau.
  const etat = (reponse.donnees as { etat?: unknown } | null | undefined)?.etat;
  return (ETATS_MICRO as readonly unknown[]).includes(etat) ? (etat as EtatMicroAndroid) : 'inconnu';
}

/** Ce qui s'affiche sous le bouton quand les réglages ne se sont pas ouverts. */
export interface AvisDesReglages {
  /** La phrase de la page, dans sa langue et au vouvoiement. */
  cle: MessageKey;
  /** La phrase de la coquille telle qu'elle l'a dite, citée sous la première (§100) ; `null` pour un code. */
  reponse: string | null;
}

/**
 * `micro/reglages` : `null` quand il n'y a RIEN à dire — les réglages se sont
 * ouverts, ou le délai a expiré alors que l'app était passée derrière eux.
 * Un code (`verbeInconnu`, `actionInconnue`…) ne s'affiche jamais brut.
 *
 * 28/09/2026 (revue) : la phrase de la coquille (le cadenas, un
 * `startActivity` refusé) s'affichait SEULE. Or la coquille ne parle que
 * français, et tutoie (« ouvre Paramètres… ») : en anglais, une ligne
 * française au milieu d'un écran anglais ; en français, le vous et le tu
 * d'une ligne à l'autre. La page dit désormais sa propre phrase, et cite
 * celle du récepteur dessous, attribuée — elle reste ce qui s'est passé.
 */
export async function ouvrirLesReglagesDuMicro(demander: DemanderMicro): Promise<AvisDesReglages | null> {
  let reponse: ReponseNatif;
  try {
    reponse = await demander('micro', { action: 'reglages' });
  } catch (erreur) {
    console.warn('[micro] les réglages n’ont pas répondu', erreur);
    return null;
  }
  if (reponse.ok) return null;
  const erreur = reponse.erreur?.trim() ?? '';
  if (erreur === 'verbeInconnu' || erreur === 'actionInconnue') {
    return { cle: 'talk.micro.reglagesIndisponibles', reponse: null };
  }
  return { cle: 'talk.micro.reglagesEchec', reponse: /\s/.test(erreur) ? erreur : null };
}

// ---------------------------------------------------------------------------
// La phrase et le bouton.

/** Les codes d'erreur de la voix qu'un échec du micro peut produire. */
export const CODES_DU_MICRO = [
  'microphone-denied',
  'microphone-busy',
  'microphone-missing',
  'microphone-page',
  'microphone-audio-failed',
  'microphone-failed',
  'microphone-phone-checking',
  'microphone-phone-denied',
  'microphone-phone-denied-forever',
  'microphone-phone-restricted',
  'microphone-phone-refused-by-app',
  'microphone-phone-denied-unknown',
  'microphone-phone-busy',
  'microphone-phone-app-outdated',
  'microphone-phone-busy-unknown',
  'microphone-phone-missing',
  'microphone-phone-page',
  'microphone-phone-audio-failed',
  'microphone-phone-failed',
  'microphone-phone-now-allowed',
] as const;
export type CodeDuMicro = (typeof CODES_DU_MICRO)[number];

export interface MessageDuMicro {
  code: CodeDuMicro;
  /** Le bouton « Ouvrir les réglages » : seulement quand la coquille sait les ouvrir. */
  reglages: boolean;
}

/** `enAttente` : la réponse de `micro/etat` n'est pas encore arrivée. */
export type EtatPourLeMessage = EtatMicroLu | 'enAttente';

const sans = (code: CodeDuMicro): MessageDuMicro => ({ code, reglages: false });
const avec = (code: CodeDuMicro): MessageDuMicro => ({ code, reglages: true });

/**
 * « Au téléphone » se décide par `serviParLeTailnet()` (le pont OU l'en-tête
 * de la passerelle), pas par le seul pont : une coquille dont le pont n'est
 * pas lié afficherait sinon les Réglages Système de macOS. Le bouton, lui,
 * n'existe qu'avec un état rendu par la coquille — donc qu'avec le pont.
 */
export function messageDuMicro({
  classe,
  auTelephone,
  etat,
}: {
  classe: ClasseEchecMicro;
  auTelephone: boolean;
  etat: EtatPourLeMessage;
}): MessageDuMicro {
  if (!auTelephone) {
    // Au bureau, le refus garde le message de macOS : WKWebView rend
    // NotAllowedError pour un refus TCC, et c'est là qu'on l'autorise.
    if (classe === 'refus') return sans('microphone-denied');
    if (classe === 'indisponible') return sans('microphone-busy');
    if (classe === 'aucunMicro') return sans('microphone-missing');
    if (classe === 'pageSansMicro') return sans('microphone-page');
    if (classe === 'echecAudio') return sans('microphone-audio-failed');
    return sans('microphone-failed');
  }
  if (classe === 'refus' || classe === 'indisponible') {
    if (etat === 'enAttente') return sans('microphone-phone-checking');
    // Android dit « non accordé » : c'est la cause, quel que soit le nom de
    // l'erreur. permission_handler ne sait pas distinguer « jamais demandé »
    // de « refusé une fois », et son « définitif » repose sur une préférence
    // qu'il écrit lui-même : un refus fait par la dictée de l'Entité reste
    // `refuse` alors qu'Android ne demande plus. Le texte de `refuse` ne
    // promet donc jamais d'invite, et le bouton y figure aussi.
    //
    // L'erreur inverse existe aussi (banc 5 bis du 28/09/2026) : les
    // drapeaux de RECORD_AUDIO effacés côté Android, `etat` rendait encore
    // `refuseDefinitivement` — la préférence
    // `sp_permission_handler_permission_was_denied_before` survit à toute
    // remise à zéro — et le toucher suivant de « Parler » MONTRAIT l'invite.
    // Le texte du refus définitif ne dit donc pas « Android ne demande
    // plus », seulement qu'il ne le demandera sans doute plus.
    if (etat === 'refuseDefinitivement') return avec('microphone-phone-denied-forever');
    if (etat === 'refuse' || etat === 'aDemander') return avec('microphone-phone-denied');
    // `restreint` vient d'iOS : aucun réglage de l'app ne le lève.
    if (etat === 'restreint') return sans('microphone-phone-restricted');
    if (classe === 'refus') {
      // Android a accordé, et pourtant non : c'est la coquille qui a refusé.
      // Seule la coquille qui connaît `micro` rend `accorde` ; elle sérialise
      // les demandes simultanées et ne lie son pont qu'aux pages du Mac. La
      // phrase ne devine donc aucune cause (revue du 28/09/2026 : elle en
      // énumérait deux devenues impossibles) et renvoie au détail affiché.
      return sans(etat === 'accorde' ? 'microphone-phone-refused-by-app' : 'microphone-phone-denied-unknown');
    }
    // Une coquille qui ne connaît pas `micro` est antérieure à
    // MODIFY_AUDIO_SETTINGS : lui conseiller les réglages ne servirait à
    // rien, il faut la nouvelle app.
    if (etat === 'verbeInconnu') return sans('microphone-phone-app-outdated');
    return sans(etat === 'accorde' ? 'microphone-phone-busy' : 'microphone-phone-busy-unknown');
  }
  if (classe === 'aucunMicro') return sans('microphone-phone-missing');
  if (classe === 'pageSansMicro') return sans('microphone-phone-page');
  // 28/09/2026 (revue) : les phrases du bureau renvoient « aux journaux ».
  // Un téléphone n'en a aucun qu'on puisse ouvrir ; le détail est affiché
  // juste en dessous.
  if (classe === 'echecAudio') return sans('microphone-phone-audio-failed');
  return sans('microphone-phone-failed');
}

/**
 * Au retour des réglages d'Android : relire l'état, jamais relancer la
 * séance (§78 — « Parler » reste un toucher de la personne).
 */
export function messageApresLesReglages(classe: ClasseEchecMicro, etat: EtatMicroLu): MessageDuMicro {
  if (etat === 'accorde') return sans('microphone-phone-now-allowed');
  return messageDuMicro({ classe, auTelephone: true, etat });
}
