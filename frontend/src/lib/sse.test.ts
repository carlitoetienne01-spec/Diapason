import { afterEach, describe, expect, it, vi } from 'vitest';
import { streamChat, streamResearch } from './sse';

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
