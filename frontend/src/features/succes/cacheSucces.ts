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
 * L'empreinte du BUILD qui a écrit l'entrée — `__BUILD_STAMP__`, posée par
 * `vite.config.ts` : la version de `package.json` suivie de l'instant de la
 * construction. Nouvelle à chaque `npm run build` et à chaque démarrage du
 * serveur Vite. Une entrée d'un autre build est ignorée même si
 * `VERSION_SCHEMA` n'a pas bougé : oublier de le monter quand la forme d'une
 * réponse change ferait planter la page à chaque montage, sur des données
 * que rien ne remplace tant qu'elle plante (constaté le 18 sept. 2026 avec
 * une doublure de tableau de bord sans `habits.items` : « Cannot read
 * properties of undefined » à chaque ouverture, et « Réessayer » relisait
 * le même cache).
 *
 * Jusqu'à la revue du cache (18 sept. 2026), l'empreinte était
 * `__APP_VERSION__` — « 1.0.4 » pour les 44 builds depuis le dernier bump :
 * le garde-fou ne jouait qu'à une version publiée, jamais entre deux
 * reconstructions locales, là où les formes changent plusieurs fois par
 * semaine. Le prix, assumé : le cache persisté repart à vide UNE fois après
 * chaque reconstruction — la mémoire fait le reste dans la session.
 */
export const EMPREINTE_BUNDLE: string = typeof __BUILD_STAMP__ === 'string' ? __BUILD_STAMP__ : 'dev';

export const PREFIXE_STOCKAGE = 'diapason-succes-cache:';

/**
 * Les tailles se comptent en OCTETS UTF-16, deux par unité de code : WebKit
 * (la fenêtre Tauri et le mini-panneau) range une chaîne sur 16 bits dès
 * qu'UN caractère dépasse U+00FF, et les vraies réponses en ont — 1 439
 * tirets cadratins dans les tâches, des flèches et des emoji dans les notes
 * (mesuré le 18 sept. 2026). Compter 1 octet par caractère, comme avant la
 * revue du cache, laissait croire que deux entrées de 1,5 M de caractères
 * tenaient dans les 5 Mo par origine : à 2 octets ce sont 6 Mo, et
 * `purgerLesAutres` faisait alors s'évincer tâches et notes en alternance.
 */
export const OCTETS_PAR_UNITE = 2;

/**
 * Au-delà, l'entrée reste en mémoire seule. 2,4 Mo, soit 1,2 M d'unités :
 * la plus grosse réponse mesurée le 18 sept. 2026 (les notes, 927 654
 * unités, 1,86 Mo) tient avec 29 % de marge, et deux entrées à ce plafond
 * (4,8 Mo) ne passent PAS le budget global — c'est lui qui arbitre.
 */
export const PLAFOND_OCTETS = 2_400_000;

/**
 * Le budget de TOUTES nos entrées, mesuré en octets UTF-16 et comparé avant
 * d'écrire. 4,2 Mo sur les 5 Mo (5 242 880 octets) que WebKit accorde à
 * l'origine : tâches (1,62 Mo) + notes (1,86 Mo) + les petites listes
 * (≈ 30 Ko) y tiennent, et il reste ≈ 1 Mo aux autres modules — réglages
 * (≈ 400 octets), préférences d'interface (3 Ko), statistiques de dictée —
 * dont `saveSettings` écrit sans `try/catch` : un quota plein leur ferait
 * perdre le réglage en mémoire même. Une écriture qui dépasserait le budget
 * reste en mémoire seule ; elle ne purge personne.
 */
export const BUDGET_OCTETS = 4_200_000;

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

/** La ressource d'une clé : ce qui précède le `?` — `dashboard` pour `dashboard?date=…`. */
export function ressourceDe(cle: string): string {
  const i = cle.indexOf('?');
  return i === -1 ? cle : cle.slice(0, i);
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
  resumesNotes: (search = '') => cleDeCache('notes/resumes', { search }),
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

/**
 * Les clés de LANCEMENT : celles que Tâches, Projets, Notes et Planificateur
 * lisent au montage, et qui rendent le lancement instantané. Un quota plein
 * ne les évince jamais au profit d'une clé datée (revue du cache, 18 sept.
 * 2026 : `purgerLesAutres` retirait tâches et notes pour loger un tableau
 * de bord du jour, et chaque page remontrait son spinner au lancement).
 */
export const CLES_DE_LANCEMENT: ReadonlySet<string> = new Set([
  clesSucces.taches(),
  clesSucces.notes(),
  clesSucces.resumesNotes(),
  clesSucces.projets(),
]);

/** Le strict nécessaire d'un `Storage`, pour pouvoir le doubler. */
export interface Stockage {
  getItem(cle: string): string | null;
  setItem(cle: string, valeur: string): void;
  removeItem(cle: string): void;
  /** Présents sur un vrai `Storage` ; sans eux, on ne sait ni mesurer ni purger. */
  readonly length?: number;
  key?(index: number): string | null;
}

export interface OptionsEcriture {
  /**
   * Ne pas persister : les listes filtrées par une recherche tapée sont des
   * sous-ensembles que rien ne borne — une clé par frappe finirait par
   * remplir le quota avec des listes que personne ne redemandera.
   */
  memoireSeule?: boolean;
  /**
   * Une seule entrée persistée pour cette RESSOURCE : les autres clés de la
   * même ressource (`dashboard?date=hier`) sont retirées du stockage. Sans
   * cela, tableau de bord, habitudes et aperçu des finances laissaient une
   * entrée par jour que rien ne relisait ni ne retirait — ≈ 15 Ko par jour,
   * quota plein en une centaine de jours, puis purge des clés de lancement
   * (revue du cache, 18 sept. 2026). La mémoire, elle, garde tout : on
   * feuillette les dates sans relire.
   */
  uniqueParRessource?: boolean;
  /**
   * Clés de la même ressource à NE PAS évincer — la clé que le montage relit
   * (le mois courant des finances, l'année du bilan, le jour du tableau de
   * bord). Sans elle, feuilleter « Année » évinçait « Mois » du disque et le
   * prochain lancement repartait du spinner (contre-revue, 18 sept. 2026).
   */
  conserver?: readonly string[];
}

export interface OptionsCache {
  /** Rend le stockage, ou `null` s'il n'existe pas (navigation privée, Node). */
  stockage?: () => Stockage | null;
  /** Diffère un travail hors du rendu — `requestIdleCallback` en production. */
  planifier?: (travail: () => void) => void;
  plafondOctets?: number;
  budgetOctets?: number;
  /** L'empreinte de build — injectée par les tests, `EMPREINTE_BUNDLE` sinon. */
  empreinte?: string;
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

/** Nos entrées du stockage — celles sous `PREFIXE_STOCKAGE`, nom complet. */
function nosEntrees(store: Stockage): string[] {
  const noms: string[] = [];
  if (typeof store.length !== 'number' || typeof store.key !== 'function') return noms;
  for (let i = 0; i < store.length; i += 1) {
    const nom = store.key(i);
    if (nom && nom.startsWith(PREFIXE_STOCKAGE)) noms.push(nom);
  }
  return noms;
}

export interface CacheSucces {
  lireCache<T>(cle: string): T | null;
  ecrireCache(cle: string, valeur: unknown, options?: OptionsEcriture): void;
  /**
   * Transforme ce que le cache tient sous `cle`, s'il tient quelque chose ;
   * rend vrai si une écriture a eu lieu. Pour refléter une ligne ou un
   * retrait dans une entrée qu'on ne recharge pas — la clé principale des
   * tâches pendant qu'une recherche est active — sans jamais y écrire une
   * liste filtrée.
   */
  appliquerAuCache<T>(cle: string, transformer: (valeur: T) => T, options?: OptionsEcriture): boolean;
  oublierCache(cle: string): void;
  /** Écrit tout de suite ce qui attend — pour les tests, et avant de quitter. */
  vider(): void;
}

export function creerCacheSucces(options: OptionsCache = {}): CacheSucces {
  const stockage = options.stockage ?? stockageDuNavigateur;
  const planifier = options.planifier ?? planifierEnCreux;
  const plafond = options.plafondOctets ?? PLAFOND_OCTETS;
  const budget = options.budgetOctets ?? BUDGET_OCTETS;
  const empreinte = options.empreinte ?? EMPREINTE_BUNDLE;
  /** Ce par quoi commence toute enveloppe de CE build — vérifiable sans `JSON.parse`. */
  const debutEnveloppe = JSON.stringify({ v: VERSION_SCHEMA, b: empreinte, d: 0 }).slice(0, -2);

  const memoire = new Map<string, unknown>();
  /** Les clés déjà cherchées dans le stockage : on ne relit pas un disque qui a dit non. */
  const consultees = new Set<string>();
  /** Les clés dont la mémoire attend d'être persistée (ou retirée : `null`). */
  const enAttente = new Map<string, { valeur: unknown | null; uniqueParRessource: boolean; conserver: readonly string[] }>();
  let planifiee = false;
  /**
   * La taille (en unités de code) de chacune de nos entrées persistées, pour
   * comparer au budget sans relire 3,5 Mo à chaque persistance. Remplie au
   * premier besoin, tenue à jour à chaque écriture, et refaite après un
   * quota plein — le stockage a alors bougé sans nous.
   */
  let tailles: Map<string, number> | null = null;

  const mesurer = (store: Stockage): Map<string, number> => {
    if (tailles) return tailles;
    tailles = new Map();
    for (const nom of nosEntrees(store)) {
      try {
        tailles.set(nom, store.getItem(nom)?.length ?? 0);
      } catch {
        // Une entrée illisible ne pèse rien de connu : elle sera retirée à la lecture.
      }
    }
    return tailles;
  };

  const retirer = (store: Stockage, nomComplet: string): void => {
    store.removeItem(nomComplet);
    tailles?.delete(nomComplet);
  };

  /**
   * Les clés datées d'un autre build — ou d'un autre schéma, ou corrompues —
   * qu'aucune page ne relira jamais : `dashboard?date=2026-09-11` n'est
   * redemandé par personne, et la lecture, seule à invalider par empreinte,
   * ne le voit donc jamais (revue du cache, 18 sept. 2026). Élagué une fois,
   * à la naissance du cache.
   */
  const elaguerLesOrphelines = (): void => {
    const store = stockage();
    if (!store) return;
    try {
      for (const nom of nosEntrees(store)) {
        const brut = store.getItem(nom);
        if (brut === null || brut.startsWith(debutEnveloppe)) continue;
        store.removeItem(nom);
      }
    } catch {
      // Un stockage qui refuse de se laisser lire ou nettoyer : la mémoire suffira.
    }
  };

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
        enveloppe.b !== empreinte
      ) {
        // Un ancien schéma, un autre build, ou n'importe quoi : on l'efface
        // pour ne pas le relire à chaque démarrage.
        retirer(store, nomComplet);
        return null;
      }
      return enveloppe.d ?? null;
    } catch {
      try {
        retirer(store, nomComplet);
      } catch {
        // Le stockage refuse même d'effacer : tant pis, la mémoire suffira.
      }
      return null;
    }
  };

  const purgerLesAutres = (store: Stockage, cle: string, saufNomComplet: string): void => {
    // Un VRAI quota plein (le budget a été respecté, donc c'est un autre
    // module qui a grossi, ou un stockage plus petit que prévu) : plutôt que
    // renoncer, on fait de la place en retirant NOS autres entrées — jamais
    // celles d'un autre module, et jamais une clé de lancement pour loger
    // une clé datée : tâches et notes valent plus qu'un tableau de bord
    // d'hier (revue du cache, 18 sept. 2026).
    const ecritUneCleDeLancement = CLES_DE_LANCEMENT.has(cle);
    for (const nom of nosEntrees(store)) {
      if (nom === saufNomComplet) continue;
      if (!ecritUneCleDeLancement && CLES_DE_LANCEMENT.has(nom.slice(PREFIXE_STOCKAGE.length))) continue;
      store.removeItem(nom);
    }
    tailles = null;
  };

  const retirerLesMemesRessources = (
    store: Stockage,
    cle: string,
    saufNomComplet: string,
    conserver: readonly string[],
  ): void => {
    const ressource = ressourceDe(cle);
    const gardees = new Set(conserver.map((c) => PREFIXE_STOCKAGE + c));
    for (const nom of nosEntrees(store)) {
      if (nom === saufNomComplet || gardees.has(nom)) continue;
      if (ressourceDe(nom.slice(PREFIXE_STOCKAGE.length)) === ressource) retirer(store, nom);
    }
  };

  const persister = (): void => {
    planifiee = false;
    const store = stockage();
    const lot = [...enAttente];
    enAttente.clear();
    if (!store) return;
    for (const [cle, { valeur, uniqueParRessource, conserver }] of lot) {
      const nomComplet = PREFIXE_STOCKAGE + cle;
      try {
        if (valeur === null) {
          retirer(store, nomComplet);
          continue;
        }
        const texte = JSON.stringify({ v: VERSION_SCHEMA, b: empreinte, d: valeur } satisfies Enveloppe);
        if (texte.length * OCTETS_PAR_UNITE > plafond) continue;
        if (uniqueParRessource) retirerLesMemesRessources(store, cle, nomComplet, conserver);
        // Le budget global : la somme de nos entrées, celle-ci remplacée.
        // Dépassé, l'entrée reste en mémoire seule — on ne purge pas les
        // autres pour la loger, elles servent au prochain lancement.
        const poids = mesurer(store);
        let total = texte.length;
        for (const [nom, longueur] of poids) if (nom !== nomComplet) total += longueur;
        if (total * OCTETS_PAR_UNITE > budget) continue;
        try {
          store.setItem(nomComplet, texte);
        } catch {
          purgerLesAutres(store, cle, nomComplet);
          store.setItem(nomComplet, texte);
        }
        mesurer(store).set(nomComplet, texte.length);
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

  const ecrireCache = (cle: string, valeur: unknown, options: OptionsEcriture = {}): void => {
    memoire.set(cle, valeur);
    // Une entrée écrite ne se relit plus sur le disque : la mémoire prime.
    consultees.add(cle);
    if (options.memoireSeule) {
      // Une persistance en attente pour cette clé serait plus vieille que
      // la mémoire : on l'annule plutôt que d'écrire du périmé.
      enAttente.delete(cle);
      return;
    }
    enAttente.set(cle, {
      valeur,
      uniqueParRessource: Boolean(options.uniqueParRessource),
      conserver: options.conserver ?? [],
    });
    programmer();
  };

  const lireCache = <T,>(cle: string): T | null => {
    if (memoire.has(cle)) return memoire.get(cle) as T;
    if (consultees.has(cle)) return null;
    consultees.add(cle);
    const valeur = lireStockage(cle);
    if (valeur !== null) memoire.set(cle, valeur);
    return valeur as T | null;
  };

  elaguerLesOrphelines();

  return {
    lireCache,
    ecrireCache,

    appliquerAuCache<T>(cle: string, transformer: (valeur: T) => T, options: OptionsEcriture = {}): boolean {
      const courante = lireCache<T>(cle);
      if (courante === null) return false;
      ecrireCache(cle, transformer(courante), options);
      return true;
    },

    oublierCache(cle: string): void {
      memoire.delete(cle);
      consultees.add(cle);
      enAttente.set(cle, { valeur: null, uniqueParRessource: false, conserver: [] });
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
export const appliquerAuCache: CacheSucces['appliquerAuCache'] = (cle, transformer, options) =>
  cache.appliquerAuCache(cle, transformer, options);
export const oublierCache: CacheSucces['oublierCache'] = (cle) => cache.oublierCache(cle);

// Le crochet `requestIdleCallback` n'arrive pas toujours avant qu'on ferme la
// fenêtre : ce qui attend s'écrit au moment de partir, sinon la dernière
// réponse du serveur est perdue pour le prochain lancement.
if (typeof window !== 'undefined' && typeof window.addEventListener === 'function') {
  window.addEventListener('pagehide', () => cache.vider());
}
