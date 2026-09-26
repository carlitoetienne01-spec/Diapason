// Ce que la page Appareils dit des sessions d'un appareil — hors React, pour
// être vérifié sous vitest (aucun test de composant dans ce dépôt).
//
// 26/09/2026, phase 2 étape 9 du plan mobile. Les deux routes existaient
// côté serveur (`GET /v1/mesh/devices/{id}/sessions`, `POST …/sessions/close`)
// sans que rien ne les montre : le Mac ne voyait rien des sessions de 12 h
// que le téléphone ouvre par le tailnet, et ne pouvait y mettre fin qu'en
// RÉVOQUANT le téléphone — clé jetée, appairage à refaire. Et l'adresse que
// l'invitation rend (`tailnetAddress`) n'était affichée nulle part : il
// fallait la deviner sur le téléphone, et une adresse devinée qui se trompe
// se lit « réseau ».

import type { Locale } from '../../i18n/locale';
import type { MessageKey, Vars } from '../../i18n/translate';
import type { MeshDeviceSessions, MeshPairingInvitation } from './types';

export type Traduire = (cle: MessageKey, vars?: Vars) => string;

/** Ce que la page sait des sessions d'un appareil. */
export type EtatSessions =
  | { etat: 'chargement' }
  | { etat: 'erreur'; message: string }
  | { etat: 'lu'; lecture: MeshDeviceSessions };

export type ResumeSessions = {
  texte: string;
  /** Vrai seulement quand le serveur a dit qu'au moins une session est ouverte. */
  fermable: boolean;
  ton: 'neutre' | 'erreur';
};

const MINUTE_MS = 60_000;
const HEURE_MS = 60 * MINUTE_MS;
const JOUR_MS = 24 * HEURE_MS;

/**
 * « à l'instant », « il y a 3 min », « il y a 2 h », puis une date.
 *
 * À la minute près, jamais plus fin : le serveur ne réécrit la dernière
 * activité qu'une fois par minute (`SESSION_TOUCH_INTERVAL_MS`), et
 * « il y a 12 s » affirmerait une précision qu'il n'a pas. Une date dans
 * le futur (horloges du Mac et de la page décalées) se lit « à l'instant »
 * plutôt que « il y a -1 min ».
 */
export function depuis(ms: number, maintenant: number, t: Traduire, locale: Locale): string {
  const ecart = maintenant - ms;
  if (ecart < MINUTE_MS) return t('appareils.depuis.instant');
  if (ecart < HEURE_MS) return t('appareils.depuis.minutes', { n: Math.floor(ecart / MINUTE_MS) });
  if (ecart < JOUR_MS) return t('appareils.depuis.heures', { n: Math.floor(ecart / HEURE_MS) });
  const date = new Intl.DateTimeFormat(locale === 'fr' ? 'fr-CA' : 'en-CA', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(ms));
  return t('appareils.depuis.date', { date });
}

/**
 * La ligne « sessions » d'un appareil.
 *
 * Le nombre et la dernière activité viennent du SERVEUR (`count`,
 * `lastUsedAtMs`), jamais d'un compte fait ici sur une liste qui aurait pu
 * être tronquée : c'est lui qui sait ce que la passerelle acceptera.
 */
export function resumeDesSessions(
  etat: EtatSessions,
  maintenant: number,
  t: Traduire,
  locale: Locale,
): ResumeSessions {
  if (etat.etat === 'chargement') {
    return { texte: t('appareils.sessions.chargement'), fermable: false, ton: 'neutre' };
  }
  if (etat.etat === 'erreur') {
    return {
      texte: t('appareils.sessions.illisibles', { message: etat.message }),
      fermable: false,
      ton: 'erreur',
    };
  }
  const { count, lastUsedAtMs } = etat.lecture;
  if (!count) return { texte: t('appareils.sessions.aucune'), fermable: false, ton: 'neutre' };
  const ouvertes = t('appareils.sessions.ouvertes', { count });
  const texte =
    lastUsedAtMs === null
      ? ouvertes
      : `${ouvertes} · ${t('appareils.sessions.activite', {
          depuis: depuis(lastUsedAtMs, maintenant, t, locale),
        })}`;
  return { texte, fermable: true, ton: 'neutre' };
}

/**
 * Ce que « Fermer ses sessions » a fait — d'après le `closed` RENDU par le
 * serveur (§100), pas d'après le nombre que la page affichait avant le clic :
 * une session expirée entre-temps, ou déjà fermée depuis un autre écran,
 * n'a pas été fermée par ce clic.
 */
export function phraseDeFermeture(closed: unknown, nom: string, t: Traduire): string {
  const n = typeof closed === 'number' && Number.isInteger(closed) && closed > 0 ? closed : 0;
  if (n === 0) return t('appareils.sessions.aucuneAFermer', { nom });
  return t('appareils.sessions.fermees', { count: n, nom });
}

export type AdresseDInvitation =
  | { type: 'adresse'; adresse: string }
  | { type: 'nonPosee' }
  | { type: 'serveurAncien' };

/**
 * L'adresse à saisir dans l'app, telle que le serveur l'a lue dans
 * `[tailnet] adresse`.
 *
 * Trois cas, parce qu'ils ne demandent pas le même geste : `null`, la clé
 * n'est pas posée (la poser, puis relancer le serveur — `load_config` est en
 * cache) ; absente, le serveur ne connaît pas encore le champ (le relancer
 * après la mise à jour) ; sinon l'adresse. Une valeur qui n'est pas https
 * n'est pas affichée : le serveur ne la rendrait pas, et le téléphone passe
 * toujours par https (décidé le 25/09/2026).
 */
export function adresseDInvitation(invitation: MeshPairingInvitation): AdresseDInvitation {
  if (!('tailnetAddress' in invitation) || invitation.tailnetAddress === undefined) {
    return { type: 'serveurAncien' };
  }
  const brute = invitation.tailnetAddress;
  if (typeof brute !== 'string' || !/^https:\/\/[^\s/]+$/i.test(brute.trim())) {
    return { type: 'nonPosee' };
  }
  return { type: 'adresse', adresse: brute.trim() };
}
