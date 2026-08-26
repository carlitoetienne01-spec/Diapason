/**
 * Un mini-React pour le banc d'essai — et rien d'autre.
 *
 * Ce dépôt teste sous node, avec des doublures maison plutôt que jsdom
 * (voir src/features/succes/useRefreshOnFocus.test.ts, qui le dit et le
 * fait). Or le mode gestes vit ENTIÈREMENT dans des crochets React et deux
 * composants : sans de quoi les exécuter, la moitié qui capture, encode et
 * envoie ne peut être vérifiée par rien.
 *
 * Ce module est donc branché à la place de `react`, `react/jsx-runtime` et
 * `react/jsx-dev-runtime` par `vi.mock`. Il n'implante que ce que
 * frontend/src/features/gestes/ utilise réellement : useState, useRef,
 * useCallback, useMemo, useEffect, et la création d'éléments. Il ne
 * réconcilie rien, ne diffère rien et ne rend aucun DOM — il exécute, et
 * c'est tout ce qu'on lui demande.
 *
 * AUCUN code de production ne l'importe.
 */

export type Props = Record<string, unknown> & { children?: unknown };

export type TypeElement = string | symbol | ((props: Props) => unknown);

export type Element = {
  type: TypeElement;
  props: Props;
  key: string | null;
};

/** Un nœud développé : le composant a été exécuté, ses enfants aussi. */
export type Noeud = {
  type: TypeElement;
  props: Props;
  enfants: Array<Noeud | string>;
};

type Crochet = {
  valeur?: unknown;
  poser?: (v: unknown) => void;
  deps?: unknown[];
  fn?: () => void | (() => void);
  nettoyage?: (() => void) | void;
};

type Instance = { crochets: Crochet[]; i: number };

let instanceCourante: Instance | null = null;
let racineCourante: Racine | null = null;

function memesDeps(avant: unknown[], apres: unknown[]): boolean {
  if (avant.length !== apres.length) return false;
  return avant.every((v, i) => Object.is(v, apres[i]));
}

function exiger(): { inst: Instance; racine: Racine } {
  if (instanceCourante === null || racineCourante === null) {
    throw new Error('Crochet appelé hors d’un rendu du banc.');
  }
  return { inst: instanceCourante, racine: racineCourante };
}

function nettoyerInstance(inst: Instance): void {
  for (const c of inst.crochets) {
    if (typeof c.nettoyage === 'function') c.nettoyage();
    c.nettoyage = undefined;
  }
}

// ---------------------------------------------------------------------------
// La racine : un corps à exécuter, des instances de crochets, une boucle.
// ---------------------------------------------------------------------------

export class Racine {
  resultat: unknown = null;
  private readonly instances = new Map<string, Instance>();
  private readonly utilisees = new Set<string>();
  private effetsEnAttente: Array<{ inst: Instance; i: number }> = [];
  private sale = false;
  private enCours = false;
  private demontee = false;

  constructor(private readonly corps: (racine: Racine) => unknown) {}

  instance(chemin: string): Instance {
    this.utilisees.add(chemin);
    let inst = this.instances.get(chemin);
    if (!inst) {
      inst = { crochets: [], i: 0 };
      this.instances.set(chemin, inst);
    }
    inst.i = 0;
    return inst;
  }

  executer<T>(inst: Instance, fn: () => T): T {
    const avantInstance = instanceCourante;
    const avantRacine = racineCourante;
    instanceCourante = inst;
    racineCourante = this;
    try {
      return fn();
    } finally {
      instanceCourante = avantInstance;
      racineCourante = avantRacine;
    }
  }

  programmerEffet(inst: Instance, i: number): void {
    this.effetsEnAttente.push({ inst, i });
  }

  /** Un état a changé : re-rendre, ou noter qu'il faudra recommencer. */
  salir(): void {
    if (this.demontee) return;
    if (this.enCours) {
      this.sale = true;
      return;
    }
    this.rendre();
  }

  rendre(): void {
    if (this.demontee) return;
    if (this.enCours) {
      this.sale = true;
      return;
    }
    this.enCours = true;
    try {
      let tours = 0;
      do {
        this.sale = false;
        this.utilisees.clear();
        this.effetsEnAttente = [];
        this.resultat = this.corps(this);
        for (const [chemin, inst] of [...this.instances]) {
          if (this.utilisees.has(chemin)) continue;
          nettoyerInstance(inst);
          this.instances.delete(chemin);
        }
        const aLancer = this.effetsEnAttente;
        this.effetsEnAttente = [];
        for (const { inst, i } of aLancer) {
          const c = inst.crochets[i];
          if (!c) continue;
          if (typeof c.nettoyage === 'function') c.nettoyage();
          c.nettoyage = c.fn ? c.fn() : undefined;
        }
        tours += 1;
        if (tours > 50) {
          throw new Error('Le banc tourne en rond : plus de cinquante rendus.');
        }
      } while (this.sale);
    } finally {
      this.enCours = false;
    }
  }

  demonter(): void {
    if (this.demontee) return;
    this.demontee = true;
    for (const inst of this.instances.values()) nettoyerInstance(inst);
    this.instances.clear();
  }
}

// ---------------------------------------------------------------------------
// Les crochets
// ---------------------------------------------------------------------------

export function useState<T>(
  initial: T | (() => T),
): [T, (v: T | ((precedent: T) => T)) => void] {
  const { inst, racine } = exiger();
  const i = inst.i++;
  let c = inst.crochets[i];
  if (!c) {
    const cree: Crochet = {
      valeur:
        typeof initial === 'function' ? (initial as () => T)() : initial,
    };
    cree.poser = (v: unknown) => {
      const prochaine =
        typeof v === 'function'
          ? (v as (p: unknown) => unknown)(cree.valeur)
          : v;
      if (Object.is(prochaine, cree.valeur)) return;
      cree.valeur = prochaine;
      racine.salir();
    };
    inst.crochets[i] = cree;
    c = cree;
  }
  return [
    c.valeur as T,
    c.poser as (v: T | ((precedent: T) => T)) => void,
  ];
}

export function useRef<T>(initial: T): { current: T } {
  const { inst } = exiger();
  const i = inst.i++;
  let c = inst.crochets[i];
  if (!c) {
    c = { valeur: { current: initial } };
    inst.crochets[i] = c;
  }
  return c.valeur as { current: T };
}

export function useMemo<T>(fabrique: () => T, deps?: unknown[]): T {
  const { inst } = exiger();
  const i = inst.i++;
  const c = inst.crochets[i];
  if (c && deps && c.deps && memesDeps(c.deps, deps)) return c.valeur as T;
  const valeur = fabrique();
  inst.crochets[i] = { valeur, deps };
  return valeur;
}

export function useCallback<T>(fn: T, deps?: unknown[]): T {
  return useMemo(() => fn, deps);
}

export function useEffect(
  fn: () => void | (() => void),
  deps?: unknown[],
): void {
  const { inst, racine } = exiger();
  const i = inst.i++;
  const c = inst.crochets[i];
  const relancer = !c || !deps || !c.deps || !memesDeps(c.deps, deps);
  inst.crochets[i] = { deps, fn, nettoyage: c?.nettoyage };
  if (relancer) racine.programmerEffet(inst, i);
}

export const useLayoutEffect = useEffect;

// ---------------------------------------------------------------------------
// Les éléments (jsx-runtime)
// ---------------------------------------------------------------------------

export const Fragment: unique symbol = Symbol.for('banc.fragment');

export function jsx(
  type: TypeElement,
  props?: Props,
  key?: string | number | null,
): Element {
  return {
    type,
    props: props ?? {},
    key: key === undefined || key === null ? null : String(key),
  };
}

export const jsxs = jsx;
export const jsxDEV = (
  type: TypeElement,
  props?: Props,
  key?: string | number | null,
): Element => jsx(type, props, key);

export const createElement = (
  type: TypeElement,
  props?: Props,
  ...enfants: unknown[]
): Element =>
  jsx(type, { ...(props ?? {}), ...(enfants.length ? { children: enfants.length === 1 ? enfants[0] : enfants } : {}) });

// ---------------------------------------------------------------------------
// Le développement de l'arbre
// ---------------------------------------------------------------------------

function nomDe(type: TypeElement): string {
  if (typeof type === 'string') return type;
  if (typeof type === 'symbol') return 'fragment';
  return type.name || 'anonyme';
}

function developper(
  valeur: unknown,
  chemin: string,
  racine: Racine,
): Array<Noeud | string> {
  if (valeur === null || valeur === undefined || typeof valeur === 'boolean') {
    return [];
  }
  if (typeof valeur === 'string') return valeur ? [valeur] : [];
  if (typeof valeur === 'number') return [String(valeur)];
  if (Array.isArray(valeur)) {
    return valeur.flatMap((v, i) => developper(v, `${chemin}[${i}]`, racine));
  }
  const el = valeur as Element;
  if (typeof el !== 'object' || !('type' in el)) return [];
  const marque = `${chemin}/${nomDe(el.type)}${el.key === null ? '' : `#${el.key}`}`;
  if (typeof el.type === 'function') {
    const inst = racine.instance(marque);
    const composant = el.type;
    const sortie = racine.executer(inst, () => composant(el.props));
    return [
      { type: el.type, props: el.props, enfants: developper(sortie, marque, racine) },
    ];
  }
  const enfants = developper(el.props.children, marque, racine);
  if (el.type === Fragment) return enfants;
  return [{ type: el.type, props: el.props, enfants }];
}

// ---------------------------------------------------------------------------
// Ce que les tests appellent
// ---------------------------------------------------------------------------

export type Monture<T> = {
  valeur: () => T;
  demonter: () => void;
};

/** Monter un crochet seul, comme le ferait un composant qui ne rend rien. */
export function monterCrochet<T>(crochet: () => T): Monture<T> {
  const racine = new Racine((r) => r.executer(r.instance('crochet'), crochet));
  racine.rendre();
  return {
    valeur: () => racine.resultat as T,
    demonter: () => racine.demonter(),
  };
}

export type MontureArbre = {
  arbre: () => Array<Noeud | string>;
  rendre: () => void;
  demonter: () => void;
};

export function monterComposant(element: Element): MontureArbre {
  const racine = new Racine((r) => developper(element, '', r));
  racine.rendre();
  return {
    arbre: () => racine.resultat as Array<Noeud | string>,
    rendre: () => racine.rendre(),
    demonter: () => racine.demonter(),
  };
}

export function creer(
  type: TypeElement,
  props: Props = {},
): Element {
  return jsx(type, props);
}

function parcourir(
  noeuds: Array<Noeud | string>,
  visiter: (n: Noeud) => void,
): void {
  for (const n of noeuds) {
    if (typeof n === 'string') continue;
    visiter(n);
    parcourir(n.enfants, visiter);
  }
}

/** Tous les nœuds hôtes d'un type donné : 'button', 'input', … */
export function elements(
  noeuds: Array<Noeud | string>,
  type: string,
): Noeud[] {
  const trouves: Noeud[] = [];
  parcourir(noeuds, (n) => {
    if (n.type === type) trouves.push(n);
  });
  return trouves;
}

/** Le texte rendu, espaces insécables ramenés à des espaces ordinaires. */
export function texte(n: Noeud | string | Array<Noeud | string>): string {
  const morceaux: string[] = [];
  const collecter = (v: Noeud | string): void => {
    if (typeof v === 'string') {
      morceaux.push(v);
      return;
    }
    for (const e of v.enfants) collecter(e);
  };
  if (Array.isArray(n)) n.forEach(collecter);
  else collecter(n);
  // \s couvre l'espace insecable : « Depots&nbsp;: » se lit « Depots : ».
  return morceaux.join('').replace(/\s+/g, ' ').trim();
}

/** Cliquer : appeler onClick comme le navigateur le ferait. */
export function cliquer(n: Noeud): void {
  const onClick = n.props.onClick;
  if (typeof onClick !== 'function') {
    throw new Error(`Ce <${String(n.type)}> n’a pas de onClick.`);
  }
  (onClick as (e: unknown) => void)({});
}
