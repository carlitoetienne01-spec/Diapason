// Le préchargement des pages, au téléphone, pendant les creux.
//
// 26/09/2026, chantier de la fluidité (lot 2). Chaque page est un morceau
// JS chargé à la PREMIÈRE visite : au banc (4G simulée, 110 ms d'aller-
// retour, processeur ×4), la première visite des Tâches attendait 400 ms
// que ses 12 morceaux arrivent avant même de demander ses données — le
// contenu s'affichait à 644 ms, dont les deux tiers passés à charger du
// code. Le Mac, lui, lit ses morceaux sur le disque : rien à gagner, et le
// bureau ne change pas (le préchargement n'est lancé que sous `estMobile`).
//
// Deux pièces, pures pour être vérifiées sous vitest :
// - `memoiserChargeur` : UN import par page, partagé entre le préchargement
//   et `React.lazy` — et le module, une fois là, lisible sans attendre ;
// - `planifierPrechargement` : les morceaux un à un, chacun dans un creux
//   du fil principal, jamais pendant que l'écran est caché, et plus du tout
//   après un échec ou si le système demande d'économiser les données.

export type Chargeur<M> = () => Promise<M>;

export interface ChargeurMemoise<M> {
  /** Le même `Promise` à chaque appel, tant qu'il n'a pas échoué. */
  charger: () => Promise<M>;
  /** Le module s'il est déjà arrivé, sinon `null` — sans rien lancer. */
  module: () => M | null;
}

/**
 * Un import mémoïsé. Un échec est OUBLIÉ : le prochain appel relance
 * l'import plutôt que de rendre pour toujours le rejet d'une coupure 4G
 * passagère (ce que le navigateur en fait ensuite ne dépend plus de nous).
 */
export function memoiserChargeur<M>(chargeur: Chargeur<M>): ChargeurMemoise<M> {
  let enCours: Promise<M> | null = null;
  let arrive: { module: M } | null = null;
  return {
    charger: () => {
      if (!enCours) {
        const courant = chargeur().then(
          (module) => {
            arrive = { module };
            return module;
          },
          (erreur: unknown) => {
            if (enCours === courant) enCours = null;
            throw erreur;
          },
        );
        enCours = courant;
      }
      return enCours;
    },
    module: () => (arrive ? arrive.module : null),
  };
}

export interface OptionsPrechargement {
  /** Rend la main jusqu'au prochain creux — `requestIdleCallback` au téléphone. */
  enCreux: (travail: () => void) => void;
  /** Vrai si l'écran est affiché : caché, on n'occupe ni la radio ni le processeur. */
  visible: () => boolean;
  /** Réessaie plus tard quand l'écran est caché (minuteur). */
  plusTard: (travail: () => void) => void;
  /** Vrai si Android demande d'économiser les données (`navigator.connection.saveData`). */
  economieDeDonnees: () => boolean;
}

export interface BilanPrechargement {
  charges: number;
  /** Vrai si le préchargement s'est arrêté avant la fin (échec, annulation, économie). */
  interrompu: boolean;
}

/**
 * Précharge les pages dans l'ordre donné — les onglets d'abord —, une à la
 * fois : en parallèle, elles se disputeraient le lien avec les lectures
 * `/v1` de la page que l'on regarde. Rend de quoi l'annuler et son bilan.
 */
export function planifierPrechargement(
  chargeurs: readonly (() => Promise<unknown>)[],
  options: OptionsPrechargement,
): { annuler: () => void; fini: Promise<BilanPrechargement> } {
  let annule = false;
  let charges = 0;
  const fini = new Promise<BilanPrechargement>((resoudre) => {
    const terminer = (interrompu: boolean) => resoudre({ charges, interrompu });
    const suivant = (i: number) => {
      if (annule) return terminer(true);
      if (i >= chargeurs.length) return terminer(false);
      options.enCreux(() => {
        if (annule) return terminer(true);
        if (options.economieDeDonnees()) return terminer(true);
        if (!options.visible()) {
          options.plusTard(() => suivant(i));
          return;
        }
        chargeurs[i]().then(
          () => {
            charges += 1;
            suivant(i + 1);
          },
          // Un morceau qui ne vient pas : le réseau est tombé ou le Mac a
          // changé de build. Insister ne ferait qu'user la radio — la page
          // se chargera à sa visite, comme avant.
          () => terminer(true),
        );
      });
    };
    suivant(0);
  });
  return {
    annuler: () => {
      annule = true;
    },
    fini,
  };
}

/**
 * Après une navigation, le préchargement se tait tant que la page n'a pas
 * fini ses propres lectures. 26/09/2026, contre-épreuve : touchées dès que
 * la Discussion paraît (4G simulée, ×4), les Tâches partageaient le lien
 * avec 40 morceaux d'autres pages — 404 Ko et 57 requêtes, page stable à
 * 2 628-2 709 ms au lieu de ~800. Leurs lectures /v1 finissent vers 600 ms
 * après le toucher en 4G ; 1 500 ms laissent la marge d'une page lente
 * (Finances, deux lectures en cascade) sans repousser le préchargement
 * au-delà du moment où l'on regarde encore la page.
 */
export const REPRISE_APRES_NAVIGATION_MS = 1500;

/**
 * Après l'événement `load`, le temps que les lectures `/v1` du démarrage
 * finissent : au banc, les neuf partent avec la Discussion et se terminent
 * 280 ms après elle (1 461 → 1 735 ms, 4G simulée). Précharger avant, c'est
 * leur voler le lien.
 */
export const DEPART_APRES_LOAD_MS = 500;

export interface OptionsPilote extends OptionsPrechargement {
  /** Programme `travail` dans `ms` ; rend de quoi l'annuler. */
  minuteur: (travail: () => void, ms: number) => () => void;
  /** L'horloge, en millisecondes. */
  maintenant: () => number;
}

/**
 * Le préchargement tel que l'app le mène : il part `departMs` après
 * `demarrer()` (l'événement `load`), se met en pause à chaque navigation et
 * ne reprend que `repriseMs` après la DERNIÈRE — là où il s'était arrêté, les
 * pages déjà arrivées se résolvant sans requête. Un morceau déjà en vol finit
 * son transfert (un `import()` ne s'annule pas) ; aucun autre ne part.
 */
export function piloterPrechargement(
  chargeurs: readonly (() => Promise<unknown>)[],
  options: OptionsPilote,
  delais: { departMs?: number; repriseMs?: number } = {},
): { demarrer: () => void; navigation: () => void; arreter: () => void } {
  const departMs = delais.departMs ?? DEPART_APRES_LOAD_MS;
  const repriseMs = delais.repriseMs ?? REPRISE_APRES_NAVIGATION_MS;
  let pretDepuis: number | null = null;
  let derniereNavigation = -Infinity;
  let courant: { annuler: () => void } | null = null;
  let annulerMinuteur: (() => void) | null = null;
  let termine = false;
  let arrete = false;
  // Les pages arrivées ne repartent pas à la reprise : la liste reprend là
  // où la pause l'a laissée.
  const arrivees = new Set<number>();
  const suivis = chargeurs.map((charger, i) => () =>
    charger().then((module) => {
      arrivees.add(i);
      return module;
    }),
  );

  const lancer = () => {
    annulerMinuteur = null;
    if (arrete || termine) return;
    const plan = planifierPrechargement(
      suivis.filter((_, i) => !arrivees.has(i)),
      options,
    );
    courant = plan;
    void plan.fini.then(() => {
      // Remplacé par une pause : ce n'est pas la fin.
      if (courant !== plan) return;
      courant = null;
      // Au bout de la liste, ou arrêté par un échec ou l'économie de
      // données : on ne relance plus.
      termine = true;
    });
  };

  const reprogrammer = () => {
    if (pretDepuis === null || arrete || termine) return;
    annulerMinuteur?.();
    const echeance = Math.max(pretDepuis + departMs, derniereNavigation + repriseMs);
    annulerMinuteur = options.minuteur(lancer, Math.max(0, echeance - options.maintenant()));
  };

  return {
    demarrer: () => {
      if (pretDepuis !== null) return;
      pretDepuis = options.maintenant();
      reprogrammer();
    },
    navigation: () => {
      derniereNavigation = options.maintenant();
      if (courant) {
        courant.annuler();
        courant = null;
      }
      reprogrammer();
    },
    arreter: () => {
      arrete = true;
      courant?.annuler();
      annulerMinuteur?.();
    },
  };
}

/** Les vraies dépendances du navigateur, pour `planifierPrechargement`. */
export function optionsDuNavigateur(): OptionsPilote {
  const ric = (globalThis as { requestIdleCallback?: (cb: () => void, o?: { timeout: number }) => void })
    .requestIdleCallback;
  return {
    // 2 s au plus : un fil principal jamais au repos (une animation) ne
    // doit pas repousser le préchargement indéfiniment.
    enCreux: (travail) => (typeof ric === 'function' ? ric(travail, { timeout: 2000 }) : setTimeout(travail, 200)),
    visible: () => typeof document === 'undefined' || document.visibilityState !== 'hidden',
    plusTard: (travail) => setTimeout(travail, 2000),
    minuteur: (travail, ms) => {
      const id = setTimeout(travail, ms);
      return () => clearTimeout(id);
    },
    maintenant: () => performance.now(),
    economieDeDonnees: () => {
      try {
        const connexion = (navigator as { connection?: { saveData?: boolean } }).connection;
        return Boolean(connexion?.saveData);
      } catch {
        return false;
      }
    },
  };
}
