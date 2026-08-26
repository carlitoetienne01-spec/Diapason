import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * La moitié qui DÉPENSE.
 *
 * Dix-neuf tests Python vérifient que le serveur met le bon nombre dans son
 * JSON. Aucun ne pouvait vérifier que l'interface l'applique — or c'est elle
 * seule qui ouvre la caméra, encode et envoie, donc elle seule qui coûte.
 * Un serveur qui répond « fps: 3 » à une interface qui filme toujours à
 * douze n'a rien économisé du tout.
 *
 * Doublures maison plutôt que jsdom : c'est la convention de ce dépôt
 * (voir src/features/succes/useRefreshOnFocus.test.ts). React lui-même est
 * remplacé par __banc__/miniReact, l'horloge par __banc__/environnement.
 */

const api = vi.hoisted(() => ({
  armer: vi.fn(),
  desarmer: vi.fn(),
  envoyerImage: vi.fn(),
  lireDiagnostic: vi.fn(),
  ecouterLesClaps: vi.fn(),
  choisirLAppareil: vi.fn(),
  renoncerAuDepot: vi.fn(),
}));

vi.mock('./api', () => ({
  ...api,
  EchecGeste: class EchecGeste extends Error {
    constructor(
      readonly etape: string,
      message: string,
    ) {
      super(message);
    }
  },
}));

vi.mock('react', async () => await import('./__banc__/miniReact'));

import { monterCrochet, type Monture } from './__banc__/miniReact';
import {
  installerEnvironnement,
  vider,
  type Environnement,
} from './__banc__/environnement';
import type { ModeGestes } from './useModeGestes';
import { useModeGestes } from './useModeGestes';

// 1000/12 = 83 ms, 1000/3 = 333 ms. Les deux cadences que le §83 oppose.
const PERIODE_DOUZE = 83;
const PERIODE_TROIS = 333;

const IMAGE_SANS_MAIN = {
  state: 'REPOS' as const,
  changed: false,
  hand: false,
  frames: 1,
};

let env: Environnement;
let monture: Monture<ModeGestes> | null = null;

beforeEach(() => {
  env = installerEnvironnement();
  for (const espion of Object.values(api)) espion.mockReset();
  api.armer.mockResolvedValue({ armed: true });
  api.desarmer.mockResolvedValue(undefined);
  api.lireDiagnostic.mockResolvedValue({ armed: true });
  api.envoyerImage.mockResolvedValue(IMAGE_SANS_MAIN);
  api.ecouterLesClaps.mockResolvedValue(true);
  api.choisirLAppareil.mockResolvedValue({ done: true });
  api.renoncerAuDepot.mockResolvedValue(undefined);
});

afterEach(() => {
  monture?.demonter();
  monture = null;
  env.restaurer();
});

function monter(): Monture<ModeGestes> {
  monture = monterCrochet(() => useModeGestes());
  return monture;
}

/** Armer par le bouton et attendre que la caméra soit réellement ouverte. */
async function armerParLeBouton(): Promise<Monture<ModeGestes>> {
  const m = monter();
  m.valeur().basculer();
  await vider();
  return m;
}

describe('la cadence vient du serveur', () => {
  it('part à douze images par seconde', async () => {
    const m = await armerParLeBouton();
    expect(m.valeur().actif).toBe(true);
    expect(env.camerasOuvertes()).toBe(1);
    expect(env.horloge.periodes()).toContain(PERIODE_DOUZE);
  });

  it('replanifie la boucle quand une réponse porte fps: 3', async () => {
    api.envoyerImage.mockResolvedValue({ ...IMAGE_SANS_MAIN, fps: 3 });
    const m = await armerParLeBouton();

    await env.horloge.avancer(PERIODE_DOUZE);
    expect(api.envoyerImage).toHaveBeenCalledTimes(1);

    // Le serveur a dit trois. La boucle de douze ne doit plus exister.
    expect(env.horloge.periodes()).toContain(PERIODE_TROIS);
    expect(env.horloge.periodes()).not.toContain(PERIODE_DOUZE);

    api.envoyerImage.mockClear();
    await env.horloge.avancer(1000);
    // Trois images dans la seconde qui suit, pas douze. C'est tout le §83.
    expect(api.envoyerImage).toHaveBeenCalledTimes(3);
    expect(env.imagesEncodees()).toBe(4);
    expect(m.valeur().actif).toBe(true);
  });

  it('ne replanifie rien quand la cadence rendue est celle en cours', async () => {
    api.envoyerImage.mockResolvedValue({ ...IMAGE_SANS_MAIN, fps: 12 });
    await armerParLeBouton();
    await env.horloge.avancer(PERIODE_DOUZE * 3);
    expect(env.horloge.periodes()).toContain(PERIODE_DOUZE);
    expect(api.envoyerImage).toHaveBeenCalledTimes(3);
  });

  it('remonte de trois à douze dès qu’une main réapparaît', async () => {
    api.envoyerImage.mockResolvedValue({ ...IMAGE_SANS_MAIN, fps: 3 });
    await armerParLeBouton();
    await env.horloge.avancer(PERIODE_DOUZE);
    expect(env.horloge.periodes()).toContain(PERIODE_TROIS);

    api.envoyerImage.mockResolvedValue({
      state: 'MAIN_VUE',
      changed: true,
      hand: true,
      frames: 2,
      fps: 12,
    });
    await env.horloge.avancer(PERIODE_TROIS);
    expect(env.horloge.periodes()).toContain(PERIODE_DOUZE);
    expect(env.horloge.periodes()).not.toContain(PERIODE_TROIS);
  });

  it('ignore une cadence absente ou nulle plutôt que de diviser par zéro', async () => {
    api.envoyerImage.mockResolvedValue({ ...IMAGE_SANS_MAIN, fps: 0 });
    await armerParLeBouton();
    await env.horloge.avancer(PERIODE_DOUZE);
    expect(env.horloge.periodes()).toContain(PERIODE_DOUZE);
  });
});

describe('éteindre coupe pour de bon', () => {
  it('une réponse en vol ne rallume aucun minuteur', async () => {
    let repondre: ((v: unknown) => void) | null = null;
    api.envoyerImage.mockImplementation(
      () =>
        new Promise((r) => {
          repondre = r as (v: unknown) => void;
        }),
    );
    const m = await armerParLeBouton();
    await env.horloge.avancer(PERIODE_DOUZE);
    expect(api.envoyerImage).toHaveBeenCalledTimes(1);
    expect(repondre).not.toBeNull();

    // On coupe pendant que l'image est encore en l'air.
    m.valeur().basculer();
    await vider();
    expect(m.valeur().actif).toBe(false);
    expect(api.desarmer).toHaveBeenCalledTimes(1);
    expect(env.pistesArretees()).toBe(1);
    expect(env.horloge.armes).toBe(0);

    // …et maintenant la réponse arrive, avec une cadence à appliquer.
    repondre!({ ...IMAGE_SANS_MAIN, fps: 3 });
    await vider();

    expect(env.horloge.armes).toBe(0);
    expect(env.horloge.periodes()).not.toContain(PERIODE_TROIS);
    api.envoyerImage.mockClear();
    await env.horloge.avancer(5000);
    expect(api.envoyerImage).not.toHaveBeenCalled();
    expect(m.valeur().actif).toBe(false);
  });

  it('le démontage ferme la caméra, réponse en vol ou non', async () => {
    let repondre: ((v: unknown) => void) | null = null;
    api.envoyerImage.mockImplementation(
      () =>
        new Promise((r) => {
          repondre = r as (v: unknown) => void;
        }),
    );
    const m = await armerParLeBouton();
    await env.horloge.avancer(PERIODE_DOUZE);

    m.demonter();
    expect(env.pistesArretees()).toBe(1);
    expect(env.horloge.armes).toBe(0);

    repondre!({ ...IMAGE_SANS_MAIN, fps: 3 });
    await vider();
    expect(env.horloge.armes).toBe(0);
  });

  it('suit le serveur qui s’est désarmé tout seul (409)', async () => {
    api.envoyerImage.mockResolvedValue(null);
    const m = await armerParLeBouton();
    await env.horloge.avancer(PERIODE_DOUZE);
    expect(m.valeur().actif).toBe(false);
    expect(env.pistesArretees()).toBe(1);
    expect(env.horloge.armes).toBe(0);
  });

  it('tient un hoquet réseau, cède au troisième d’affilée', async () => {
    api.envoyerImage.mockRejectedValue(new Error('Load failed'));
    const m = await armerParLeBouton();
    await env.horloge.avancer(PERIODE_DOUZE * 2);
    expect(m.valeur().actif).toBe(true);
    await env.horloge.avancer(PERIODE_DOUZE);
    expect(m.valeur().actif).toBe(false);
    expect(m.valeur().erreur).toContain('Load failed');
    expect(env.pistesArretees()).toBe(1);
  });
});

describe('deux clics sur « Activer » pendant l’armement', () => {
  /**
   * CE BLOC ÉCHOUE, ET C'EST LE CONSTAT.
   *
   * Rien ne garde `allumer()` contre un second appel. Le bouton « Activer »
   * n'est pas désactivé pendant l'armement, et cet armement dure un
   * aller-retour serveur PLUS, la première fois, la fenêtre d'autorisation
   * caméra de macOS — plusieurs secondes pendant lesquelles l'écran ne
   * change pas. Recliquer est le réflexe normal.
   *
   * Deux `allumer()` ouvrent alors DEUX flux. `flux.current` ne retient que
   * le second ; le premier n'est plus référencé par rien, donc `eteindre()`
   * ne l'arrête jamais — ni au bouton, ni au démontage. Le voyant vert de
   * macOS reste allumé alors que l'application affiche le mode éteint.
   *
   * C'est exactement ce que le §78 dit vouloir rendre impossible, et ce que
   * l'en-tête du crochet promet : « la caméra se referme à tout coup ».
   */
  it('n’ouvre qu’une seule caméra', async () => {
    const m = monter();
    m.valeur().basculer();
    m.valeur().basculer();
    await vider();
    expect(env.camerasOuvertes()).toBe(1);
    expect(api.armer).toHaveBeenCalledTimes(1);
  });

  it('arrête TOUTES les pistes ouvertes quand on coupe', async () => {
    const m = monter();
    m.valeur().basculer();
    m.valeur().basculer();
    await vider();

    m.valeur().basculer();
    await vider();
    expect(m.valeur().actif).toBe(false);
    // Le voyant vert doit dire la vérité : plus une seule piste vivante.
    expect(env.pistesArretees()).toBe(env.pistes.length);
  });

  it('ne laisse aucune piste survivre au démontage', async () => {
    const m = monter();
    m.valeur().basculer();
    m.valeur().basculer();
    await vider();
    m.demonter();
    expect(env.pistesArretees()).toBe(env.pistes.length);
  });
});

describe('la case des claps suit le serveur', () => {
  it('se coche sur ce que le serveur confirme, pas sur le clic', async () => {
    api.ecouterLesClaps.mockResolvedValue(false);
    const m = monter();
    m.valeur().basculerLesClaps();
    await vider();
    expect(api.ecouterLesClaps).toHaveBeenCalledWith(true);
    // Le serveur a répondu « non » : la case ne doit pas mentir.
    expect(m.valeur().clapsEcoutent).toBe(false);
  });

  it('se décoche quand le fil d’écoute meurt tout seul', async () => {
    api.lireDiagnostic.mockResolvedValue({
      armed: false,
      clapListening: true,
      clapsHeard: 2,
    });
    const m = monter();
    m.valeur().basculerLesClaps();
    await vider();
    expect(m.valeur().clapsEcoutent).toBe(true);

    // Casque débranché, micro repris par une autre application : le
    // serveur n'écoute plus. La case ne doit pas rester cochée.
    api.lireDiagnostic.mockResolvedValue({
      armed: false,
      clapListening: false,
      clapsHeard: 2,
    });
    await env.horloge.avancer(2000);
    expect(m.valeur().clapsEcoutent).toBe(false);
    expect(m.valeur().erreur).toContain('micro');
    // Le sondage s'arrête avec l'écoute : rien ne guette en permanence.
    expect(env.horloge.armes).toBe(0);
  });

  it('se réaligne aussi caméra allumée, pas seulement caméra éteinte', async () => {
    api.lireDiagnostic.mockResolvedValue({ armed: true, clapListening: true });
    const m = monter();
    m.valeur().basculerLesClaps();
    await vider();
    m.valeur().basculer();
    await vider();
    expect(m.valeur().actif).toBe(true);
    expect(m.valeur().clapsEcoutent).toBe(true);

    api.lireDiagnostic.mockResolvedValue({ armed: true, clapListening: false });
    await env.horloge.avancer(1000);
    expect(m.valeur().clapsEcoutent).toBe(false);
    expect(m.valeur().erreur).toContain('micro');
  });

  it('laisse la case tranquille quand le serveur ne dit rien de l’écoute', async () => {
    api.lireDiagnostic.mockResolvedValue({ armed: false, clapsHeard: 0 });
    const m = monter();
    m.valeur().basculerLesClaps();
    await vider();
    expect(m.valeur().clapsEcoutent).toBe(true);
    await env.horloge.avancer(2000);
    expect(m.valeur().clapsEcoutent).toBe(true);
    expect(m.valeur().erreur).toBeNull();
  });

  it('ouvre la caméra sur un double clap sans réarmer la session', async () => {
    api.lireDiagnostic.mockResolvedValue({ armed: true, clapListening: true });
    const m = monter();
    m.valeur().basculerLesClaps();
    await vider();
    await env.horloge.avancer(2000);
    expect(m.valeur().actif).toBe(true);
    expect(env.camerasOuvertes()).toBe(1);
    // Ré-armer ici perdrait le geste que le clap vient d'ouvrir.
    expect(api.armer).not.toHaveBeenCalled();
  });
});

describe('répondre à « vers lequel ? »', () => {
  const enAttente = {
    armed: true,
    pendingDrop: {
      token: 'jeton-42',
      object: { type: 'project', id: 'p-1', title: 'Zéro à Héro' },
      candidates: [
        { deviceId: 'mac-atelier', name: 'Mac de l’atelier' },
        { deviceId: 'iphone-poche', name: 'iPhone' },
      ],
      secondsLeft: 12,
    },
  };

  it('transmet le jeton du serveur et l’appareil choisi', async () => {
    api.lireDiagnostic.mockResolvedValue(enAttente);
    const m = await armerParLeBouton();
    await env.horloge.avancer(1000);
    expect(m.valeur().diagnostic?.pendingDrop?.token).toBe('jeton-42');

    m.valeur().choisir('iphone-poche');
    await vider();
    expect(api.choisirLAppareil).toHaveBeenCalledWith('jeton-42', 'iphone-poche');
  });

  it('n’envoie rien quand aucune question n’est en cours', async () => {
    api.lireDiagnostic.mockResolvedValue({ armed: true });
    const m = await armerParLeBouton();
    await env.horloge.avancer(1000);
    m.valeur().choisir('iphone-poche');
    await vider();
    expect(api.choisirLAppareil).not.toHaveBeenCalled();
  });
});
