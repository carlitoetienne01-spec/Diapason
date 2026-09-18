/**
 * Le cache client des pages Succès — « montrer la dernière réponse du
 * serveur, puis relire derrière » (stale-while-revalidate).
 *
 * Carlito, 18 sept. 2026 : « les tâches prennent beaucoup de temps pour se
 * recharger, je veux que le temps de rechargement partout soit instantané ».
 * La capture montrait « Chargement des tâches… » sur un écran vide pendant
 * que l'onglet disait déjà « Terminées 37 ». Le serveur, lui, répondait en
 * 20-40 ms pour /v1/succes/tasks?include_done=true (825 Ko), 3-8 ms pour les
 * projets, les notes (924 Ko), le planificateur, les habitudes, 46 ms pour
 * le tableau de bord. Le temps perdu était côté client : chaque page repart
 * d'un `useState([])` à chaque montage — Tâches → Projets → Tâches, ou
 * chaque clic de module du mini-panneau —, retarde son premier `load()` de
 * 180 ms, et rien ne survit au relancement de l'application.
 *
 * Deux étages : une Map de module (survit aux remontages tant que le bundle
 * vit) et `localStorage` (survit au relancement), lu au PREMIER accès d'une
 * clé seulement. Le stockage est cloisonné par origine : la fenêtre
 * (`tauri://localhost`) et le mini-panneau (`http://127.0.0.1:8000`) ont
 * chacun le leur, c'est normal et c'est le même partage que le reste des
 * préférences.
 *
 * §100 : le cache ne contient QUE ce que le serveur a rendu la dernière fois
 * (ou un état optimiste que la page réconcilie aussitôt, règle déjà posée
 * dans Tâches). Il ne promet rien : la page relit toujours derrière.
 *
 * Pur, sans React : les doublures de stockage et de planification le rendent
 * vérifiable sous vitest, et aucune exception ne remonte jamais à la page —
 * un quota plein ou un JSON corrompu vaut « pas de cache », pas un écran
 * blanc.
 */

/**
 * Change quand la forme des données mises en cache change (un champ renommé
 * côté serveur, une liste devenue objet) : un cache écrit par l'ancien
 * bundle est alors ignoré plutôt que peint avec des `undefined`.
 */
export const VERSION_SCHEMA = 1;

/**
 * L'empreinte du bundle qui a écrit l'entrée. Une entrée d'un AUTRE bundle
 * est ignorée même si `VERSION_SCHEMA` n'a pas bougé : oublier de le
 * monter quand la forme d'une réponse change ferait planter la page à
 * chaque montage, sur des données que rien ne remplace tant qu'elle plante
 * (constaté le 18 sept. 2026 avec une doublure de tableau de bord sans
 * `habits.items` : « Cannot read properties of undefined » à chaque
 * ouverture, et « Réessayer » relisait le même cache). Le prix : le cache
 * repart à vide après une mise à jour de l'application — une fois.
 */
export const EMPREINTE_BUNDLE: string = typeof __APP_VERSION__ === 'string' ? __APP_VERSION__ : 'dev';

export const PREFIXE_STOCKAGE = 'diapason-succes-cache:';

/**
 * Au-delà, l'entrée reste en mémoire seule. 1,5 million de caractères :
 * la plus grosse réponse mesurée le 18 sept. 2026 (les notes, 924 Ko) tient
 * avec de la marge, et le budget `localStorage` de WebKit est de 5 Mo par
 * origine — deux entrées de cette taille plus les petites listes restent
 * sous le budget ; à 5 Mo une seule entrée l'aurait mangé.
 */
export const PLAFOND_CARACTERES = 1_500_000;

type Parametres = Record<string, string | number | boolean | undefined | null>;

/**
 * La clé d'une ressource sous des paramètres donnés, dans un ordre fixe :
 * `tasks?include_done=true&search=`. Un paramètre `undefined` ou `null` est
 * omis ; une chaîne vide est GARDÉE — `search=` et « pas de recherche » sont
 * la même requête et doivent partager la même entrée.
 */
export function cleDeCache(ressource: string, params: Parametres = {}): string {
  const paires = Object.keys(params)
    .sort()
    .filter((nom) => params[nom] !== undefined && params[nom] !== null)
    .map((nom) => `${nom}=${String(params[nom])}`);
  return paires.length ? `${ressource}?${paires.join('&')}` : ressource;
}

/**
 * Les clés que les pages partagent. Nommées ici pour qu'une même requête
 * serveur ait UNE entrée : Tâches, Projets et Planificateur lisent tous
 * `/v1/succes/tasks?include_done=true`, et une liste rendue à l'une des trois
 * sert aux deux autres. Les paramètres sont ceux que `api.ts` met sur le fil.
 */
export const clesSucces = {
  taches: (search = '') => cleDeCache('tasks', { include_done: true, search }),
  projets: (search = '') => cleDeCache('projects', { search }),
  kitsProjets: () => cleDeCache('project-kits'),
  gabarits: () => cleDeCache('templates'),
  notes: (search = '') => cleDeCache('notes', { search }),
  categoriesNotes: () => cleDeCache('notes/categories'),
  habitudes: (date: string) => cleDeCache('habits', { date }),
  journalHabitudes: (from: string, to: string) => cleDeCache('habits/logs', { from, to }),
  tableauDeBord: (date: string) => cleDeCache('dashboard', { date }),
  bilan: (year: number, month?: number) => cleDeCache('year-review', { year, month }),
  financesApercu: (period: string, anchor: string) => cleDeCache('finances/overview', { period, anchor }),
  financesCategories: () => cleDeCache('finances/categories'),
  financesAbonnements: () => cleDeCache('finances/subscriptions'),
  financesTransactions: (from: string, to: string) => cleDeCache('finances/transactions', { from, to, limit: 200 }),
  citations: () => cleDeCache('quotes'),
} as const;

/** Le strict nécessaire d'un `Storage`, pour pouvoir le doubler. */
export interface Stockage {
  getItem(cle: string): string | null;
  setItem(cle: string, valeur: string): void;
  removeItem(cle: string): void;
}

export interface OptionsEcriture {
  /**
   * Ne pas persister : les listes filtrées par une recherche tapée sont des
   * sous-ensembles que rien ne borne — une clé par frappe finirait par
   * remplir le quota avec des listes que personne ne redemandera.
   */
  memoireSeule?: boolean;
}

export interface OptionsCache {
  /** Rend le stockage, ou `null` s'il n'existe pas (navigation privée, Node). */
  stockage?: () => Stockage | null;
  /** Diffère un travail hors du rendu — `requestIdleCallback` en production. */
  planifier?: (travail: () => void) => void;
  plafondCaracteres?: number;
}

interface Enveloppe {
  v: number;
  b: string;
  d: unknown;
}

function stockageDuNavigateur(): Stockage | null {
  try {
    // L'accès lui-même peut lever (Safari, cookies bloqués).
    return typeof localStorage === 'undefined' ? null : localStorage;
  } catch {
    return null;
  }
}

function planifierEnCreux(travail: () => void): void {
  const ric = (globalThis as { requestIdleCallback?: (cb: () => void, o?: { timeout: number }) => void })
    .requestIdleCallback;
  // WebKit n'a pas `requestIdleCallback` : le mini-panneau et la fenêtre
  // Tauri passent par le minuteur. Le délai de 1 s borne l'attente ailleurs.
  if (typeof ric === 'function') ric(travail, { timeout: 1000 });
  else setTimeout(travail, 0);
}

export interface CacheSucces {
  lireCache<T>(cle: string): T | null;
  ecrireCache(cle: string, valeur: unknown, options?: OptionsEcriture): void;
  oublierCache(cle: string): void;
  /** Écrit tout de suite ce qui attend — pour les tests, et avant de quitter. */
  vider(): void;
}

export function creerCacheSucces(options: OptionsCache = {}): CacheSucces {
  const stockage = options.stockage ?? stockageDuNavigateur;
  const planifier = options.planifier ?? planifierEnCreux;
  const plafond = options.plafondCaracteres ?? PLAFOND_CARACTERES;

  const memoire = new Map<string, unknown>();
  /** Les clés déjà cherchées dans le stockage : on ne relit pas un disque qui a dit non. */
  const consultees = new Set<string>();
  /** Les clés dont la mémoire attend d'être persistée (ou retirée : `null`). */
  const enAttente = new Map<string, unknown | null>();
  let planifiee = false;

  const lireStockage = (cle: string): unknown | null => {
    const store = stockage();
    if (!store) return null;
    const nomComplet = PREFIXE_STOCKAGE + cle;
    try {
      const brut = store.getItem(nomComplet);
      if (brut === null) return null;
      const enveloppe = JSON.parse(brut) as Enveloppe | null;
      if (
        !enveloppe ||
        typeof enveloppe !== 'object' ||
        enveloppe.v !== VERSION_SCHEMA ||
        enveloppe.b !== EMPREINTE_BUNDLE
      ) {
        // Un ancien schéma, ou n'importe quoi : on l'efface pour ne pas le
        // relire à chaque démarrage.
        store.removeItem(nomComplet);
        return null;
      }
      return enveloppe.d ?? null;
    } catch {
      try {
        store.removeItem(nomComplet);
      } catch {
        // Le stockage refuse même d'effacer : tant pis, la mémoire suffira.
      }
      return null;
    }
  };

  const purgerLesAutres = (store: Stockage, saufNomComplet: string): void => {
    // Le quota est plein : plutôt que renoncer, on fait de la place en
    // retirant NOS autres entrées (jamais celles d'un autre module — les
    // préférences, les conversations n'y sont pour rien).
    const aRetirer: string[] = [];
    const s = store as Stockage & { length?: number; key?: (i: number) => string | null };
    if (typeof s.length !== 'number' || typeof s.key !== 'function') return;
    for (let i = 0; i < s.length; i += 1) {
      const nom = s.key(i);
      if (nom && nom.startsWith(PREFIXE_STOCKAGE) && nom !== saufNomComplet) aRetirer.push(nom);
    }
    for (const nom of aRetirer) store.removeItem(nom);
  };

  const persister = (): void => {
    planifiee = false;
    const store = stockage();
    const lot = [...enAttente];
    enAttente.clear();
    if (!store) return;
    for (const [cle, valeur] of lot) {
      const nomComplet = PREFIXE_STOCKAGE + cle;
      try {
        if (valeur === null) {
          store.removeItem(nomComplet);
          continue;
        }
        const texte = JSON.stringify({ v: VERSION_SCHEMA, b: EMPREINTE_BUNDLE, d: valeur } satisfies Enveloppe);
        if (texte.length > plafond) continue;
        try {
          store.setItem(nomComplet, texte);
        } catch {
          purgerLesAutres(store, nomComplet);
          store.setItem(nomComplet, texte);
        }
      } catch {
        // Quota toujours plein, valeur non sérialisable : la mémoire
        // garde la valeur et la page n'en saura rien — c'est voulu.
      }
    }
  };

  const programmer = (): void => {
    if (planifiee) return;
    planifiee = true;
    try {
      planifier(persister);
    } catch {
      planifiee = false;
    }
  };

  return {
    lireCache<T>(cle: string): T | null {
      if (memoire.has(cle)) return memoire.get(cle) as T;
      if (consultees.has(cle)) return null;
      consultees.add(cle);
      const valeur = lireStockage(cle);
      if (valeur !== null) memoire.set(cle, valeur);
      return valeur as T | null;
    },

    ecrireCache(cle: string, valeur: unknown, options: OptionsEcriture = {}): void {
      memoire.set(cle, valeur);
      // Une entrée écrite ne se relit plus sur le disque : la mémoire prime.
      consultees.add(cle);
      if (options.memoireSeule) {
        // Une persistance en attente pour cette clé serait plus vieille que
        // la mémoire : on l'annule plutôt que d'écrire du périmé.
        enAttente.delete(cle);
        return;
      }
      enAttente.set(cle, valeur);
      programmer();
    },

    oublierCache(cle: string): void {
      memoire.delete(cle);
      consultees.add(cle);
      enAttente.set(cle, null);
      programmer();
    },

    vider(): void {
      if (enAttente.size) persister();
    },
  };
}

const cache = creerCacheSucces();

export const lireCache: CacheSucces['lireCache'] = (cle) => cache.lireCache(cle);
export const ecrireCache: CacheSucces['ecrireCache'] = (cle, valeur, options) =>
  cache.ecrireCache(cle, valeur, options);
export const oublierCache: CacheSucces['oublierCache'] = (cle) => cache.oublierCache(cle);

// Le crochet `requestIdleCallback` n'arrive pas toujours avant qu'on ferme la
// fenêtre : ce qui attend s'écrit au moment de partir, sinon la dernière
// réponse du serveur est perdue pour le prochain lancement.
if (typeof window !== 'undefined' && typeof window.addEventListener === 'function') {
  window.addEventListener('pagehide', () => cache.vider());
}
