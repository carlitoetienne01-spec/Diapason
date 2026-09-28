import { afterEach, describe, expect, it, vi } from 'vitest';
import { streamChat, streamResearch } from './sse';
import { CoupureDuFlux, lireCoupure } from './coupureDuFlux';

vi.mock('./api', () => ({ getBase: () => 'http://test.invalid', authHeaders: (v: unknown) => v }));
afterEach(() => vi.unstubAllGlobals());
const request = { model: 'test', messages: [], stream: true as const };

function fournisseur(morceaux: string[]) {
  const annuler = vi.fn();
  const encodeur = new TextEncoder();
  const body = new ReadableStream({
    start(controller) { for (const morceau of morceaux) controller.enqueue(encodeur.encode(morceau)); },
    cancel: annuler,
  });
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, body }));
  return annuler;
}
describe('réception et fermeture du flux', () => {
  it('publie le début d’outil avant la réponse et mesure les octets UTF-8 reçus', async () => {
    let controleur!: ReadableStreamDefaultController<Uint8Array>;
    const body = new ReadableStream<Uint8Array>({ start(c) { controleur = c; } });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, body }));
    const mesurer = vi.fn();
    const flux = streamChat(request, undefined, mesurer);
    const debut = flux.next();
    const appel = new TextEncoder().encode('event: tool_call_start\ndata: {"tool":"web_search","arguments":"écriture"}\n\n');
    controleur.enqueue(appel);
    const recu = await debut;
    expect(recu.value?.event).toBe('tool_call_start');
    expect(mesurer.mock.calls[0][0].byteLength).toBe(appel.byteLength);
    // La fin n'existe pas encore. Un consommateur qui mettrait en tampon
    // jusqu'à la réponse finale ne pourrait pas satisfaire cette assertion.
    const suivant = flux.next();
    controleur.enqueue(new TextEncoder().encode('data: {"choices":[{"delta":{"content":"Réponse"}}]}\n\n'));
    expect((await suivant).value?.data).toContain('Réponse');
    await flux.return(undefined);
  });
  it('transmet les questions fragmentées et conserve le refus de reposer le formulaire au tour suivant', async () => {
    fournisseur(['event: questions\n', 'data: {"id":"q"}\n\n', 'data: [DONE]\n\n']);
    const resultats = [];
    for await (const event of streamChat({ ...request, interactiveQuestions: false })) resultats.push(event);
    expect(resultats).toEqual([{ event: 'questions', data: '{"id":"q"}' }]);
    expect(JSON.parse(vi.mocked(fetch).mock.calls[0][1]!.body as string).interactiveQuestions).toBe(false);
  });
  it('garde un nom d’événement séparé de ses données par deux lectures réseau', async () => {
    fournisseur(['event: tool_call_start\n', 'data: {"tool":"succes_tasks"}\n\n', 'data: [DONE]\n\n']);
    const resultats = [];
    for await (const event of streamChat(request)) resultats.push(event);
    expect(resultats).toEqual([{ event: 'tool_call_start', data: '{"tool":"succes_tasks"}' }]);
  });
  it('ferme la lecture au finish_reason même si le serveur n’a pas envoyé DONE', async () => {
    const annuler = fournisseur(['data: {"choices":[{"finish_reason":"stop"}]}\n\n']);
    for await (const _ of streamChat(request)) break;
    expect(annuler).toHaveBeenCalledTimes(1);
  });
  it('la recherche ferme aussi sa lecture à la fin logique', async () => {
    const annuler = fournisseur(['data: {"type":"done"}\n\n']);
    const resultats = [];
    for await (const event of streamResearch('test')) resultats.push(event);
    expect(resultats).toEqual([{ type: 'done' }]);
    expect(annuler).toHaveBeenCalledTimes(1);
  });
});

// 28/09/2026 : les en-têtes 200 arrivés, `reader.read()` échoue au milieu du
// corps (TypeError « network error » de la WebView Chromium). La bulle disait
// « Erreur : network error » ; le flux lève désormais une CoupureDuFlux.
function corpsQuiCasse(avant: string, erreur: unknown) {
  const encodeur = new TextEncoder();
  let envoye = false;
  const body = new ReadableStream<Uint8Array>({
    pull(controller) {
      if (!envoye) { envoye = true; controller.enqueue(encodeur.encode(avant)); return; }
      controller.error(erreur);
    },
  });
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, body }));
}
describe('un corps qui casse après les en-têtes', () => {
  it('le chat lève une CoupureDuFlux, après avoir rendu ce qui était arrivé', async () => {
    corpsQuiCasse('data: {"choices":[{"delta":{"content":"Début"}}]}\n\n', new TypeError('network error'));
    const recus: string[] = [];
    const erreur = await (async () => { for await (const ev of streamChat(request)) recus.push(ev.data); })()
      .catch((e: unknown) => e);
    expect(recus, 'le texte déjà reçu n’est pas perdu').toHaveLength(1);
    expect(erreur, 'une coupure, plus « Erreur : network error »').toBeInstanceOf(CoupureDuFlux);
    expect(lireCoupure(erreur, true)).toEqual({ detail: 'TypeError: network error', during: 'response', overTailnet: true });
  });
  it('la recherche approfondie aussi', async () => {
    corpsQuiCasse('data: {"type":"synthesis","text":"Début"}\n\n', new TypeError('Load failed'));
    const erreur = await (async () => { for await (const _ of streamResearch('test')) { /* lire */ } })()
      .catch((e: unknown) => e);
    expect(erreur).toBeInstanceOf(CoupureDuFlux);
    expect((erreur as CoupureDuFlux).brut).toBe('TypeError: Load failed');
  });
  it('un arrêt demandé pendant la lecture reste un AbortError', async () => {
    const arret = Object.assign(new Error('aborted'), { name: 'AbortError' });
    corpsQuiCasse('data: {"choices":[{"delta":{"content":"Début"}}]}\n\n', arret);
    const erreur = await (async () => { for await (const _ of streamChat(request)) { /* lire */ } })()
      .catch((e: unknown) => e);
    expect(erreur, 'le bouton Arrêter garde « (Génération interrompue) »').toBe(arret);
  });
});
