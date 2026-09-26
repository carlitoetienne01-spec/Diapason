// Le relevé honnête de la fluidité, au téléphone : combien de temps entre
// le geste qui change de page et le CONTENU à l'écran.
//
// 26/09/2026, chantier de la fluidité (lot 2). Carlito trouvait la
// navigation « tellement lente » ; les chiffres du banc (4G simulée sur ce
// Mac) ne sont pas ceux de son Nothing Phone. Ce relevé tourne dans la
// WebView même, et Réglages → « Mesures de fluidité » en montre la médiane
// et le 90e centile par page — des chiffres qu'il lit lui-même, sans
// instrument ni ordinateur.
//
// Ce qui est mesuré, et ce qui ne l'est pas :
// - le DÉBUT est le premier rendu de la nouvelle adresse (quelques
//   millisecondes après le toucher), ou l'origine du document pour
//   l'ouverture de l'app ;
// - la FIN est la première image où la page est MONTÉE (son morceau JS est
//   là, son `Suspense` est levé) et où aucun `[data-chargement]` n'est dans
//   le document : les données sont à l'écran, venues du cache ou du Mac ;
// - la relecture derrière un cache n'est PAS attendue : ce qui s'affiche
//   déjà vient du serveur, à sa lecture précédente (cacheVie.ts, §100) ;
// - une page quittée avant son contenu, ou un écran éteint pendant
//   l'attente, ne donne AUCUN chiffre — une durée qui contient une mise en
//   veille ne mesure rien ;
// - au-delà de `PLAFOND_MS`, le chiffre est gardé AU PLAFOND et marqué :
//   une page qui n'arrive jamais doit peser dans le relevé, pas en sortir.
//
// Le cœur est pur (horloge, image, contenu et stockage injectés) : vitest le
// vérifie sans navigateur.

/** Ouverture de l'app, première visite d'une page dans la session, ou retour. */
export type GenreVisite = 'ouverture' | 'premiere' | 'revisite';

export interface Echantillon {
  route: string;
  genre: GenreVisite;
  ms: number;
  /** L'instant du relevé (Date.now) : pour dater, pas pour calculer. */
  quand: number;
  /** Vrai si le contenu n'était toujours pas là au plafond. */
  plafond?: boolean;
}

/** Au-delà, on arrête d'attendre : 15 s couvrent un morceau lent en 4G faible. */
export const PLAFOND_MS = 15_000;

/**
 * Les 30 derniers relevés par page et par genre : de quoi un 90e centile
 * qui a un sens (le 27e sur 30), sans grossir — 16 pages × 3 genres × 30
 * relevés × ~90 octets ≈ 130 Ko au pire, loin du quota de l'origine.
 */
export const PAR_SERIE_MAX = 30;

export const CLE_STOCKAGE = 'diapason-mesures-navigation';

/** Le 90e centile « au rang le plus proche » : une valeur réellement mesurée, jamais interpolée. */
export function centile(valeurs: readonly number[], p: number): number | null {
  if (!valeurs.length) return null;
  const tri = [...valeurs].sort((a, b) => a - b);
  const rang = Math.max(1, Math.ceil((p / 100) * tri.length));
  return tri[Math.min(rang, tri.length) - 1];
}

/** La médiane ; pour un nombre pair de relevés, la moyenne des deux du milieu. */
export function mediane(valeurs: readonly number[]): number | null {
  if (!valeurs.length) return null;
  const tri = [...valeurs].sort((a, b) => a - b);
  const milieu = Math.floor(tri.length / 2);
  return tri.length % 2 ? tri[milieu] : (tri[milieu - 1] + tri[milieu]) / 2;
}

/** `/vie/tasks/` et `/vie/tasks` sont la même page ; la requête et l'ancre n'en font pas une autre. */
export function routeDe(chemin: string): string {
  const sansRequete = chemin.split(/[?#]/)[0] || '/';
  return sansRequete.length > 1 ? sansRequete.replace(/\/+$/, '') || '/' : sansRequete;
}

export interface LigneResume {
  route: string;
  genre: GenreVisite;
  n: number;
  medianeMs: number;
  p90Ms: number;
  dernierMs: number;
  /** Combien de relevés ont atteint le plafond sans contenu. */
  auPlafond: number;
}

const ORDRE_GENRES: GenreVisite[] = ['ouverture', 'premiere', 'revisite'];

/** Une ligne par page et par genre, triées par page puis par genre. */
export function resumer(echantillons: readonly Echantillon[]): LigneResume[] {
  const series = new Map<string, Echantillon[]>();
  for (const e of echantillons) {
    const cle = `${e.route}\0${e.genre}`;
    const serie = series.get(cle);
    if (serie) serie.push(e);
    else series.set(cle, [e]);
  }
  const lignes: LigneResume[] = [];
  for (const serie of series.values()) {
    const ms = serie.map((e) => e.ms);
    lignes.push({
      route: serie[0].route,
      genre: serie[0].genre,
      n: serie.length,
      medianeMs: Math.round(mediane(ms) ?? 0),
      p90Ms: Math.round(centile(ms, 90) ?? 0),
      dernierMs: Math.round(serie[serie.length - 1].ms),
      auPlafond: serie.filter((e) => e.plafond).length,
    });
  }
  return lignes.sort((a, b) =>
    a.route === b.route ? ORDRE_GENRES.indexOf(a.genre) - ORDRE_GENRES.indexOf(b.genre) : a.route.localeCompare(b.route),
  );
}

/** Le strict nécessaire d'un `Storage`, pour pouvoir le doubler. */
export interface StockageMesures {
  getItem(cle: string): string | null;
  setItem(cle: string, valeur: string): void;
  removeItem(cle: string): void;
}

export interface DependancesReleve {
  /** L'horloge des images — `performance.now()`, la même base que `requestAnimationFrame`. */
  maintenant: () => number;
  /** L'instant civil, pour dater un relevé. */
  horodatage: () => number;
  /** Appelle `rappel` à la prochaine image avec son horodatage (`requestAnimationFrame`). */
  image: (rappel: (t: number) => void) => void;
  /** Vrai quand la page montée n'affiche plus aucun `[data-chargement]`. */
  contenuPret: () => boolean;
  /** Vrai si l'écran est affiché. */
  visible: () => boolean;
  stockage: () => StockageMesures | null;
}

function lireStockage(stockage: StockageMesures | null): Echantillon[] {
  if (!stockage) return [];
  try {
    const brut = stockage.getItem(CLE_STOCKAGE);
    if (!brut) return [];
    const lu = JSON.parse(brut) as unknown;
    if (!Array.isArray(lu)) return [];
    return lu.filter(
      (e): e is Echantillon =>
        !!e &&
        typeof e === 'object' &&
        typeof (e as Echantillon).route === 'string' &&
        ORDRE_GENRES.includes((e as Echantillon).genre) &&
        typeof (e as Echantillon).ms === 'number' &&
        Number.isFinite((e as Echantillon).ms),
    );
  } catch {
    // Un relevé corrompu vaut « pas de relevé », jamais un écran blanc.
    return [];
  }
}

/** Garde les `PAR_SERIE_MAX` derniers de chaque série, dans l'ordre d'arrivée. */
export function borner(echantillons: readonly Echantillon[], parSerie = PAR_SERIE_MAX): Echantillon[] {
  const comptes = new Map<string, number>();
  const gardes: Echantillon[] = [];
  for (let i = echantillons.length - 1; i >= 0; i -= 1) {
    const e = echantillons[i];
    const cle = `${e.route}\0${e.genre}`;
    const n = comptes.get(cle) ?? 0;
    if (n >= parSerie) continue;
    comptes.set(cle, n + 1);
    gardes.push(e);
  }
  return gardes.reverse();
}

interface Navigation {
  cle: string;
  route: string;
  genre: GenreVisite;
  t0: number;
  montee: boolean;
  finie: boolean;
}

export class ReleveNavigation {
  private courante: Navigation | null = null;
  private readonly visitees = new Set<string>();
  private derniereRoute: string | null = null;
  private memoire: Echantillon[] | null = null;

  constructor(private readonly deps: DependancesReleve) {}

  /**
   * Une nouvelle adresse est rendue. Idempotent par `cle` (le double rendu
   * de StrictMode, un rendu de transition rejoué) ; la première navigation
   * de la session est l'ouverture de l'app, et `t0` vaut alors 0 — l'origine
   * du document. Un changement de requête sur la même page n'est pas une
   * navigation.
   */
  debut(cle: string, chemin: string, t0 = this.deps.maintenant()): void {
    if (this.courante?.cle === cle) return;
    const route = routeDe(chemin);
    if (this.derniereRoute === route) return;
    const genre: GenreVisite =
      this.derniereRoute === null ? 'ouverture' : this.visitees.has(route) ? 'revisite' : 'premiere';
    if (this.courante && !this.courante.finie) this.courante.finie = true;
    this.derniereRoute = route;
    this.visitees.add(route);
    this.courante = { cle, route, genre, t0: genre === 'ouverture' ? 0 : t0, montee: false, finie: false };
  }

  /** La page de cette adresse est montée : on guette la première image où son contenu est là. */
  montee(cle: string): void {
    const nav = this.courante;
    if (!nav || nav.cle !== cle || nav.montee || nav.finie) return;
    nav.montee = true;
    const guetter = (t: number) => {
      if (nav.finie || this.courante !== nav) return;
      // Une durée qui contient une mise en veille ne mesure rien.
      if (!this.deps.visible()) {
        nav.finie = true;
        return;
      }
      const ecoule = t - nav.t0;
      if (this.deps.contenuPret()) {
        this.enregistrer(nav, ecoule, false);
        return;
      }
      if (ecoule >= PLAFOND_MS) {
        this.enregistrer(nav, PLAFOND_MS, true);
        return;
      }
      this.deps.image(guetter);
    };
    this.deps.image(guetter);
  }

  private enregistrer(nav: Navigation, ms: number, plafond: boolean): void {
    nav.finie = true;
    const e: Echantillon = { route: nav.route, genre: nav.genre, ms: Math.max(0, Math.round(ms)), quand: this.deps.horodatage() };
    if (plafond) e.plafond = true;
    const tous = borner([...this.echantillons(), e]);
    this.memoire = tous;
    const stockage = this.deps.stockage();
    try {
      stockage?.setItem(CLE_STOCKAGE, JSON.stringify(tous));
    } catch {
      // Quota plein : le relevé reste en mémoire pour cette session.
    }
  }

  /** Les relevés gardés, du plus ancien au plus récent. */
  echantillons(): Echantillon[] {
    if (!this.memoire) this.memoire = lireStockage(this.deps.stockage());
    return [...this.memoire];
  }

  effacer(): void {
    this.memoire = [];
    try {
      this.deps.stockage()?.removeItem(CLE_STOCKAGE);
    } catch {
      // Rien à faire : la mémoire est vide, c'est ce qu'on affiche.
    }
  }
}

function stockageDuNavigateur(): StockageMesures | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage;
  } catch {
    return null;
  }
}

/** Le relevé de CETTE WebView. Il n'observe que si on l'appelle (App.tsx, sous `estMobile`). */
export const releveNavigation = new ReleveNavigation({
  maintenant: () => performance.now(),
  horodatage: () => Date.now(),
  image: (rappel) => requestAnimationFrame(rappel),
  contenuPret: () => typeof document !== 'undefined' && !document.querySelector('[data-chargement]'),
  visible: () => typeof document === 'undefined' || document.visibilityState !== 'hidden',
  stockage: stockageDuNavigateur,
});
