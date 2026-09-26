// Servi par le tailnet, le bundle ne demande plus ce que la passerelle refuse
// (plan mobile, constat 15 — 26/09/2026). La liste est tenue contre
// l'instantané du serveur, dans les deux sens.

import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  ENTETE_PASSERELLE,
  FAMILLES_REFUSEES,
  SONDES_REFUSEES,
  SondeNonEnvoyee,
  cleDeSonde,
  creerAnnonceur,
  creerEtatDuTailnet,
  garderLaSonde,
} from './tailnet';

// vitest tourne depuis `frontend/` (voir appelsApi.test.ts).
const PORTEE = JSON.parse(
  readFileSync(join(process.cwd(), '..', 'tests', 'contract', 'tailnet_portee.json'), 'utf-8'),
) as Record<string, 'ouverte' | 'session' | 'refusee'>;

/** Un chemin concret pour un gabarit Starlette : `{x}` → `x1`, `{x:path}` → `a/b`. */
function exemple(gabarit: string): string {
  return gabarit.replace(/\{[^}]+:path\}/g, 'a/b').replace(/\{[^}]+\}/g, 'x1');
}

const CLES = Object.entries(PORTEE).map(([cle, classe]) => {
  const [methode, chemin] = cle.split(' ');
  return { cle, classe, methode, chemin };
});

describe('La liste des sondes refusées suit tailnet_portee.json', () => {
  it('l’instantané est bien lu (sinon le reste ne prouve rien)', () => {
    expect(CLES.length, 'tests/contract/tailnet_portee.json est vide ou illisible').toBeGreaterThan(400);
  });

  it('chaque entrée est une route que la passerelle REFUSE', () => {
    const fausses = SONDES_REFUSEES.filter((cle) => PORTEE[cle] !== 'refusee').map(
      (cle) => `${cle} → ${PORTEE[cle] ?? 'absente de l’instantané'}`,
    );
    expect(
      fausses,
      'ces routes ne sont plus refusées au téléphone : le bundle les priverait d’une lecture permise',
    ).toEqual([]);
  });

  it('aucune lecture refusée n’y manque', () => {
    const manquantes = CLES.filter(
      ({ classe, methode }) => classe === 'refusee' && methode === 'GET',
    )
      .filter(({ chemin }) => cleDeSonde('GET', exemple(chemin)) === null)
      .map(({ cle }) => cle);
    expect(
      manquantes,
      'la passerelle refuse ces lectures, et le bundle les relancerait pour un 403 : les ajouter à SONDES_REFUSEES',
    ).toEqual([]);
  });

  it('aucune route ouverte ou sous session n’est retenue par erreur', () => {
    const retenues = CLES.filter(({ classe, methode }) => classe !== 'refusee' && /^[A-Z]+$/.test(methode))
      .filter(({ methode, chemin }) => methode !== 'WS' && methode !== 'MOUNT')
      .filter(({ methode, chemin }) => cleDeSonde(methode, exemple(chemin)) !== null)
      .map(({ cle, classe }) => `${cle} (${classe})`);
    expect(retenues, 'le téléphone perdrait ces routes que la passerelle lui ouvre').toEqual([]);
  });

  it('les familles couvrent des routes toutes refusées', () => {
    for (const famille of FAMILLES_REFUSEES) {
      const [methode, prefixe] = famille.split(' ');
      const couvertes = CLES.filter((c) => c.methode === methode && c.chemin.startsWith(prefixe));
      expect(couvertes.length, `${famille} ne couvre aucune route`).toBeGreaterThan(0);
      expect(
        couvertes.filter((c) => c.classe !== 'refusee').map((c) => c.cle),
        `${famille} couvrirait une route permise`,
      ).toEqual([]);
    }
  });

  it('la seule écriture retenue est la publication automatique de la vue', () => {
    // Une ACTION refusée (un clic) part : c'est la passerelle qui dit
    // pourquoi (§100). Seul ce que le bundle fait SANS clic est retenu.
    expect(SONDES_REFUSEES.filter((cle) => !cle.startsWith('GET '))).toEqual(['POST /v1/context/view']);
  });
});

describe('cleDeSonde — reconnaître une route au gabarit près', () => {
  it('ignore la requête et l’ancre', () => {
    expect(cleDeSonde('GET', '/v1/triggers/poll?since=12')).toBe('GET /v1/triggers/poll');
    expect(cleDeSonde(undefined, '/v1/mesh/inbox?drain=true#x')).toBe('GET /v1/mesh/inbox');
  });

  it('lit une adresse absolue', () => {
    expect(cleDeSonde('GET', 'https://atelier.tail6efbba.ts.net/v1/voice/live/health')).toBe(
      'GET /v1/voice/live/health',
    );
  });

  it('remplit les paramètres du gabarit', () => {
    expect(cleDeSonde('GET', '/v1/mesh/devices/dev_abc/sessions')).toBe('GET /v1/mesh/devices/{device_id}/sessions');
    expect(cleDeSonde('GET', '/v1/tools/web_search/credentials/status')).toBe(
      'GET /v1/tools/{tool_name}/credentials/status',
    );
  });

  it('classe HEAD comme GET, comme la passerelle', () => {
    expect(cleDeSonde('HEAD', '/v1/account/status')).toBe('GET /v1/account/status');
  });

  it('laisse partir une action au clic, même sur une route refusée', () => {
    expect(cleDeSonde('POST', '/v1/mesh/devices/dev_abc/revoke'), 'la passerelle dira pourquoi').toBeNull();
    expect(cleDeSonde('POST', '/v1/account/login')).toBeNull();
  });

  it('laisse partir les lectures permises', () => {
    expect(cleDeSonde('GET', '/v1/models')).toBeNull();
    expect(cleDeSonde('GET', '/v1/vie/tasks')).toBeNull();
    expect(cleDeSonde('GET', '/v1/mesh/devices/x/sessions/extra')).toBeNull();
  });

  it('retient l’alias /v1/succes/ par famille, sans déborder', () => {
    expect(cleDeSonde('GET', '/v1/succes/tasks')).toBe('GET /v1/succes/');
    expect(cleDeSonde('GET', '/v1/successeur')).toBeNull();
  });
});

describe('creerEtatDuTailnet — le signal de la passerelle', () => {
  const avec = (valeur: string | null) => ({ headers: { get: (nom: string) => (nom === ENTETE_PASSERELLE ? valeur : null) } });

  it('le pont natif suffit', () => {
    expect(creerEtatDuTailnet(true).servi()).toBe(true);
  });

  it('se verrouille sur l’en-tête de la passerelle, et sur lui seul', () => {
    const etat = creerEtatDuTailnet(false);
    expect(etat.noterReponse(avec(null)), 'une réponse de 8000 ne dit rien').toBe(false);
    expect(etat.noterReponse(avec('autre')), 'une autre valeur ne dit rien').toBe(false);
    expect(etat.noterReponse(avec('tailnet'))).toBe(true);
    expect(
      etat.noterReponse(avec(null)),
      'une réponse sans l’en-tête (cache, service worker) ne rend pas au bundle ce que la passerelle refuse',
    ).toBe(true);
  });

  it('servi dès le chargement quand le pont est là, avant tout en-tête', async () => {
    // 26/09/2026, contre-épreuve (mutant V11 : `creerEtatDuTailnet(false)`
    // au lieu d'`estMobile`) : au téléphone, les premières sondes seraient
    // parties avant la première réponse de la passerelle.
    const fenetre = window as unknown as Record<string, unknown>;
    fenetre.DiapasonNatif = { postMessage: () => {} };
    vi.resetModules();
    try {
      const module = await import('./tailnet');
      expect(module.serviParLeTailnet(), 'le pont natif dit « téléphone » dès le chargement').toBe(true);
      expect(() => module.garderLaSonde('GET', '/v1/triggers/poll', undefined, () => true)).toThrow(
        module.SondeNonEnvoyee,
      );
    } finally {
      delete fenetre.DiapasonNatif;
      delete fenetre.diapasonNatifRecevoir;
      document.documentElement.removeAttribute('data-diapason-mobile');
      vi.resetModules();
    }
  });

  it('survit à des en-têtes illisibles', () => {
    const etat = creerEtatDuTailnet(false);
    const casse = {
      headers: {
        get: () => {
          throw new Error('illisible');
        },
      },
    };
    expect(etat.noterReponse(casse)).toBe(false);
    expect(etat.noterReponse(undefined)).toBe(false);
  });
});

describe('garderLaSonde — ne pas envoyer, et le dire une fois', () => {
  it('ne fait rien hors du tailnet : le Mac relève ses déclencheurs', () => {
    const dire = vi.fn(() => true);
    expect(() => garderLaSonde('GET', '/v1/triggers/poll', creerEtatDuTailnet(false), dire)).not.toThrow();
    expect(dire).not.toHaveBeenCalled();
  });

  it('retient une lecture refusée par une erreur nommée', () => {
    const etat = creerEtatDuTailnet(true);
    let levee: unknown = null;
    try {
      garderLaSonde('GET', '/v1/voice/live/health', etat, () => true);
    } catch (e) {
      levee = e;
    }
    expect(levee).toBeInstanceOf(SondeNonEnvoyee);
    expect((levee as SondeNonEnvoyee).cle).toBe('GET /v1/voice/live/health');
  });

  it('laisse passer ce que la passerelle permet', () => {
    expect(() => garderLaSonde('GET', '/v1/models', creerEtatDuTailnet(true), () => true)).not.toThrow();
  });

  it('dit chaque route une seule fois, au lieu d’un 403 toutes les deux secondes', () => {
    const journal = vi.fn();
    const dire = creerAnnonceur(journal);
    const etat = creerEtatDuTailnet(true);
    for (let i = 0; i < 5; i += 1) {
      expect(() => garderLaSonde('GET', '/v1/triggers/poll?since=0', etat, dire)).toThrow(SondeNonEnvoyee);
    }
    expect(() => garderLaSonde('GET', '/v1/account/status', etat, dire)).toThrow(SondeNonEnvoyee);
    expect(journal, 'une ligne par route, pas une par tour').toHaveBeenCalledTimes(2);
    expect(String(journal.mock.calls[0][0])).toContain('GET /v1/triggers/poll');
  });
});

describe('apiFetch — la garde avant tout envoi', () => {
  const fetchOriginal = globalThis.fetch;
  afterEach(() => {
    globalThis.fetch = fetchOriginal;
    vi.resetModules();
  });

  it('après une réponse de la passerelle, une lecture refusée ne part plus', async () => {
    vi.resetModules();
    const { apiFetch } = await import('./api');
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      new Response('{"data":[]}', { status: 200, headers: { [ENTETE_PASSERELLE]: 'tailnet' } }),
    );
    globalThis.fetch = fetchMock;
    const info = vi.spyOn(console, 'info').mockImplementation(() => undefined);

    await apiFetch('/v1/models');
    expect(fetchMock).toHaveBeenCalledTimes(1);

    const { SondeNonEnvoyee: Erreur } = await import('./tailnet');
    await expect(apiFetch('/v1/triggers/poll?since=0')).rejects.toBeInstanceOf(Erreur);
    await expect(apiFetch('/v1/triggers/poll?since=2')).rejects.toBeInstanceOf(Erreur);
    expect(fetchMock, 'la relève ne doit pas atteindre le réseau').toHaveBeenCalledTimes(1);
    expect(info, 'dit une fois').toHaveBeenCalledTimes(1);

    await apiFetch('/v1/vie/tasks');
    expect(fetchMock, 'une lecture permise part toujours').toHaveBeenCalledTimes(2);
    info.mockRestore();
  });

  it('sur la boucle locale, rien ne change', async () => {
    vi.resetModules();
    const { apiFetch } = await import('./api');
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(new Response('{}', { status: 200 }));
    globalThis.fetch = fetchMock;
    await apiFetch('/v1/triggers/poll?since=0');
    await apiFetch('/v1/triggers/poll?since=0');
    expect(fetchMock, 'le Mac relève ses déclencheurs').toHaveBeenCalledTimes(2);
  });
});
