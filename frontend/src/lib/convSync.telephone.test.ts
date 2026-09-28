// Le moteur de synchronisation servi par le tailnet, sans clé locale.
//
// 28/09/2026 : les gardes « sans clé, ne rien tenter » rendaient la
// synchronisation muette au téléphone depuis le premier jour — zéro GET, zéro
// PUT /v1/conversations dans le journal complet. Ces tests rejouent le
// moteur entier (tirer, pousser, supprimer, curseur) avec `getApiKey() === ''`
// et le signal « servi par le tailnet », puis vérifient qu'un 401 de la
// passerelle (session d'appareil morte) ne boucle pas et ne vide rien.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Conversation, ConversationStore } from '../types';

const reseau = vi.hoisted(() => vi.fn());
const contexte = vi.hoisted(() => ({ cle: '', tailnet: true }));
vi.mock('./api', () => ({ apiFetch: reseau, getApiKey: () => contexte.cle }));
vi.mock('./tailnet', () => ({ serviParLeTailnet: () => contexte.tailnet }));

let store: typeof import('./store');
let sync: typeof import('./convSync');
let stockage: Map<string, string>;
const ecoutes: Array<[EventTarget, string, EventListenerOrEventListenerObject]> = [];

const reponse = (corps: unknown, status = 200) => ({ ok: status < 400, status, json: async () => corps });

// Tapée au téléphone le 26/09, jamais partie : c'est elle qu'on récupère.
const duTelephone: Conversation = {
  id: 'tel', title: 'Au téléphone', createdAt: 1, updatedAt: 10, model: 'test',
  messages: [
    { id: 'q-tel', role: 'user', timestamp: 2, content: 'Question posée au téléphone' },
    { id: 'r-tel', role: 'assistant', timestamp: 3, content: 'Réponse lue au téléphone' },
  ],
};
const duMac: Conversation = {
  id: 'mac', title: 'Au Mac', createdAt: 4, updatedAt: 20, model: 'test',
  messages: [{ id: 'q-mac', role: 'user', timestamp: 5, content: 'Question posée au Mac' }],
};
const magasin = (): ConversationStore => ({ version: 1, activeId: 'tel', conversations: { tel: duTelephone } });

const appels = (methode: string) =>
  reseau.mock.calls.filter(([, init]) => (init?.method ?? 'GET') === methode);

function repondre(get: () => ReturnType<typeof reponse>) {
  reseau.mockImplementation(async (_url: string, init?: RequestInit) => {
    if (init?.method === 'PUT') return reponse({ conversation: JSON.parse(String(init.body)) });
    if (init?.method === 'DELETE') return reponse({ deleted: true, deletedAt: 99 });
    return get();
  });
}

beforeEach(async () => {
  vi.resetModules(); vi.useFakeTimers(); reseau.mockReset();
  contexte.cle = ''; contexte.tailnet = true;
  stockage = new Map();
  const local = {
    getItem: (k: string) => stockage.get(k) ?? null,
    setItem: (k: string, v: string) => { stockage.set(k, v); },
    removeItem: (k: string) => { stockage.delete(k); },
  };
  vi.stubGlobal('localStorage', local); vi.stubGlobal('sessionStorage', local);
  for (const cible of [window, document] as EventTarget[]) {
    const original = cible.addEventListener.bind(cible);
    vi.spyOn(cible, 'addEventListener').mockImplementation((nom, fn, options?: boolean | AddEventListenerOptions) => {
      if (fn) ecoutes.push([cible, nom, fn]); original(nom, fn, options);
    });
  }
  vi.spyOn(console, 'warn').mockImplementation(() => {});
  store = await import('./store'); sync = await import('./convSync');
  store.saveConversations(magasin()); store.useAppStore.getState().loadConversations();
  store.useAppStore.getState().loadMessages('tel');
});

afterEach(() => {
  for (const [cible, nom, fn] of ecoutes.splice(0)) cible.removeEventListener(nom, fn);
  vi.clearAllTimers(); vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals();
});

describe('au téléphone, la synchronisation passe par le cookie, sans clé', () => {
  it('le premier tick tire les conversations du Mac et pousse celles du téléphone', async () => {
    repondre(() => reponse({ conversations: [duMac], deleted: [], seq: 7 }));
    sync.demarrerSyncConversations();
    await vi.advanceTimersByTimeAsync(0);

    const [get] = appels('GET');
    expect(get?.[0], 'le premier tirage demande tout, sans curseur').toBe('/v1/conversations');
    const locales = store.loadConversations().conversations;
    expect(locales.mac?.messages[0].content, 'la conversation du Mac doit arriver au téléphone')
      .toBe('Question posée au Mac');
    expect(locales.tel?.messages.length, 'celle du téléphone ne doit rien perdre').toBe(2);

    const puts = appels('PUT');
    expect(puts.map(([url]) => url), 'seule la conversation inconnue du serveur part')
      .toEqual(['/v1/conversations/tel']);
    expect(JSON.parse(String(puts[0][1].body)).messages.map((m: { id: string }) => m.id))
      .toEqual(['q-tel', 'r-tel']);
    for (const [, init] of reseau.mock.calls) {
      const entetes = (init?.headers ?? {}) as Record<string, string>;
      expect(Object.keys(entetes).map((k) => k.toLowerCase()), 'la passerelle refuse toute clé locale')
        .not.toContain('authorization');
    }

    const etat = JSON.parse(stockage.get(sync.ETAT_SYNC_KEY)!);
    expect(etat.curseur, 'le curseur avance au numéro d’écriture reçu').toBe(7);
    expect(etat.carte).toEqual({ mac: 20, tel: 10 });

    await vi.advanceTimersByTimeAsync(10_000);
    const [, second] = appels('GET');
    expect(second?.[0], 'le tick suivant repart du curseur').toBe('/v1/conversations?since=7');
    expect(appels('PUT').length, 'rien de neuf, rien de repoussé').toBe(1);
  });

  it('une suppression faite au téléphone part en DELETE, sans clé elle aussi', async () => {
    repondre(() => reponse({ conversations: [], deleted: [], seq: 3 }));
    sync.demarrerSyncConversations();
    await vi.advanceTimersByTimeAsync(0);
    store.useAppStore.getState().deleteConversation('tel');
    await vi.advanceTimersByTimeAsync(1_500);

    expect(appels('DELETE').map(([url]) => url)).toEqual(['/v1/conversations/tel']);
    expect(JSON.parse(stockage.get(sync.ETAT_SYNC_KEY)!).suppressions,
      'la file se vide quand le DELETE a abouti').toEqual([]);
  });

  it('hors du tailnet et sans clé, rien ne part — la garde du 16/09 tient toujours', async () => {
    contexte.tailnet = false;
    repondre(() => reponse({ conversations: [duMac], deleted: [], seq: 7 }));
    sync.demarrerSyncConversations();
    store.useAppStore.getState().renameConversation('tel', 'Renommée');
    await vi.advanceTimersByTimeAsync(35_000);
    expect(reseau, 'sans clé ni passerelle, aucune requête').not.toHaveBeenCalled();
  });
});

describe('un 401 de la passerelle : session perdue, rien ne boucle ni ne se vide', () => {
  it('se tait jusqu’à la reprise, garde tout, puis réessaie une fois', async () => {
    stockage.set(sync.ETAT_SYNC_KEY, JSON.stringify({ curseur: 5, suppressions: ['vieille'], carte: { tel: 10 } }));
    reseau.mockResolvedValue(reponse({ detail: 'Aucune session d’appareil valide' }, 401));
    sync.demarrerSyncConversations();
    await vi.advanceTimersByTimeAsync(0);
    expect(reseau, 'le premier tick fait UN GET, et le 401 arrête la poussée').toHaveBeenCalledTimes(1);

    store.useAppStore.getState().renameConversation('tel', 'Renommée pendant la panne');
    await vi.advanceTimersByTimeAsync(60_000);
    expect(reseau, 'six ticks et une modification : aucune requête de plus').toHaveBeenCalledTimes(1);

    const locales = store.loadConversations().conversations;
    expect(locales.tel?.title, 'le 401 ne vide rien').toBe('Renommée pendant la panne');
    expect(locales.tel?.messages.length).toBe(2);
    const etat = JSON.parse(stockage.get(sync.ETAT_SYNC_KEY)!);
    expect(etat, 'curseur, carte et file des suppressions intacts')
      .toEqual({ curseur: 5, suppressions: ['vieille'], carte: { tel: 10 } });

    reseau.mockReset();
    repondre(() => reponse({ conversations: [], deleted: [], seq: 6 }));
    window.dispatchEvent(new Event('focus'));
    await vi.advanceTimersByTimeAsync(0);
    expect(appels('GET').length, 'la reprise réessaie').toBe(1);
    expect(appels('DELETE').map(([url]) => url), 'la suppression en attente part enfin')
      .toEqual(['/v1/conversations/vieille']);
    expect(appels('PUT').map(([url]) => url), 'le renommage fait pendant la panne part aussi')
      .toEqual(['/v1/conversations/tel']);
  });

  it('au Mac, un 401 reste transitoire : le tick suivant réessaie', async () => {
    contexte.tailnet = false; contexte.cle = 'cle-pas-encore-injectee';
    reseau.mockResolvedValue(reponse({ detail: 'Unauthorized' }, 401));
    sync.demarrerSyncConversations();
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(20_000);
    expect(appels('GET').length, 'le démarrage puis deux ticks : trois GET').toBe(3);
  });
});
