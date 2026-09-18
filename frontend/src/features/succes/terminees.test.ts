import { describe, expect, it } from 'vitest';

import {
  JOUR_INCONNU,
  bilanSuppression,
  compterParJour,
  etendreSelection,
  grouperParJourDeCompletion,
  libelleJourDeCompletion,
  trierTerminees,
} from './terminees';
import type { SuccesTask } from './types';

// Le 17 septembre 2026 est un jeudi.
const AUJOURDHUI = '2026-09-17';

function terminee(id: string, completedDate: string, extra: Partial<SuccesTask> = {}): SuccesTask {
  return {
    id,
    title: id,
    done: true,
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
    completedDate,
    postponedCount: 0,
    estimateDays: 0,
    updatedAtMs: 0,
    stage: '',
    cadence: null,
    subtasks: [],
    ...extra,
  };
}

describe('l’ordre des terminées (demande de Carlito, 17 sept. 2026)', () => {
  it('met les plus récentes d’abord, puis la dernière modification, puis le titre', () => {
    const liste = [
      terminee('vieille', '2026-09-06'),
      terminee('b', '2026-09-17', { updatedAtMs: 10 }),
      terminee('a', '2026-09-17', { updatedAtMs: 10 }),
      terminee('tard', '2026-09-17', { updatedAtMs: 20 }),
      terminee('hier', '2026-09-16'),
    ];
    expect(trierTerminees(liste).map((t) => t.id)).toEqual(['tard', 'a', 'b', 'hier', 'vieille']);
  });

  it('ferme la marche avec les lignes sans jour de complétion — leur place n’est pas devinable', () => {
    const liste = [terminee('sans', ''), terminee('avec', '2026-09-06')];
    expect(trierTerminees(liste).map((t) => t.id)).toEqual(['avec', 'sans']);
  });

  it('ne modifie pas la liste reçue', () => {
    const liste = [terminee('vieille', '2026-09-06'), terminee('recente', '2026-09-17')];
    trierTerminees(liste);
    expect(liste.map((t) => t.id)).toEqual(['vieille', 'recente']);
  });
});

describe('le libellé du jour de complétion', () => {
  it('dit « Aujourd’hui » et « Hier »', () => {
    expect(libelleJourDeCompletion('2026-09-17', AUJOURDHUI)).toBe('Aujourd’hui');
    expect(libelleJourDeCompletion('2026-09-16', AUJOURDHUI)).toBe('Hier');
  });

  it('donne la date avec son jour de semaine au-delà, sans jamais dire « En retard »', () => {
    // Un jour de complétion est un fait passé, pas une échéance.
    expect(libelleJourDeCompletion('2026-09-15', AUJOURDHUI)).toBe('mar. 15 sept.');
    expect(libelleJourDeCompletion('2026-09-06', AUJOURDHUI)).toBe('dim. 6 sept.');
    expect(libelleJourDeCompletion('2025-12-30', AUJOURDHUI)).toBe('mar. 30 déc. 2025');
  });

  it('nomme l’absence de date plutôt que de la taire', () => {
    expect(libelleJourDeCompletion('', AUJOURDHUI)).toBe('Sans date de complétion');
  });
});

describe('le regroupement par jour', () => {
  it('groupe dans l’ordre d’apparition, avec le libellé du jour', () => {
    const groupes = grouperParJourDeCompletion(
      [terminee('a', '2026-09-17'), terminee('b', '2026-09-17'), terminee('c', '2026-09-15')],
      AUJOURDHUI,
    );
    expect(groupes.map((g) => [g.libelle, g.taches.map((t) => t.id)])).toEqual([
      ['Aujourd’hui', ['a', 'b']],
      ['mar. 15 sept.', ['c']],
    ]);
  });

  it('fonctionne sur une tranche de page : l’en-tête du jour se répète là où il tombe', () => {
    // Cinq par page, six terminées le même jour : la page 2 porte encore
    // « Aujourd'hui », avec la sixième.
    const jour = Array.from({ length: 6 }, (_, i) => terminee(`t${i}`, '2026-09-17'));
    const page2 = grouperParJourDeCompletion(jour.slice(5), AUJOURDHUI);
    expect(page2).toHaveLength(1);
    expect(page2[0].libelle).toBe('Aujourd’hui');
    expect(page2[0].taches.map((t) => t.id)).toEqual(['t5']);
  });

  it('compte par jour sur TOUTE la liste — « Aujourd’hui · 3 » dit le jour, pas la page', () => {
    const comptes = compterParJour([
      terminee('a', '2026-09-17'),
      terminee('b', '2026-09-17'),
      terminee('c', '2026-09-15'),
      terminee('d', ''),
    ]);
    expect(comptes.get('2026-09-17')).toBe(2);
    expect(comptes.get('2026-09-15')).toBe(1);
    expect(comptes.get(JOUR_INCONNU)).toBe(1);
  });
});

describe('la sélection par plage (Maj+clic)', () => {
  const ordre = ['a', 'b', 'c', 'd', 'e'];

  it('bascule une ligne au clic simple', () => {
    const une = etendreSelection(ordre, new Set(), 'c', null, false);
    expect([...une]).toEqual(['c']);
    expect([...etendreSelection(ordre, une, 'c', 'c', false)]).toEqual([]);
  });

  it('étend de l’ancre à la cible, dans les deux sens, sans jamais retirer', () => {
    const depuisB = etendreSelection(ordre, new Set(['b']), 'd', 'b', true);
    expect([...depuisB].sort()).toEqual(['b', 'c', 'd']);
    const versLeHaut = etendreSelection(ordre, new Set(['d', 'a']), 'b', 'd', true);
    expect([...versLeHaut].sort()).toEqual(['a', 'b', 'c', 'd']);
  });

  it('vaut un clic simple sans ancre, ou si l’ancre n’est plus affichée', () => {
    expect([...etendreSelection(ordre, new Set(), 'c', null, true)]).toEqual(['c']);
    // L'ancre a quitté la page (rouverte, supprimée, autre page).
    expect([...etendreSelection(ordre, new Set(), 'c', 'zz', true)]).toEqual(['c']);
  });

  it('rend un nouvel ensemble et laisse l’ancien intact', () => {
    const avant = new Set(['a']);
    const apres = etendreSelection(ordre, avant, 'b', null, false);
    expect([...avant]).toEqual(['a']);
    expect(apres).not.toBe(avant);
  });
});

describe('le bilan d’une suppression en masse (§100)', () => {
  it('dit « 4 supprimées » quand les quatre réponses sont là', () => {
    expect(bilanSuppression(4, [])).toEqual({ ok: true, titre: '4 supprimées' });
    expect(bilanSuppression(1, []).titre).toBe('1 supprimée');
  });

  it('dit « 3 sur 4 » et NOMME ce qui a échoué — jamais un succès global déduit', () => {
    const bilan = bilanSuppression(4, [{ titre: 'Payer le loyer', message: 'HTTP 500' }]);
    expect(bilan.ok).toBe(false);
    expect(bilan.titre).toBe('3 sur 4 supprimées');
    expect(bilan.description).toBe('« Payer le loyer » a échoué : HTTP 500');
  });

  it('énumère chaque échec sur sa ligne', () => {
    const bilan = bilanSuppression(2, [
      { titre: 'A', message: 'x' },
      { titre: 'B', message: 'y' },
    ]);
    expect(bilan.titre).toBe('0 sur 2 supprimées');
    expect(bilan.description?.split('\n')).toHaveLength(2);
  });
});
