// Servi par le tailnet — ce que le bundle ne demande plus quand il l'est.
//
// 26/09/2026, constat 15 des contre-épreuves de la phase 2 (plan mobile,
// docs/development/diapason-mobile.md). Dans la WebView du téléphone, le
// bundle passe par la passerelle du socket 8002, qui REFUSE des lectures
// que le Mac se garde (server/portee_tailnet.py). Rien ne le lui disait :
// il relançait /v1/triggers/poll toutes les 2 s, /v1/voice/live/health
// toutes les 5 s, /v1/account/status toutes les 30 s, /v1/vie/sync/status à
// chaque liste de tâches — des 403 à la chaîne, dont chacun passe par la
// session, le classement des routes et une écriture possible sur mesh.db.
// (La santé de la voix est rouverte depuis la phase 4 : elle n'est plus
// retenue, mais sa relève toutes les 5 s reste coupée au téléphone,
// hooks/useVoiceLive.ts.)
//
// Deux signaux, l'un OU l'autre :
// - le pont natif (`estMobile`), présent dès le chargement ;
// - l'en-tête `X-Diapason-Passerelle: tailnet`, que la passerelle pose sur
//   CHAQUE réponse, refus compris, et que la boucle locale ne pose jamais —
//   pour un bundle chargé par le tailnet sans le pont (une coquille qui ne
//   l'aurait pas injecté, une page ouverte autrement).
//
// Ce qui ne part plus : toute lecture (GET) que la passerelle refuse, plus
// la publication automatique de la vue (`POST /v1/context/view`). La liste
// est gardée contre `tests/contract/tailnet_portee.json` par
// `tailnet.test.ts`, dans les deux sens : une route que la passerelle ouvre
// ne peut pas y rester, une lecture qu'elle refuse ne peut pas y manquer.
// Une ACTION refusée (un POST au clic), elle, part : c'est la passerelle
// qui rend la phrase du refus, pas le bundle (§100).

import { traduire } from '../i18n/translate';
import { estMobile } from './natif';

export const ENTETE_PASSERELLE = 'x-diapason-passerelle';

/**
 * Chaque lecture que la passerelle refuse, au gabarit près de la route
 * Starlette (« MÉTHODE /chemin/{param} »), plus l'unique écriture que le
 * bundle fait SEUL, sans clic : la publication de la vue.
 */
export const SONDES_REFUSEES = [
  'GET /docs',
  'GET /docs/oauth2-redirect',
  'GET /metrics',
  'GET /openapi.json',
  'GET /redoc',
  'GET /v1/account/devices',
  'GET /v1/account/status',
  'GET /v1/actions/capabilities',
  'GET /v1/actions/metrics',
  'GET /v1/channels/sendblue/health',
  'GET /v1/connectors/{connector_id}/oauth/callback',
  'GET /v1/connectors/{connector_id}/oauth/start',
  'GET /v1/context/view',
  'GET /v1/gestures/state',
  'GET /v1/managed-agents/{agent_id}/channels',
  'GET /v1/mesh/commands',
  'GET /v1/mesh/commands/{command_id}',
  'GET /v1/mesh/devices',
  'GET /v1/mesh/devices/{device_id}',
  'GET /v1/mesh/devices/{device_id}/presence',
  'GET /v1/mesh/devices/{device_id}/sessions',
  'GET /v1/mesh/inbox',
  'GET /v1/mesh/me',
  'GET /v1/mesh/tools',
  'GET /v1/screen_share/status',
  'GET /v1/security/scan',
  'GET /v1/tools/{tool_name}/credentials/status',
  'GET /v1/triggers/poll',
  'GET /v1/vie/sync/operations',
  'GET /v1/vie/sync/status',
  'GET /v1/voice/profile',
  'GET /webhooks/whatsapp',
  'POST /v1/context/view',
] as const;

/**
 * Les familles refusées ENTIÈRES, par préfixe : l'alias `/v1/succes/` (cent
 * routes, que le bundle n'appelle plus depuis l'étape 9 de la 1b). Le
 * préfixe se termine par « / » : `/v1/successeur` n'y tomberait pas.
 */
export const FAMILLES_REFUSEES = ['GET /v1/succes/'] as const;

function versExpression(gabarit: string): RegExp {
  const echappe = gabarit.replace(/[.*+?^$()|[\]\\]/g, '\\$&');
  const motif = echappe
    .replace(/\{[^}/]+:path\}/g, '.+')
    .replace(/\{[^}/]+\}/g, '[^/]+');
  return new RegExp(`^${motif}$`);
}

const COMPILEES = SONDES_REFUSEES.map((cle) => {
  const [methode, gabarit] = cle.split(' ');
  return { cle, methode, expression: versExpression(gabarit) };
});

/** Le chemin seul : sans origine, sans requête, sans ancre, sans « / » final. */
function cheminSeul(chemin: string): string {
  let brut = chemin;
  if (/^[a-z][a-z0-9+.-]*:\/\//i.test(brut)) {
    try {
      brut = new URL(brut).pathname;
    } catch {
      return '';
    }
  }
  brut = brut.split('#')[0].split('?')[0];
  return brut.length > 1 ? brut.replace(/\/+$/, '') : brut;
}

/**
 * La clé de la sonde refusée que cette requête serait, ou `null`.
 * HEAD se classe comme GET, comme dans `portee_tailnet.cle_de_route`.
 */
export function cleDeSonde(methode: string | undefined, chemin: string): string | null {
  const m = (methode || 'GET').toUpperCase();
  const verbe = m === 'HEAD' ? 'GET' : m;
  const seul = cheminSeul(chemin);
  if (!seul) return null;
  for (const { cle, methode: attendue, expression } of COMPILEES) {
    if (attendue === verbe && expression.test(seul)) return cle;
  }
  for (const famille of FAMILLES_REFUSEES) {
    const [attendue, prefixe] = famille.split(' ');
    if (attendue === verbe && seul.startsWith(prefixe)) return famille;
  }
  return null;
}

/** Une requête que le bundle n'a PAS envoyée : la passerelle l'aurait refusée. */
export class SondeNonEnvoyee extends Error {
  readonly cle: string;

  constructor(cle: string) {
    super(traduire('tailnet.nonDemande'));
    this.name = 'SondeNonEnvoyee';
    this.cle = cle;
  }
}

type AvecEntetes = { headers?: { get?: (nom: string) => string | null } } | null | undefined;

/** L'état « servi par le tailnet » : faux au départ hors du pont, puis verrouillé. */
export function creerEtatDuTailnet(initial: boolean) {
  let servi = initial;
  return {
    servi: () => servi,
    /**
     * Lire une réponse. Une fois vu, l'en-tête verrouille l'état pour la
     * vie de la page : une réponse sans lui (un cache, un service worker)
     * ne rend pas au bundle des droits que la passerelle lui refuse.
     */
    noterReponse(reponse: AvecEntetes): boolean {
      if (!servi) {
        try {
          if (reponse?.headers?.get?.(ENTETE_PASSERELLE) === 'tailnet') servi = true;
        } catch {
          // Des en-têtes illisibles ne disent rien.
        }
      }
      return servi;
    },
  };
}

export type EtatDuTailnet = ReturnType<typeof creerEtatDuTailnet>;

/**
 * Dire, UNE fois par route, qu'elle ne part pas — au lieu d'un 403 toutes
 * les deux secondes dans la console et le journal réseau.
 */
export function creerAnnonceur(journal: (texte: string) => void) {
  const dites = new Set<string>();
  return (cle: string): boolean => {
    if (dites.has(cle)) return false;
    dites.add(cle);
    try {
      journal(`[tailnet] ${cle} — ${traduire('tailnet.nonDemande')}`);
    } catch {
      // Un journal qui échoue n'arrête pas la garde.
    }
    return true;
  };
}

const etatDuTailnet = creerEtatDuTailnet(estMobile);
const annoncer = creerAnnonceur((texte) => console.info(texte));

/** Vrai dans le téléphone, ou dès qu'une réponse de la passerelle l'a dit. */
export function serviParLeTailnet(): boolean {
  return etatDuTailnet.servi();
}

/** Pour `apiFetch` : chaque réponse peut porter le signal. */
export function noterReponseDuServeur(reponse: AvecEntetes): void {
  etatDuTailnet.noterReponse(reponse);
}

/**
 * Pour `apiFetch`, avant tout envoi : lève `SondeNonEnvoyee` si cette
 * requête est une lecture que la passerelle refuse et qu'on est servi par
 * elle. Hors du tailnet (le Mac, le mini-panneau), ne fait rien.
 */
export function garderLaSonde(
  methode: string | undefined,
  chemin: string,
  etat: EtatDuTailnet = etatDuTailnet,
  dire: (cle: string) => boolean = annoncer,
): void {
  if (!etat.servi()) return;
  const cle = cleDeSonde(methode, chemin);
  if (!cle) return;
  dire(cle);
  throw new SondeNonEnvoyee(cle);
}
