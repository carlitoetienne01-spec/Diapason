import { runInNewContext } from 'node:vm';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { creerCaptureVocale } from './captureVocale';
import code from './captureVocale.worklet.js?raw';

class Noeud {
  connect = vi.fn(); disconnect = vi.fn();
  gain = { value: 1 };
  onaudioprocess: ((event: unknown) => void) | null = null;
}
class Contexte {
  destination = new Noeud();
  state = 'running';
  audioWorklet = { addModule: vi.fn(async (_url: string) => {}) };
  secours = new Noeud();
  muet = new Noeud();
  createGain = () => this.muet;
  createScriptProcessor = vi.fn(() => this.secours);
}
class Worklet extends Noeud {
  static dernier: Worklet;
  port = { onmessage: null as null | ((event: { data: ArrayBuffer }) => void), close: vi.fn() };
  constructor() { super(); Worklet.dernier = this; }
}
afterEach(() => vi.unstubAllGlobals());

describe('§78 — une seule capture, silencieuse et libérée à l’arrêt', () => {
  it('charge le worklet local et ne branche jamais le micro directement aux haut-parleurs', async () => {
    vi.stubGlobal('AudioWorkletNode', Worklet);
    const contexte = new Contexte(); const source = new Noeud(); const recevoir = vi.fn();
    const capture = await creerCaptureVocale(contexte as unknown as AudioContext, source as unknown as AudioNode, recevoir);
    expect(contexte.audioWorklet.addModule).toHaveBeenCalledOnce();
    expect(contexte.createScriptProcessor).not.toHaveBeenCalled();
    expect(contexte.muet.gain.value).toBe(0);
    expect(source.connect).toHaveBeenCalledWith(Worklet.dernier);
    Worklet.dernier.port.onmessage?.({ data: new ArrayBuffer(640) });
    expect(recevoir).toHaveBeenCalledOnce();
    capture.arreter();
    expect(Worklet.dernier.port.onmessage).toBeNull();
    expect(Worklet.dernier.port.close).toHaveBeenCalledOnce();
    expect(source.disconnect).toHaveBeenCalledWith(Worklet.dernier);
  });
  it('garde un repli de 64 ms si la WebView refuse le worklet', async () => {
    vi.stubGlobal('AudioWorkletNode', Worklet);
    const contexte = new Contexte(); const source = new Noeud(); const recevoir = vi.fn();
    contexte.audioWorklet.addModule.mockRejectedValueOnce(new Error('refus de la WebView'));
    const capture = await creerCaptureVocale(contexte as unknown as AudioContext, source as unknown as AudioNode, recevoir);
    expect(contexte.createScriptProcessor).toHaveBeenCalledWith(1024, 1, 1);
    contexte.secours.onaudioprocess?.({ inputBuffer: { getChannelData: () => new Float32Array([-1, 0, 1]) } });
    const pcm = new DataView(recevoir.mock.calls[0][0]);
    expect([0, 2, 4].map((offset) => pcm.getInt16(offset, true))).toEqual([-32768, 0, 32767]);
    capture.arreter();
    expect(contexte.secours.onaudioprocess).toBeNull();
    expect(contexte.muet.disconnect).toHaveBeenCalledOnce();
  });
});

describe('§100 — le processeur réellement embarqué découpe du PCM, pas une simulation', () => {
  it.each([16000, 44100, 48000])('émet chaque 20 ms à %i Hz, sans perte ni duplication', (frequence) => {
    const paquets: ArrayBuffer[] = [];
    let constructeur: new () => { process: (entrees: Float32Array[][], sorties: Float32Array[][]) => boolean };
    runInNewContext(code, {
      sampleRate: frequence,
      AudioWorkletProcessor: class { port = { postMessage: (paquet: ArrayBuffer) => paquets.push(paquet) }; },
      registerProcessor: (_nom: string, valeur: typeof constructeur) => { constructeur = valeur; },
    });
    const processeur = new constructeur!();
    const taille = Math.round(frequence * 0.02);
    const entree = Float32Array.from({ length: taille * 3 }, (_, i) => i % 2 ? 1 : -1);
    const sortie = new Float32Array(128);
    for (let i = 0; i < entree.length; i += 128) processeur.process([[entree.slice(i, i + 128)]], [[sortie]]);
    expect(paquets.map((p) => p.byteLength)).toEqual([taille * 2, taille * 2, taille * 2]);
    for (const paquet of paquets) {
      const vue = new DataView(paquet);
      for (let i = 0; i < taille; i++) expect(vue.getInt16(i * 2, true)).toBe(i % 2 ? 32767 : -32768);
    }
    expect(sortie.every((valeur) => valeur === 0), 'aucun retour du micro dans les enceintes').toBe(true);
    expect(processeur.process([], [[sortie]])).toBe(true);
    expect(paquets).toHaveLength(3);
  });
});
