import { beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * La couche qui parle au serveur — celle que useModeGestes.test.ts remplace
 * par des doublures, et que rien ne vérifiait donc.
 *
 * Deux points y valent d'être constatés plutôt que supposés : le 409 de
 * /v1/gestures/frame n'est PAS une panne (c'est le mode qui se referme comme
 * prévu, et le confondre avec une erreur ferait clignoter un message rouge à
 * chaque extinction normale), et l'image voyage en base64 dans du JSON —
 * WKWebView échoue sur un corps binaire.
 */

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock('../../lib/api', () => ({ apiFetch }));

import {
  armer,
  choisirLAppareil,
  desarmer,
  EchecGeste,
  ecouterLesClaps,
  envoyerImage,
  lireDiagnostic,
  oublierFichierPrepare,
  preparerFichierPourGeste,
  renoncerAuDepot,
} from './api';

function repondre(corps: unknown, status = 200): Response {
  return new Response(typeof corps === 'string' ? corps : JSON.stringify(corps), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

beforeEach(() => {
  apiFetch.mockReset();
});

describe('envoyerImage', () => {
  it('envoie du JSON, pas du binaire', async () => {
    apiFetch.mockResolvedValue(
      repondre({ state: 'MAIN_VUE', changed: true, hand: true, frames: 7, fps: 12 }),
    );
    await envoyerImage('SU1BR0U=');
    expect(apiFetch).toHaveBeenCalledWith('/v1/gestures/frame', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image: 'SU1BR0U=' }),
    });
  });

  it('rend la cadence que le serveur a décidée', async () => {
    apiFetch.mockResolvedValue(
      repondre({ state: 'REPOS', changed: false, hand: false, frames: 40, fps: 3 }),
    );
    await expect(envoyerImage('SU1BR0U=')).resolves.toMatchObject({ fps: 3 });
  });

  it('lit un 409 comme un désarmement, pas comme une panne', async () => {
    apiFetch.mockResolvedValue(repondre({ detail: 'not armed' }, 409));
    await expect(envoyerImage('SU1BR0U=')).resolves.toBeNull();
  });

  it('nomme l’étape quand le réseau lâche', async () => {
    apiFetch.mockRejectedValue(new Error('Load failed'));
    await expect(envoyerImage('SU1BR0U=')).rejects.toBeInstanceOf(EchecGeste);
    await expect(envoyerImage('SU1BR0U=')).rejects.toMatchObject({
      etape: 'envoi',
    });
  });

  it('remonte le corps d’une vraie erreur du serveur', async () => {
    apiFetch.mockResolvedValue(new Response('image illisible', { status: 400 }));
    await expect(envoyerImage('SU1BR0U=')).rejects.toThrow('image illisible');
  });
});

describe('armer / désarmer', () => {
  it('nomme l’armement quand le serveur ne répond pas', async () => {
    apiFetch.mockRejectedValue(new Error('ECONNREFUSED'));
    await expect(armer()).rejects.toMatchObject({ etape: 'armement' });
  });

  it('désarme sans se plaindre de ce que le serveur répond', async () => {
    apiFetch.mockResolvedValue(repondre({}, 409));
    await expect(desarmer()).resolves.toBeUndefined();
    expect(apiFetch).toHaveBeenCalledWith('/v1/gestures/disarm', {
      method: 'POST',
    });
  });
});

describe('lireDiagnostic', () => {
  it('rend « désarmé » plutôt que de jeter quand la lecture échoue', async () => {
    apiFetch.mockResolvedValue(new Response('nope', { status: 500 }));
    await expect(lireDiagnostic()).resolves.toEqual({ armed: false });
  });
});

describe('choisirLAppareil', () => {
  it('renvoie au serveur SON jeton et l’appareil choisi', async () => {
    apiFetch.mockResolvedValue(repondre({ done: true, target: 'iPhone' }));
    await choisirLAppareil('jeton-42', 'iphone-poche');
    expect(apiFetch).toHaveBeenCalledWith('/v1/gestures/drop/target', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: 'jeton-42', deviceId: 'iphone-poche' }),
    });
  });

  it('répète la raison du refus au lieu de dire « une erreur »', async () => {
    apiFetch.mockResolvedValue(repondre({ detail: 'La question a expiré.' }, 409));
    await expect(choisirLAppareil('jeton-42', 'iphone-poche')).rejects.toThrow(
      'La question a expiré.',
    );
  });

  it('renonce sans corps ni en-tête', async () => {
    apiFetch.mockResolvedValue(repondre({}));
    await renoncerAuDepot();
    expect(apiFetch).toHaveBeenCalledWith('/v1/gestures/drop/cancel', {
      method: 'POST',
    });
  });
});

describe('préparer un vrai fichier', () => {
  it('envoie seulement son chemin au serveur local et rend les métadonnées', async () => {
    apiFetch.mockResolvedValue(
      repondre({
        preparedFile: {
          type: 'file',
          id: 'file-42',
          title: 'vacances.mp4',
          sizeBytes: 8192,
          mimeType: 'video/mp4',
        },
      }),
    );
    await expect(
      preparerFichierPourGeste('C:\\Photos\\vacances.mp4'),
    ).resolves.toMatchObject({ id: 'file-42', sizeBytes: 8192 });
    expect(apiFetch).toHaveBeenCalledWith('/v1/gestures/file', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: 'C:\\Photos\\vacances.mp4' }),
    });
  });

  it('retire le fichier préparé sans envoyer de corps', async () => {
    apiFetch.mockResolvedValue(repondre({ preparedFile: null }));
    await oublierFichierPrepare();
    expect(apiFetch).toHaveBeenCalledWith('/v1/gestures/file/cancel', {
      method: 'POST',
    });
  });
});

describe('ecouterLesClaps', () => {
  it('vise on ou off selon ce qu’on demande', async () => {
    apiFetch.mockResolvedValue(repondre({ listening: true }));
    await ecouterLesClaps(true);
    expect(apiFetch).toHaveBeenCalledWith('/v1/gestures/clap/on', {
      method: 'POST',
    });
    await ecouterLesClaps(false);
    expect(apiFetch).toHaveBeenCalledWith('/v1/gestures/clap/off', {
      method: 'POST',
    });
  });

  it('rend ce que le serveur CONSTATE, pas ce qu’on a demandé', async () => {
    apiFetch.mockResolvedValue(repondre({ listening: false }));
    await expect(ecouterLesClaps(true)).resolves.toBe(false);
  });

  it('remonte le refus du serveur', async () => {
    apiFetch.mockResolvedValue(repondre({ detail: 'Aucun micro.' }, 503));
    await expect(ecouterLesClaps(true)).rejects.toThrow('Aucun micro.');
  });
});
