import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// Banc des callbacks du hook, sans composant React ni micro réel. Les effets
// de montage sont hors de ce banc ; start/stop et les événements sont exercés.
const banc = vi.hoisted(() => ({
  cases: [] as { current: any }[], curseur: 0,
  health: vi.fn(), micro: vi.fn(), capture: vi.fn(),
}));
vi.mock('react', () => ({
  useRef: (initial: unknown) => banc.cases[banc.curseur++] ??= { current: initial },
  useState: (initial: unknown) => {
    const cellule = banc.cases[banc.curseur++] ??= { current: initial };
    return [cellule.current, (valeur: any) => {
      cellule.current = typeof valeur === 'function' ? valeur(cellule.current) : valeur;
    }];
  },
  useCallback: (callback: unknown) => callback,
  useEffect: () => {},
}));
vi.mock('../lib/voiceLive', () => ({
  fetchVoiceLiveHealth: banc.health, canStartVoiceSession: (sante: unknown) => !!sante,
  VoiceLiveHealthError: class extends Error {},
  voiceLiveDiagnosticUrl: (url: string) => url,
  voiceLiveProtocols: () => [], voiceLiveWsUrl: () => 'ws://localhost/voice-test',
}));
vi.mock('../lib/api', () => ({ refreshLocalApiKey: async () => {} }));
vi.mock('../lib/captureVocale', () => ({ creerCaptureVocale: banc.capture }));
import { useVoiceLive } from './useVoiceLive';

class Socket {
  static OPEN = 1;
  static tous: Socket[] = [];
  readyState = 1;
  onopen: () => Promise<void> = async () => {};
  onmessage: (event: { data: string }) => void = () => {};
  onclose: (event: object) => void = () => {};
  onerror: (event: object) => void = () => {};
  send = vi.fn(); close = vi.fn();
  constructor() { Socket.tous.push(this); }
  message(donnees: object) { this.onmessage({ data: JSON.stringify(donnees) }); }
}
class Noeud {
  gain = { value: 1 }; connect = vi.fn(); disconnect = vi.fn();
  start = vi.fn(); stop = vi.fn();
  onended: (() => void) | null = null;
  buffer: unknown;
  constructor(public context: Contexte) {}
}
class Contexte {
  static tous: Contexte[] = [];
  state = 'running'; currentTime = 0; sampleRate = 48000;
  destination = new Noeud(this);
  sources: Noeud[] = [];
  close = vi.fn(async () => { this.state = 'closed'; });
  resume = vi.fn(async () => {});
  constructor() { Contexte.tous.push(this); }
  createMediaStreamSource() { return new Noeud(this); }
  createGain() { return new Noeud(this); }
  createBuffer(_c: number, n: number, hz: number) { return { duration: n / hz, copyToChannel: vi.fn() }; }
  createBufferSource() { const source = new Noeud(this); this.sources.push(source); return source; }
}
function rendu() { banc.curseur = 0; return useVoiceLive(); }
function flux() { const piste = { stop: vi.fn() }; return { getTracks: () => [piste] }; }
async function connecter() {
  await rendu().start();
  const socket = Socket.tous[Socket.tous.length - 1];
  await socket.onopen(); socket.message({ type: 'ready' });
  return socket;
}
beforeEach(() => {
  banc.cases = []; banc.curseur = 0;
  Socket.tous = []; Contexte.tous = [];
  banc.health.mockReset().mockResolvedValue({ available: true });
  banc.micro.mockReset().mockResolvedValue(flux());
  banc.capture.mockReset().mockImplementation(async () => ({ arreter: vi.fn() }));
  vi.stubGlobal('WebSocket', Socket); vi.stubGlobal('AudioContext', Contexte);
  vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: banc.micro } });
});
afterEach(() => { rendu().stop(); vi.unstubAllGlobals(); });

describe('§78 / §100 — la capture appartient à la session, pas à sa lecture', () => {
  it('garde le même micro après une interruption et continue d’envoyer ses trames', async () => {
    const socket = await connecter();
    const micro = rendu().micNode;
    socket.message({ type: 'audio', data: btoa('\0\0'.repeat(240)), sample_rate: 24000 });
    expect(rendu().state).toBe('speaking');
    rendu().interrupt();
    socket.message({ type: 'interrupted' });
    expect(rendu().micNode, 'interrompre la réponse ne débranche pas la forme du micro').toBe(micro);
    expect(rendu().state).toBe('listening');
    expect(Contexte.tous[0].close).not.toHaveBeenCalled();
    const envoyer = banc.capture.mock.calls[0][2];
    envoyer(new ArrayBuffer(640));
    expect(JSON.parse(socket.send.mock.calls[socket.send.mock.calls.length - 1][0])).toMatchObject({ type: 'audio', sample_rate: 48000 });
    rendu().stop();
    expect(rendu().micNode).toBeNull();
    expect(Contexte.tous[0].close).toHaveBeenCalledOnce();
  });
  it('retrouve l’écoute et le micro après la fin naturelle de la réponse', async () => {
    const socket = await connecter();
    const micro = rendu().micNode;
    socket.message({ type: 'audio', data: btoa('\0\0'.repeat(240)) });
    Contexte.tous[1].sources[0].onended?.();
    expect(rendu().state).toBe('listening');
    expect(rendu().micNode).toBe(micro);
  });
  it('arrête un micro accordé après la fermeture sans relancer la capture', async () => {
    let accorder!: (value: ReturnType<typeof flux>) => void;
    banc.micro.mockReturnValue(new Promise((resolve) => { accorder = resolve; }));
    await rendu().start();
    const ouverture = Socket.tous[0].onopen();
    rendu().stop();
    const tardif = flux(); accorder(tardif); await ouverture;
    expect(tardif.getTracks()[0].stop).toHaveBeenCalledOnce();
    expect(banc.capture).not.toHaveBeenCalled();
    expect(rendu().state).toBe('idle');
  });
  it('ignore la fermeture et les trames retardées de l’ancienne session', async () => {
    const ancien = await connecter(); rendu().stop();
    await connecter(); const micro = rendu().micNode;
    ancien.onclose({}); ancien.message({ type: 'audio', data: btoa('\0\0') });
    expect(rendu().micNode).toBe(micro);
    expect(rendu().state).toBe('listening');
    expect(Contexte.tous).toHaveLength(2);
  });
  it('ne rallume rien si Terminer arrive pendant le contrôle du service', async () => {
    let repondre!: (value: object) => void;
    banc.health.mockReturnValue(new Promise((resolve) => { repondre = resolve; }));
    const demarrage = rendu().start(); rendu().stop();
    repondre({ available: true }); await demarrage;
    expect(Socket.tous).toHaveLength(0);
    expect(banc.micro).not.toHaveBeenCalled();
  });
  it('ferme immédiatement le micro sur une erreur sans effacer le diagnostic', async () => {
    const socket = await connecter();
    socket.message({ type: 'audio', data: btoa('\0\0') });
    socket.message({ type: 'error', detail: 'problème vocal' });
    expect(rendu().micNode).toBeNull();
    expect(rendu().state).toBe('error');
    socket.message({ type: 'ready' });
    expect(rendu().state).toBe('error');
  });
});

describe('§5 — la pastille de vérification du panneau vocal', () => {
  // 22/09/2026 : le panneau n'avait rien. L'épilogue parlé ne se prononce QUE
  // lorsqu'il a quelque chose à avouer, donc son silence disait aussi bien
  // « vérifié en ligne » que « personne n'a rien vérifié ».
  it('retient le niveau que le serveur envoie', async () => {
    const socket = await connecter();
    socket.message({ type: 'verification', level: 'verified', searchTried: true });
    expect(rendu().verification).toEqual({
      notFound: [],
      level: 'verified',
      searchTried: true,
    });
  });

  it('distingue « de mémoire » de « de mémoire, recherche sans résultat »', async () => {
    const socket = await connecter();
    socket.message({ type: 'verification', level: 'memory' });
    expect(rendu().verification).toEqual({ notFound: [], level: 'memory' });
    socket.message({ type: 'verification', level: 'memory', searchTried: true });
    expect(rendu().verification?.searchTried).toBe(true);
  });

  it('efface la pastille quand le tour suivant n’en porte pas', async () => {
    // Garder celle du tour d'avant sous la réponse d'à côté serait la pire
    // des lectures : un badge vert sur une réponse que rien n'a vérifiée.
    const socket = await connecter();
    socket.message({ type: 'verification', level: 'verified', searchTried: true });
    socket.message({ type: 'verification' });
    expect(rendu().verification).toBeUndefined();
  });

  it('ne garde rien d’une session à l’autre', async () => {
    const socket = await connecter();
    socket.message({ type: 'verification', level: 'partial', searchTried: true });
    expect(rendu().verification?.level).toBe('partial');
    rendu().stop();
    await connecter();
    expect(rendu().verification).toBeUndefined();
  });
});

describe('§5 — une recherche vide se voit aussi au panneau vocal', () => {
  // 22/09/2026 : le panneau recevait {name, ok, detail} et rien d'autre. Une
  // recherche à zéro résultat y arrivait en ok=true, detail='' —
  // indiscernable d'une recherche qui a rendu huit sources.
  it('garde le moteur et le compte de la recherche', async () => {
    const socket = await connecter();
    socket.message({ type: 'tool', name: 'web_search', ok: true, detail: '', engine: 'brave/news', numResults: 8 });
    // Une recherche vide n'a pas de moteur (web_search.py:427).
    socket.message({ type: 'tool', name: 'web_search', ok: true, detail: '', numResults: 0 });
    const [plein, vide] = rendu().toolEvents;
    expect(plein.engine).toBe('brave/news');
    expect(plein.numResults).toBe(8);
    expect(vide.numResults).toBe(0);
  });

  it('n’ajoute rien à un outil qui ne cherche pas', async () => {
    const socket = await connecter();
    socket.message({ type: 'tool', name: 'focus_app', ok: true, detail: 'Focused' });
    const [ligne] = rendu().toolEvents;
    expect('engine' in ligne).toBe(false);
    expect('numResults' in ligne).toBe(false);
  });

  it('refuse un compte qui n’est pas entier', async () => {
    // Le banc sérialise en JSON, comme le vrai fil : NaN et Infinity y
    // deviennent `null`, que `typeof === 'number'` écarterait déjà. Ce que la
    // garde doit vraiment refuser et qu'un `typeof` laisserait passer, c'est
    // un DÉCIMAL — `resumeDeRecherche` afficherait « 2.5 rés. ».
    const socket = await connecter();
    socket.message({ type: 'tool', name: 'web_search', ok: true, numResults: 2.5 });
    expect('numResults' in rendu().toolEvents[0]).toBe(false);
    socket.message({ type: 'tool', name: 'web_search', ok: true, numResults: Number.NaN });
    expect('numResults' in rendu().toolEvents[1]).toBe(false);
    socket.message({ type: 'tool', name: 'web_search', ok: true, numResults: '8' });
    expect('numResults' in rendu().toolEvents[2]).toBe(false);
  });
});
