import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * §16 : deux poses mesurées, pas des seuils devinés. L'assistant enchaîne
 * quatre appels au serveur dans un ordre qui compte, avec 2,5 s d'écoute
 * chacun — un enchaînement qu'aucun test ne parcourait.
 */

const api = vi.hoisted(() => ({
  mesurerPose: vi.fn(),
  finirLaMesure: vi.fn(),
  appliquerCalibration: vi.fn(),
  oublierCalibration: vi.fn(),
}));

vi.mock('./api', () => api);
vi.mock('react', async () => await import('./__banc__/miniReact'));

import { monterCrochet, type Monture } from './__banc__/miniReact';
import {
  installerEnvironnement,
  vider,
  type Environnement,
} from './__banc__/environnement';
import { useCalibration, type Calibration } from './useCalibration';

const DUREE = 2500;

let env: Environnement;
let monture: Monture<Calibration> | null = null;

beforeEach(() => {
  env = installerEnvironnement();
  for (const espion of Object.values(api)) espion.mockReset();
  api.mesurerPose.mockResolvedValue(undefined);
  api.appliquerCalibration.mockResolvedValue(undefined);
  api.oublierCalibration.mockResolvedValue(undefined);
});

afterEach(() => {
  monture?.demonter();
  monture = null;
  env.restaurer();
});

function monter(actif = true): Monture<Calibration> {
  monture = monterCrochet(() => useCalibration(actif));
  return monture;
}

describe('useCalibration', () => {
  it('mesure la main ouverte puis le poing, et applique les deux', async () => {
    api.finirLaMesure.mockResolvedValueOnce(0.82).mockResolvedValueOnce(0.31);
    const m = monter();
    expect(m.valeur().etape).toBe('repos');

    m.valeur().demarrer();
    expect(m.valeur().etape).toBe('ouverte');
    expect(m.valeur().message).toContain('Ouvre bien la main');
    expect(api.mesurerPose).toHaveBeenCalledWith('ouverte');
    // La mesure dure : rien ne doit être conclu avant la fin de l'écoute.
    await vider();
    expect(api.finirLaMesure).not.toHaveBeenCalled();

    await env.horloge.avancer(DUREE);
    expect(api.finirLaMesure).toHaveBeenCalledWith('ouverte');
    expect(m.valeur().etape).toBe('fermee');
    expect(m.valeur().message).toContain('serre le poing');
    expect(api.mesurerPose).toHaveBeenCalledWith('fermee');

    await env.horloge.avancer(DUREE);
    expect(api.appliquerCalibration).toHaveBeenCalledWith(0.82, 0.31);
    expect(m.valeur().etape).toBe('terminee');
    expect(m.valeur().message).toContain('0.31 poing fermé');
    expect(m.valeur().message).toContain('0.82 main ouverte');
    expect(m.valeur().erreur).toBeNull();
  });

  it('ne mesure rien quand la caméra est éteinte', async () => {
    const m = monter(false);
    m.valeur().demarrer();
    await vider();
    expect(api.mesurerPose).not.toHaveBeenCalled();
    expect(m.valeur().etape).toBe('repos');
  });

  it('revient au repos et DIT pourquoi quand une mesure échoue', async () => {
    api.finirLaMesure.mockRejectedValue(new Error('Pas de main dans le champ.'));
    const m = monter();
    m.valeur().demarrer();
    await env.horloge.avancer(DUREE);
    expect(m.valeur().etape).toBe('repos');
    expect(m.valeur().erreur).toBe('Pas de main dans le champ.');
    expect(m.valeur().message).toBe('');
    expect(api.appliquerCalibration).not.toHaveBeenCalled();
  });

  it('revient aux réglages d’usine sur demande', async () => {
    api.finirLaMesure.mockResolvedValueOnce(0.9).mockResolvedValueOnce(0.2);
    const m = monter();
    m.valeur().demarrer();
    await env.horloge.avancer(DUREE * 2);
    expect(m.valeur().etape).toBe('terminee');

    m.valeur().reinitialiser();
    await vider();
    expect(api.oublierCalibration).toHaveBeenCalledTimes(1);
    expect(m.valeur().etape).toBe('repos');
    expect(m.valeur().message).toContain('usine');
  });
});
