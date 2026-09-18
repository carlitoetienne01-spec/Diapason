import { describe, expect, it } from 'vitest';

import {
  EMPREINTE_BUNDLE,
  PREFIXE_STOCKAGE,
  VERSION_SCHEMA,
  cleDeCache,
  creerCacheSucces,
  type Stockage,
} from './cacheSucces';

/**
 * Carlito, 18 sept. 2026 : « les tâches prennent beaucoup de temps pour se
 * recharger, je veux que le temps de rechargement partout soit instantané ».
 * Le serveur répondait en 20-40 ms ; c'est le client qui repartait d'un
 * écran vide à chaque montage. Ce cache est ce qui évite l'écran vide ; ces
 * tests prouvent qu'il rend la dernière réponse, qu'il survit à un stockage
 * absent, plein ou corrompu, et qu'il ne lève jamais.
 */
class StockageFactice implements Stockage {
  readonly entrees = new Map<string, string>();
  /** Au-delà, `setItem` lève comme un vrai quota plein. */
  quota = Number.POSITIVE_INFINITY;
  ecritures = 0;
  lectures = 0;

  getItem(cle: string): string | null {
    this.lectures += 1;
    return this.entrees.get(cle) ?? null;
  }

  setItem(cle: string, valeur: string): void {
    this.ecritures += 1;
    let total = valeur.length;
    for (const [nom, v] of this.entrees) if (nom !== cle) total += v.length;
    if (total > this.quota) throw new Error('QuotaExceededError');
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

/** Un planificateur à la main : rien ne s'écrit tant qu'on n'a pas appelé `tic()`. */
function planificateurManuel() {
  const travaux: Array<() => void> = [];
  return {
    planifier: (travail: () => void) => {
      travaux.push(travail);
    },
    tic: () => {
      for (const travail of travaux.splice(0)) travail();
    },
    get enAttente() {
      return travaux.length;
    },
  };
}

function monter(stockage: Stockage | null = new StockageFactice(), plafond?: number) {
  const plan = planificateurManuel();
  const cache = creerCacheSucces({
    stockage: () => stockage,
    planifier: plan.planifier,
    plafondCaracteres: plafond,
  });
  return { cache, plan, stockage };
}

describe('cleDeCache', () => {
  it('nomme la ressource et ses paramètres dans un ordre fixe', () => {
    expect(cleDeCache('tasks', { search: '', include_done: true })).toBe(
      'tasks?include_done=true&search=',
    );
    expect(cleDeCache('tasks', { include_done: true, search: '' })).toBe(
      cleDeCache('tasks', { search: '', include_done: true }),
    );
  });

  it('garde une chaîne vide mais omet undefined et null', () => {
    // `search=` et « pas de recherche » sont la même requête serveur et
    // doivent partager la même entrée ; un paramètre absent ne change rien.
    expect(cleDeCache('year-review', { year: 2026, month: undefined })).toBe('year-review?year=2026');
    expect(cleDeCache('planner', { date: null })).toBe('planner');
    expect(cleDeCache('projects', { search: '' })).toBe('projects?search=');
  });

  it('rend la ressource nue sans paramètre', () => {
    expect(cleDeCache('templates')).toBe('templates');
  });
});

describe('Le cache en mémoire', () => {
  it('rend null pour une clé jamais écrite', () => {
    const { cache } = monter();
    expect(cache.lireCache('tasks')).toBeNull();
  });

  it('rend tout de suite ce qui vient d’être écrit, sans attendre la persistance', () => {
    const { cache, plan } = monter();
    cache.ecrireCache('tasks', [{ id: 'a' }]);
    expect(cache.lireCache('tasks')).toEqual([{ id: 'a' }]);
    expect(plan.enAttente).toBe(1);
  });

  it('oublie une clé en mémoire et sur le disque', () => {
    const { cache, plan, stockage } = monter();
    cache.ecrireCache('tasks', [1]);
    plan.tic();
    expect(stockage!.getItem(PREFIXE_STOCKAGE + 'tasks')).not.toBeNull();
    cache.oublierCache('tasks');
    expect(cache.lireCache('tasks')).toBeNull();
    plan.tic();
    expect(stockage!.getItem(PREFIXE_STOCKAGE + 'tasks')).toBeNull();
  });
});

describe('La persistance', () => {
  it('écrit une enveloppe versionnée, en une seule écriture pour plusieurs mises à jour', () => {
    const { cache, plan, stockage } = monter();
    const store = stockage as StockageFactice;
    cache.ecrireCache('tasks', [1]);
    cache.ecrireCache('tasks', [1, 2]);
    cache.ecrireCache('tasks', [1, 2, 3]);
    expect(store.ecritures, 'rien ne s’écrit avant le creux').toBe(0);
    plan.tic();
    expect(store.ecritures, 'trois mises à jour, une écriture').toBe(1);
    expect(JSON.parse(store.entrees.get(PREFIXE_STOCKAGE + 'tasks')!)).toEqual({
      v: VERSION_SCHEMA,
      b: EMPREINTE_BUNDLE,
      d: [1, 2, 3],
    });
  });

  it('relit le disque au premier accès d’un nouveau cache — le relancement de l’app', () => {
    const store = new StockageFactice();
    const premier = monter(store);
    premier.cache.ecrireCache('notes', [{ id: 'n1' }]);
    premier.plan.tic();

    const second = monter(store);
    expect(second.cache.lireCache('notes')).toEqual([{ id: 'n1' }]);
    // Une seule lecture disque par clé : la mémoire prend le relais.
    const lectures = store.lectures;
    second.cache.lireCache('notes');
    second.cache.lireCache('notes');
    expect(store.lectures).toBe(lectures);
  });

  it('ignore et efface une entrée d’un autre schéma', () => {
    const store = new StockageFactice();
    store.setItem(
      PREFIXE_STOCKAGE + 'tasks',
      JSON.stringify({ v: VERSION_SCHEMA + 1, b: EMPREINTE_BUNDLE, d: [1] }),
    );
    const { cache } = monter(store);
    expect(cache.lireCache('tasks')).toBeNull();
    expect(store.entrees.has(PREFIXE_STOCKAGE + 'tasks'), 'l’entrée périmée est retirée').toBe(false);
  });

  it('ignore et efface une entrée écrite par un autre bundle', () => {
    // Une forme de réponse changée sans monter VERSION_SCHEMA plantait la
    // page à chaque montage, sur un cache que rien ne remplaçait.
    const store = new StockageFactice();
    store.setItem(PREFIXE_STOCKAGE + 'dashboard', JSON.stringify({ v: VERSION_SCHEMA, b: '0.0.0', d: { x: 1 } }));
    const { cache } = monter(store);
    expect(cache.lireCache('dashboard')).toBeNull();
    expect(store.entrees.has(PREFIXE_STOCKAGE + 'dashboard')).toBe(false);
  });

  it('ignore et efface une entrée corrompue', () => {
    const store = new StockageFactice();
    store.setItem(PREFIXE_STOCKAGE + 'tasks', '{pas du json');
    const { cache } = monter(store);
    expect(cache.lireCache('tasks')).toBeNull();
    expect(store.entrees.has(PREFIXE_STOCKAGE + 'tasks')).toBe(false);
  });

  it('garde en mémoire seule ce qui dépasse le plafond', () => {
    const { cache, plan, stockage } = monter(new StockageFactice(), 50);
    const gros = Array.from({ length: 40 }, (_, i) => ({ id: String(i) }));
    cache.ecrireCache('tasks', gros);
    plan.tic();
    expect(cache.lireCache('tasks')).toEqual(gros);
    expect((stockage as StockageFactice).entrees.size).toBe(0);
  });

  it('fait de la place parmi ses propres entrées quand le quota est plein, et jamais ailleurs', () => {
    const store = new StockageFactice();
    store.setItem('diapason-succes-ui-prefs', '{"tasksViewMode":"week"}');
    const { cache, plan } = monter(store);
    cache.ecrireCache('notes', 'x'.repeat(60));
    plan.tic();
    store.quota = 120;
    cache.ecrireCache('tasks', 'y'.repeat(60));
    plan.tic();
    expect(cache.lireCache('tasks'), 'la mémoire garde toujours la valeur').toBe('y'.repeat(60));
    expect(store.entrees.has(PREFIXE_STOCKAGE + 'tasks'), 'écrite après purge').toBe(true);
    expect(store.entrees.has(PREFIXE_STOCKAGE + 'notes'), 'la nôtre est sacrifiée').toBe(false);
    expect(store.entrees.get('diapason-succes-ui-prefs'), 'les préférences sont intouchées').toBe(
      '{"tasksViewMode":"week"}',
    );
  });

  it('ne lève jamais quand le quota reste plein même après purge', () => {
    const store = new StockageFactice();
    store.quota = 10;
    const { cache, plan } = monter(store);
    cache.ecrireCache('tasks', 'z'.repeat(100));
    expect(() => plan.tic()).not.toThrow();
    expect(cache.lireCache('tasks')).toBe('z'.repeat(100));
  });

  it('fonctionne sans stockage du tout', () => {
    const { cache, plan } = monter(null);
    cache.ecrireCache('tasks', [1]);
    expect(() => plan.tic()).not.toThrow();
    expect(cache.lireCache('tasks')).toEqual([1]);
  });

  it('ne persiste pas une écriture « mémoire seule » et annule celle qui attendait', () => {
    const { cache, plan, stockage } = monter();
    cache.ecrireCache('tasks?search=a', [1]);
    cache.ecrireCache('tasks?search=a', [1, 2], { memoireSeule: true });
    plan.tic();
    expect(cache.lireCache('tasks?search=a')).toEqual([1, 2]);
    expect(
      (stockage as StockageFactice).entrees.has(PREFIXE_STOCKAGE + 'tasks?search=a'),
      'la version [1] en attente aurait été plus vieille que la mémoire',
    ).toBe(false);
  });

  it('vider() écrit tout de suite ce qui attend — au pagehide', () => {
    const { cache, stockage } = monter();
    cache.ecrireCache('tasks', [7]);
    cache.vider();
    expect((stockage as StockageFactice).entrees.has(PREFIXE_STOCKAGE + 'tasks')).toBe(true);
  });
});
