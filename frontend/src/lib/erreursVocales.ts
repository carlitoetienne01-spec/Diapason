import type { MessageKey } from '../i18n/translate';

export const ERREURS_VOCALES = {
  'missing-key-gemini': 'talk.missingKeyGemini',
  'missing-key-openai': 'talk.missingKeyOpenai',
  'local-not-ready': 'talk.localNotReady',
  'local-components-missing': 'talk.localComponentsMissing',
  'voice-auth-unavailable': 'talk.authUnavailable',
  'voice-service-unavailable': 'talk.serviceUnavailable',
  'voice-connection-failed': 'talk.connectionFailed',
  'microphone-denied': 'talk.microphoneDenied',
  // 28/09/2026 : chaque classe d'échec du micro a sa phrase (lib/echecMicro.ts).
  'microphone-busy': 'talk.micro.occupe',
  'microphone-missing': 'talk.micro.aucun',
  'microphone-page': 'talk.micro.page',
  'microphone-audio-failed': 'talk.micro.echecAudio',
  'microphone-failed': 'talk.micro.echec',
  'microphone-phone-checking': 'talk.micro.telephone.verification',
  'microphone-phone-denied': 'talk.micro.telephone.refuse',
  'microphone-phone-denied-forever': 'talk.micro.telephone.refuseDefinitivement',
  'microphone-phone-restricted': 'talk.micro.telephone.restreint',
  'microphone-phone-refused-by-app': 'talk.micro.telephone.refuseParLApp',
  'microphone-phone-denied-unknown': 'talk.micro.telephone.refuseSansEtat',
  'microphone-phone-busy': 'talk.micro.telephone.occupe',
  'microphone-phone-app-outdated': 'talk.micro.telephone.appTropAncienne',
  'microphone-phone-busy-unknown': 'talk.micro.telephone.occupeSansEtat',
  'microphone-phone-missing': 'talk.micro.telephone.aucun',
  'microphone-phone-page': 'talk.micro.telephone.page',
  'microphone-phone-now-allowed': 'talk.micro.telephone.maintenantAutorise',
  'voice-session-failed': 'talk.sessionFailed',
  'voice-closed-inactivity': 'talk.closedInactivity',
  'voice-closed-max-duration': 'talk.closedMaxDuration',
  'voice-lost-server': 'talk.lostServer',
  'voice-conversation-unavailable': 'talk.conversation.unavailable',
} as const satisfies Record<string, MessageKey>;

/**
 * La phrase d'un code d'erreur de la voix. 28/09/2026 : l'orbe affichait le
 * CODE brut pour toute clé absente de la table (« microphone-busy » à
 * l'écran), la barre de la Discussion retombait sur « la séance n'a pas pu
 * démarrer ». Un seul repli, le même partout.
 */
export function cleErreurVocale(code: string): MessageKey {
  return Object.prototype.hasOwnProperty.call(ERREURS_VOCALES, code)
    ? ERREURS_VOCALES[code as keyof typeof ERREURS_VOCALES]
    : 'talk.sessionFailed';
}
