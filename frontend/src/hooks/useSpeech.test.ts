import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { MESSAGES } from '../i18n/messages';

// Banc des callbacks du hook, sans composant React ni micro réel (le même
// procédé que useVoiceLive.test.ts) : les effets de montage sont hors banc.
const banc = vi.hoisted(() => ({
  cases: [] as { current: any }[], curseur: 0,
  micro: vi.fn(), telephone: false, natif: vi.fn(),
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
vi.mock('../lib/api', () => ({ transcribeAudio: vi.fn(), fetchSpeechHealth: vi.fn() }));
vi.mock('../lib/tailnet', () => ({ serviParLeTailnet: () => banc.telephone }));
vi.mock('../lib/natif', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../lib/natif')>()),
  demanderAuTelephone: (...args: unknown[]) => banc.natif(...args),
}));
import { useSpeech } from './useSpeech';

function rendu() { banc.curseur = 0; return useSpeech(); }
function flux() { const piste = { stop: vi.fn() }; return { getTracks: () => [piste] }; }
class Enregistreur {
  state = 'inactive';
  ondataavailable: unknown = null;
  constructor(public stream: unknown) {}
  start() { this.state = 'recording'; }
  stop() { this.state = 'inactive'; }
}
const fr = MESSAGES.fr;

beforeEach(() => {
  banc.cases = []; banc.curseur = 0; banc.telephone = false;
  banc.micro.mockReset().mockResolvedValue(flux());
  banc.natif.mockReset().mockRejectedValue(new Error('pas de pont dans ce banc'));
  vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: banc.micro } });
  vi.stubGlobal('MediaRecorder', Enregistreur);
  document.documentElement.setAttribute('lang', 'fr');
  vi.spyOn(console, 'error').mockImplementation(() => {});
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.documentElement.removeAttribute('lang');
});

/**
 * 28/09/2026 : la dictée « maintenir pour parler » disait « Microphone access
 * denied », en anglais et en dur, pour TOUTE erreur du micro — au téléphone,
 * le NotReadableError d'une WebView sans MODIFY_AUDIO_SETTINGS compris (§5).
 */
describe('§5 — la dictée dit pourquoi le micro ne s’ouvre pas', () => {
  it('au bureau, un NotReadableError dit « occupé », en français, jamais « access denied »', async () => {
    banc.micro.mockRejectedValue(new DOMException('Could not start audio source', 'NotReadableError'));
    await rendu().startRecording();
    expect(rendu().error).toBe(fr['talk.micro.occupe']);
    expect(rendu().error).not.toMatch(/denied/i);
    expect(rendu().micro, 'au bureau, pas de détail ni de bouton').toEqual({ technique: null, reglages: false });
    expect(rendu().state).toBe('idle');
  });

  it('au bureau, un refus garde la phrase de macOS', async () => {
    banc.micro.mockRejectedValue(new DOMException('Permission denied', 'NotAllowedError'));
    await rendu().startRecording();
    expect(rendu().error).toBe(fr['talk.microphoneDenied']);
  });

  it('sans navigator.mediaDevices : la page n’a pas le micro, ce n’est pas un refus', async () => {
    vi.stubGlobal('navigator', {});
    await rendu().startRecording();
    expect(rendu().error).toBe(fr['talk.micro.page']);
  });

  it('au téléphone, attend micro/etat avant de parler, puis montre le détail et le bouton', async () => {
    banc.telephone = true;
    banc.micro.mockRejectedValue(new DOMException('Permission denied', 'NotAllowedError'));
    let repondre!: (r: object) => void;
    banc.natif.mockReturnValue(new Promise((r) => { repondre = r; }));
    const depart = rendu().startRecording();
    await vi.waitFor(() => expect(banc.natif).toHaveBeenCalledWith('micro', { action: 'etat' }));
    expect(rendu().error, 'un toast dit une chose, une fois : rien avant l’état').toBeNull();
    repondre({ type: 'reponse', id: 'x', ok: true, donnees: { etat: 'refuseDefinitivement' } });
    await depart;
    expect(rendu().error).toBe(fr['talk.micro.telephone.refuseDefinitivement']);
    expect(rendu().micro).toEqual({ technique: 'NotAllowedError · Permission denied', reglages: true });
  });

  it('au téléphone, une coquille ancienne et un micro indisponible : « installez la nouvelle version »', async () => {
    banc.telephone = true;
    banc.micro.mockRejectedValue(new DOMException('Could not start audio source', 'NotReadableError'));
    banc.natif.mockResolvedValue({ type: 'reponse', id: 'x', ok: false, erreur: 'verbeInconnu' });
    await rendu().startRecording();
    expect(rendu().error).toBe(fr['talk.micro.telephone.appTropAncienne']);
    expect(rendu().micro?.reglages).toBe(false);
  });

  it('§78 — un MediaRecorder refusé après le flux éteint le micro et se dit « échec audio »', async () => {
    const stream = flux(); banc.micro.mockResolvedValue(stream);
    vi.stubGlobal('MediaRecorder', class { constructor() { throw new DOMException('codec', 'NotSupportedError'); } });
    await rendu().startRecording();
    expect(stream.getTracks()[0].stop, 'le voyant restait allumé').toHaveBeenCalledOnce();
    expect(rendu().error).toBe(fr['talk.micro.echecAudio']);
    expect(rendu().state).toBe('idle');
  });

  it('le bouton du toast demande micro/reglages et rend la phrase de la coquille', async () => {
    const phrase = 'Déverrouillez Diapason pour ouvrir ses réglages.';
    banc.natif.mockResolvedValue({ type: 'reponse', id: 'y', ok: false, erreur: phrase });
    expect(await rendu().ouvrirReglagesMicro()).toEqual({ cle: 'talk.micro.reglagesEchec', reponse: phrase });
    expect(banc.natif).toHaveBeenCalledWith('micro', { action: 'reglages' });
  });
});

/**
 * 28/09/2026, audit du micro au téléphone : l'invite d'Android apparaît sous
 * le doigt qui tient la dictée. Le relâcher arrivait AVANT l'accord, ne
 * trouvait aucun enregistreur, et l'accord tardif démarrait un MediaRecorder
 * que rien n'arrêtait (§78 : le voyant vert doit dire la vérité).
 */
describe('§78 — relâcher pendant l’invite d’Android n’allume pas le micro', () => {
  it('l’accord qui arrive après le relâcher referme le flux sans enregistrer', async () => {
    let accorder!: (s: ReturnType<typeof flux>) => void;
    banc.micro.mockReturnValue(new Promise((r) => { accorder = r; }));
    const construit = vi.fn();
    vi.stubGlobal('MediaRecorder', class extends Enregistreur {
      constructor(s: unknown) { super(s); construit(); }
    });
    const depart = rendu().startRecording();
    await expect(rendu().stopRecording(), 'le doigt se lève pour répondre à Android').rejects.toThrow('Not recording');
    const stream = flux(); accorder(stream); await depart;
    expect(stream.getTracks()[0].stop, 'le micro accordé trop tard reste allumé').toHaveBeenCalledOnce();
    expect(construit, 'aucun enregistreur après le relâcher').not.toHaveBeenCalled();
    expect(rendu().state).toBe('idle');
  });

  it('tenu jusqu’à l’accord, le micro enregistre comme avant', async () => {
    await rendu().startRecording();
    expect(rendu().state).toBe('recording');
    expect(rendu().isRecording).toBe(true);
  });

  it('une nouvelle pression après un relâcher annulé enregistre de nouveau', async () => {
    let accorder!: (s: ReturnType<typeof flux>) => void;
    banc.micro.mockReturnValueOnce(new Promise((r) => { accorder = r; }));
    const premiere = rendu().startRecording();
    await rendu().stopRecording().catch(() => undefined);
    accorder(flux()); await premiere;
    await rendu().startRecording();
    expect(rendu().state, 'l’annulation ne vaut que pour la demande relâchée').toBe('recording');
  });
});

/**
 * 28/09/2026, revue du chantier : la réponse de micro/etat n'était pas
 * rapportée à son appui. §5 — un toast « Android n'a pas donné le micro » et
 * « Ouvrir les réglages » pendant que le micro enregistre.
 */
describe('§5 — une réponse tardive de micro/etat ne parle que pour son appui', () => {
  it('un second appui accordé fait taire la réponse tardive du premier', async () => {
    banc.telephone = true;
    let repondre!: (r: object) => void;
    banc.natif.mockReturnValue(new Promise((r) => { repondre = r; }));
    banc.micro.mockRejectedValueOnce(new DOMException('Permission denied', 'NotAllowedError'));
    const premier = rendu().startRecording();
    await vi.waitFor(() => expect(banc.natif).toHaveBeenCalledWith('micro', { action: 'etat' }));
    await rendu().stopRecording().catch(() => undefined);
    await rendu().startRecording();
    expect(rendu().state, 'l’invite a accordé le second appui').toBe('recording');
    repondre({ type: 'reponse', id: 'x', ok: true, donnees: { etat: 'refuse' } });
    await premier;
    expect(rendu().state).toBe('recording');
    expect(rendu().error, 'un refus affiché pendant que le micro enregistre').toBeNull();
    expect(rendu().micro, 'le bouton des réglages sous un micro qui enregistre').toBeNull();
  });

  it('le refus répondu en levant le doigt s’affiche encore : le relâcher n’est pas un nouvel appui', async () => {
    banc.telephone = true;
    let refuser!: (e: unknown) => void;
    banc.micro.mockReturnValue(new Promise((_, r) => { refuser = r; }));
    banc.natif.mockResolvedValue({ type: 'reponse', id: 'x', ok: true, donnees: { etat: 'refuseDefinitivement' } });
    const depart = rendu().startRecording();
    // Le doigt se lève pour toucher « Refuser » dans l'invite d'Android.
    await rendu().stopRecording().catch(() => undefined);
    refuser(new DOMException('Permission denied', 'NotAllowedError'));
    await depart;
    expect(rendu().error, 'le refus d’Android tu parce que le doigt s’était levé')
      .toBe(fr['talk.micro.telephone.refuseDefinitivement']);
    expect(rendu().micro?.reglages).toBe(true);
  });
});
