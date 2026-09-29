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
  resume = vi.fn(async () => { this.state = 'running'; });
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
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

describe('§100 — l’état suit la lecture réellement en file', () => {
  it('réveille la sortie dans le geste, puis la conserve après interruption (§78)', async () => {
    let toucher = true;
    vi.stubGlobal('AudioContext', class extends Contexte {
      state = 'suspended';
      resume = vi.fn(() => {
        if (toucher) { this.state = 'running'; return Promise.resolve(); }
        return new Promise<void>(() => {});
      });
    });
    const publier = vi.fn();
    const lecture = new LectureVocale(publier);
    const preparation = lecture.preparer();
    toucher = false;
    await preparation;
    const contexte = Contexte.tous[0];
    expect(contexte.resume, 'le toucher autorise le lecteur avant le réseau').toHaveBeenCalledOnce();
    expect(publier, 'préparer le son ne prétend pas encore parler ni écouter').not.toHaveBeenCalled();
    lecture.ajouter(trame, 24000);
    const ancienCallback = contexte.sources[0].onended;
    lecture.interrompre();
    expect(contexte.close, 'une interruption garde le lecteur autorisé').not.toHaveBeenCalled();
    contexte.currentTime = 1;
    lecture.ajouter(trame, 24000);
    expect(Contexte.tous).toHaveLength(1);
    expect(contexte.sources[1].start).toHaveBeenCalledWith(1.06);
    publier.mockClear(); ancienCallback?.();
    expect(publier).not.toHaveBeenCalled();
    lecture.arreter();
    expect(contexte.close, 'terminer ferme réellement la sortie').toHaveBeenCalledOnce();
  });

  it('borne un réveil refusé silencieusement par le navigateur', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('AudioContext', class extends Contexte {
      state = 'suspended';
      resume = vi.fn(() => new Promise<void>(() => {}));
    });
    const publier = vi.fn(), echec = vi.fn();
    const lecture = new LectureVocale(publier, echec);
    lecture.ajouter(trame, 24000);
    lecture.ajouter(trame, 24000);
    expect(publier.mock.calls.every(([, parle]) => !parle), 'aucun faux état « parle »').toBe(true);
    await vi.advanceTimersByTimeAsync(2000);
    expect(Contexte.tous[0].resume, 'un seul réveil pour les morceaux en attente').toHaveBeenCalledOnce();
    expect(echec).toHaveBeenCalledOnce();
    expect(Contexte.tous[0].sources.every(s => s.stop.mock.calls.length === 1)).toBe(true);
    lecture.arreter();
    expect(vi.getTimerCount()).toBe(0);
  });

  it('un réveil tardif après fermeture ne rejoue rien dans la séance suivante', async () => {
    let finir!: () => void;
    vi.stubGlobal('AudioContext', class extends Contexte {
      state = 'suspended';
      resume = vi.fn(() => new Promise<void>(resolve => { finir = resolve; }));
    });
    const publier = vi.fn(), echec = vi.fn();
    const lecture = new LectureVocale(publier, echec);
    lecture.ajouter(trame, 24000);
    lecture.arreter();
    publier.mockClear(); finir();
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
    expect(publier).not.toHaveBeenCalled();
    expect(echec).not.toHaveBeenCalled();
  });

  it('remonte un rejet de resume au lieu de prétendre jouer', async () => {
    vi.stubGlobal('AudioContext', class extends Contexte {
      state = 'suspended';
      resume = vi.fn(async () => { throw new DOMException('gesture', 'NotAllowedError'); });
    });
    const lecture = new LectureVocale(vi.fn());
    await expect(lecture.preparer()).rejects.toThrow('gesture');
    lecture.arreter();
  });

  it('revient à l’écoute après le dernier morceau, pas après le premier', () => {
    const publier = vi.fn();
    const lecture = new LectureVocale(publier);
    lecture.ajouter(trame, 24000);
    lecture.ajouter(trame, 24000);
    const contexte = Contexte.tous[0];
    expect(contexte.sources[0].start).toHaveBeenCalledWith(0.06);
    expect(contexte.sources[1].start.mock.calls[0][0]).toBeCloseTo(0.07);
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
    expect(contexte.sources[1].start).toHaveBeenCalledWith(2.06);
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
  it('joue une phrase préparée sans trou même si la livraison varie de quelques millisecondes', () => {
    const lecture = new LectureVocale(vi.fn());
    const morceau = btoa('\x00\x00'.repeat(11520)); // 480 ms par morceau.
    lecture.ajouter(morceau, 24000);
    const contexte = Contexte.tous[0];
    contexte.currentTime = 0.014;
    lecture.ajouter(morceau, 24000);
    contexte.currentTime = 0.039;
    lecture.ajouter(morceau, 24000);
    const debuts = contexte.sources.map((source) => source.start.mock.calls[0][0]);
    expect(debuts[1] - debuts[0]).toBeCloseTo(0.48);
    expect(debuts[2] - debuts[1]).toBeCloseTo(0.48);
    lecture.arreter();
  });
});
