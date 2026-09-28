import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { assemblerPcm, capturerProfil, requeteProfil } from './captureProfil';
import { creerCaptureVocale } from '../../lib/captureVocale';
import { apiFetch } from '../../lib/api';
vi.mock('../../lib/captureVocale', () => ({ creerCaptureVocale: vi.fn() }));
vi.mock('../../lib/api', () => ({ apiFetch: vi.fn() }));

const arreter = vi.fn(), fermer = vi.fn(async () => {}), decrocher = vi.fn();
let envoyer: (bloc: ArrayBuffer) => void;
const flux = { getTracks: () => [{ stop: arreter }] } as unknown as MediaStream;
class Contexte {
  sampleRate = 16000;
  state = 'running';
  resume = vi.fn(async () => {});
  close = fermer;
  createMediaStreamSource = vi.fn(() => ({}));
}
beforeEach(() => {
  vi.useFakeTimers(); vi.clearAllMocks();
  vi.stubGlobal('AudioContext', Contexte);
  vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: vi.fn(async () => flux) } });
  vi.mocked(creerCaptureVocale).mockImplementation(async (_c, _s, recevoir) => { envoyer = recevoir; return { methode: 'worklet', arreter: decrocher }; });
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });
const tour = () => new Promise<void>(r => { queueMicrotask(r); });
async function pret() { for (let i = 0; i < 12; i++) await tour(); }
function lancer(controle = new AbortController()) {
  let fin!: () => void;
  const debut = vi.fn(), niveau = vi.fn();
  const resultat = capturerProfil({ signal: controle.signal, fin: new Promise(r => { fin = r; }), pret: debut, niveau });
  return { resultat, fin, controle, debut, niveau };
}

describe('Le microphone du profil ne survit pas à sa capture (§78)', () => {
  it('arrête le micro et garde les octets dans leur ordre au clic Terminer', async () => {
    const t = lancer(); await pret();
    expect(t.debut).toHaveBeenCalledOnce();
    envoyer(new Uint8Array([1, 0, 2, 0]).buffer); envoyer(new Uint8Array([3, 0]).buffer);
    t.fin(); expect(atob(await t.resultat)).toBe('\x01\0\x02\0\x03\0');
    expect(arreter).toHaveBeenCalledOnce(); expect(fermer).toHaveBeenCalledOnce(); expect(decrocher).toHaveBeenCalledOnce();
  });
  it('ferme automatiquement après huit secondes, même sans clic', async () => {
    const t = lancer(); await pret(); envoyer(new ArrayBuffer(1000));
    await vi.advanceTimersByTimeAsync(8000); await t.resultat;
    expect(arreter).toHaveBeenCalledOnce(); expect(t.niveau).toHaveBeenLastCalledWith(0);
  });
  it('borne aussi les octets si le navigateur retarde sa minuterie', async () => {
    const t = lancer(); await pret(); envoyer(new ArrayBuffer(260000)); t.fin();
    expect(atob(await t.resultat)).toHaveLength(256000);
  });
  it('une permission tardive après annulation ferme immédiatement la piste', async () => {
    let autoriser!: (m: MediaStream) => void;
    vi.mocked(navigator.mediaDevices.getUserMedia).mockReturnValue(new Promise(r => { autoriser = r; }));
    const t = lancer(); const verdict = expect(t.resultat).rejects.toMatchObject({ name: 'AbortError' });
    t.controle.abort(); await verdict;
    autoriser(flux); await pret();
    expect(arreter).toHaveBeenCalledOnce(); expect(t.debut).not.toHaveBeenCalled();
  });
  it('une annulation pendant la capture ferme sans fournir d’enregistrement', async () => {
    const t = lancer(); await pret(); envoyer(new ArrayBuffer(1000));
    const verdict = expect(t.resultat).rejects.toMatchObject({ name: 'AbortError' });
    t.controle.abort(); await verdict;
    expect(arreter).toHaveBeenCalledOnce(); expect(decrocher).toHaveBeenCalledOnce();
  });
  it('une capture vide ne devient pas une empreinte', async () => {
    const t = lancer(); await pret(); t.fin();
    await expect(t.resultat).rejects.toMatchObject({ motif: 'invalidSample' });
    expect(arreter).toHaveBeenCalledOnce();
  });
  it('refuse un contexte audio au mauvais débit', async () => {
    vi.stubGlobal('AudioContext', class extends Contexte { sampleRate = 48000; });
    await expect(lancer().resultat).rejects.toMatchObject({ motif: 'capture' });
    expect(arreter).toHaveBeenCalledOnce();
  });
  it('ferme aussi le micro si le nœud audio échoue pendant le nettoyage', async () => {
    const t = lancer(); await pret(); envoyer(new ArrayBuffer(1000));
    decrocher.mockImplementationOnce(() => { throw new Error('déjà déconnecté'); }); t.fin();
    await t.resultat; expect(arreter).toHaveBeenCalledOnce(); expect(fermer).toHaveBeenCalledOnce();
  });
  it('une annulation pendant le chargement du worklet ferme le micro sans attendre', async () => {
    let charger!: (v: Awaited<ReturnType<typeof creerCaptureVocale>>) => void;
    vi.mocked(creerCaptureVocale).mockReturnValueOnce(new Promise(r => { charger = r; }));
    const t = lancer(); await pret();
    const verdict = expect(t.resultat).rejects.toMatchObject({ name: 'AbortError' });
    t.controle.abort(); await verdict;
    expect(arreter).toHaveBeenCalledOnce(); expect(fermer).toHaveBeenCalledOnce();
    charger({ methode: 'worklet', arreter: decrocher }); await pret();
    expect(decrocher).toHaveBeenCalledOnce(); expect(t.debut).not.toHaveBeenCalled();
  });
  it('refuse des octets incomplets sans les réinterpréter', () => {
    expect(() => assemblerPcm([new ArrayBuffer(1)])).toThrow();
  });
});

describe('Les erreurs ne s’affichent pas comme un profil enregistré (§100)', () => {
  it('signale le serveur ancien sans prétendre que le profil est absent', async () => {
    vi.mocked(apiFetch).mockResolvedValue(new Response('{}', { status: 404 }));
    await expect(requeteProfil()).rejects.toMatchObject({ motif: 'notLoaded' });
  });
  it('garde l’indice à reprendre quand une autre voix se trouve dans les captures', async () => {
    vi.mocked(apiFetch).mockResolvedValue(new Response(JSON.stringify({ detail: { reason: 'differentVoice', index: 6 } }), { status: 422 }));
    await expect(requeteProfil('', 'PUT', {})).rejects.toMatchObject({ motif: 'differentVoice', indice: 6 });
  });
});
