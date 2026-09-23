import type { ChatReception, ToolCallInfo } from '../../types';
import { etatExecution, resumeDeRecherche } from './etatExecution';

// Une minute conservée : 60 nombres au maximum, pas tous les jetons du fil.
const FENETRE_S = 60;
export function creerReception(startedAtMs: number): ChatReception {
  return { startedAtMs, status: 'open', receivedBytes: 0, samples: [], tailHex: '' };
}
export function recevoirOctets(reception: ChatReception, octets: Uint8Array, maintenant: number): void {
  const second = Math.max(0, Math.floor((maintenant - reception.startedAtMs) / 1000));
  reception.receivedBytes += octets.byteLength;
  reception.lastReceivedAtMs = maintenant;
  const dernier = reception.samples[reception.samples.length - 1];
  if (dernier?.second === second) dernier.bytes += octets.byteLength;
  else reception.samples.push({ second, bytes: octets.byteLength });
  reception.samples = reception.samples.filter(s => s.second > second - FENETRE_S);
  if (octets.length) {
    const queue = reception.tailHex ? reception.tailHex.split(' ') : [];
    reception.tailHex = [...queue, ...Array.from(octets.slice(-16), o => o.toString(16).padStart(2, '0'))].slice(-16).join(' ');
  }
}

export function courbeReception(reception: ChatReception, maintenant: number) {
  const fin = Math.max(0, Math.floor(((reception.endedAtMs ?? maintenant) - reception.startedAtMs) / 1000));
  const debut = Math.max(0, fin - 29);
  const seaux = new Map(reception.samples.map(s => [s.second, s.bytes]));
  // Le graphique montre des fenêtres fixes d'une seconde, y compris les
  // secondes sans réception. Zéro reçu ne veut pas dire que le modèle est inactif.
  const valeurs = Array.from({ length: fin - debut + 1 }, (_, i) => ({
    second: debut + i, bytes: seaux.get(debut + i) ?? 0,
  }));
  const maximum = Math.max(1, ...valeurs.map(v => v.bytes));
  const points = valeurs.map((v, i) => `${i * 200 / Math.max(1, valeurs.length - 1)},${64 - v.bytes / maximum * 58}`).join(' ');
  return { valeurs, maximum, points };
}

export function commandeOutil(appel?: ToolCallInfo): string {
  if (!appel) return '';
  // Affichage d'un appel JSON, jamais de flags shell supposés (--limit 5
  // n'existait que dans la démo du 22/09/2026).
  return `${appel.tool}(${appel.arguments || ''})`;
}

export interface LigneTerminal {
  id: string;
  tag: 'REQ' | 'CALL' | 'DATA' | 'OK' | 'FAIL' | 'WAIT' | 'TEXT' | 'CLOSE' | 'STOP';
  texte: string;
  atMs?: number;
  etat?: string;
}
/** La ligne de fin d'un outil : son nom, et pour une recherche ce qu'elle a
 *  rendu — « web_search · brave/news · 0 rés. ».
 *
 *  22/09/2026 (S2 du jury). Une recherche vide sort en `OK` comme une autre :
 *  l'appel a réussi, il n'a simplement rien trouvé. Sans le compte, le
 *  terminal montrait donc un succès vert là où la réponse qui suit ne repose
 *  sur rien (§5). Le moteur est dit aussi : trois moteurs se relaient, et
 *  savoir lequel a répondu explique un vide autant qu'il le date. */
export function finDOutil(appel: ToolCallInfo): string {
  const resume = resumeDeRecherche(appel);
  return resume ? `${appel.tool} · ${resume.texte}` : appel.tool;
}

export function journalExecution(appels: ToolCallInfo[], reception: ChatReception | undefined, direct: boolean): LigneTerminal[] {
  const lignes: LigneTerminal[] = [];
  if (reception) lignes.push({ id: 'request', tag: 'REQ', texte: 'request', atMs: reception.startedAtMs });
  for (const appel of appels) {
    lignes.push({ id: `${appel.id}:call`, tag: 'CALL', texte: commandeOutil(appel), atMs: appel.startedAtMs });
    if (appel.result != null) {
      for (const [i, texte] of appel.result.split('\n').filter(l => l.trim()).entries()) {
        lignes.push({ id: `${appel.id}:data:${i}`, tag: 'DATA', texte, atMs: appel.endedAtMs });
      }
    }
    const etat = etatExecution(appel, direct);
    if (etat !== 'running') lignes.push({
      id: `${appel.id}:end`, tag: etat === 'success' ? 'OK' : etat === 'error' ? 'FAIL' : 'WAIT',
      texte: finDOutil(appel), atMs: appel.endedAtMs, etat,
    });
  }
  if (reception?.firstTextAtMs != null) lignes.push({ id: 'text', tag: 'TEXT', texte: 'text', atMs: reception.firstTextAtMs });
  if (reception?.endedAtMs != null) lignes.push({ id: 'close', tag: reception.status === 'closed' ? 'CLOSE' : 'STOP', texte: reception.status, atMs: reception.endedAtMs });
  // Les anciens messages n'ont pas d'horodatage de réception : conserver
  // leur ordre existant plutôt que leur inventer une chronologie.
  return lignes.every(l => l.atMs != null) ? lignes.sort((a, b) => a.atMs! - b.atMs!) : lignes;
}
