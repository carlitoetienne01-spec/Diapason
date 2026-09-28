// La coupure du flux du chat : la reconnaître, la dire, renvoyer sans doublon.
//
// 26/09/2026, 19:44 : « Erreur : network error » au téléphone — le nom brut
// d'une TypeError de la WebView, collé tel quel dans la bulle, sans dire que
// c'était le réseau ni quoi faire.

import { describe, expect, it } from 'vitest';
import type { ChatMessage } from '../types';
import { translate } from '../i18n/translate';
import {
  CoupureDuFlux,
  cleDeCoupure,
  issueDuFlux,
  lireCoupure,
  lireLeCorps,
  nomBrut,
  preparerRenvoi,
  texteFinal,
} from './coupureDuFlux';

const abandon = () => Object.assign(new Error('The user aborted a request.'), { name: 'AbortError' });

describe('reconnaître une coupure de transport, quel que soit le moteur', () => {
  it.each([
    ['network error', 'response', 'Chromium : le corps SSE interrompu après les en-têtes (26/09, 19:44)'],
    ['Error in body stream', 'response', 'Firefox : le corps interrompu'],
    ['The network connection was lost.', 'response', 'WebKit : NSURLErrorNetworkConnectionLost'],
    ['Failed to fetch', 'request', 'Chromium : la requête n’a jamais abouti'],
    ['Load failed', 'request', 'WebKit (fenêtre Tauri, Safari) : la requête n’a jamais abouti'],
    ['NetworkError when attempting to fetch resource.', 'request', 'Firefox : la requête n’a jamais abouti'],
  ] as const)('« %s » est une coupure (%s) — %s', (mot, pendant, _moteur) => {
    const coupure = lireCoupure(new TypeError(mot), true);
    expect(coupure, `« ${mot} » doit se dire comme une coupure, pas « Erreur : ${mot} »`).not.toBeNull();
    expect(coupure!.during).toBe(pendant);
    expect(coupure!.detail, 'le nom brut, affiché en petit sous la phrase').toBe(`TypeError: ${mot}`);
    expect(coupure!.overTailnet).toBe(true);
  });

  it('une lecture du corps qui échoue est une coupure PENDANT la réponse, quel que soit le mot', () => {
    const coupure = lireCoupure(new CoupureDuFlux(new TypeError('Load failed')), false);
    expect(coupure, 'la place de l’échec décide, pas le vocabulaire du moteur').toEqual({
      detail: 'TypeError: Load failed',
      during: 'response',
      overTailnet: false,
    });
  });

  it.each([
    ['un arrêt demandé', abandon()],
    ['un refus du serveur (tailscale serve devant un Mac arrêté)', new Error('Chat request failed: 502')],
    ['un refus de la recherche', new Error('Research request failed: 500')],
    ['un bug du bundle', new TypeError("Cannot read properties of undefined (reading 'choices')")],
    ['une URL d’API invalide', new Error("L'URL de l'API est invalide. Vérifiez Réglages → Connexion → URL de l'API.")],
    ['un mot du transport noyé dans une autre phrase', new Error('Unexpected network error in the parser')],
    ['une chaîne levée telle quelle', 'Failed to fetch'],
    ['rien', undefined],
  ])('%s n’est pas une coupure', (_nom, erreur) => {
    expect(lireCoupure(erreur, true), 'seule une coupure du réseau reçoit la phrase et « Renvoyer »').toBeNull();
  });

  it('un arrêt demandé n’est jamais une coupure, même dit avec les mots du réseau', () => {
    const arret = Object.assign(new Error('Load failed'), { name: 'AbortError' });
    expect(lireCoupure(arret, true), 'Arrêter n’appelle pas « Renvoyer »').toBeNull();
  });

  it('le nom brut garde le type et le message, ou le nom seul', () => {
    expect(nomBrut(new TypeError('network error'))).toBe('TypeError: network error');
    expect(nomBrut(Object.assign(new Error(''), { name: 'TypeError' }))).toBe('TypeError');
    expect(nomBrut(new CoupureDuFlux(new TypeError('network error'))), 'la cause, pas l’enveloppe')
      .toBe('TypeError: network error');
  });
});

describe('lire le corps : l’échec d’une lecture devient une CoupureDuFlux', () => {
  it('une lecture qui échoue lève une CoupureDuFlux qui garde la cause', async () => {
    const lecteur = { read: () => Promise.reject(new TypeError('network error')) };
    const erreur = await lireLeCorps(lecteur).catch((e: unknown) => e);
    expect(erreur, 'sinon la bulle dirait encore « Erreur : network error »').toBeInstanceOf(CoupureDuFlux);
    expect((erreur as CoupureDuFlux).brut).toBe('TypeError: network error');
  });

  it('un arrêt demandé reste un AbortError, pour garder « (Génération interrompue) »', async () => {
    const arret = abandon();
    const erreur = await lireLeCorps({ read: () => Promise.reject(arret) }).catch((e: unknown) => e);
    expect(erreur, 'le bouton Arrêter n’est pas une coupure').toBe(arret);
  });

  it('une lecture qui réussit passe telle quelle', async () => {
    const morceau = { done: false as const, value: new Uint8Array([1]) };
    await expect(lireLeCorps({ read: () => Promise.resolve(morceau) })).resolves.toBe(morceau);
  });
});

const t = (cle: string, vars?: Record<string, string | number>) => translate('fr', cle as never, vars);

describe('ce que la bulle garde quand le flux s’arrête', () => {
  it('une coupure garde le texte reçu tel quel, sans « Erreur : network error »', () => {
    const issue = issueDuFlux(new CoupureDuFlux(new TypeError('network error')), 'Début de rép', true, t);
    expect(issue.texte, 'le modèle relirait l’erreur comme sa propre réponse').toBe('Début de rép');
    expect(issue.statut).toBe('error');
    expect(issue.coupure?.during).toBe('response');
  });

  it('une coupure sans texte reste vide : la phrase vient de connectionLost, pas du texte', () => {
    const issue = issueDuFlux(new TypeError('Failed to fetch'), '', false, t);
    expect(issue.texte).toBe('');
    expect(texteFinal(issue.texte, issue.coupure, t), 'ni « Aucune réponse n’a été générée »').toBe('');
  });

  it('un arrêt demandé et une autre erreur gardent leurs phrases d’avant', () => {
    const arret = issueDuFlux(abandon(), '', true, t);
    expect(arret).toEqual({ texte: '(Génération interrompue)', coupure: null, statut: 'interrupted' });
    const refus = issueDuFlux(new Error('Chat request failed: 502'), '', true, t);
    expect(refus).toEqual({ texte: 'Erreur : Chat request failed: 502', coupure: null, statut: 'error' });
    expect(issueDuFlux(new Error('Chat request failed: 502'), 'Déjà reçu', true, t).texte,
      'le texte déjà reçu prime, comme avant').toBe('Déjà reçu');
  });

  it('sans texte ni coupure, « Aucune réponse n’a été générée »', () => {
    expect(texteFinal('', null, t)).toBe('Aucune réponse n’a été générée. Réessayez.');
    expect(texteFinal('Réponse', null, t)).toBe('Réponse');
  });
});

describe('la phrase dite, au téléphone ou au Mac', () => {
  it('au téléphone, pendant la réponse : la phrase demandée, en français et en anglais', () => {
    const cle = cleDeCoupure({ detail: 'TypeError: network error', during: 'response', overTailnet: true });
    expect(translate('fr', cle)).toBe(
      'La connexion au Mac s’est coupée pendant la réponse (réseau ou mise en veille du téléphone).',
    );
    expect(translate('en', cle)).toMatch(/connection to the Mac dropped during the reply/);
  });

  it('chaque cas a sa phrase : ni le téléphone ne parle de redémarrage, ni le Mac de veille du téléphone', () => {
    const cles = [true, false].flatMap((overTailnet) =>
      (['request', 'response'] as const).map((during) => cleDeCoupure({ detail: '', during, overTailnet })),
    );
    expect(new Set(cles).size, 'quatre situations, quatre phrases').toBe(4);
    for (const cle of cles) {
      const fr = translate('fr', cle);
      const auTelephone = cle.startsWith('chat.coupure.telephone');
      expect(fr.includes('téléphone'), `${cle} : « ${fr} »`).toBe(auTelephone);
    }
    expect(translate('fr', cleDeCoupure({ detail: '', during: 'request', overTailnet: true })),
      'une requête qui n’a jamais abouti ne se dit pas « pendant la réponse »').not.toMatch(/pendant la réponse/);
  });
});

const q = (id: string, extra: Partial<ChatMessage> = {}): ChatMessage =>
  ({ id, role: 'user', content: `Question ${id}`, timestamp: 1, ...extra });
const r = (id: string, extra: Partial<ChatMessage> = {}): ChatMessage =>
  ({ id, role: 'assistant', content: '', timestamp: 2, ...extra });
const coupee = { connectionLost: { detail: 'TypeError: network error', during: 'response' as const, overTailnet: true } };

describe('renvoyer la même question, sans doublon', () => {
  it('rend la question déjà dans le fil, et le fil jusqu’à elle seulement', () => {
    const question = q('q1', { images: ['data:image/png;base64,AAAA'] });
    const fil = [q('q0'), r('r0', { content: 'Réponse entière' }), question, r('r1', { ...coupee, content: 'Début de rép' })];
    const renvoi = preparerRenvoi(fil, 'r1');
    expect(renvoi, 'la dernière bulle, coupée, se renvoie').not.toBeNull();
    expect(renvoi!.question, 'la question n’est pas recopiée : c’est le même message').toBe(question);
    expect(renvoi!.historique.map((m) => m.id), 'la réponse coupée n’entre pas dans ce que le modèle relit')
      .toEqual(['q0', 'r0', 'q1']);
    expect(renvoi!.recherche).toBe(false);
  });

  it('une réponse coupée deux fois se renvoie encore, depuis la dernière', () => {
    const fil = [q('q1'), r('r1', coupee), r('r2', coupee)];
    expect(preparerRenvoi(fil, 'r2')?.historique.map((m) => m.id)).toEqual(['q1']);
    expect(preparerRenvoi(fil, 'r1'), 'une bulle qui n’est plus la dernière ne propose rien').toBeNull();
  });

  it.each([
    ['une question posée depuis', [q('q1'), r('r1', coupee), q('q2')], 'r1'],
    ['une vraie réponse arrivée entre-temps', [q('q1'), r('r0', { content: 'Réponse entière' }), r('r1', coupee)], 'r1'],
    ['une réponse qui n’a pas été coupée', [q('q1'), r('r1', { content: 'Erreur : Chat request failed: 500' })], 'r1'],
    ['un fil sans question', [r('r1', coupee)], 'r1'],
    ['une question en dernière bulle', [q('q1')], 'q1'],
    ['un identifiant absent', [q('q1'), r('r1', coupee)], 'inconnu'],
    ['un fil vide', [], 'r1'],
  ] as const)('pas de renvoi après %s', (_cas, fil, id) => {
    expect(preparerRenvoi([...fil], id), 'rejouer ici enverrait une question qui a déjà eu sa réponse, ou aucune').toBeNull();
  });

  it('une recherche approfondie coupée se renvoie en recherche approfondie', () => {
    const fil = [q('q1'), r('r1', { ...coupee, isResearch: true })];
    expect(preparerRenvoi(fil, 'r1')?.recherche).toBe(true);
  });
});
