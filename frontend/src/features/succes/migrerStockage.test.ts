import { describe, expect, it } from 'vitest';

import {
  BUDGET_OCTETS,
  OCTETS_PAR_UNITE,
  PREFIXE_STOCKAGE,
  clesSucces,
  creerCacheSucces,
  type Stockage,
} from './cacheSucces';
import { CLES_RENOMMEES, PREFIXE_CACHE_HERITE, migrerStockage } from './migrerStockage';

/**
 * 25/09/2026, étape 8 du plan de la phase 1b : `diapason-succes-*` devient
 * `diapason-vie-*`. Sans copie, les préférences des pages et les rappels
 * d'habitude du jour repartaient ; sans suppression, 1,7 Mo d'anciens caches
 * s'ajoutaient au budget du cache renommé et dépassaient les 5 Mo de WebKit —
 * `saveSettings`, écrit sans `try`, aurait alors perdu les réglages.
 */

/** 5 Mo par origine, comme WebKit — compté en octets UTF-16. */
const QUOTA_WEBKIT_OCTETS = 5_242_880;

class StockageFactice implements Stockage {
  readonly entrees = new Map<string, string>();
  /** En unités de code ; au-delà, `setItem` lève comme un vrai quota plein. */
  quotaUnites = Number.POSITIVE_INFINITY;

  getItem(cle: string): string | null {
    return this.entrees.get(cle) ?? null;
  }

  setItem(cle: string, valeur: string): void {
    let total = cle.length + valeur.length;
    for (const [nom, v] of this.entrees) if (nom !== cle) total += nom.length + v.length;
    if (total > this.quotaUnites) throw new Error('QuotaExceededError');
    this.entrees.set(cle, valeur);
  }

  removeItem(cle: string): void {
    this.entrees.delete(cle);
  }

  get length(): number {
    return this.entrees.size;
  }

  key(i: number): string | null {
    return [...this.entrees.keys()][i] ?? null;
  }
}

const PREFS = '{"tasksViewMode":"week","tasksPageSize":10,"taskSubtasksOpen":{"t1":true}}';
const RAPPELS = '{"h1:10":"2026-09-25"}';

function stockageDAvant(): StockageFactice {
  const store = new StockageFactice();
  store.setItem('diapason-succes-ui-prefs', PREFS);
  store.setItem('diapason-succes-habit-reminder-fired', RAPPELS);
  store.setItem(`${PREFIXE_CACHE_HERITE}tasks?include_done=true&search=`, '{"v":1}');
  store.setItem(`${PREFIXE_CACHE_HERITE}notes?search=`, '{"v":1}');
  store.setItem('diapason-settings', '{"theme":"dark"}');
  return store;
}

describe('migrerStockage', () => {
  it('recopie les préférences et les rappels à l’identique, puis retire l’ancien nom', () => {
    const store = stockageDAvant();
    const bilan = migrerStockage(store);
    expect(store.getItem('diapason-vie-ui-prefs'), 'les préférences des pages').toBe(PREFS);
    expect(store.getItem('diapason-vie-habit-reminder-fired'), 'les rappels du jour').toBe(RAPPELS);
    for (const [ancien] of CLES_RENOMMEES) {
      expect(store.getItem(ancien), `${ancien} doit être retirée`).toBeNull();
    }
    expect(bilan).toEqual({ recopiees: 2, retirees: 2, cachesSupprimes: 2 });
  });

  it('supprime les anciens caches sans toucher aux autres modules', () => {
    const store = stockageDAvant();
    migrerStockage(store);
    const restes = [...store.entrees.keys()].filter((nom) => nom.startsWith(PREFIXE_CACHE_HERITE));
    expect(restes, 'aucun ancien cache ne doit rester').toEqual([]);
    expect(store.getItem('diapason-settings'), 'les réglages sont intouchés').toBe('{"theme":"dark"}');
  });

  it('ne change rien au second passage', () => {
    const store = stockageDAvant();
    migrerStockage(store);
    const apres = new Map(store.entrees);
    const bilan = migrerStockage(store);
    expect(bilan).toEqual({ recopiees: 0, retirees: 0, cachesSupprimes: 0 });
    expect(store.entrees, 'idempotente : une origine rechargée ne perd rien').toEqual(apres);
  });

  it('n’écrase pas une valeur neuve déjà écrite', () => {
    // Un bundle neuf a déjà servi (l'autre origine a migré, ou la page a
    // été ouverte), puis un vieux bundle en cache a réécrit l'ancien nom.
    const store = stockageDAvant();
    store.setItem('diapason-vie-ui-prefs', '{"tasksViewMode":"month"}');
    migrerStockage(store);
    expect(store.getItem('diapason-vie-ui-prefs'), 'la valeur neuve gagne').toBe('{"tasksViewMode":"month"}');
    expect(store.getItem('diapason-succes-ui-prefs'), 'l’ancienne est retirée quand même').toBeNull();
  });

  it('garde l’ancienne clé quand la copie échoue, pour réessayer au lancement suivant', () => {
    const store = new StockageFactice();
    store.setItem('diapason-succes-ui-prefs', PREFS);
    store.quotaUnites = 0;
    expect(() => migrerStockage(store)).not.toThrow();
    expect(store.getItem('diapason-succes-ui-prefs'), 'rien de perdu').toBe(PREFS);
    expect(store.getItem('diapason-vie-ui-prefs')).toBeNull();
  });

  it('ne lève jamais sans stockage', () => {
    expect(migrerStockage(null)).toEqual({ recopiees: 0, retirees: 0, cachesSupprimes: 0 });
  });

  it('laisse la place aux caches neufs et aux réglages sous un quota de 5 Mo', () => {
    // 3,5 Mo d'anciens caches (le 25/09/2026 : 1,7 Mo mesurés, deux fois
    // plus pour la marge), puis ce que le lancement écrit vraiment : tâches
    // (1,62 Mo) et notes (1,86 Mo), et les réglages d'apparence.
    const store = new StockageFactice();
    store.quotaUnites = QUOTA_WEBKIT_OCTETS / OCTETS_PAR_UNITE;
    const ancien = 'a'.repeat(3_500_000 / OCTETS_PAR_UNITE / 4);
    for (let i = 0; i < 4; i += 1) store.setItem(`${PREFIXE_CACHE_HERITE}vieux-${i}`, ancien);
    store.setItem('diapason-succes-ui-prefs', PREFS);

    migrerStockage(store);

    const travaux: Array<() => void> = [];
    const cache = creerCacheSucces({
      stockage: () => store,
      planifier: (travail) => travaux.push(travail),
      empreinte: 'neuf',
    });
    cache.ecrireCache(clesSucces.taches(), 't'.repeat(1_620_000 / OCTETS_PAR_UNITE));
    cache.ecrireCache(clesSucces.notes(), 'n'.repeat(1_860_000 / OCTETS_PAR_UNITE));
    for (const travail of travaux.splice(0)) travail();

    expect(store.entrees.has(PREFIXE_STOCKAGE + clesSucces.taches()), 'tâches persistées').toBe(true);
    expect(store.entrees.has(PREFIXE_STOCKAGE + clesSucces.notes()), 'notes persistées').toBe(true);
    expect(
      () => store.setItem('diapason-settings', JSON.stringify({ theme: 'terminal', pad: 'x'.repeat(400) })),
      'saveSettings écrit sans try : il ne doit pas trouver le quota plein',
    ).not.toThrow();
    expect(store.getItem('diapason-vie-ui-prefs')).toBe(PREFS);
  });

  it('sans la migration, les anciens caches privent le lancement de ses caches neufs', () => {
    // La même scène, migration omise : le défaut que ce module évite.
    const store = new StockageFactice();
    store.quotaUnites = QUOTA_WEBKIT_OCTETS / OCTETS_PAR_UNITE;
    const ancien = 'a'.repeat(3_500_000 / OCTETS_PAR_UNITE / 4);
    for (let i = 0; i < 4; i += 1) store.setItem(`${PREFIXE_CACHE_HERITE}vieux-${i}`, ancien);

    const travaux: Array<() => void> = [];
    const cache = creerCacheSucces({
      stockage: () => store,
      planifier: (travail) => travaux.push(travail),
      empreinte: 'neuf',
    });
    cache.ecrireCache(clesSucces.taches(), 't'.repeat(1_620_000 / OCTETS_PAR_UNITE));
    cache.ecrireCache(clesSucces.notes(), 'n'.repeat(1_860_000 / OCTETS_PAR_UNITE));
    for (const travail of travaux.splice(0)) travail();

    const persistees = [clesSucces.taches(), clesSucces.notes()].filter((cle) =>
      store.entrees.has(PREFIXE_STOCKAGE + cle),
    );
    expect(persistees.length, 'au moins un des deux caches de lancement reste en mémoire seule').toBeLessThan(2);
    expect(BUDGET_OCTETS, 'le budget du cache neuf ignore les anciennes entrées').toBe(4_200_000);
  });
});
