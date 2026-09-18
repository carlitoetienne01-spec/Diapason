import { describe, expect, it } from 'vitest';

import {
  OCTETS_PAR_UNITE,
  PREFIXE_STOCKAGE,
  VERSION_SCHEMA,
  cleDeCache,
  clesSucces,
  creerCacheSucces,
  ressourceDe,
  type Stockage,
} from './cacheSucces';

/**
 * L'empreinte de build est injectée, pas lue de `__BUILD_STAMP__` : elle
 * change à chaque démarrage de Vite, et un test qui la lirait ne pourrait
 * ni écrire une enveloppe « d'un autre build » ni prouver qu'elle est
 * rejetée (revue du cache, 18 sept. 2026).
 */
const EMPREINTE = 'test-1';

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

function monter(
  stockage: Stockage | null = new StockageFactice(),
  limites: { plafondOctets?: number; budgetOctets?: number } = {},
  empreinte = EMPREINTE,
) {
  const plan = planificateurManuel();
  const cache = creerCacheSucces({
    stockage: () => stockage,
    planifier: plan.planifier,
    empreinte,
    ...limites,
  });
  return { cache, plan, stockage };
}

/** Une enveloppe telle que le module l'écrit — pour semer le stockage. */
function enveloppe(valeur: unknown, b = EMPREINTE, v = VERSION_SCHEMA): string {
  return JSON.stringify({ v, b, d: valeur });
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

  it('retrouve la ressource d’une clé datée', () => {
    expect(ressourceDe('dashboard?date=2026-09-18')).toBe('dashboard');
    expect(ressourceDe('finances/transactions?from=a&limit=200&to=b')).toBe('finances/transactions');
    expect(ressourceDe('templates')).toBe('templates');
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
      b: EMPREINTE,
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
    store.setItem(PREFIXE_STOCKAGE + 'tasks', enveloppe([1], EMPREINTE, VERSION_SCHEMA + 1));
    const { cache } = monter(store);
    expect(cache.lireCache('tasks')).toBeNull();
    expect(store.entrees.has(PREFIXE_STOCKAGE + 'tasks'), 'l’entrée périmée est retirée').toBe(false);
  });

  it('ignore et efface une entrée écrite par un autre build', () => {
    // Une forme de réponse changée sans monter VERSION_SCHEMA plantait la
    // page à chaque montage, sur un cache que rien ne remplaçait. Deux
    // builds d'une même version sont deux builds : l'empreinte change.
    const store = new StockageFactice();
    const premier = monter(store, {}, '1.0.4-abc');
    premier.cache.ecrireCache('dashboard', { x: 1 });
    premier.plan.tic();
    expect(store.entrees.has(PREFIXE_STOCKAGE + 'dashboard')).toBe(true);

    const second = monter(store, {}, '1.0.4-abd');
    expect(second.cache.lireCache('dashboard')).toBeNull();
    expect(store.entrees.has(PREFIXE_STOCKAGE + 'dashboard')).toBe(false);
  });

  it('élague à la naissance les clés datées qu’un autre build a laissées', () => {
    // `dashboard?date=hier` n'est relu par personne : l'invalidation à la
    // lecture ne l'atteignait jamais, et elle pesait sur le quota jusqu'à
    // faire purger tâches et notes (revue du cache, 18 sept. 2026).
    const store = new StockageFactice();
    store.setItem(PREFIXE_STOCKAGE + 'dashboard?date=2026-09-11', enveloppe({ x: 1 }, 'ancien'));
    store.setItem(PREFIXE_STOCKAGE + 'habits?date=2026-09-11', enveloppe([], EMPREINTE, VERSION_SCHEMA + 1));
    store.setItem(PREFIXE_STOCKAGE + 'quotes', '{corrompu');
    store.setItem(PREFIXE_STOCKAGE + 'dashboard?date=2026-09-18', enveloppe({ x: 2 }));
    store.setItem('diapason-succes-ui-prefs', '{"tasksViewMode":"week"}');
    monter(store);
    expect([...store.entrees.keys()].sort()).toEqual([
      PREFIXE_STOCKAGE + 'dashboard?date=2026-09-18',
      'diapason-succes-ui-prefs',
    ]);
  });

  it('ignore et efface une entrée corrompue', () => {
    const store = new StockageFactice();
    store.setItem(PREFIXE_STOCKAGE + 'tasks', '{pas du json');
    const { cache } = monter(store);
    expect(cache.lireCache('tasks')).toBeNull();
    expect(store.entrees.has(PREFIXE_STOCKAGE + 'tasks')).toBe(false);
  });

  it('garde en mémoire seule ce qui dépasse le plafond, compté en octets UTF-16', () => {
    // WebKit range une chaîne sur deux octets par unité dès qu'un caractère
    // dépasse U+00FF — les tirets cadratins des tâches, les emoji des
    // notes. Une entrée de 30 unités pèse 60 octets, pas 30.
    const texte = enveloppe('x'.repeat(30));
    expect(OCTETS_PAR_UNITE).toBe(2);
    const passe = monter(new StockageFactice(), { plafondOctets: texte.length * 2 });
    passe.cache.ecrireCache('tasks', 'x'.repeat(30));
    passe.plan.tic();
    expect((passe.stockage as StockageFactice).entrees.size, 'au plafond exactement : écrite').toBe(1);

    const trop = monter(new StockageFactice(), { plafondOctets: texte.length * 2 - 1 });
    trop.cache.ecrireCache('tasks', 'x'.repeat(30));
    trop.plan.tic();
    expect(trop.cache.lireCache('tasks')).toBe('x'.repeat(30));
    expect((trop.stockage as StockageFactice).entrees.size, 'un octet de trop : mémoire seule').toBe(0);
  });

  it('laisse en mémoire seule une écriture qui dépasserait le budget global, sans purger les autres', () => {
    // Deux entrées sous le plafond chacune ne tiennent pas forcément
    // ensemble : à 1 octet par caractère le commentaire d'avant la revue
    // du cache (18 sept. 2026) les croyait à 3 Mo, elles en faisaient 6 —
    // et la seconde faisait évincer la première, puis l'inverse à la
    // visite suivante. Le budget arbitre AVANT d'écrire.
    const store = new StockageFactice();
    const unite = enveloppe('x'.repeat(30)).length;
    const { cache, plan } = monter(store, { plafondOctets: unite * 2, budgetOctets: unite * 3 });
    cache.ecrireCache(clesSucces.taches(), 'x'.repeat(30));
    plan.tic();
    cache.ecrireCache(clesSucces.notes(), 'y'.repeat(30));
    plan.tic();
    expect(store.entrees.has(PREFIXE_STOCKAGE + clesSucces.taches()), 'la première reste').toBe(true);
    expect(store.entrees.has(PREFIXE_STOCKAGE + clesSucces.notes()), 'la seconde : mémoire seule').toBe(false);
    expect(cache.lireCache(clesSucces.notes())).toBe('y'.repeat(30));
    expect(store.ecritures, 'une seule écriture : pas de purge, pas de réessai').toBe(1);

    // Remplacer une entrée par une version plus grosse compte l'ancienne
    // comme retirée, pas deux fois.
    cache.ecrireCache(clesSucces.taches(), 'z'.repeat(30));
    plan.tic();
    expect(JSON.parse(store.entrees.get(PREFIXE_STOCKAGE + clesSucces.taches())!).d).toBe('z'.repeat(30));
  });

  it('fait de la place parmi ses propres entrées quand le quota est VRAIMENT plein, et jamais ailleurs', () => {
    const store = new StockageFactice();
    store.setItem('diapason-succes-ui-prefs', '{"tasksViewMode":"week"}');
    const { cache, plan } = monter(store);
    cache.ecrireCache('habits?date=2026-09-17', 'x'.repeat(60));
    plan.tic();
    store.quota = 120;
    cache.ecrireCache('dashboard?date=2026-09-18', 'y'.repeat(60));
    plan.tic();
    expect(cache.lireCache('dashboard?date=2026-09-18'), 'la mémoire garde toujours la valeur').toBe('y'.repeat(60));
    expect(store.entrees.has(PREFIXE_STOCKAGE + 'dashboard?date=2026-09-18'), 'écrite après purge').toBe(true);
    expect(store.entrees.has(PREFIXE_STOCKAGE + 'habits?date=2026-09-17'), 'la nôtre est sacrifiée').toBe(false);
    expect(store.entrees.get('diapason-succes-ui-prefs'), 'les préférences sont intouchées').toBe(
      '{"tasksViewMode":"week"}',
    );
  });

  it('n’évince jamais une clé de lancement pour loger une clé datée', () => {
    // Tâches et notes rendent le lancement instantané ; un tableau de bord
    // du jour ne vaut pas qu'on les sacrifie (revue du cache, 18 sept. 2026).
    const store = new StockageFactice();
    const { cache, plan } = monter(store);
    cache.ecrireCache(clesSucces.taches(), 'x'.repeat(60));
    cache.ecrireCache('habits?date=2026-09-17', 'h'.repeat(20));
    plan.tic();
    // Les trois enveloppes font 86 + 46 + 86 unités : à 180, il faut en
    // retirer une — et ce doit être la datée, pas les tâches.
    store.quota = 180;
    cache.ecrireCache('dashboard?date=2026-09-18', 'y'.repeat(60));
    plan.tic();
    expect(store.entrees.has(PREFIXE_STOCKAGE + clesSucces.taches()), 'les tâches restent').toBe(true);
    expect(store.entrees.has(PREFIXE_STOCKAGE + 'habits?date=2026-09-17'), 'la datée est sacrifiée').toBe(false);
    expect(store.entrees.has(PREFIXE_STOCKAGE + 'dashboard?date=2026-09-18'), 'le tableau tient après purge').toBe(true);
    expect(cache.lireCache('dashboard?date=2026-09-18')).toBe('y'.repeat(60));

    // Une clé de lancement, elle, peut évincer une autre clé de lancement.
    store.quota = 100;
    cache.ecrireCache(clesSucces.notes(), 'n'.repeat(60));
    plan.tic();
    expect(store.entrees.has(PREFIXE_STOCKAGE + clesSucces.notes())).toBe(true);
    expect(store.entrees.has(PREFIXE_STOCKAGE + clesSucces.taches())).toBe(false);
  });

  it('ne garde qu’une entrée persistée par ressource datée quand on le demande', () => {
    // Une entrée par jour de tableau de bord, d'habitudes, d'aperçu des
    // finances, que rien ne relisait ni ne retirait : ≈ 15 Ko par jour,
    // quota plein en une centaine de jours (revue du cache, 18 sept. 2026).
    const store = new StockageFactice();
    const { cache, plan } = monter(store);
    cache.ecrireCache('dashboard?date=2026-09-17', { j: 17 }, { uniqueParRessource: true });
    cache.ecrireCache('habits?date=2026-09-17', [1], { uniqueParRessource: true });
    plan.tic();
    cache.ecrireCache('dashboard?date=2026-09-18', { j: 18 }, { uniqueParRessource: true });
    plan.tic();
    expect(store.entrees.has(PREFIXE_STOCKAGE + 'dashboard?date=2026-09-17'), 'hier est retiré du disque').toBe(false);
    expect(store.entrees.has(PREFIXE_STOCKAGE + 'dashboard?date=2026-09-18')).toBe(true);
    expect(store.entrees.has(PREFIXE_STOCKAGE + 'habits?date=2026-09-17'), 'une autre ressource est intouchée').toBe(true);
    expect(cache.lireCache('dashboard?date=2026-09-17'), 'la mémoire garde hier : on feuillette sans relire').toEqual({ j: 17 });
  });

  it('garde la clé d’ouverture quand une autre date de la même ressource s’écrit', () => {
    // Contre-revue du 18 sept. 2026 : feuilleter « hier » évinçait le jour
    // courant du disque, et le prochain lancement repartait du spinner.
    const store = new StockageFactice();
    const { cache, plan } = monter(store);
    cache.ecrireCache('dashboard?date=2026-09-18', { j: 18 }, { uniqueParRessource: true });
    plan.tic();
    cache.ecrireCache('dashboard?date=2026-09-17', { j: 17 }, {
      uniqueParRessource: true,
      conserver: ['dashboard?date=2026-09-18'],
    });
    plan.tic();
    expect(store.entrees.has(PREFIXE_STOCKAGE + 'dashboard?date=2026-09-18'), 'le jour courant reste sur le disque').toBe(true);
    expect(store.entrees.has(PREFIXE_STOCKAGE + 'dashboard?date=2026-09-17'), 'hier est écrit aussi').toBe(true);
    cache.ecrireCache('dashboard?date=2026-09-16', { j: 16 }, {
      uniqueParRessource: true,
      conserver: ['dashboard?date=2026-09-18'],
    });
    plan.tic();
    expect(store.entrees.has(PREFIXE_STOCKAGE + 'dashboard?date=2026-09-17'), 'les autres dates, elles, s’évincent').toBe(false);
    expect(store.entrees.has(PREFIXE_STOCKAGE + 'dashboard?date=2026-09-18')).toBe(true);
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

describe('appliquerAuCache', () => {
  it('transforme ce que le cache tient, en mémoire et sur le disque', () => {
    // Sous une recherche active, une suppression ou une ligne réconciliée
    // ne touchait que la clé de recherche : la clé principale — lue par
    // Planificateur, Projets et le prochain montage — gardait la tâche
    // supprimée ou l'intérim optimiste (revue du cache, 18 sept. 2026).
    const { cache, plan, stockage } = monter();
    cache.ecrireCache(clesSucces.taches(), [{ id: 'a' }, { id: 'b' }]);
    const applique = cache.appliquerAuCache<Array<{ id: string }>>(clesSucces.taches(), (liste) =>
      liste.filter((t) => t.id !== 'a'),
    );
    expect(applique).toBe(true);
    expect(cache.lireCache(clesSucces.taches())).toEqual([{ id: 'b' }]);
    plan.tic();
    expect(JSON.parse((stockage as StockageFactice).entrees.get(PREFIXE_STOCKAGE + clesSucces.taches())!).d).toEqual([
      { id: 'b' },
    ]);
  });

  it('ne fait rien — et le dit — quand le cache ne tient rien sous la clé', () => {
    const { cache, plan, stockage } = monter();
    let appels = 0;
    const applique = cache.appliquerAuCache<number[]>('tasks?search=x', (liste) => {
      appels += 1;
      return liste;
    });
    expect(applique).toBe(false);
    expect(appels, 'rien à transformer : le transformateur n’est pas appelé').toBe(0);
    expect(cache.lireCache('tasks?search=x'), 'rien n’est inventé').toBeNull();
    plan.tic();
    expect((stockage as StockageFactice).entrees.size).toBe(0);
  });

  it('respecte « mémoire seule » pour une clé de recherche', () => {
    const { cache, plan, stockage } = monter();
    cache.ecrireCache('tasks?search=x', [1], { memoireSeule: true });
    cache.appliquerAuCache<number[]>('tasks?search=x', (liste) => [...liste, 2], { memoireSeule: true });
    plan.tic();
    expect(cache.lireCache('tasks?search=x')).toEqual([1, 2]);
    expect((stockage as StockageFactice).entrees.size).toBe(0);
  });
});
