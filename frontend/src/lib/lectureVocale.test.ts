import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { LectureVocale } from './lectureVocale';

class Source {
  buffer: { duration: number } | null = null;
  onended: (() => void) | null = null;
  connect = vi.fn(); disconnect = vi.fn(); start = vi.fn(); stop = vi.fn();
}
class Contexte {
  static tous: Contexte[] = [];
  sources: Source[] = [];
  currentTime = 0;
  state = 'running';
  destination = {};
  sortie = { connect: vi.fn(), disconnect: vi.fn() };
  resume = vi.fn(async () => {});
  close = vi.fn(async () => { this.state = 'closed'; });
  constructor() { Contexte.tous.push(this); }
  createGain() { return this.sortie; }
  createBuffer(_canaux: number, taille: number, frequence: number) {
    return { duration: taille / frequence, copyToChannel: vi.fn() };
  }
  createBufferSource() { const source = new Source(); this.sources.push(source); return source; }
}
const trame = btoa('\x00\x00'.repeat(240));
beforeEach(() => { Contexte.tous = []; vi.stubGlobal('AudioContext', Contexte); });
afterEach(() => vi.unstubAllGlobals());

describe('§100 — l’état suit la lecture réellement en file', () => {
  it('revient à l’écoute après le dernier morceau, pas après le premier', () => {
    const publier = vi.fn();
    const lecture = new LectureVocale(publier);
    lecture.ajouter(trame, 24000);
    lecture.ajouter(trame, 24000);
    const contexte = Contexte.tous[0];
    expect(contexte.sources[1].start).toHaveBeenCalledWith(0.01);
    contexte.sources[0].onended?.();
    expect(publier).toHaveBeenLastCalledWith(contexte.sortie, true);
    contexte.sources[1].onended?.();
    expect(publier).toHaveBeenLastCalledWith(contexte.sortie, false);
    expect(contexte.sources.every((source) => source.disconnect.mock.calls.length === 1)).toBe(true);
    lecture.arreter();
  });
  it('arrête toutes les sources sans laisser un callback ancien modifier la nouvelle réponse', () => {
    const publier = vi.fn();
    const lecture = new LectureVocale(publier);
    lecture.ajouter(trame, 24000);
    const ancien = Contexte.tous[0];
    const finTardive = ancien.sources[0].onended;
    lecture.arreter();
    expect(ancien.sources[0].stop).toHaveBeenCalledOnce();
    expect(ancien.close).toHaveBeenCalledOnce();
    lecture.ajouter(trame, 24000);
    publier.mockClear();
    finTardive?.();
    expect(publier, 'une ancienne lecture ne doit plus publier d’état').not.toHaveBeenCalled();
    lecture.arreter();
    lecture.arreter();
    expect(Contexte.tous[1].close).toHaveBeenCalledOnce();
  });
  it('réutilise la sortie après un silence et réveille un contexte suspendu', () => {
    const lecture = new LectureVocale(vi.fn());
    lecture.ajouter(trame, 24000);
    const contexte = Contexte.tous[0];
    contexte.sources[0].onended?.();
    contexte.currentTime = 2;
    contexte.state = 'suspended';
    lecture.ajouter(trame, 24000);
    expect(Contexte.tous).toHaveLength(1);
    expect(contexte.sources[1].start).toHaveBeenCalledWith(2);
    expect(contexte.resume).toHaveBeenCalledOnce();
    lecture.arreter();
  });
  it('refuse les trames corrompues sans lancer de lecture', () => {
    const publier = vi.fn();
    const lecture = new LectureVocale(publier);
    lecture.ajouter('', 24000);
    expect(() => lecture.ajouter(btoa('x'), 24000)).toThrow();
    expect(() => lecture.ajouter(trame, NaN)).toThrow();
    expect(publier).not.toHaveBeenCalled();
  });
});
