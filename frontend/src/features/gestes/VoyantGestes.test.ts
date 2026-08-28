import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';

/**
 * Le voyant est le SEUL morceau du mode gestes monté sur toutes les pages.
 * La question « vers lequel ? » n'a donc qu'un endroit où être vue au moment
 * où elle se pose — et une seule occasion d'envoyer le bon identifiant. Si
 * elle envoie celui du voisin, le serveur obéit : il ne peut pas savoir.
 */

const contexte = vi.hoisted(() => ({ valeur: {} as Record<string, unknown> }));

vi.mock('react', async () => await import('./__banc__/miniReact'));
vi.mock('react/jsx-runtime', async () => await import('./__banc__/miniReact'));
vi.mock(
  'react/jsx-dev-runtime',
  async () => await import('./__banc__/miniReact'),
);
vi.mock('lucide-react', () => ({ FileUp: () => null, Hand: () => null }));
vi.mock('./ModeGestesContexte', () => ({
  useModeGestesPartage: () => contexte.valeur,
}));

import {
  creer,
  cliquer,
  elements,
  monterComposant,
  texte,
  type MontureArbre,
} from './__banc__/miniReact';
import {
  installerEnvironnement,
  type Environnement,
} from './__banc__/environnement';
import { VoyantGestes } from './VoyantGestes';

const CANDIDATS = [
  { deviceId: 'mac-atelier', name: 'Mac de l’atelier' },
  { deviceId: 'iphone-poche', name: 'iPhone' },
  { deviceId: 'ipad-salon', name: 'iPad du salon' },
];

let env: Environnement;
let monture: MontureArbre | null = null;
let choisir: ReturnType<typeof vi.fn>;
let renoncer: ReturnType<typeof vi.fn>;
let basculer: ReturnType<typeof vi.fn>;

function poserLeContexte(supplement: Record<string, unknown>): void {
  choisir = vi.fn();
  renoncer = vi.fn();
  basculer = vi.fn();
  contexte.valeur = {
    actif: true,
    etat: null,
    mainVue: false,
    erreur: null,
    diagnostic: null,
    clapsEcoutent: false,
    basculerLesClaps: vi.fn(),
    basculer,
    choisir,
    renoncer,
    preparerUnFichier: vi.fn(),
    annulerFichierPrepare: vi.fn(),
    ...supplement,
  };
}

function avecQuestion(candidats = CANDIDATS): void {
  poserLeContexte({
    diagnostic: {
      armed: true,
      pendingDrop: {
        token: 'jeton-42',
        object: { type: 'project', id: 'p-1', title: 'Zéro à Héro' },
        candidates: candidats,
        secondsLeft: 11.6,
      },
    },
  });
}

function monter(): MontureArbre {
  monture = monterComposant(creer(VoyantGestes));
  return monture;
}

beforeEach(() => {
  env = installerEnvironnement();
  poserLeContexte({});
});

afterEach(() => {
  monture?.demonter();
  monture = null;
  env.restaurer();
});

describe('la carte « vers lequel ? »', () => {
  it('rend un bouton par candidat, et un seul', () => {
    avecQuestion();
    const boutons = elements(monter().arbre(), 'button');
    // Trois candidats, plus « laisse tomber » — rien de plus.
    expect(boutons).toHaveLength(4);
    expect(boutons.map((b) => texte(b))).toEqual([
      'Mac de l’atelier',
      'iPhone',
      'iPad du salon',
      'laisse tomber',
    ]);
  });

  it('transmet le deviceId du bouton cliqué, pas celui du premier', () => {
    avecQuestion();
    const boutons = elements(monter().arbre(), 'button');
    cliquer(boutons[1]);
    expect(choisir).toHaveBeenCalledTimes(1);
    expect(choisir).toHaveBeenCalledWith('iphone-poche');
  });

  it('donne à chaque candidat son propre identifiant', () => {
    avecQuestion();
    const boutons = elements(monter().arbre(), 'button');
    for (const [i, candidat] of CANDIDATS.entries()) {
      choisir.mockClear();
      cliquer(boutons[i]);
      expect(choisir).toHaveBeenCalledWith(candidat.deviceId);
    }
  });

  it('« laisse tomber » renonce au lieu de choisir', () => {
    avecQuestion();
    const boutons = elements(monter().arbre(), 'button');
    cliquer(boutons[boutons.length - 1]);
    expect(renoncer).toHaveBeenCalledTimes(1);
    expect(choisir).not.toHaveBeenCalled();
  });

  it('nomme l’objet tenu et le temps qui reste', () => {
    avecQuestion();
    const lu = texte(monter().arbre());
    expect(lu).toContain('« Zéro à Héro » — vers lequel ?');
    expect(lu).toContain('12 s pour répondre');
  });

  it('n’affiche aucun bouton de candidat quand rien n’attend', () => {
    poserLeContexte({ diagnostic: { armed: true } });
    const boutons = elements(monter().arbre(), 'button');
    expect(boutons.map((b) => texte(b))).toEqual(['fichier', 'arrêter']);
    cliquer(boutons[1]);
    expect(basculer).toHaveBeenCalledTimes(1);
  });

  it('ne rend rien du tout quand le mode est éteint', () => {
    poserLeContexte({ actif: false, diagnostic: null });
    expect(elements(monter().arbre(), 'button')).toHaveLength(0);
  });
});

describe('le sélecteur piloté par le poing', () => {
  it('surligne exactement l’appareil désigné par le serveur', () => {
    poserLeContexte({
      diagnostic: {
        armed: true,
        pendingDrop: {
          token: 'jeton-geste',
          object: {
            type: 'file',
            id: 'file-1',
            title: 'vacances.mp4',
            sizeBytes: 12_582_912,
          },
          candidates: CANDIDATS,
          secondsLeft: 18,
          gestureControlled: true,
          selectedIndex: 1,
          selectedDeviceId: 'iphone-poche',
          handPosition: { x: 0.72, y: 0.41 },
        },
      },
    });

    const m = monter();
    const boutons = elements(m.arbre(), 'button');
    const iphone = boutons.find((b) => texte(b).includes('iPhone'));
    const mac = boutons.find((b) => texte(b).includes('Mac de l’atelier'));
    expect(iphone?.props['aria-current']).toBe('true');
    expect(mac?.props['aria-current']).toBeUndefined();
    expect(texte(m.arbre())).toContain('Ouvre la main pour envoyer');
    expect(texte(m.arbre())).toContain('droite / bas : suivant');
    expect(texte(m.arbre())).toContain('12.0 Mio');
  });
});

describe('l’annonce du dernier dépôt', () => {
  it('affiche le message du serveur, puis le laisse partir', async () => {
    poserLeContexte({
      diagnostic: {
        armed: true,
        lastDrop: { done: true, message: 'Envoyé au Mac de l’atelier.' },
      },
    });
    const m = monter();
    expect(texte(m.arbre())).toContain('Envoyé au Mac de l’atelier.');
    // Six secondes : assez pour lire, trop peu pour devenir un décor.
    await env.horloge.avancer(6000);
    expect(texte(m.arbre())).not.toContain('Envoyé au Mac de l’atelier.');
  });
});
