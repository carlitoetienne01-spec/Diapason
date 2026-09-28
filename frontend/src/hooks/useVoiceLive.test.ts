import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// Banc des callbacks du hook, sans composant React ni micro réel. Les effets
// de montage sont hors de ce banc ; start/stop et les événements sont exercés.
const banc = vi.hoisted(() => ({
  cases: [] as { current: any }[], curseur: 0,
  health: vi.fn(), micro: vi.fn(), capture: vi.fn(),
  // Le téléphone (28/09/2026) : servi par le tailnet, et le pont natif.
  telephone: false, natif: vi.fn(), coupure: vi.fn(),
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
  motifDeFermeture: () => null, coupureCliente: (...args: unknown[]) => banc.coupure(...args),
  voiceLiveDiagnosticUrl: (url: string) => url,
  voiceLiveProtocols: () => [], voiceLiveWsUrl: () => 'ws://localhost/voice-test',
}));
vi.mock('../lib/api', () => ({ refreshLocalApiKey: async () => {} }));
vi.mock('../lib/captureVocale', () => ({ creerCaptureVocale: banc.capture }));
vi.mock('../lib/tailnet', () => ({ serviParLeTailnet: () => banc.telephone }));
vi.mock('../lib/natif', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../lib/natif')>()),
  demanderAuTelephone: (...args: unknown[]) => banc.natif(...args),
}));
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
  banc.capture.mock.calls[banc.capture.mock.calls.length - 1][2](new ArrayBuffer(640));
  return socket;
}
beforeEach(() => {
  banc.cases = []; banc.curseur = 0;
  Socket.tous = []; Contexte.tous = [];
  banc.health.mockReset().mockResolvedValue({ available: true });
  banc.micro.mockReset().mockResolvedValue(flux());
  banc.capture.mockReset().mockImplementation(async () => ({ arreter: vi.fn() }));
  banc.telephone = false;
  banc.coupure.mockReset().mockReturnValue(null);
  banc.natif.mockReset().mockRejectedValue(new Error('pas de pont dans ce banc'));
  vi.stubGlobal('WebSocket', Socket); vi.stubGlobal('AudioContext', Contexte);
  vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: banc.micro } });
});
afterEach(() => { rendu().stop(); vi.unstubAllGlobals(); });

describe('§78 — le départ parlé laisse finir Orion avec le micro fermé', () => {
  it('ferme la capture avant le dernier son et conserve les transcriptions', async () => {
    const stream = flux(); banc.micro.mockResolvedValue(stream);
    const socket = await connecter();
    socket.message({ type: 'closing', reason: 'farewell' });
    expect(stream.getTracks()[0].stop).toHaveBeenCalledOnce();
    expect(rendu().micNode).toBeNull();
    expect(rendu().enFermeture).toBe(true);
    expect(rendu().statusLabel).toBe('ending');
    const n = socket.send.mock.calls.length;
    rendu().mettreMicroEnPause(true); rendu().mettreMicroEnPause(false);
    banc.capture.mock.calls[0][2](new ArrayBuffer(640));
    socket.message({ type: 'ready' });
    socket.message({ type: 'status', stage: 'listening' });
    expect(socket.send).toHaveBeenCalledTimes(n);
    expect(rendu().statusLabel).toBe('ending');
    socket.message({ type: 'transcript', role: 'user', text: 'Diapason, au revoir.', final: true });
    socket.message({ type: 'transcript', role: 'assistant', text: 'À bientôt.', final: false, replace: true });
    socket.message({ type: 'audio', data: btoa('\0\0'.repeat(240)), sample_rate: 24000 });
    socket.message({ type: 'transcript', role: 'assistant', text: 'À bientôt.', final: true });
    socket.message({ type: 'closed', reason: 'farewell' });
    socket.onclose({ code: 1000 });
    expect(rendu().state).toBe('speaking');
    expect(Contexte.tous[1].sources[0].stop).not.toHaveBeenCalled();
    Contexte.tous[1].sources[0].onended?.();
    expect(rendu().state).toBe('idle');
    expect(rendu().finVocale).toBe(true);
    expect(rendu().transcripts.map(l => l.text)).toEqual(['Diapason, au revoir.', 'À bientôt.']);
    expect(rendu().error).toBeNull();
  });
  it('attend closed quand le son termine avant la dernière trame', async () => {
    const socket = await connecter();
    socket.message({ type: 'closing', reason: 'farewell' });
    socket.message({ type: 'audio', data: btoa('\0\0') });
    Contexte.tous[1].sources[0].onended?.();
    expect(rendu().enFermeture).toBe(true);
    expect(rendu().statusLabel).toBe('ending');
    socket.message({ type: 'closed', reason: 'farewell' });
    expect(rendu().state).toBe('idle');
  });
  it('se ferme aussi sans son et ignore les trames tardives', async () => {
    const socket = await connecter();
    socket.message({ type: 'closing', reason: 'farewell' });
    socket.message({ type: 'closed', reason: 'farewell' });
    socket.message({ type: 'audio', data: btoa('\0\0') });
    expect(rendu().state).toBe('idle');
    expect(Contexte.tous).toHaveLength(1);
    await connecter();
    expect(rendu().finVocale).toBe(false);
    expect(rendu().enFermeture).toBe(false);
    expect(rendu().state).toBe('listening');
  });
  it('X reste immédiat pendant la préparation du départ', async () => {
    const socket = await connecter();
    socket.message({ type: 'closing', reason: 'farewell' });
    rendu().stop();
    socket.message({ type: 'audio', data: btoa('\0\0') });
    expect(rendu().state).toBe('idle');
    expect(Contexte.tous).toHaveLength(1);
  });
  it('libère la séance même si le serveur ou le lecteur ne termine pas', async () => {
    vi.useFakeTimers();
    try {
      const socket = await connecter();
      socket.message({ type: 'closing', reason: 'farewell' });
      socket.message({ type: 'audio', data: btoa('\0\0') });
      await vi.advanceTimersByTimeAsync(12000);
      expect(rendu().state).toBe('idle');
      expect(Contexte.tous[1].sources[0].stop).toHaveBeenCalledOnce();
    } finally { vi.useRealTimers(); }
  });
  it('une permission tardive ne rallume pas le micro pendant le départ', async () => {
    let accorder!: (value: ReturnType<typeof flux>) => void;
    banc.micro.mockReturnValue(new Promise(resolve => { accorder = resolve; }));
    await rendu().start();
    const socket = Socket.tous[0];
    const ouverture = socket.onopen();
    socket.message({ type: 'closing', reason: 'farewell' });
    const stream = flux(); accorder(stream); await ouverture;
    expect(stream.getTracks()[0].stop).toHaveBeenCalledOnce();
    expect(banc.capture).not.toHaveBeenCalled();
  });
});

describe('la seule voix masculine de Parler', () => {
  it('lit la voix du serveur sans ouvrir le micro', async () => {
    banc.health.mockResolvedValue({ available: true, defaultVoice: 'qwen3-b', voices: ['qwen3-b'] });
    await rendu().refreshAvailability();
    expect(rendu().voix).toBe('qwen3-b');
    expect(rendu().voixDisponibles).toEqual(['qwen3-b']);
    expect(banc.micro).not.toHaveBeenCalled();
  });
  it('démarre et conserve la voix masculine pendant une actualisation', async () => {
    banc.health.mockResolvedValue({ available: true, defaultVoice: 'qwen3-b', voices: ['qwen3-b'] });
    const socket = await connecter();
    expect(JSON.parse(socket.send.mock.calls[0][0]).voice).toBe('qwen3-b');
    await rendu().refreshAvailability();
    expect(rendu().voix).toBe('qwen3-b');
    rendu().stop();
    expect(rendu().voix).toBe('qwen3-b');
  });
});

describe('§78 / §100 — la capture appartient à la session, pas à sa lecture', () => {
  it('n’annonce pas l’écoute tant que le micro prêt n’a pas réellement produit un échantillon', async () => {
    let accorder!: (value: ReturnType<typeof flux>) => void;
    banc.micro.mockReturnValue(new Promise((resolve) => { accorder = resolve; }));
    await rendu().start();
    const socket = Socket.tous[0];
    const ouverture = socket.onopen();
    socket.message({ type: 'ready' });
    expect(rendu().state).toBe('connecting');
    accorder(flux()); await ouverture;
    expect(rendu().state).toBe('connecting');
    const envoyer = banc.capture.mock.calls[0][2];
    envoyer(new ArrayBuffer(0));
    expect(rendu().state).toBe('connecting');
    envoyer(new ArrayBuffer(640));
    expect(rendu().state).toBe('listening');
    expect(JSON.parse(socket.send.mock.calls[socket.send.mock.calls.length - 1][0]).type).toBe('audio');
  });
  it('attend aussi le serveur quand le micro est prêt en premier', async () => {
    await rendu().start();
    const socket = Socket.tous[0];
    await socket.onopen();
    banc.capture.mock.calls[0][2](new ArrayBuffer(640));
    expect(rendu().state).toBe('connecting');
    expect(socket.send).toHaveBeenCalledTimes(1);
    socket.message({ type: 'ready' });
    expect(rendu().state).toBe('listening');
  });
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
  it('affiche le motif d’attente réel sans couper le micro', async () => {
    const socket = await connecter();
    const micro = rendu().micNode;
    socket.message({ type: 'status', stage: 'waitingForName' });
    expect(rendu().statusLabel).toBe('waitingForName');
    expect(rendu().micNode).toBe(micro);
    socket.message({ type: 'status', stage: 'inconnu' });
    expect(rendu().statusLabel).toBe('waitingForName');
    socket.message({ type: 'status', stage: 'responding' });
    expect(rendu().statusLabel).toBe('responding');
  });
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

describe('§78 / §100 — une conversation entre IA reste limitée à sa session', () => {
  async function inviter(confirmer = true) {
    // Comme le menu + de Discussion, qui joint le fil en cours.
    await rendu().start({ conversationOnly: true, history: [{ role: 'user', content: 'Mon rendez-vous médical' }] });
    const socket = Socket.tous[Socket.tous.length - 1];
    await socket.onopen();
    banc.capture.mock.calls[banc.capture.mock.calls.length - 1][2](new ArrayBuffer(640));
    if (confirmer) socket.message({ type: 'ready', conversationOnly: true });
    return socket;
  }
  it('demande le mode sans outils et laisse passer la voix des haut-parleurs', async () => {
    const socket = await inviter();
    expect(JSON.parse(socket.send.mock.calls[0][0])).toMatchObject({
      provider: 'local', conversationOnly: true, enable_tools: false, include_memory: false,
    });
    expect('history' in JSON.parse(socket.send.mock.calls[0][0])).toBe(false);
    expect(banc.micro).toHaveBeenCalledWith({ audio: { echoCancellation: false, noiseSuppression: false, channelCount: 1 } });
    expect(rendu().conversationSeule).toBe(true);
    const envoyer = banc.capture.mock.calls[0][2];
    envoyer(new ArrayBuffer(640));
    expect(JSON.parse(socket.send.mock.calls[socket.send.mock.calls.length - 1][0]).type).toBe('audio');
  });
  it('ne transmet aucun son avant confirmation et refuse un ancien serveur', async () => {
    const socket = await inviter(false);
    const envoyer = banc.capture.mock.calls[0][2];
    envoyer(new ArrayBuffer(640));
    expect(socket.send).toHaveBeenCalledTimes(1);
    socket.message({ type: 'ready' });
    expect(rendu().error).toBe('voice-conversation-unavailable');
    expect(rendu().micNode).toBeNull();
    envoyer(new ArrayBuffer(640));
    expect(socket.send.mock.calls.some(([data]) => JSON.parse(data).type === 'audio')).toBe(false);
  });
  it('suspend la capture de sa propre voix puis reprend après la réverbération', async () => {
    let maintenant = 1000;
    const horloge = vi.spyOn(performance, 'now').mockImplementation(() => maintenant);
    try {
      const socket = await inviter();
      const envoyer = banc.capture.mock.calls[0][2];
      socket.message({ type: 'audio', data: btoa('\0\0'.repeat(240)) });
      const avant = socket.send.mock.calls.length;
      envoyer(new ArrayBuffer(640));
      expect(socket.send).toHaveBeenCalledTimes(avant);
      Contexte.tous[1].sources[0].onended?.();
      maintenant = 1299;
      envoyer(new ArrayBuffer(640));
      expect(socket.send).toHaveBeenCalledTimes(avant);
      maintenant = 1301;
      envoyer(new ArrayBuffer(640));
      expect(socket.send).toHaveBeenCalledTimes(avant + 1);
    } finally { horloge.mockRestore(); }
  });
  it('le démarrage suivant retrouve la capture normale et son anti-écho', async () => {
    await inviter(); rendu().stop(); await connecter();
    expect(rendu().conversationSeule).toBe(false);
    expect(banc.micro.mock.calls[banc.micro.mock.calls.length - 1][0].audio.echoCancellation).toBe(true);
    const socket = Socket.tous[Socket.tous.length - 1];
    expect(JSON.parse(socket.send.mock.calls[0][0]).conversationOnly).toBeUndefined();
  });
  it('garde la préparation visible entre deux morceaux de voix', async () => {
    const socket = await connecter();
    socket.message({ type: 'status', stage: 'responding' });
    socket.message({ type: 'audio', data: btoa('\0\0'.repeat(240)) });
    Contexte.tous[1].sources[0].onended?.();
    expect(rendu().statusLabel).toBe('responding');
    socket.message({ type: 'status', stage: 'listening' });
    expect(rendu().statusLabel).toBe('listening');
  });
});

describe('la voix intégrée au chat', () => {
  it('transmet le modèle et le contexte écrit sans ouvrir un second micro', async () => {
    const history = [{role: 'user' as const, content: 'Je débute en anglais'}];
    await rendu().start({ model: 'modele-local', history });
    await Socket.tous[0].onopen();
    expect(JSON.parse(Socket.tous[0].send.mock.calls[0][0])).toMatchObject({ model: 'modele-local', history });
    await rendu().start({ history });
    expect(banc.micro).toHaveBeenCalledTimes(1);
  });
  it('coupe les pistes et les trames pendant la pause puis reprend le même micro', async () => {
    const socket = await connecter();
    const stream = await banc.micro.mock.results[0].value;
    rendu().mettreMicroEnPause(true);
    expect(stream.getTracks()[0].enabled).toBe(false);
    const nombre = socket.send.mock.calls.length;
    banc.capture.mock.calls[0][2](new ArrayBuffer(640));
    expect(socket.send).toHaveBeenCalledTimes(nombre);
    rendu().mettreMicroEnPause(false);
    expect(stream.getTracks()[0].enabled).toBe(true);
    banc.capture.mock.calls[0][2](new ArrayBuffer(640));
    expect(socket.send).toHaveBeenCalledTimes(nombre + 1);
    expect(banc.micro).toHaveBeenCalledTimes(1);
  });
  it('révise la réponse dans une seule ligne puis sépare une interruption du tour suivant', async () => {
    const socket = await connecter();
    socket.message({ type: 'transcript', role: 'assistant', text: 'Écoute.', replace: true });
    socket.message({ type: 'transcript', role: 'assistant', text: 'Écoute. Répète.', replace: true });
    expect(rendu().transcripts).toHaveLength(1);
    rendu().interrupt();
    expect(rendu().transcripts[0]).toMatchObject({ final: true, interrupted: true });
    socket.message({ type: 'transcript', role: 'assistant', text: 'Autre réponse.', final: true });
    expect(rendu().transcripts).toHaveLength(2);
  });
});

/**
 * 28/09/2026, constat de Carlito : au téléphone, « Parler » affichait « Micro
 * fermé » et « L'accès au microphone est bloqué. Autorisez Diapason dans
 * Réglages Système… » — le message du Mac, pour TOUTE exception du bloc du
 * micro. Cause la plus probable : un NotReadableError (la WebView sans
 * MODIFY_AUDIO_SETTINGS), pas un refus. §5 : ne jamais faire semblant.
 */
describe('§5 — un micro qui ne s’ouvre pas dit pourquoi', () => {
  const muet = () => vi.spyOn(console, 'error').mockImplementation(() => {});
  async function echouer(erreur: unknown) {
    banc.micro.mockRejectedValue(erreur);
    await rendu().start();
    const socket = Socket.tous[Socket.tous.length - 1];
    await socket.onopen();
    return socket;
  }
  const occupe = () => new DOMException('Could not start audio source', 'NotReadableError');
  const refuse = () => new DOMException('Permission denied', 'NotAllowedError');

  it('au bureau, un NotReadableError ne dit plus « accès bloqué »', async () => {
    const journal = muet();
    try {
      const socket = await echouer(occupe());
      expect(rendu().error, 'un micro occupé n’est pas un refus').toBe('microphone-busy');
      expect(rendu().state).toBe('error');
      expect(socket.close, 'la séance préchauffée se referme').toHaveBeenCalled();
      expect(rendu().micro?.technique, 'au bureau, rien ne change hors de la phrase').toBeNull();
      expect(banc.natif, 'le bureau n’a pas de coquille à interroger').not.toHaveBeenCalled();
    } finally { journal.mockRestore(); }
  });

  it('au bureau, un refus garde le message de macOS', async () => {
    const journal = muet();
    try {
      await echouer(refuse());
      expect(rendu().error).toBe('microphone-denied');
      expect(rendu().micro?.reglages).toBe(false);
    } finally { journal.mockRestore(); }
  });

  it('un AudioContext qui lève après le flux n’est pas un refus, et le flux est rendu', async () => {
    const journal = muet();
    const stream = flux(); banc.micro.mockResolvedValue(stream);
    vi.stubGlobal('AudioContext', class { constructor() { throw new DOMException('rate', 'NotSupportedError'); } });
    try {
      await rendu().start();
      await Socket.tous[0].onopen();
      expect(rendu().error, 'le micro s’était ouvert').toBe('microphone-audio-failed');
      expect(stream.getTracks()[0].stop, 'le voyant d’Android s’éteint (§78)').toHaveBeenCalledOnce();
    } finally { journal.mockRestore(); }
  });

  it('une AbortError de la capture, après le flux, est un échec audio, pas un micro occupé', async () => {
    const journal = muet();
    banc.capture.mockRejectedValue(new DOMException('worklet', 'AbortError'));
    try {
      await rendu().start();
      await Socket.tous[0].onopen();
      expect(rendu().error).toBe('microphone-audio-failed');
    } finally { journal.mockRestore(); }
  });

  it('au téléphone, un NotAllowedError interroge micro/etat puis montre le bouton et le détail', async () => {
    const journal = muet();
    banc.telephone = true;
    let repondre!: (r: object) => void;
    banc.natif.mockReturnValue(new Promise((r) => { repondre = r; }));
    try {
      banc.micro.mockRejectedValue(refuse());
      await rendu().start();
      const ouverture = Socket.tous[0].onopen();
      await vi.waitFor(() => expect(banc.natif).toHaveBeenCalledWith('micro', { action: 'etat' }));
      expect(rendu().error, 'en attente de l’état, on le dit').toBe('microphone-phone-checking');
      expect(rendu().micro?.reglages, 'pas de bouton avant de savoir').toBe(false);
      repondre({ type: 'reponse', id: 'x', ok: true, donnees: { etat: 'refuseDefinitivement' } });
      await ouverture;
      expect(rendu().error).toBe('microphone-phone-denied-forever');
      expect(rendu().micro).toEqual({
        technique: 'NotAllowedError · Permission denied', reglages: true, avis: null,
      });
      expect(banc.natif, 'une seule demande pour la barre ET l’orbe').toHaveBeenCalledTimes(1);
    } finally { journal.mockRestore(); }
  });

  it('au téléphone, un NotReadableError d’une coquille ancienne dit « installez la nouvelle app », sans bouton', async () => {
    const journal = muet();
    banc.telephone = true;
    banc.natif.mockResolvedValue({ type: 'reponse', id: 'x', ok: false, erreur: 'verbeInconnu' });
    try {
      await echouer(occupe());
      expect(rendu().error).toBe('microphone-phone-app-outdated');
      expect(rendu().micro?.reglages).toBe(false);
      expect(rendu().micro?.technique).toBe('NotReadableError · Could not start audio source');
    } finally { journal.mockRestore(); }
  });

  it('une réponse tardive de micro/etat ne réécrit pas l’erreur d’une séance relancée', async () => {
    const journal = muet();
    banc.telephone = true;
    let repondre!: (r: object) => void;
    banc.natif.mockReturnValue(new Promise((r) => { repondre = r; }));
    try {
      banc.micro.mockRejectedValue(refuse());
      await rendu().start();
      const ancien = Socket.tous[0];
      const ouverture = ancien.onopen();
      await vi.waitFor(() => expect(banc.natif).toHaveBeenCalled());
      // Le navigateur ferme la socket refermée par le hook.
      ancien.onclose({});
      banc.micro.mockResolvedValue(flux());
      await connecter();
      repondre({ type: 'reponse', id: 'x', ok: true, donnees: { etat: 'refuse' } });
      await ouverture;
      expect(rendu().error, 'la nouvelle séance écoute').toBeNull();
      expect(rendu().state).toBe('listening');
    } finally { journal.mockRestore(); }
  });

  it('« Ouvrir les réglages » : le verbe part, et au retour on relit l’état sans rouvrir le micro (§78)', async () => {
    const journal = muet();
    banc.telephone = true;
    banc.natif.mockImplementation(async (_verbe: string, donnees: { action: string }) =>
      donnees.action === 'etat'
        ? { type: 'reponse', id: 'x', ok: true, donnees: { etat: banc.natif.mock.calls.length > 2 ? 'accorde' : 'refuse' } }
        : { type: 'reponse', id: 'y', ok: true });
    let visibilite: DocumentVisibilityState = 'visible';
    const lecture = vi.spyOn(document, 'visibilityState', 'get').mockImplementation(() => visibilite);
    try {
      const socket = await echouer(refuse());
      // Comme le navigateur après ws.close() : rien ne retient plus une relance.
      socket.onclose({});
      expect(rendu().micro?.reglages).toBe(true);
      await rendu().ouvrirReglagesMicro();
      expect(banc.natif).toHaveBeenLastCalledWith('micro', { action: 'reglages' });
      const appelsMicro = banc.micro.mock.calls.length;
      const sockets = Socket.tous.length;
      visibilite = 'hidden'; document.dispatchEvent(new Event('visibilitychange'));
      visibilite = 'visible'; document.dispatchEvent(new Event('visibilitychange'));
      await vi.waitFor(() => expect(rendu().error).toBe('microphone-phone-now-allowed'));
      await new Promise((fin) => setTimeout(fin, 0));
      expect(banc.natif).toHaveBeenLastCalledWith('micro', { action: 'etat' });
      expect(banc.health, 'aucune séance préparée au retour des réglages').toHaveBeenCalledTimes(1);
      expect(banc.micro, 'aucun getUserMedia au retour des réglages').toHaveBeenCalledTimes(appelsMicro);
      expect(Socket.tous, 'aucune séance relancée au retour des réglages').toHaveLength(sockets);
    } finally { lecture.mockRestore(); journal.mockRestore(); }
  });

  it('les réglages refusés sous le cadenas : la phrase de la coquille, telle quelle', async () => {
    const journal = muet();
    banc.telephone = true;
    const phrase = 'Déverrouillez Diapason pour ouvrir ses réglages.';
    banc.natif.mockImplementation(async (_verbe: string, donnees: { action: string }) =>
      donnees.action === 'etat'
        ? { type: 'reponse', id: 'x', ok: true, donnees: { etat: 'refuse' } }
        : { type: 'reponse', id: 'y', ok: false, erreur: phrase });
    try {
      await echouer(refuse());
      await rendu().ouvrirReglagesMicro();
      expect(rendu().micro?.avis).toEqual({ texte: phrase });
    } finally { journal.mockRestore(); }
  });

  it('une autre erreur posée ensuite n’hérite ni du détail ni du bouton', async () => {
    const journal = muet();
    const avertir = vi.spyOn(console, 'warn').mockImplementation(() => {});
    banc.telephone = true;
    banc.natif.mockResolvedValue({ type: 'reponse', id: 'x', ok: true, donnees: { etat: 'refuse' } });
    vi.useFakeTimers();
    try {
      await echouer(refuse());
      await vi.waitFor(() => expect(rendu().micro?.reglages).toBe(true));
      // La garde du client coupe ensuite : sa phrase n'est pas celle du micro.
      banc.coupure.mockReturnValue('voice-lost-server');
      await vi.advanceTimersByTimeAsync(5000);
      expect(rendu().error).toBe('voice-lost-server');
      expect(rendu().micro, 'le détail et le bouton du micro sous « le Mac ne répond plus »').toBeNull();
    } finally { vi.useRealTimers(); avertir.mockRestore(); journal.mockRestore(); }
  });

  it('choisir un autre fournisseur oublie l’échec du micro', async () => {
    const journal = muet();
    banc.telephone = true;
    banc.natif.mockResolvedValue({ type: 'reponse', id: 'x', ok: true, donnees: { etat: 'refuse' } });
    try {
      await echouer(refuse());
      await vi.waitFor(() => expect(rendu().micro).not.toBeNull());
      rendu().setProvider('local');
      expect(rendu().micro, 'plus d’échec du micro à montrer').toBeNull();
    } finally { journal.mockRestore(); }
  });
});
