import { describe, expect, it, vi } from 'vitest';

import { MESSAGES } from '../i18n/messages';
import {
  CODES_DU_MICRO,
  ETATS_MICRO,
  TECHNIQUE_MAX,
  classerEchecMicro,
  detailTechnique,
  doitLireEtatAndroid,
  lireEtatDuMicro,
  messageApresLesReglages,
  messageDuMicro,
  ouvrirLesReglagesDuMicro,
  type ClasseEchecMicro,
  type DemanderMicro,
  type EtatPourLeMessage,
} from './echecMicro';
import { ERREURS_VOCALES, cleErreurVocale } from './erreursVocales';
import type { ReponseNatif } from './natif';

const erreur = (nom: string, message = '') => new DOMException(message, nom);
const reponse = (ok: boolean, extra: Partial<ReponseNatif> = {}): ReponseNatif => ({
  type: 'reponse', id: 'b1-1', ok, ...extra,
});

/**
 * 28/09/2026, constat de Carlito : au téléphone, « Parler » disait « L'accès
 * au microphone est bloqué… Réglages Système » pour toute exception du bloc
 * du micro. §5 : un NotReadableError n'est pas un refus.
 */
describe('TestClasserUnEchecDuMicro — l’étape d’abord, le nom ensuite', () => {
  it.each([
    ['NotAllowedError', 'refus'],
    ['PermissionDeniedError', 'refus'],
    ['NotReadableError', 'indisponible'],
    ['TrackStartError', 'indisponible'],
    ['AbortError', 'indisponible'],
    ['NotSupportedError', 'indisponible'],
    ['InvalidStateError', 'indisponible'],
    ['NotFoundError', 'aucunMicro'],
    ['DevicesNotFoundError', 'aucunMicro'],
    ['OverconstrainedError', 'aucunMicro'],
    ['SecurityError', 'pageSansMicro'],
    ['QuelqueChoseError', 'inconnu'],
  ] as const)('avant le flux, %s se classe « %s »', (nom, classe) => {
    expect(classerEchecMicro(erreur(nom), 'avantLeFlux').classe, `${nom} mal classé`).toBe(classe);
  });

  it('un NotReadableError n’est jamais un refus : c’est la WebView sans MODIFY_AUDIO_SETTINGS', () => {
    const echec = classerEchecMicro(erreur('NotReadableError', 'Could not start audio source'), 'avantLeFlux');
    expect(echec.classe, 'le constat du 28/09 : ce nom devenait « accès bloqué »').not.toBe('refus');
  });

  it('navigator.mediaDevices absent (TypeError) : la page n’a pas le micro, ce n’est pas un refus', () => {
    let leve: unknown;
    try {
      (undefined as unknown as MediaDevices).getUserMedia({ audio: true });
    } catch (e) {
      leve = e;
    }
    expect(classerEchecMicro(leve, 'avantLeFlux').classe).toBe('pageSansMicro');
  });

  it('APRÈS le flux, même une AbortError ou un NotAllowedError est un échec audio', () => {
    // L'AudioContext, la capture ou resume() : le micro s'était ouvert.
    for (const nom of ['AbortError', 'NotAllowedError', 'NotSupportedError', 'TypeError']) {
      expect(classerEchecMicro(erreur(nom), 'apresLeFlux').classe, `${nom} après le flux`).toBe('echecAudio');
    }
  });
});

describe('TestLeDetailTechnique — la prochaine capture d’écran dit la cause', () => {
  it('rend « nom · message » de l’erreur', () => {
    expect(detailTechnique(erreur('NotReadableError', 'Could not start audio source')))
      .toBe('NotReadableError · Could not start audio source');
    expect(detailTechnique(erreur('NotAllowedError', 'Permission denied'))).toBe('NotAllowedError · Permission denied');
  });

  it('le nom seul quand le message est vide ou le répète', () => {
    expect(detailTechnique(erreur('NotFoundError'))).toBe('NotFoundError');
    expect(detailTechnique({ name: 'X', message: 'X' })).toBe('X');
  });

  it('borne une trace démesurée à TECHNIQUE_MAX signes, sur une ligne', () => {
    const detail = detailTechnique(new Error(`ligne\n${'a'.repeat(400)}`));
    expect(detail.length, 'un détail qui envahirait l’écran').toBeLessThanOrEqual(TECHNIQUE_MAX);
    expect(detail).not.toContain('\n');
    expect(detail.endsWith('…')).toBe(true);
  });

  it('une valeur qui n’est pas une erreur se lit quand même', () => {
    expect(detailTechnique('occupé')).toBe('occupé');
    expect(detailTechnique(null)).toBe('null');
  });
});

describe('TestLeMessageAuBureau — rien ne change hors des nouvelles classes', () => {
  const auBureau = (classe: ClasseEchecMicro) => messageDuMicro({ classe, auTelephone: false, etat: 'inconnu' });

  it('le refus garde le message de macOS, sans bouton', () => {
    expect(auBureau('refus')).toEqual({ code: 'microphone-denied', reglages: false });
  });

  it('les autres classes ont leur propre phrase, jamais celle du refus', () => {
    const classes: ClasseEchecMicro[] = ['indisponible', 'aucunMicro', 'pageSansMicro', 'echecAudio', 'inconnu'];
    for (const classe of classes) {
      const message = auBureau(classe);
      expect(message.code, `${classe} disait « accès bloqué »`).not.toBe('microphone-denied');
      expect(message.code, `${classe} au bureau parle d’Android`).not.toMatch(/^microphone-phone-/);
      expect(message.reglages).toBe(false);
    }
  });
});

describe('TestLeMessageAuTelephone — l’état d’Android décide, jamais les Réglages du Mac', () => {
  const auTelephone = (classe: ClasseEchecMicro, etat: EtatPourLeMessage) =>
    messageDuMicro({ classe, auTelephone: true, etat });

  it('aucune combinaison ne désigne les Réglages Système de macOS', () => {
    const classes: ClasseEchecMicro[] = ['refus', 'indisponible', 'aucunMicro', 'pageSansMicro', 'echecAudio', 'inconnu'];
    const etats: EtatPourLeMessage[] = [...ETATS_MICRO, 'verbeInconnu', 'inconnu', 'enAttente'];
    for (const classe of classes) {
      for (const etat of etats) {
        expect(auTelephone(classe, etat).code, `${classe} / ${etat}`).not.toBe('microphone-denied');
      }
    }
  });

  it('en attente de micro/etat : on le dit, sans bouton ni instruction', () => {
    expect(auTelephone('refus', 'enAttente')).toEqual({ code: 'microphone-phone-checking', reglages: false });
    expect(auTelephone('indisponible', 'enAttente').code).toBe('microphone-phone-checking');
  });

  it('refus définitif : le message d’Android et le bouton', () => {
    expect(auTelephone('refus', 'refuseDefinitivement')).toEqual({ code: 'microphone-phone-denied-forever', reglages: true });
  });

  it('refusé ou jamais demandé : le même texte, avec le bouton — permission_handler ne sait pas les distinguer', () => {
    expect(auTelephone('refus', 'refuse')).toEqual({ code: 'microphone-phone-denied', reglages: true });
    expect(auTelephone('refus', 'aDemander')).toEqual(auTelephone('refus', 'refuse'));
  });

  it('accordé par Android, refusé quand même : c’est la coquille, on le dit tel quel', () => {
    expect(auTelephone('refus', 'accorde')).toEqual({ code: 'microphone-phone-refused-by-app', reglages: false });
  });

  it('une coquille ancienne (verbeInconnu) : les instructions en texte, sans bouton', () => {
    expect(auTelephone('refus', 'verbeInconnu')).toEqual({ code: 'microphone-phone-denied-unknown', reglages: false });
    expect(auTelephone('refus', 'inconnu').reglages, 'aucun bouton qui n’ouvrirait rien (§5)').toBe(false);
  });

  it('indisponible + verbeInconnu : l’app est trop ancienne, conseiller les réglages ne servirait à rien', () => {
    // Les trois APK construits avant ce contrat n'ont pas MODIFY_AUDIO_SETTINGS.
    expect(auTelephone('indisponible', 'verbeInconnu')).toEqual({ code: 'microphone-phone-app-outdated', reglages: false });
  });

  it('indisponible + accordé : Android n’a pas pu l’ouvrir, sans affirmer la cause', () => {
    expect(auTelephone('indisponible', 'accorde')).toEqual({ code: 'microphone-phone-busy', reglages: false });
    expect(auTelephone('indisponible', 'inconnu').code).toBe('microphone-phone-busy-unknown');
  });

  it('indisponible alors qu’Android dit « non accordé » : la permission d’abord', () => {
    expect(auTelephone('indisponible', 'refuseDefinitivement').reglages).toBe(true);
    expect(auTelephone('indisponible', 'refuse').code).toBe('microphone-phone-denied');
  });

  it('restreint : le système, sans bouton', () => {
    expect(auTelephone('refus', 'restreint')).toEqual({ code: 'microphone-phone-restricted', reglages: false });
  });

  it('seuls le refus et l’indisponible interrogent Android', () => {
    expect(doitLireEtatAndroid('refus')).toBe(true);
    expect(doitLireEtatAndroid('indisponible')).toBe(true);
    for (const classe of ['aucunMicro', 'pageSansMicro', 'echecAudio', 'inconnu'] as const) {
      expect(doitLireEtatAndroid(classe), `${classe} ne dépend pas d’une permission`).toBe(false);
    }
  });

  it('un échec audio ou inconnu au téléphone a sa phrase, qui renvoie au détail affiché', () => {
    // 28/09/2026, revue : la phrase du bureau renvoyait « aux journaux », que
    // personne ne peut ouvrir sur le téléphone.
    expect(auTelephone('echecAudio', 'inconnu')).toEqual({ code: 'microphone-phone-audio-failed', reglages: false });
    expect(auTelephone('inconnu', 'inconnu')).toEqual({ code: 'microphone-phone-failed', reglages: false });
  });

  it('au retour des réglages, un micro accordé se dit — sans relancer quoi que ce soit', () => {
    expect(messageApresLesReglages('refus', 'accorde')).toEqual({ code: 'microphone-phone-now-allowed', reglages: false });
    expect(messageApresLesReglages('refus', 'refuseDefinitivement').reglages).toBe(true);
  });
});

describe('TestChaqueCodeASaPhrase', () => {
  it('chaque code du micro est dans ERREURS_VOCALES, et sa clé existe en fr et en en', () => {
    // Un code oublié s'affichait BRUT dans l'orbe (« microphone-busy »).
    for (const code of CODES_DU_MICRO) {
      expect(ERREURS_VOCALES, `${code} absent de la table`).toHaveProperty(code);
      const cle = cleErreurVocale(code);
      expect(MESSAGES.en, `${cle} manque en anglais`).toHaveProperty(cle);
      expect(MESSAGES.fr, `${cle} manque en français`).toHaveProperty(cle);
    }
  });

  it('un code inconnu retombe sur « la séance n’a pas pu démarrer », jamais sur le code', () => {
    expect(cleErreurVocale('microphone-inexistant')).toBe('talk.sessionFailed');
    expect(cleErreurVocale('constructor'), 'une propriété du prototype n’est pas un code').toBe('talk.sessionFailed');
  });

  const cleDe = (code: string) => cleErreurVocale(code) as keyof typeof MESSAGES.fr;
  const auTelephone = CODES_DU_MICRO.filter((c) => c.startsWith('microphone-phone-'));

  it('les phrases du téléphone ne renvoient jamais à des journaux qu’il n’a pas', () => {
    for (const code of auTelephone) {
      expect(MESSAGES.fr[cleDe(code)], code).not.toMatch(/journaux/);
      expect(MESSAGES.en[cleDe(code)], code).not.toMatch(/\blogs?\b/);
    }
  });

  it('un chemin à suivre à la main nomme aussi « Diapason dev », l’app que Carlito utilise', () => {
    // 28/09/2026, revue : « Paramètres › Applis › Diapason » désignait l'app
    // de production, installée À CÔTÉ de « Diapason dev » (build.gradle.kts).
    for (const cle of ['talk.micro.telephone.refuseSansEtat', 'talk.micro.reglagesIndisponibles', 'talk.micro.reglagesEchec'] as const) {
      expect(MESSAGES.fr[cle], cle).toContain('« Diapason dev »');
      expect(MESSAGES.en[cle], cle).toContain('“Diapason dev”');
    }
    for (const [cle, texte] of Object.entries(MESSAGES.fr)) {
      expect(texte, `${cle} mène à la mauvaise app`).not.toMatch(/Applis › Diapason ›/);
    }
    for (const [cle, texte] of Object.entries(MESSAGES.en)) {
      expect(texte, `${cle} leads to the wrong app`).not.toMatch(/Apps › Diapason ›/);
    }
  });

  it('le refus d’une coquille qui a eu l’accord d’Android ne devine aucune cause (§34)', () => {
    const cle = cleDe('microphone-phone-refused-by-app');
    expect(MESSAGES.fr[cle], 'deux causes impossibles énumérées').not.toMatch(/verrouill|autre adresse|simultan/);
    expect(MESSAGES.en[cle]).not.toMatch(/locked|another address|simultaneous/);
  });

  it('le refus « définitif » n’affirme pas qu’Android ne demandera plus (banc 5 bis)', () => {
    // permission_handler le rend aussi quand Android montrerait l'invite.
    const cle = cleDe('microphone-phone-denied-forever');
    expect(MESSAGES.fr[cle]).not.toMatch(/ne demande plus/);
    expect(MESSAGES.fr[cle]).toContain('sans doute');
    expect(MESSAGES.en[cle]).not.toMatch(/no longer asks/);
    expect(MESSAGES.en[cle]).toContain('probably');
  });

  it('les phrases du téléphone ne nomment jamais les Réglages Système du Mac', () => {
    for (const code of CODES_DU_MICRO.filter((c) => c.startsWith('microphone-phone-'))) {
      const cle = cleErreurVocale(code) as keyof typeof MESSAGES.fr;
      expect(MESSAGES.fr[cle], code).not.toMatch(/Réglages Système/);
      expect(MESSAGES.en[cle], code).not.toMatch(/System Settings/);
    }
  });
});

describe('TestLeVerbeMicro — lire l’état et ouvrir les réglages', () => {
  it('etat : lit donnees.etat, sans rien d’autre', async () => {
    const demander = vi.fn<DemanderMicro>(async () => reponse(true, { donnees: { etat: 'refuseDefinitivement' } }));
    expect(await lireEtatDuMicro(demander)).toBe('refuseDefinitivement');
    expect(demander).toHaveBeenCalledWith('micro', { action: 'etat' });
  });

  it('etat au premier niveau de la réponse : jeté par le pont, donc inconnu', async () => {
    const demander: DemanderMicro = async () => ({ ...reponse(true), etat: 'accorde' }) as ReponseNatif;
    expect(await lireEtatDuMicro(demander)).toBe('inconnu');
  });

  it('une coquille ancienne rend verbeInconnu ; un délai, un refus ou un état étranger : inconnu', async () => {
    expect(await lireEtatDuMicro(async () => reponse(false, { erreur: 'verbeInconnu' }))).toBe('verbeInconnu');
    expect(await lireEtatDuMicro(async () => reponse(false, { erreur: 'actionInconnue' }))).toBe('inconnu');
    expect(await lireEtatDuMicro(async () => { throw new Error('délai'); })).toBe('inconnu');
    expect(await lireEtatDuMicro(async () => reponse(true, { donnees: { etat: 'peutEtre' } }))).toBe('inconnu');
  });

  it('reglages ouverts ou délai expiré derrière eux : rien à afficher', async () => {
    const demander = vi.fn<DemanderMicro>(async () => reponse(true));
    expect(await ouvrirLesReglagesDuMicro(demander)).toBeNull();
    expect(demander).toHaveBeenCalledWith('micro', { action: 'reglages' });
    const avertir = vi.spyOn(console, 'warn').mockImplementation(() => {});
    try {
      expect(await ouvrirLesReglagesDuMicro(async () => { throw new Error('délai'); }), 'l’app est passée derrière les Réglages').toBeNull();
    } finally {
      avertir.mockRestore();
    }
  });

  it('la phrase de la coquille (le cadenas) se montre telle quelle ; un code jamais', async () => {
    const phrase = 'Déverrouillez Diapason pour ouvrir ses réglages.';
    expect(await ouvrirLesReglagesDuMicro(async () => reponse(false, { erreur: phrase }))).toEqual({ texte: phrase });
    expect(await ouvrirLesReglagesDuMicro(async () => reponse(false, { erreur: 'actionInconnue' })))
      .toEqual({ cle: 'talk.micro.reglagesIndisponibles' });
    expect(await ouvrirLesReglagesDuMicro(async () => reponse(false, { erreur: 'verbeInconnu' })))
      .toEqual({ cle: 'talk.micro.reglagesIndisponibles' });
    expect(await ouvrirLesReglagesDuMicro(async () => reponse(false, { erreur: 'bizarre' })))
      .toEqual({ cle: 'talk.micro.reglagesEchec' });
    expect(await ouvrirLesReglagesDuMicro(async () => reponse(false))).toEqual({ cle: 'talk.micro.reglagesEchec' });
  });
});
