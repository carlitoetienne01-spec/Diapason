import { afterEach, describe, expect, it, vi } from 'vitest';

// Banc du branchement audio, sans monter de composant ni ouvrir un micro.
const cycle = vi.hoisted(() => ({ nettoyer: undefined as undefined | (() => void) }));
vi.mock('react', () => ({
  useRef: (current: unknown) => ({ current }),
  useEffect: (effet: () => void | (() => void)) => { cycle.nettoyer = effet() || undefined; },
}));
import { useAudioSpectrum } from './useAudioSpectrum';

class Noeud {
  sorties = new Set<Noeud>();
  constructor(public context: Contexte) {}
  connect(sortie: Noeud) { this.sorties.add(sortie); }
  disconnect(sortie?: Noeud) { if (sortie) this.sorties.delete(sortie); else this.sorties.clear(); }
}
class Contexte {
  destination = new Noeud(this);
  state = 'running';
  sampleRate = 48000;
  close = vi.fn();
  resume = vi.fn();
  analyseur = Object.assign(new Noeud(this), {
    fftSize: 0, smoothingTimeConstant: 0, frequencyBinCount: 1024,
    getByteFrequencyData: (donnees: Uint8Array) => donnees.fill(0),
    getFloatTimeDomainData: (donnees: Float32Array) => donnees.fill(0),
  });
  createAnalyser() { return this.analyseur; }
}
afterEach(() => { cycle.nettoyer?.(); cycle.nettoyer = undefined; vi.unstubAllGlobals(); });

describe('§100 — le visualiseur ne doit pas couper la voix qu’il observe', () => {
  it('détache seulement son analyseur et préserve les haut-parleurs', () => {
    vi.stubGlobal('AudioContext', Contexte);
    vi.stubGlobal('AudioNode', Noeud);
    const contexte = new Contexte();
    const source = new Noeud(contexte);
    source.connect(contexte.destination);
    const analyse = useAudioSpectrum(source as unknown as AudioNode, true);
    expect(source.sorties.has(contexte.analyseur)).toBe(true);
    expect(analyse.read().level).toBe(0);
    cycle.nettoyer?.();
    cycle.nettoyer = undefined;
    expect(source.sorties.has(contexte.destination), 'la réponse doit rester audible').toBe(true);
    expect(source.sorties.has(contexte.analyseur)).toBe(false);
    expect(contexte.close, 'le moteur vocal possède ce contexte').not.toHaveBeenCalled();
  });
  it('ne crée aucun branchement quand l’écoute est désactivée', () => {
    const constructeur = vi.fn();
    vi.stubGlobal('AudioContext', constructeur);
    expect(useAudioSpectrum(null, false).read().level).toBe(0);
    expect(constructeur).not.toHaveBeenCalled();
  });
  it('réagit au PCM même si les bandes fréquentielles sont vides', () => {
    vi.stubGlobal('AudioContext', Contexte);
    vi.stubGlobal('AudioNode', Noeud);
    const contexte = new Contexte();
    contexte.analyseur.getFloatTimeDomainData = (donnees) => {
      for (let i = 0; i < donnees.length; i++) donnees[i] = i % 2 ? 0.04 : -0.04;
      return donnees;
    };
    const analyse = useAudioSpectrum(new Noeud(contexte) as unknown as AudioNode, true);
    expect(analyse.read().level, 'le niveau ne doit plus être la moyenne de bandes vides').toBeGreaterThan(0.95);
  });
});
