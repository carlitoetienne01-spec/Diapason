import { describe, expect, it } from 'vitest';
import { commandeOutil, creerReception, recevoirOctets, courbeReception, journalExecution } from './receptionTerminal';

describe('Les graphiques du terminal sont mesurés sur le flux', () => {
  it('compte les octets UTF-8 plutôt que les caractères', () => {
    const r = creerReception(1000);
    const octets = new TextEncoder().encode('é🔦');
    recevoirOctets(r, octets.slice(0, 3), 1100);
    recevoirOctets(r, octets.slice(3), 1200);
    expect(r.receivedBytes).toBe(6);
    expect(r.samples).toEqual([{ second: 0, bytes: 6 }]);
    expect(r.tailHex).toBe('c3 a9 f0 9f 94 a6');
    expect(r.lastReceivedAtMs).toBe(1200);
  });
  it('mesure les secondes silencieuses sans inventer de trafic', () => {
    const r = creerReception(1000);
    recevoirOctets(r, new Uint8Array(120), 1200);
    recevoirOctets(r, new Uint8Array(30), 3300);
    expect(courbeReception(r, 4000).valeurs.map(v => v.bytes)).toEqual([120, 0, 30, 0]);
  });
  it('borne la fenêtre et l’hexadécimal sans perdre le total', () => {
    const r = creerReception(0);
    for (let i = 0; i < 200; i++) recevoirOctets(r, new Uint8Array(5), i * 1000);
    expect(r.samples).toHaveLength(60);
    expect(r.tailHex.split(' ')).toHaveLength(16);
    expect(r.receivedBytes).toBe(1000);
    expect(courbeReception(r, 199000).valeurs).toHaveLength(30);
  });
  it('fige les mesures à la fermeture, y compris lors d’une relecture', () => {
    const r = creerReception(0);
    recevoirOctets(r, new Uint8Array(10), 500);
    r.endedAtMs = 900;
    expect(courbeReception(r, 999999).valeurs).toEqual([{ second: 0, bytes: 10 }]);
  });
  it('affiche le lancement avant tout résultat sans inventer un outil', () => {
    expect(journalExecution([], creerReception(100), true)).toEqual([{ id: 'request', tag: 'REQ', texte: 'request', atMs: 100 }]);
    expect(commandeOutil()).toBe('');
  });
  it('respecte l’ordre réel des outils imbriqués et des premiers mots', () => {
    const r = creerReception(0); r.firstTextAtMs = 350; r.endedAtMs = 500; r.status = 'closed';
    const lignes = journalExecution([
      { id: 's', tool: 'web_search', arguments: '{"query":"verbes"}', status: 'success', startedAtMs: 100, endedAtMs: 400, result: 'source' },
      { id: 'r', tool: 'web_read', arguments: '{}', status: 'error', startedAtMs: 200, endedAtMs: 300, result: 'refus' },
    ], r, false);
    expect(lignes.map(l => l.id)).toEqual(['request', 's:call', 'r:call', 'r:data:0', 'r:end', 'text', 's:data:0', 's:end', 'close']);
    expect(lignes.find(l => l.id === 'r:end')?.tag).toBe('FAIL');
    expect(lignes[1].texte).toBe('web_search({"query":"verbes"})');
    expect(lignes.some(l => l.texte.includes('--limit'))).toBe(false);
  });
});
