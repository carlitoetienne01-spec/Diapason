import { describe, expect, it } from 'vitest';
import type { ToolCallInfo } from '../../types';
import { appelsDeRecherche, bilanExecution, cloreAppels, dureeOutil, dureeValide, etatExecution, resumeDeRecherche, terminerAppel, texteRecu } from './etatExecution';
import { journalExecution, creerReception } from './receptionTerminal';
import { dernierTexteVisible } from './GravureReponse';

const appel = (id = 'a', outil = 'web_search'): ToolCallInfo => ({ id, tool: outil, arguments: '{}', status: 'running' });

describe('Le terminal raconte uniquement les événements reçus', () => {
  it('affiche les secondes serveur sans les prendre pour des millisecondes', () => {
    expect(dureeOutil(1.2, 'fr')).toBe('1,2 s');
    expect(dureeOutil(.031, 'fr')).toBe('31 ms');
    expect(dureeOutil(76.8, 'en')).toBe('76.8 s');
    expect(dureeOutil(0, 'fr')).toBe('0 s');
  });
  it.each([null, undefined, '3', NaN, Infinity, -1])('ignore la durée absente ou invalide %s', valeur => {
    expect(dureeValide(valeur)).toBe(false);
  });
  it('respecte le refus serveur même si le contenu a l’air réussi', () => {
    const appels = [appel()];
    terminerAppel(appels, { tool: 'web_search', success: false, result: 'OK', latency: .4 });
    expect(appels[0]).toMatchObject({ status: 'error', result: 'OK', latency: .4 });
    expect(bilanExecution(appels, true).reussis).toBe(0);
  });
  it.each([undefined, 'false', 1, null])('ne transforme pas un succès ambigu %s en réussite', success => {
    const appels = [appel()];
    terminerAppel(appels, { tool: 'web_search', success });
    expect(appels[0].status).toBe('unconfirmed');
  });
  it('associe les lectures imbriquées à leur propre résultat', () => {
    const appels = [appel(), appel('b', 'web_read')];
    terminerAppel(appels, { tool: 'web_read', success: true, result: 'La page', latency: 2 });
    expect(appels[0].status).toBe('running');
    expect(appels[1].status).toBe('success');
    terminerAppel(appels, { tool: 'web_search', success: true, result: 'Les sources', latency: 1 });
    expect(bilanExecution(appels, false).reussis).toBe(2);
  });
  it('ne devine pas à qui appartient un résultat homonyme simultané', () => {
    const appels = [appel(), appel('b')];
    expect(terminerAppel(appels, { tool: 'web_search', success: true })).toBe(false);
    cloreAppels(appels);
    expect(bilanExecution(appels, false).nonConfirmes).toBe(2);
  });
  it('distingue deux appels successifs au même outil et ignore une fin orpheline', () => {
    const appels = [appel()];
    terminerAppel(appels, { tool: 'web_search', success: true });
    appels.push(appel('b'));
    terminerAppel(appels, { tool: 'web_search', success: false });
    expect(appels.map(a => a.status)).toEqual(['success', 'error']);
    expect(terminerAppel(appels, { tool: 'absent', success: true })).toBe(false);
    expect(appels).toHaveLength(2);
  });
  it('la coupure du flux ne prouve pas l’arrêt ni la réussite de l’outil', () => {
    const appels = [appel(), { ...appel('b'), status: 'success' as const }];
    cloreAppels(appels);
    expect(appels.map(a => a.status)).toEqual(['unconfirmed', 'success']);
    expect(etatExecution(appel(), false)).toBe('unconfirmed');
    expect(etatExecution(appel(), true)).toBe('running');
  });
  it('préserve les arguments objets et les résultats vides sans inventer une sortie', () => {
    expect(texteRecu({ query: 'verbes' })).toBe('{"query":"verbes"}');
    expect(texteRecu('brut')).toBe('brut');
    const appels = [appel()];
    terminerAppel(appels, { tool: 'web_search', success: true, result: '', latency: -1 });
    expect(appels[0].result).toBe('');
    expect(appels[0].latency).toBeUndefined();
  });
  it('ne fabrique pas une durée ni zéro résultat pour une recherche sans mesures', () => {
    const appels = appelsDeRecherche([{ id: 's', query: 'verbes', status: 'complete', tool: 'web_search' }]);
    expect(appels[0].latency).toBeUndefined();
    expect(JSON.parse(appels[0].result!)).not.toHaveProperty('num_hits');
  });
  it('rend l’échec et le nombre zéro explicites de la recherche approfondie', () => {
    const appels = appelsDeRecherche([{ id: 's', query: 'verbes', status: 'complete', numHits: 0, error: 'Unavailable' }]);
    expect(appels[0].status).toBe('error');
    expect(JSON.parse(appels[0].result!)).toEqual({ error: 'Unavailable', num_hits: 0 });
  });
});

describe('La gravure ne retape ni ne modifie la réponse', () => {
  it('vise le contenu de la dernière cellule sans toucher au tableau', () => {
    const el = document.createElement('div');
    el.innerHTML = '<table><tbody><tr><td>go</td><td>gone  </td></tr></tbody></table>';
    const html = el.innerHTML;
    const dernier = dernierTexteVisible(el);
    expect(dernier?.noeud.textContent).toBe('gone  ');
    expect(dernier?.fin).toBe(4);
    expect(el.innerHTML).toBe(html);
  });
  it('ignore les boutons de copie et le contenu masqué', () => {
    const el = document.createElement('div');
    el.innerHTML = '<p>Réponse</p><button>Copier</button><span aria-hidden="true">curseur</span><span hidden>caché</span>';
    expect(dernierTexteVisible(el)?.noeud.textContent).toBe('Réponse');
    el.innerHTML = '<p> </p>';
    expect(dernierTexteVisible(el)).toBeNull();
  });
});

describe('Une recherche vide se voit (S2, 22/09/2026)', () => {
  // La carte disait « web_search · 0,8 s » et rien d'autre. Une recherche qui
  // rend ZÉRO résultat se lisait exactement comme une qui en rend huit, et la
  // réponse bâtie sur ce vide ne s'annonçait pas (§5). Le serveur savait
  // depuis le 20/09 quel moteur avait répondu ; rien ne le faisait traverser.
  const fini = (donnees: Record<string, unknown>): ToolCallInfo => {
    const appels = [appel()];
    terminerAppel(appels, { tool: 'web_search', success: true, latency: 0.8, ...donnees });
    return appels[0];
  };

  it('recopie le moteur et le compte que le serveur envoie', () => {
    const a = fini({ engine: 'brave/news', numResults: 0 });
    expect(a.engine).toBe('brave/news');
    expect(a.numResults).toBe(0);
  });

  it('laisse vides les champs qu’un outil ordinaire n’envoie pas', () => {
    const a = fini({});
    expect(a.engine).toBeUndefined();
    expect(a.numResults).toBeUndefined();
  });

  it('refuse un compte qui n’est pas entier', () => {
    // `typeof === "number"` laisserait entrer NaN et Infinity, qui
    // s'afficheraient tels quels dans la carte.
    expect(fini({ numResults: Number.NaN }).numResults).toBeUndefined();
    expect(fini({ numResults: 2.5 }).numResults).toBeUndefined();
  });

  it('dit le moteur et le nombre, et marque le vide', () => {
    expect(resumeDeRecherche({ engine: 'brave/news', numResults: 8 })).toEqual({
      texte: 'brave/news · 8 rés.', vide: false,
    });
    expect(resumeDeRecherche({ engine: 'brave/news', numResults: 0 })).toEqual({
      texte: 'brave/news · 0 rés.', vide: true,
    });
  });

  it('accorde le singulier et supporte un champ manquant', () => {
    expect(resumeDeRecherche({ numResults: 1 })?.texte).toBe('1 rés.');
    expect(resumeDeRecherche({ engine: 'tavily' })?.texte).toBe('tavily');
    expect(resumeDeRecherche({})).toBeNull();
  });

  it('porte le résumé À PART sur la ligne de fin, pour qu’il soit peint', () => {
    // Une recherche vide sort en OK comme une autre : l'appel a réussi, il
    // n'a rien trouvé. Collé dans `texte`, le compte sortait de la même
    // couleur qu'un succès ordinaire — un zéro affiché comme un huit n'est
    // pas affiché (§5). Le tag reste OK : le peindre en erreur mentirait
    // dans l'autre sens.
    const appels = [appel()];
    terminerAppel(appels, { tool: 'web_search', success: true, latency: 0.8, engine: 'brave/news', numResults: 0 });
    appels[0].endedAtMs = 400;
    const fin = journalExecution(appels, creerReception(100), false).find(l => l.tag === 'OK');
    expect(fin).toBeDefined();
    expect(fin!.texte).toBe('web_search');
    expect(fin!.resume).toBe('brave/news · 0 rés.');
    expect(fin!.vide).toBe(true);
  });

  it('ne pose ni résumé ni drapeau sur un outil qui ne cherche pas', () => {
    const appels: ToolCallInfo[] = [{ id: 'a', tool: 'read_file', arguments: '{}', status: 'running' }];
    terminerAppel(appels, { tool: 'read_file', success: true, latency: 0.1 });
    appels[0].endedAtMs = 400;
    const fin = journalExecution(appels, creerReception(100), false).find(l => l.tag === 'OK');
    expect(fin!.resume).toBeUndefined();
    expect(fin!.vide).toBeUndefined();
  });

  it('une recherche fructueuse porte son résumé sans lever le drapeau', () => {
    const appels = [appel()];
    terminerAppel(appels, { tool: 'web_search', success: true, latency: 0.8, engine: 'brave/news', numResults: 8 });
    appels[0].endedAtMs = 400;
    const fin = journalExecution(appels, creerReception(100), false).find(l => l.tag === 'OK');
    expect(fin!.resume).toBe('brave/news · 8 rés.');
    expect(fin!.vide).toBe(false);
  });
});
