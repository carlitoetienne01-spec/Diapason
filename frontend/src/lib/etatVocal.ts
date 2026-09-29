// 26/09/2026 : « Je t'écoute » restait affiché pendant un refus de voix,
// l'attente du nom ou la préparation de la réponse. Seuls les états connus
// du protocole peuvent remplacer cette indication, jamais un texte serveur.
const ETATS = {
  transcribing: 'talk.stage.transcribing',
  checkingVoice: 'talk.stage.checkingVoice',
  waitingForName: 'talk.stage.waitingForName',
  voiceNeedsMoreSpeech: 'talk.stage.voiceNeedsMoreSpeech',
  voiceProfileRequired: 'talk.stage.voiceProfileRequired',
  voiceCheckUnavailable: 'talk.stage.voiceCheckUnavailable',
  voiceNotRecognized: 'talk.stage.voiceNotRecognized',
  noSpeech: 'talk.stage.noSpeech',
  responding: 'talk.stage.responding',
  study_processing: 'talk.stage.responding',
  ending: 'talk.stage.ending',
  listening: 'talk.resonance.listening',
} as const;

export function cleEtatVocal(etat: unknown) {
  return typeof etat === 'string' && Object.prototype.hasOwnProperty.call(ETATS, etat)
    ? ETATS[etat as keyof typeof ETATS] : undefined;
}
