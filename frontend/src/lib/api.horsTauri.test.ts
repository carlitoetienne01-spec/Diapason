import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  getCloudKeyStatus,
  getInferenceSource,
  lireStatutCles,
  oublierStatutDesCles,
  saveCloudKey,
  setInferenceSource,
} from './api';

// Hors de Tauri — le téléphone, un navigateur — ces fonctions inventaient
// leur réponse : `{}` pour les clés, `ollama` pour la source (26/09/2026).

const fetchMock = vi.fn<typeof fetch>();
const fetchOriginal = globalThis.fetch;

function reponseJson(corps: unknown, status = 200): Response {
  return new Response(JSON.stringify(corps), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

beforeEach(() => {
  fetchMock.mockReset();
  globalThis.fetch = fetchMock;
  oublierStatutDesCles();
});

afterEach(() => {
  globalThis.fetch = fetchOriginal;
  document.documentElement.removeAttribute('lang');
});

describe('Hors de Tauri, les réglages du Mac se lisent sur le serveur', () => {
  it('la source d’inférence vient du serveur, pas d’un « ollama » inventé', async () => {
    fetchMock.mockResolvedValue(reponseJson({ kind: 'custom', engine: 'lmstudio', model: 'm' }));
    await expect(getInferenceSource()).resolves.toEqual({ kind: 'custom', engine: 'lmstudio', model: 'm' });
    expect(String(fetchMock.mock.calls[0][0])).toMatch(/\/v1\/inference\/source$/);
  });

  it('un serveur qui échoue fait échouer la lecture au lieu de rendre ollama', async () => {
    fetchMock.mockResolvedValue(reponseJson({}, 500));
    await expect(getInferenceSource()).rejects.toThrow(/500/);
  });

  it('l’état des clés vient du serveur, pas d’un `{}` inventé', async () => {
    fetchMock.mockResolvedValue(
      reponseJson({ keys: [{ key: 'ANTHROPIC_API_KEY', set: true }, { key: 'OPENAI_API_KEY', set: false }] }),
    );
    await expect(getCloudKeyStatus()).resolves.toEqual({ ANTHROPIC_API_KEY: true, OPENAI_API_KEY: false });
    expect(String(fetchMock.mock.calls[0][0])).toMatch(/\/v1\/cloud\/keys$/);
  });

  it('un serveur qui échoue fait échouer l’état des clés au lieu de rendre `{}`', async () => {
    // Échec évité (26/09/2026) : rendre `{}` sur un 500 disait « aucune
    // clé » pour un Mac qui en a — aucun test ne le gardait.
    fetchMock.mockResolvedValue(reponseJson({}, 500));
    await expect(getCloudKeyStatus()).rejects.toThrow();
  });

  it('une rafale de lectures ne fait qu’un appel ; un échec n’est pas gardé', async () => {
    fetchMock.mockResolvedValueOnce(reponseJson({}, 500));
    await expect(getCloudKeyStatus()).rejects.toThrow();
    fetchMock.mockResolvedValue(reponseJson({ keys: [{ key: 'OPENAI_API_KEY', set: true }] }));
    const lectures = await Promise.all([getCloudKeyStatus(), getCloudKeyStatus(), getCloudKeyStatus()]);
    expect(lectures.every((l) => l.OPENAI_API_KEY === true)).toBe(true);
    expect(fetchMock, 'un échec, puis UNE lecture pour trois demandes').toHaveBeenCalledTimes(2);
  });

  it('écrire reste l’affaire de l’app de bureau, et le dit dans la langue affichée', async () => {
    document.documentElement.setAttribute('lang', 'fr');
    await expect(saveCloudKey('OPENAI_API_KEY', 'x')).rejects.toThrow('app Diapason du Mac');
    await expect(setInferenceSource({ kind: 'ollama' })).rejects.toThrow('app Diapason du Mac');
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe('lireStatutCles', () => {
  it('ignore les lignes mal formées plutôt que d’inventer une clé présente', () => {
    expect(
      lireStatutCles([
        { key: 'A_API_KEY', set: true },
        { key: 'B_API_KEY', set: 'oui' },
        { set: true },
        null,
      ]),
    ).toEqual({ A_API_KEY: true });
    expect(lireStatutCles(undefined)).toEqual({});
  });
});
