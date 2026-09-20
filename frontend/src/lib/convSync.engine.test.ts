import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Conversation, ConversationStore } from '../types';

const reseau = vi.hoisted(() => vi.fn());
vi.mock('./api', () => ({ apiFetch: reseau, getApiKey: () => 'cle-de-test' }));
let store: typeof import('./store');
let sync: typeof import('./convSync');
let stockage: Map<string, string>;
const ecoutes: Array<[EventTarget, string, EventListenerOrEventListenerObject]> = [];
const reponse = (corps: unknown, status = 200) => ({ ok: status < 400, status, json: async () => corps });
const conv = (content = 'local', updatedAt = 10): Conversation => ({
  id: 'a', title: 'Titre', createdAt: 1, updatedAt, model: 'test',
  messages: [{ id: 'r', role: 'assistant', timestamp: 2, content }],
});
const magasin = (c = conv()): ConversationStore => ({ version: 1, activeId: 'a', conversations: { a: c } });
const differee = <T,>() => { let resolve!: (v: T) => void; const promise = new Promise<T>((r) => { resolve = r; }); return { promise, resolve }; };

beforeEach(async () => {
  vi.resetModules(); vi.useFakeTimers(); reseau.mockReset();
  stockage = new Map();
  const local = { getItem: (k: string) => stockage.get(k) ?? null, setItem: (k: string, v: string) => { stockage.set(k, v); }, removeItem: (k: string) => { stockage.delete(k); } };
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
  store.useAppStore.getState().loadMessages('a');
});
afterEach(() => {
  for (const [cible, nom, fn] of ecoutes.splice(0)) cible.removeEventListener(nom, fn);
  vi.clearAllTimers(); vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals();
});

describe('les deux vues et les écritures retardées', () => {
  it('mutualise les GET et retient le curseur pendant un flux', async () => {
    const attente = differee<ReturnType<typeof reponse>>();
    reseau.mockReturnValueOnce(attente.promise);
    store.useAppStore.getState().setStreamState({ isStreaming: true, conversationId: 'a' });
    const a = sync.tirer(); const b = sync.tirer();
    expect(a).toBe(b); expect(reseau).toHaveBeenCalledTimes(1);
    attente.resolve(reponse({ conversations: [conv('distante plus complète', 20)], seq: 4 }));
    await a;
    expect(JSON.parse(stockage.get(sync.ETAT_SYNC_KEY)!).curseur).toBe(0);
    expect(store.loadConversations().conversations.a.messages[0].content).toBe('local');
    store.useAppStore.getState().resetStream();
    reseau.mockResolvedValueOnce(reponse({ conversations: [conv('distante plus complète', 20)], seq: 4 }));
    await sync.tirer();
    expect(store.useAppStore.getState().messages[0].content).toBe('distante plus complète');
    expect(JSON.parse(stockage.get(sync.ETAT_SYNC_KEY)!).curseur).toBe(4);
  });
  it('une réponse PUT ancienne ne remplace pas le fragment, le titre ou l’épingle récents', async () => {
    const attente = differee<ReturnType<typeof reponse>>();
    reseau.mockReturnValueOnce(attente.promise);
    const poussee = sync.pousser();
    const envoyee = JSON.parse(reseau.mock.calls[0][1].body);
    const app = store.useAppStore.getState();
    app.updateLastAssistant('a', 'local beaucoup plus complet');
    app.renameConversation('a', 'Nouveau titre'); app.togglePinConversation('a');
    attente.resolve(reponse({ conversation: envoyee })); await poussee;
    const courant = store.loadConversations().conversations.a;
    expect(courant.messages[0].content).toBe('local beaucoup plus complet');
    expect(courant.title).toBe('Nouveau titre'); expect(courant.pinned).toBe(true);
    reseau.mockImplementation(async (_url, init) => reponse({ conversation: JSON.parse(init.body) }));
    await sync.pousser();
    expect(JSON.parse(reseau.mock.calls[reseau.mock.calls.length - 1][1].body)).toEqual(courant);
  });
  it('réessaie une panne réseau avec le texte en mémoire même si le disque est plein', async () => {
    vi.spyOn(localStorage, 'setItem').mockImplementation(() => { throw Error('quota'); });
    store.useAppStore.getState().updateLastAssistant('a', 'texte conservé malgré le quota');
    reseau.mockRejectedValueOnce(Error('hors ligne'));
    await sync.pousser();
    reseau.mockImplementation(async (_url, init) => reponse({ conversation: JSON.parse(init.body) }));
    await sync.pousser();
    expect(JSON.parse(reseau.mock.calls[reseau.mock.calls.length - 1][1].body).messages[0].content).toBe('texte conservé malgré le quota');
  });
  it('une suppression pendant un PUT ne ressuscite pas à son retour', async () => {
    const attente = differee<ReturnType<typeof reponse>>();
    reseau.mockReturnValueOnce(attente.promise).mockResolvedValue(reponse({ deleted: true }));
    const poussee = sync.pousser();
    store.useAppStore.getState().deleteConversation('a');
    sync.programmerSuppressionsServeur(['a']);
    attente.resolve(reponse({ conversation: conv() })); await poussee;
    expect(store.loadConversations().conversations.a).toBeUndefined();
    expect(reseau.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(true);
  });
  it('la fusion réutilise les anciens objets sans changer les valeurs du contrat', () => {
    const locale = conv(); const distante = structuredClone(locale);
    distante.updatedAt = 30;
    distante.messages.push({ id: 'q2', role: 'user', content: 'Suite', timestamp: 3 });
    const resultat = sync.fusionnerConversations(locale, distante);
    expect(resultat.messages[0]).toBe(locale.messages[0]);
    expect(resultat.messages).toEqual(distante.messages);
  });
  it('actualise le fil consulté pendant qu’un autre reçoit encore sa réponse', async () => {
    const b = { ...conv('B local', 30), id: 'b' };
    store.saveConversations({ ...magasin(), activeId: 'b', conversations: { a: conv(), b } });
    const app = store.useAppStore.getState();
    app.loadConversations(); app.loadMessages('b');
    app.setStreamState({ isStreaming: true, conversationId: 'a' });
    reseau.mockResolvedValueOnce(reponse({ conversations: [{ ...b, messages: [{ ...b.messages[0], content: 'B reçu de l’autre vue' }], updatedAt: 40 }], seq: 5 }));
    await sync.tirer();
    expect(store.useAppStore.getState().messages[0].content).toBe('B reçu de l’autre vue');
    expect(store.loadConversations().conversations.a.messages[0].content).toBe('local');
    expect(store.useAppStore.getState().streamState.conversationId).toBe('a');
  });
  it('ne tire plus hors écran, reprend à la réouverture et pousse immédiatement à la fin', async () => {
    let cachee = false;
    vi.spyOn(document, 'hidden', 'get').mockImplementation(() => cachee);
    reseau.mockImplementation(async (_url, init) => init?.method === 'PUT'
      ? reponse({ conversation: JSON.parse(init.body) })
      : reponse({ conversations: [], seq: 0 }));
    sync.demarrerSyncConversations(); await vi.advanceTimersByTimeAsync(0);
    cachee = true; document.dispatchEvent(new Event('visibilitychange'));
    await vi.advanceTimersByTimeAsync(0); reseau.mockClear();
    await vi.advanceTimersByTimeAsync(30_000);
    expect(reseau).not.toHaveBeenCalled();
    cachee = false; window.dispatchEvent(new Event('diapason:panneau-ouvert'));
    await vi.advanceTimersByTimeAsync(0);
    expect(reseau).toHaveBeenCalledTimes(1);
    const app = store.useAppStore.getState();
    app.setStreamState({ isStreaming: true, conversationId: 'a' });
    app.updateLastAssistant('a', 'réponse terminée'); app.resetStream();
    await vi.advanceTimersByTimeAsync(0);
    expect(reseau.mock.calls.some(([, init]) => init?.method === 'PUT')).toBe(true);
  });
});
