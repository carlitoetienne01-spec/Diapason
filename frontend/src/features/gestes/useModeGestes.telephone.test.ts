import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * Dans le téléphone, la porte de la caméra reste fermée.
 *
 * Échec évité (26/09/2026, phase 3 du chantier mobile) : le bundle chargé
 * dans la coquille Flutter aurait appelé getUserMedia — la caméra DU
 * TÉLÉPHONE, alors que les gestes pilotent le Mac (§78 : rien ne s'allume
 * qu'on n'ait armé exprès, et ce n'est pas ce que la personne armait).
 *
 * Même banc que useModeGestes.test.ts ; seul le pont natif change.
 */

const api = vi.hoisted(() => ({
  armer: vi.fn(),
  desarmer: vi.fn(),
  envoyerImage: vi.fn(),
  lireDiagnostic: vi.fn(),
  ecouterLesClaps: vi.fn(),
  choisirLAppareil: vi.fn(),
  renoncerAuDepot: vi.fn(),
  preparerFichierPourGeste: vi.fn(),
  oublierFichierPrepare: vi.fn(),
}));

vi.mock('./api', () => ({
  ...api,
  EchecGeste: class EchecGeste extends Error {},
}));
vi.mock('react', async () => await import('./__banc__/miniReact'));
vi.mock('./pointeurNatif', () => ({
  appliquerPointeur: vi.fn(),
  notifierSessionGestes: vi.fn().mockResolvedValue(undefined),
  pointeurNatifDisponible: () => false,
}));
vi.mock('../../lib/natif', () => ({ estMobile: true }));

import { monterCrochet, type Monture } from './__banc__/miniReact';
import { installerEnvironnement, vider, type Environnement } from './__banc__/environnement';
import type { ModeGestes } from './useModeGestes';
import { useModeGestes } from './useModeGestes';

let env: Environnement;
let monture: Monture<ModeGestes> | null = null;

beforeEach(() => {
  env = installerEnvironnement();
  for (const espion of Object.values(api)) espion.mockReset();
  api.armer.mockResolvedValue({ armed: true });
  api.lireDiagnostic.mockResolvedValue({ armed: true });
});

afterEach(() => {
  monture?.demonter();
  monture = null;
  env.restaurer();
});

describe('Le mode gestes dans le téléphone', () => {
  it('n’arme rien et n’ouvre aucune caméra au bouton', async () => {
    monture = monterCrochet(() => useModeGestes());
    monture.valeur().basculer();
    await vider();
    expect(env.camerasOuvertes()).toBe(0);
    expect(api.armer).not.toHaveBeenCalled();
    expect(monture.valeur().actif).toBe(false);
    expect(monture.valeur().erreur, 'le refus doit se dire, pas se taire').toBeTruthy();
  });
});
