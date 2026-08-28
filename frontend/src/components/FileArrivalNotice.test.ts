import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('react', async () => await import('../features/gestes/__banc__/miniReact'));
vi.mock(
  'react/jsx-runtime',
  async () => await import('../features/gestes/__banc__/miniReact'),
);
vi.mock(
  'react/jsx-dev-runtime',
  async () => await import('../features/gestes/__banc__/miniReact'),
);
vi.mock('lucide-react', () => ({
  FileAudio2: () => null,
  FileCheck2: () => null,
  FileImage: () => null,
  FileVideo2: () => null,
  Laptop: () => null,
  X: () => null,
}));
vi.mock('../i18n/useTranslation', () => ({
  useTranslation: () => ({
    t: (key: string, vars?: Record<string, string>) => {
      if (key === 'mesh.fileArrival.title') return 'Fichier reçu';
      if (key === 'mesh.fileArrival.from') return `Depuis ${vars?.device}`;
      if (key === 'mesh.fileArrival.dismiss') return 'Fermer';
      return key;
    },
  }),
}));

import {
  cliquer,
  creer,
  elements,
  monterComposant,
  texte,
  type MontureArbre,
  type TypeElement,
} from '../features/gestes/__banc__/miniReact';
import {
  installerEnvironnement,
  type Environnement,
} from '../features/gestes/__banc__/environnement';
import { FileArrivalNotice } from './FileArrivalNotice';

let env: Environnement;
let monture: MontureArbre | null = null;
let fermer: ReturnType<typeof vi.fn>;

beforeEach(() => {
  env = installerEnvironnement();
  fermer = vi.fn();
  monture = monterComposant(
    creer(FileArrivalNotice as unknown as TypeElement, {
      eventId: 'transfer:s1',
      receipt: {
        fileName: 'vacances.mp4',
        sizeBytes: 2 * 1024 ** 2,
        mimeType: 'video/mp4',
        sourceDeviceId: 'pc-1',
        sourceDeviceName: 'PC du bureau',
      },
      onDismiss: fermer,
    }),
  );
});

afterEach(() => {
  monture?.demonter();
  monture = null;
  env.restaurer();
});

describe('la carte d’arrivée', () => {
  it('nomme le fichier, sa source et sa taille', () => {
    const lu = texte(monture!.arbre());
    expect(lu).toContain('Fichier reçu');
    expect(lu).toContain('vacances.mp4');
    expect(lu).toContain('Depuis PC du bureau');
    expect(lu).toContain('2.0 Mio');
  });

  it('se ferme au clic avec l’identifiant du bon transfert', () => {
    cliquer(elements(monture!.arbre(), 'button')[0]);
    expect(fermer).toHaveBeenCalledWith('transfer:s1');
  });

  it('disparaît seule après le temps de lecture', async () => {
    await env.horloge.avancer(6199);
    expect(fermer).not.toHaveBeenCalled();
    await env.horloge.avancer(1);
    expect(fermer).toHaveBeenCalledWith('transfer:s1');
  });
});
