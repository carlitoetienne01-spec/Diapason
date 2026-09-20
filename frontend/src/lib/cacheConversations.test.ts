import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ConversationStore } from '../types';
import { creerCacheConversations } from './cacheConversations';
import { creerCadenceFlux } from './cadenceFlux';

const copie = (texte: string): ConversationStore => ({
  version: 1, activeId: 'a', conversations: {
    a: { id: 'a', title: 'Essai', model: 'test', createdAt: 1, updatedAt: 2,
      messages: [{ id: 'r', role: 'assistant', timestamp: 1, content: texte }] },
  },
});
beforeEach(() => vi.useFakeTimers());
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

describe('le cache de travail des discussions', () => {
  it('ne relit et ne parse le disque qu’une fois pour cent fragments', () => {
    const lire = vi.fn(() => JSON.stringify(copie('ancien')));
    const ecrire = vi.fn();
    const cache = creerCacheConversations(lire, ecrire);
    const initial = cache.charger();
    expect(cache.charger()).toBe(initial);
    for (let i = 0; i < 100; i++) {
      cache.sauver(copie('x'.repeat(i + 1)), true);
      expect(cache.charger().conversations.a.messages[0].content).toHaveLength(i + 1);
      vi.advanceTimersByTime(10);
    }
    expect(lire).toHaveBeenCalledTimes(1);
    expect(ecrire).toHaveBeenCalledTimes(1);
    expect(JSON.parse(ecrire.mock.calls[0][0]).conversations.a.messages[0].content).toHaveLength(100);
  });
  it('enregistre le dernier fragment immédiatement à la sortie', () => {
    const ecrire = vi.fn();
    const cache = creerCacheConversations(() => null, ecrire);
    cache.sauver(copie('dernier'), true);
    expect(ecrire).not.toHaveBeenCalled();
    expect(cache.vider()).toBe(true);
    expect(JSON.parse(ecrire.mock.calls[0][0])).toEqual(copie('dernier'));
    vi.advanceTimersByTime(2000);
    expect(ecrire).toHaveBeenCalledTimes(1);
  });
  it('garde la copie récente après un quota plein et réessaie sans la tronquer', () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    let quota = true;
    const ecrire = vi.fn((_texte: string) => { if (quota) throw new Error('quota'); });
    const cache = creerCacheConversations(() => JSON.stringify(copie('ancien')), ecrire);
    cache.charger();
    cache.sauver(copie('complet'));
    expect(cache.charger()).toEqual(copie('complet'));
    expect(cache.vider()).toBe(false);
    quota = false;
    expect(cache.vider()).toBe(true);
    expect(JSON.parse(ecrire.mock.calls[ecrire.mock.calls.length - 1][0])).toEqual(copie('complet'));
  });
  it('une suppression remplace aussi le point de reprise en attente', () => {
    const ecrire = vi.fn();
    const cache = creerCacheConversations(() => null, ecrire);
    cache.sauver(copie('à effacer'), true);
    const vide: ConversationStore = { version: 1, activeId: null, conversations: {} };
    cache.sauver(vide);
    vi.advanceTimersByTime(2000);
    expect(ecrire).toHaveBeenCalledTimes(1);
    expect(cache.charger()).toBe(vide);
  });
});

describe('la cadence du rendu', () => {
  it('publie le premier texte immédiatement et le dernier sans attendre un autre jeton', () => {
    let texte = 'a';
    const vues: string[] = [];
    const cadence = creerCadenceFlux(() => vues.push(texte));
    cadence.demander();
    expect(vues).toEqual(['a']);
    for (let i = 0; i < 20; i++) { texte += 'b'; cadence.demander(); }
    expect(vues).toEqual(['a']);
    vi.advanceTimersByTime(80);
    expect(vues).toEqual(['a', texte]);
  });
  it('flush la sortie cachée et ne publie plus après finalisation', () => {
    const publier = vi.fn();
    const cadence = creerCadenceFlux(publier);
    cadence.demander();
    cadence.demander();
    cadence.vider();
    expect(publier).toHaveBeenCalledTimes(2);
    cadence.demander();
    cadence.annuler();
    vi.advanceTimersByTime(1000);
    expect(publier).toHaveBeenCalledTimes(2);
  });
});
