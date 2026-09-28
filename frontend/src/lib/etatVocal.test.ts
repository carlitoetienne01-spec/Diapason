import { describe, expect, it } from 'vitest';
import { cleEtatVocal } from './etatVocal';

describe('Les états du parcours vocal', () => {
  it('distingue la transcription, la réponse et les deux motifs de silence', () => {
    expect(cleEtatVocal('transcribing')).toBe('talk.stage.transcribing');
    expect(cleEtatVocal('responding')).toBe('talk.stage.responding');
    expect(cleEtatVocal('waitingForName')).toBe('talk.stage.waitingForName');
    for (const etat of ['voiceNeedsMoreSpeech', 'voiceProfileRequired', 'voiceCheckUnavailable']) {
      expect(cleEtatVocal(etat)).toBe(`talk.stage.${etat}`);
    }
    expect(cleEtatVocal('voiceNotRecognized')).toBe('talk.stage.voiceNotRecognized');
  });
  it('ne laisse pas un texte serveur arbitraire remplacer le titre', () => {
    for (const valeur of [null, {}, '__proto__', 'constructor', 'Listening · speak']) {
      expect(cleEtatVocal(valeur)).toBeUndefined();
    }
  });
});
