import { describe, expect, it } from 'vitest';

import {
  SuiviDesRequetes,
  basculerSousTache,
  estDateIso,
  remplacerLigne,
  retirerSousTache,
  sansTerminees,
} from './reconciliation';
import type { SuccesSubtask, SuccesTask } from './types';

function sousTache(id: string, children: SuccesSubtask[] = [], done = false): SuccesSubtask {
  return { id, title: id, done, isGroup: children.length > 0, updatedAtMs: 0, children };
}

function tache(id: string, extra: Partial<SuccesTask> = {}): SuccesTask {
  return {
    id,
    title: id,
    done: false,
    priority: 'medium',
    date: '',
    time: '',
    projectId: '',
    parentTaskId: '',
    category: '',
    notes: '',
    emoji: '',
    templateId: '',
    groupId: '',
    order: 0,
    createdAt: '',
    completedDate: '',
    postponedCount: 0,
    estimateDays: 0,
    updatedAtMs: 0,
    stage: '',
    cadence: null,
    subtasks: [],
    ...extra,
  };
}

describe('la ligne renvoyée par le serveur (§100)', () => {
  it('remplace la ligne locale du même id, et elle seule', () => {
    const avant = [tache('a'), tache('b'), tache('c')];
    const serveur = tache('b', { done: true, title: 'b (serveur)' });
    const apres = remplacerLigne(avant, serveur);
    expect(apres[1]).toBe(serveur);
    expect(apres[0]).toBe(avant[0]);
    expect(apres[2]).toBe(avant[2]);
    expect(apres).toHaveLength(3);
  });

  it('laisse la liste intacte si la tâche n’y est plus — rien n’est inventé', () => {
    const avant = [tache('a')];
    expect(remplacerLigne(avant, tache('z'))).toBe(avant);
  });
});

describe('l’état optimiste d’une sous-tâche', () => {
  it('coche une sous-tâche enfouie sans toucher ses sœurs', () => {
    const t = tache('t', {
      subtasks: [sousTache('s1', [sousTache('s1a'), sousTache('s1b')]), sousTache('s2')],
    });
    const apres = basculerSousTache(t, 's1b', true);
    expect(apres.subtasks[0].children[1].done).toBe(true);
    expect(apres.subtasks[0].children[0].done).toBe(false);
    expect(apres.subtasks[1].done).toBe(false);
    expect(t.subtasks[0].children[1].done).toBe(false);
  });

  it('retire une sous-tâche avec ses enfants, à toute profondeur', () => {
    const t = tache('t', {
      subtasks: [sousTache('s1', [sousTache('s1a', [sousTache('s1a1')])]), sousTache('s2')],
    });
    const apres = retirerSousTache(t, 's1a');
    expect(apres.subtasks[0].children).toHaveLength(0);
    expect(apres.subtasks.map((s) => s.id)).toEqual(['s1', 's2']);
  });
});

describe('le glissement d’une tâche cochée hors d’une liste sans terminées', () => {
  it('la garde barrée à sa place tant qu’elle est en sursis, puis la retire', () => {
    const liste = [tache('a', { done: true }), tache('b')];
    expect(sansTerminees(liste, new Set(['a'])).map((t) => t.id)).toEqual(['a', 'b']);
    expect(sansTerminees(liste, new Set()).map((t) => t.id)).toEqual(['b']);
  });

  it('la garde si elle a été rouverte entre-temps, sursis ou non', () => {
    const liste = [tache('a', { done: false }), tache('b')];
    expect(sansTerminees(liste, new Set())).toHaveLength(2);
  });

  it('ne retire jamais rien de la liste reçue — les terminées vivent dans leur onglet', () => {
    // Depuis le 17 sept. 2026, `tasks` porte tout : le compte de l'onglet
    // Terminées en a besoin ; seul le filtre de la Liste glisse.
    const liste = [tache('a', { done: true }), tache('b')];
    sansTerminees(liste, new Set());
    expect(liste).toHaveLength(2);
  });
});

describe('deux requêtes en vol sur la même ligne (revue du 17 sept. 2026, défaut 3)', () => {
  /** Une tâche à deux sous-tâches, `s1` et `s2`, cochées selon `etats`. */
  const etat = (s1: boolean, s2: boolean) =>
    tache('t', { subtasks: [sousTache('s1', [], s1), sousTache('s2', [], s2)] });
  const coches = (ligne: SuccesTask | null) => ligne?.subtasks.map((s) => s.done);

  it('en échec, rétablit la ligne d’avant la première requête — jamais l’intérim de la seconde', () => {
    const suivi = new SuiviDesRequetes();
    const t0 = etat(false, false);
    const n1 = suivi.partir(t0);
    // Le second clic reçoit la ligne OPTIMISTE du premier comme « avant ».
    const n2 = suivi.partir(basculerSousTache(t0, 's1', true));
    expect(suivi.echouer('t', n1)).toBeNull(); // s2 encore en vol : rien à peindre
    expect(coches(suivi.echouer('t', n2))).toEqual([false, false]);
    expect(suivi.enVol('t')).toBe(0);
  });

  it('sur un serveur lent, seule la dernière réponse se peint — les coches ne se décochent pas sous les yeux', () => {
    const suivi = new SuiviDesRequetes();
    const t0 = etat(false, false);
    const n1 = suivi.partir(t0);
    const n2 = suivi.partir(basculerSousTache(t0, 's1', true));
    expect(suivi.reussir('t', n1, etat(true, false))).toBeNull();
    expect(coches(suivi.reussir('t', n2, etat(true, true)))).toEqual([true, true]);
  });

  it('si la première réussit et la seconde échoue, c’est la ligne serveur de la première qui revient', () => {
    const suivi = new SuiviDesRequetes();
    const t0 = etat(false, false);
    const n1 = suivi.partir(t0);
    const n2 = suivi.partir(basculerSousTache(t0, 's1', true));
    expect(suivi.reussir('t', n1, etat(true, false))).toBeNull();
    expect(coches(suivi.echouer('t', n2))).toEqual([true, false]);
  });

  it('une réponse arrivée dans le désordre ne repeint pas une ligne plus ancienne', () => {
    const suivi = new SuiviDesRequetes();
    const t0 = etat(false, false);
    const n1 = suivi.partir(t0);
    const n2 = suivi.partir(t0);
    expect(coches(suivi.reussir('t', n2, etat(true, true)))).toEqual([true, true]);
    // n1 arrive après n2 : aucune plus récente en vol, mais sa ligne est périmée.
    expect(coches(suivi.reussir('t', n1, etat(true, false)))).toEqual([true, true]);
  });

  it('une requête seule se peint telle quelle, et l’entrée s’oublie une fois posée', () => {
    const suivi = new SuiviDesRequetes();
    const t0 = etat(false, false);
    const n1 = suivi.partir(t0);
    expect(suivi.enVol('t')).toBe(1);
    const serveur = etat(true, false);
    expect(suivi.reussir('t', n1, serveur)).toBe(serveur);
    expect(suivi.enVol('t')).toBe(0);
    // La requête suivante repart de la ligne affichée, qui est la ligne serveur.
    const n2 = suivi.partir(serveur);
    expect(coches(suivi.echouer('t', n2))).toEqual([true, false]);
  });

  it('ne mélange pas deux tâches', () => {
    const suivi = new SuiviDesRequetes();
    const a = tache('a');
    const b = tache('b');
    const na = suivi.partir(a);
    const nb = suivi.partir(b);
    expect(suivi.echouer('a', na)).toBe(a);
    expect(suivi.echouer('b', nb)).toBe(b);
  });
});

describe('ce qu’on ose peindre avant la réponse', () => {
  it('ne prend qu’une date ISO — « lundi » attend le serveur', () => {
    expect(estDateIso('2026-09-21')).toBe(true);
    expect(estDateIso('lundi')).toBe(false);
    expect(estDateIso('21 sept')).toBe(false);
  });
});

describe('le suivi et un GET complet', () => {
  it('un échec après un GET rétablit la ligne du GET, pas un cliché d’avant', () => {
    const suivi = new SuiviDesRequetes();
    const avant = { id: 't', title: 'Ancien', done: false } as unknown as SuccesTask;
    const numero = suivi.partir(avant);
    const duGet = { ...avant, title: 'Changé sur le téléphone' } as SuccesTask;
    suivi.rafraichir([duGet]);
    expect(suivi.echouer('t', numero), 'la ligne du GET est la dernière vérité serveur').toEqual(duGet);
  });
});
