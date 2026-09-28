import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ChatMessage } from '../types';

class Stockage {
  valeurs = new Map<string, string>();
  refuse = false;
  ecritures = 0;
  getItem(k: string) { return this.valeurs.get(k) ?? null; }
  setItem(k: string, v: string) { if (this.refuse) throw Error('quota'); this.ecritures++; this.valeurs.set(k, v); }
  removeItem(k: string) { this.valeurs.delete(k); }
}
let stockage: Stockage;
let mod: typeof import('./store');
const msg = (id: string, role: ChatMessage['role'], content: string): ChatMessage => ({ id, role, content, timestamp: 1 });
const ecoutes: Array<[EventTarget, string, EventListenerOrEventListenerObject]> = [];

beforeEach(async () => {
  vi.useFakeTimers();
  vi.resetModules();
  stockage = new Stockage();
  vi.stubGlobal('localStorage', stockage);
  vi.stubGlobal('sessionStorage', new Stockage());
  for (const cible of [window, document] as EventTarget[]) {
    const original = cible.addEventListener.bind(cible);
    vi.spyOn(cible, 'addEventListener').mockImplementation((nom, fn, options?: boolean | AddEventListenerOptions) => {
      if (fn) ecoutes.push([cible, nom, fn]);
      original(nom, fn, options);
    });
  }
  mod = await import('./store');
});
afterEach(() => {
  for (const [cible, nom, fn] of ecoutes.splice(0)) cible.removeEventListener(nom, fn);
  vi.clearAllTimers(); vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals();
});

describe('les écritures réelles du store', () => {
  it('conserve le questionnaire reçu en flux après la fin et la relecture', () => {
    const app = mod.useAppStore.getState();
    const id = app.createConversation('test');
    app.addMessage(id, msg('r', 'assistant', ''));
    const questions = { id: 'demande', intro: '', questions: [{ id: 'q1', title: 'Ton objectif ?', options: [{ id: 'o1', label: 'Parler', description: '' }, { id: 'o2', label: 'Étudier', description: '' }] }] };
    app.setStreamState({ isStreaming: true, conversationId: id });
    app.updateLastAssistant(id, 'Ton objectif ?', undefined, undefined, undefined, undefined, undefined, undefined, questions);
    app.updateLastAssistant(id, 'Ton objectif ? Parler / Étudier');
    app.resetStream();
    app.loadMessages(id);
    expect(mod.useAppStore.getState().messages[0].questions).toEqual(questions);
    expect(JSON.parse(stockage.getItem(mod.CONVERSATIONS_KEY)!).conversations[id].messages[0].questions).toEqual(questions);
  });
  it('garde la coupure du réseau sur la réponse, pour la phrase et « Renvoyer » (28/09/2026)', () => {
    const app = mod.useAppStore.getState();
    const id = app.createConversation('test');
    app.addMessage(id, msg('q', 'user', 'Bonjour'));
    app.addMessage(id, msg('r', 'assistant', ''));
    const coupure = { detail: 'TypeError: network error', during: 'response' as const, overTailnet: true };
    app.updateLastAssistant(id, 'Début', undefined, undefined, undefined, undefined, undefined, undefined, undefined, undefined, undefined, coupure);
    expect(mod.useAppStore.getState().messages[1].connectionLost,
      'sans elle, la bulle ne dirait ni la coupure ni comment renvoyer').toEqual(coupure);
    expect(JSON.parse(stockage.getItem(mod.CONVERSATIONS_KEY)!).conversations[id].messages[1].connectionLost,
      'elle voyage avec la conversation : l’autre vue la voit aussi').toEqual(coupure);
  });
  it('ne recrée pas les anciens messages et ne modifie pas les copies en vol', () => {
    const app = mod.useAppStore.getState();
    const id = app.createConversation('test');
    app.addMessage(id, msg('q', 'user', 'Bonjour'));
    app.addMessage(id, msg('r', 'assistant', ''));
    const ancien = mod.loadConversations();
    const avant = mod.useAppStore.getState().messages;
    app.setStreamState({ isStreaming: true, conversationId: id });
    app.updateLastAssistant(id, 'Réponse');
    const apres = mod.useAppStore.getState().messages;
    expect(apres[0]).toBe(avant[0]);
    expect(apres[1]).not.toBe(avant[1]);
    expect(ancien.conversations[id].messages[1].content).toBe('');
    expect(mod.loadConversations().conversations[id].updatedAt).toBeGreaterThan(ancien.conversations[id].updatedAt);
    app.renameConversation(id, 'Renommée');
    app.togglePinConversation(id);
    expect(ancien.conversations[id].title).toBe('Bonjour');
    expect(ancien.conversations[id].pinned).toBeUndefined();
  });
  it('sauve au plus une fois par seconde pendant le flux puis à sa fin', () => {
    const app = mod.useAppStore.getState();
    const id = app.createConversation('test');
    app.addMessage(id, msg('r', 'assistant', ''));
    app.setStreamState({ isStreaming: true, conversationId: id });
    stockage.ecritures = 0;
    for (let i = 0; i < 100; i++) { app.updateLastAssistant(id, `${i}`); vi.advanceTimersByTime(10); }
    expect(stockage.ecritures).toBe(1);
    app.updateLastAssistant(id, 'Dernier');
    app.resetStream();
    expect(stockage.ecritures).toBe(2);
    expect(JSON.parse(stockage.getItem(mod.CONVERSATIONS_KEY)!).conversations[id].messages[0].content).toBe('Dernier');
  });
  it('changer de discussion ne déplace ni la réponse ni un audio tardif', () => {
    const app = mod.useAppStore.getState();
    const a = app.createConversation('test');
    app.addMessage(a, msg('r1', 'assistant', 'réponse 1'));
    const b = app.createConversation('test');
    app.addMessage(b, msg('r2', 'assistant', 'réponse 2'));
    app.setStreamState({ isStreaming: true, conversationId: a });
    app.updateLastAssistant(a, 'A continue');
    expect(mod.useAppStore.getState().messages[0].id).toBe('r2');
    app.addMessage(a, msg('r3', 'assistant', 'réponse suivante'));
    mod.completerAudioMessage(a, 'r1', { url: '/audio' });
    const messages = mod.loadConversations().conversations[a].messages;
    expect(messages[0].audio?.url).toBe('/audio');
    expect(messages[1].audio).toBeUndefined();
    expect(mod.useAppStore.getState().messages[0].id).toBe('r2');
    app.deleteConversation(a);
    mod.completerAudioMessage(a, 'r1', { url: '/retard' });
    expect(mod.loadConversations().conversations[a]).toBeUndefined();
  });
  it('pagehide vide le cache, même si le minuteur n’a pas encore tourné', () => {
    const app = mod.useAppStore.getState();
    const id = app.createConversation('test');
    app.addMessage(id, msg('r', 'assistant', ''));
    app.setStreamState({ isStreaming: true, conversationId: id });
    app.updateLastAssistant(id, 'Sauvé à la sortie');
    window.dispatchEvent(new Event('pagehide'));
    expect(JSON.parse(stockage.getItem(mod.CONVERSATIONS_KEY)!).conversations[id].messages[0].content).toBe('Sauvé à la sortie');
  });
  it('le disque en panne ne fait pas régresser le texte ou la copie à synchroniser', () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    const app = mod.useAppStore.getState();
    const id = app.createConversation('test');
    app.addMessage(id, msg('r', 'assistant', 'ancien'));
    stockage.refuse = true;
    app.updateLastAssistant(id, 'nouveau');
    app.updateLastAssistant(id, 'nouveau complet');
    expect(mod.loadConversations().conversations[id].messages[0].content).toBe('nouveau complet');
    stockage.refuse = false;
    expect(mod.viderSauvegardeConversations()).toBe(true);
  });
});

describe('la sauvegarde des échanges vocaux', () => {
  it('persiste les révisions une seule fois et date chaque vraie écriture', () => {
    const app = mod.useAppStore.getState();
    const id = app.createConversation('local');
    app.recevoirMessagesVocaux(id, [msg('v1', 'user', 'Mon anglais'), msg('v2', 'assistant', 'Écoute.')]);
    const avant = mod.loadConversations().conversations[id];
    app.recevoirMessagesVocaux(id, [msg('v2', 'assistant', 'Écoute. Répète.')]);
    const apres = mod.loadConversations().conversations[id];
    expect(apres.messages).toHaveLength(2);
    expect(apres.title).toBe('Mon anglais');
    expect(apres.updatedAt).toBeGreaterThan(avant.updatedAt);
    const ecritures = stockage.ecritures;
    app.recevoirMessagesVocaux(id, [msg('v2', 'assistant', 'Écoute. Répète.')]);
    expect(stockage.ecritures).toBe(ecritures);
    app.loadMessages(id);
    expect(mod.useAppStore.getState().messages[1].content).toBe('Écoute. Répète.');
  });
  it('un événement tardif ne change pas de fil et ne ressuscite pas une discussion supprimée', () => {
    const app = mod.useAppStore.getState();
    const a = app.createConversation('local');
    const b = app.createConversation('local');
    app.recevoirMessagesVocaux(a, [msg('v1', 'assistant', 'Ancien fil')]);
    expect(mod.useAppStore.getState().activeId).toBe(b);
    expect(mod.useAppStore.getState().messages).toEqual([]);
    app.deleteConversation(a);
    app.recevoirMessagesVocaux(a, [msg('v2', 'assistant', 'Trop tard')]);
    expect(mod.loadConversations().conversations[a]).toBeUndefined();
  });
});
