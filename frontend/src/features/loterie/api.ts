import { authHeaders } from '../../lib/api';

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

async function demander<T>(
  chemin: string,
  init?: Omit<RequestInit, 'headers'>,
): Promise<T> {
  // `RequestInit['headers']` accepte un tableau ou un `Headers` ; `authHeaders`
  // veut un objet plat. On ne prend donc pas d'en-têtes de l'appelant plutôt
  // que d'accepter un type qu'on ne saurait pas fusionner.
  const reponse = await fetch(chemin, {
    ...init,
    headers: authHeaders({ 'Content-Type': 'application/json' }),
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
