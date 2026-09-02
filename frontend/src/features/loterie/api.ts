import { apiFetch } from '../../lib/api';

/** Les champs qui passent sur le fil sont en anglais camelCase, comme partout. */
export interface EtatLoterie {
  game: {
    name: string;
    alsoKnownAs: string;
    pick: number;
    from: number;
    grandNumberFrom: number;
    combinations: number;
    ticketPrice: number;
    expectedReturn: number;
    anyPrizeOdds: number;
    prizes: {
      matched: number;
      grandNumber: boolean;
      label: string;
      value: number;
      oneIn: number;
    }[];
  };
  source: string;
  drawCount: number;
  firstDraw: string | null;
  lastDraw: string | null;
  validation: {
    agrees: boolean;
    reason: string;
    harvested: number;
    expected: number;
    sum: number;
    expectedSum: number;
    mismatches: Record<string, { harvested: number; official: number }>;
    reference: {
      source: string;
      takenOn: string;
      draws: number;
      from: string;
      to: string;
    };
  };
  fairness: {
    draws: number;
    expectedPerNumber: number;
    standardDeviation: number;
    chiSquare: number;
    degreesOfFreedom: number;
    pValue: number;
    fair: boolean;
    hottest: { number: number; count: number; sigma: number };
    coldest: { number: number; count: number; sigma: number };
    expectedExtremeSigma: number;
  } | null;
}

export interface Recolte {
  pagesRead: number;
  drawsRead: number;
  drawsNew: number;
  stoppedBecause: string;
  drawCount: number;
  validation: { agrees: boolean; reason: string };
}

export interface ResultatSimulation {
  draws: number;
  spent: number;
  won: number;
  balance: number;
  byPrize: Record<string, number>;
  expectedPerTicket: number;
  ticketPrice: number;
}

/**
 * Passer par `apiFetch`, jamais par `fetch` nu.
 *
 * Un `fetch('/v1/…')` relatif marche dans le navigateur, où la page EST servie
 * par le serveur. Dans la fenêtre de bureau, la page vient d'un autre schéma :
 * le chemin relatif ne désigne plus rien, et WebKit rend son erreur la plus
 * opaque — « The string did not match the expected pattern. » C'est
 * exactement ce que Carlito a vu le 1er septembre 2026, avec « 0 tirage »
 * affiché alors que la base en contenait mille trente.
 *
 * `apiFetch` connaît la base, y ajoute la clé, et traduit cette erreur-là.
 */
async function demander<T>(
  chemin: string,
  init?: Omit<RequestInit, 'headers'>,
): Promise<T> {
  const reponse = await apiFetch(chemin, {
    ...init,
    headers: { 'Content-Type': 'application/json' },
  });
  if (!reponse.ok) {
    const detail = await reponse.text().catch(() => '');
    throw new Error(detail || `${reponse.status} ${reponse.statusText}`);
  }
  return (await reponse.json()) as T;
}

export const lireEtat = () => demander<EtatLoterie>('/v1/loterie/etat');

export const moissonner = () =>
  demander<Recolte>('/v1/loterie/moisson', { method: 'POST' });

export const lireFrequences = () =>
  demander<{ drawCount: number; frequencies: { number: number; count: number }[] }>(
    '/v1/loterie/frequences',
  );

export const simuler = (
  numbers: number[],
  grandNumber: number,
  draws: number,
  seed?: number,
) =>
  demander<ResultatSimulation>('/v1/loterie/simulation', {
    method: 'POST',
    body: JSON.stringify({ numbers, grandNumber, draws, seed }),
  });
