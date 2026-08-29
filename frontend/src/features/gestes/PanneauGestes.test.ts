import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';

/**
 * Le panneau : la même question « vers lequel ? » que le voyant, et la case
 * « Activer par un double clap ».
 *
 * Cette case est un cas de §5 à elle seule : quand le fil d'écoute mourait
 * tout seul, elle restait cochée et le panneau continuait d'affirmer « le
 * micro écoute en continu » au-dessus d'un compteur de claps figé. Ce que le
 * panneau doit rendre, c'est `clapsEcoutent` — que le crochet réaligne sur
 * ce que le serveur CONSTATE (voir useModeGestes.test.ts).
 */

const contexte = vi.hoisted(() => ({ valeur: {} as Record<string, unknown> }));

vi.mock('react', async () => await import('./__banc__/miniReact'));
vi.mock('react/jsx-runtime', async () => await import('./__banc__/miniReact'));
vi.mock(
  'react/jsx-dev-runtime',
  async () => await import('./__banc__/miniReact'),
);
vi.mock('lucide-react', () => ({
  FileUp: () => null,
  Hand: () => null,
  Video: () => null,
  VideoOff: () => null,
}));
vi.mock('./ModeGestesContexte', () => ({
  useModeGestesPartage: () => contexte.valeur,
}));
vi.mock('./api', () => ({
  mesurerLaPiece: vi.fn(),
  mesurerLesClaps: vi.fn(),
  mesurerPose: vi.fn(),
  finirLaMesure: vi.fn(),
  appliquerCalibration: vi.fn(),
  oublierCalibration: vi.fn(),
}));

import {
  creer,
  cliquer,
  elements,
  monterComposant,
  texte,
  type Noeud,
  type MontureArbre,
} from './__banc__/miniReact';
import {
  installerEnvironnement,
  type Environnement,
} from './__banc__/environnement';
import { PanneauGestes } from './PanneauGestes';

const CANDIDATS = [
  { deviceId: 'mac-atelier', name: 'Mac de l’atelier' },
  { deviceId: 'iphone-poche', name: 'iPhone' },
];

let env: Environnement;
let monture: MontureArbre | null = null;
let choisir: ReturnType<typeof vi.fn>;
let renoncer: ReturnType<typeof vi.fn>;
let basculerLesClaps: ReturnType<typeof vi.fn>;
let changerMode: ReturnType<typeof vi.fn>;
let preparerUnFichier: ReturnType<typeof vi.fn>;
let annulerFichierPrepare: ReturnType<typeof vi.fn>;

function poserLeContexte(supplement: Record<string, unknown>): void {
  choisir = vi.fn();
  renoncer = vi.fn();
  basculerLesClaps = vi.fn();
  changerMode = vi.fn();
  preparerUnFichier = vi.fn();
  annulerFichierPrepare = vi.fn();
  contexte.valeur = {
    actif: true,
    mode: 'TRANSFER',
    etat: 'SAISI',
    mainVue: true,
    erreur: null,
    diagnostic: { armed: true },
    clapsEcoutent: false,
    basculerLesClaps,
    basculer: vi.fn(),
    changerMode,
    choisir,
    renoncer,
    preparerUnFichier,
    annulerFichierPrepare,
    ...supplement,
  };
}

function monter(): MontureArbre {
  monture = monterComposant(creer(PanneauGestes));
  return monture;
}

function laCase(): Noeud {
  const cases = elements(monture!.arbre(), 'input').filter(
    (n) => n.props.type === 'checkbox',
  );
  expect(cases).toHaveLength(1);
  return cases[0];
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

describe('la carte « vers lequel ? » dans le panneau', () => {
  beforeEach(() => {
    poserLeContexte({
      diagnostic: {
        armed: true,
        pendingDrop: {
          token: 'jeton-42',
          object: { type: 'note', id: 'n-9', title: 'Notes du 26 août' },
          candidates: CANDIDATS,
          secondsLeft: 9.2,
        },
      },
    });
  });

  it('rend un bouton par candidat', () => {
    const m = monter();
    const noms = elements(m.arbre(), 'button').map((b) => texte(b));
    expect(noms).toContain('Mac de l’atelier');
    expect(noms).toContain('iPhone');
    expect(noms).toContain('laisse tomber');
    expect(texte(m.arbre())).toContain('« Notes du 26 août » — vers lequel ?');
  });

  it('choisir transmet le deviceId de CE candidat', () => {
    const m = monter();
    const boutons = elements(m.arbre(), 'button');
    const iphone = boutons.find((b) => texte(b) === 'iPhone');
    expect(iphone).toBeDefined();
    cliquer(iphone!);
    expect(choisir).toHaveBeenCalledTimes(1);
    expect(choisir).toHaveBeenCalledWith('iphone-poche');
  });

  it('renonce sans rien envoyer', () => {
    const m = monter();
    const abandon = elements(m.arbre(), 'button').find(
      (b) => texte(b) === 'laisse tomber',
    );
    cliquer(abandon!);
    expect(renoncer).toHaveBeenCalledTimes(1);
    expect(choisir).not.toHaveBeenCalled();
  });

  it('efface l’issue précédente tant que la question est posée', () => {
    poserLeContexte({
      diagnostic: {
        armed: true,
        lastDrop: { done: true, message: 'Envoyé au Mac.' },
        pendingDrop: {
          token: 'jeton-43',
          object: { type: 'note', id: 'n-9', title: 'Notes' },
          candidates: CANDIDATS,
          secondsLeft: 5,
        },
      },
    });
    expect(texte(monter().arbre())).not.toContain('Envoyé au Mac.');
  });
});

describe('la case « Activer par un double clap »', () => {
  it('reste décochée quand le serveur n’écoute pas', () => {
    poserLeContexte({ clapsEcoutent: false });
    monter();
    expect(laCase().props.checked).toBe(false);
    expect(texte(monture!.arbre())).not.toContain('Le micro écoute en continu');
  });

  it('se coche et annonce l’écoute quand le serveur écoute', () => {
    poserLeContexte({
      clapsEcoutent: true,
      diagnostic: { armed: true, clapsHeard: 4 },
    });
    monter();
    expect(laCase().props.checked).toBe(true);
    const lu = texte(monture!.arbre());
    expect(lu).toContain('Le micro écoute en continu');
    expect(lu).toContain('Claps entendus : 4');
  });

  it('suit le crochet quand celui-ci se réaligne sur le serveur', () => {
    // Le fil d'écoute est mort ; `useModeGestes` a remis clapsEcoutent à
    // faux et posé l'erreur. Le panneau doit cesser d'affirmer l'inverse.
    poserLeContexte({
      clapsEcoutent: false,
      erreur: 'Le micro s’est fermé tout seul — réactive l’écoute.',
      diagnostic: { armed: true, clapsHeard: 4 },
    });
    monter();
    expect(laCase().props.checked).toBe(false);
    const lu = texte(monture!.arbre());
    expect(lu).not.toContain('Le micro écoute en continu');
    expect(lu).not.toContain('Claps entendus');
    expect(lu).toContain('Le micro s’est fermé tout seul');
  });

  it('demande au crochet de basculer, sans décider elle-même', () => {
    monter();
    const surChangement = laCase().props.onChange;
    expect(typeof surChangement).toBe('function');
    (surChangement as () => void)();
    expect(basculerLesClaps).toHaveBeenCalledTimes(1);
    // Rien n'a bougé à l'écran : le serveur n'a pas encore répondu.
    expect(laCase().props.checked).toBe(false);
  });

  it('répète la raison d’un armement raté plutôt que le conseil générique', () => {
    poserLeContexte({
      clapsEcoutent: true,
      diagnostic: {
        armed: false,
        clapsHeard: 2,
        clapFailure: 'la caméra a refusé de s’ouvrir',
      },
    });
    const lu = texte(monter().arbre());
    expect(lu).toContain('la caméra a refusé de s’ouvrir');
    expect(lu).not.toContain('rapproche tes deux claps');
  });
});

describe('ce que le panneau montre du geste', () => {
  it('dit ce que la main tient', () => {
    poserLeContexte({
      diagnostic: {
        armed: true,
        held: { type: 'project', id: 'p-1', title: 'Zéro à Héro' },
      },
    });
    expect(texte(monter().arbre())).toContain('Dans ta main : Zéro à Héro');
  });

  it('nomme le fichier préparé et permet de le retirer', () => {
    poserLeContexte({
      diagnostic: {
        armed: true,
        preparedFile: {
          type: 'file',
          id: 'file-1',
          title: 'portrait.jpg',
          sizeBytes: 2048,
          mimeType: 'image/jpeg',
        },
      },
    });
    const m = monter();
    expect(texte(m.arbre())).toContain('Prêt à attraper : portrait.jpg');
    const retirer = elements(m.arbre(), 'button').find(
      (bouton) => texte(bouton) === 'retirer',
    );
    expect(retirer).toBeDefined();
    cliquer(retirer!);
    expect(annulerFichierPrepare).toHaveBeenCalledTimes(1);
  });

  it('montre quel appareil le poing a surligné', () => {
    poserLeContexte({
      diagnostic: {
        armed: true,
        pendingDrop: {
          token: 'jeton-geste',
          object: { type: 'file', id: 'file-1', title: 'portrait.jpg' },
          candidates: CANDIDATS,
          secondsLeft: 10,
          gestureControlled: true,
          selectedIndex: 1,
          selectedDeviceId: 'iphone-poche',
        },
      },
    });
    const m = monter();
    const iphone = elements(m.arbre(), 'button').find(
      (bouton) => texte(bouton) === 'iPhone',
    );
    expect(iphone?.props['aria-current']).toBe('true');
    expect(texte(m.arbre())).toContain('Déplace le poing à gauche');
  });

  it('ne montre ni état ni compteurs quand le mode est éteint', () => {
    poserLeContexte({ actif: false, diagnostic: null, etat: null });
    const lu = texte(monter().arbre());
    expect(lu).toContain('La caméra reste éteinte');
    expect(lu).not.toContain('Saisies');
    const boutons = elements(monture!.arbre(), 'button').map((b) => texte(b));
    expect(boutons).toContain('Activer');
    expect(boutons.some((libelle) => libelle.includes('Transférer'))).toBe(true);
    expect(
      boutons.some((libelle) => libelle.includes('Contrôler le curseur')),
    ).toBe(true);
  });

  it('compte ce que le serveur a constaté, sans arrondir en sa faveur', () => {
    poserLeContexte({
      diagnostic: { armed: true, grabs: 3, releases: 2, losses: 1, handRatio: 0.42 },
    });
    const lu = texte(monter().arbre());
    expect(lu).toContain('Saisies : 3');
    expect(lu).toContain('Dépôts : 2');
    expect(lu).toContain('Pertes : 1');
    expect(lu).toContain('Main vue : 42 %');
  });
});

describe('le mode pointeur explicite', () => {
  it('explique les gestes sans montrer les commandes de transfert', () => {
    poserLeContexte({
      mode: 'POINTER',
      diagnostic: {
        armed: true,
        mode: 'POINTER',
        pointer: { active: true, action: 'MOVE', pinching: false },
      },
    });
    const lu = texte(monter().arbre());
    expect(lu).toContain('Index suivi — le curseur te suit');
    expect(lu).toContain('pincement bref : cliquer');
    expect(lu).not.toContain('Choisir un fichier');
    expect(lu).not.toContain('Activer par un double clap');
  });

  it('montre si les doigts approchent réellement du seuil de contact', () => {
    poserLeContexte({
      mode: 'POINTER',
      diagnostic: {
        armed: true,
        mode: 'POINTER',
        pointer: {
          active: true,
          action: 'MOVE',
          pinching: false,
          pinchProgress: 0.62,
        },
      },
    });
    const lu = texte(monter().arbre());
    expect(lu).toContain('Rapproche encore le pouce et l’index');
    expect(lu).toContain('Contact pouce-index');
    expect(lu).toContain('62%');
  });

  it('laisse revenir au transfert par un bouton visible', () => {
    poserLeContexte({ mode: 'POINTER' });
    const transfert = elements(monter().arbre(), 'button').find((bouton) =>
      texte(bouton).includes('Transférer'),
    );
    expect(transfert).toBeDefined();
    cliquer(transfert!);
    expect(changerMode).toHaveBeenCalledWith('TRANSFER');
  });
});
