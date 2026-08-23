// Les synapses — le tirage des impulsions lumineuses de l'arbre.
//
// Demandé le 23 août 2026, réglé le même soir après un premier essai jugé
// trop nerveux : « ça va trop rapide, je veux des lumières un peu partout
// et aléatoirement ». Le modèle n'est donc plus la rafale occasionnelle
// mais un FLUX : à tout moment, plusieurs impulsions indépendantes
// voyagent quelque part dans l'arbre, lentes et somptueuses, et l'une
// d'elles peut se relayer vers une branche voisine à l'arrivée.
//
// Ce module ne touche pas au DOM : il TIRE. Le hasard s'injecte, pour les
// tests ; le composant joue les impulsions et tient l'horloge.

export interface AreteSynapse {
  /** id du nœud ENFANT — c'est ainsi que la vue identifie ses arêtes. */
  id: string;
  parentId: string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

export interface Impulsion {
  areteId: string;
  /** true : du parent vers l'enfant ; false : l'information remonte. */
  descend: boolean;
  dureeMs: number;
  /** Le nœud atteint — celui qui peut recevoir le halo, ou relayer. */
  arriveeId: string;
}

/** Longueur approchée de la courbe en S — l'hypoténuse suffit largement. */
export function longueurApprochee(a: Pick<AreteSynapse, 'x1' | 'y1' | 'x2' | 'y2'>): number {
  return Math.hypot(a.x2 - a.x1, a.y2 - a.y1) * 1.1;
}

/** Durée de voyage : lente et contemplative, bornée pour rester vivante. */
export function dureeImpulsion(longueur: number): number {
  return Math.min(3600, Math.max(1600, Math.round(longueur * 6)));
}

/** Combien de lumières en même temps — grandit avec l'arbre, sans orage. */
export function plafondImpulsions(nbAretes: number): number {
  return Math.max(3, Math.min(9, Math.ceil(nbAretes / 3)));
}

function fabriquer(arete: AreteSynapse, descend: boolean): Impulsion {
  return {
    areteId: arete.id,
    descend,
    dureeMs: dureeImpulsion(longueurApprochee(arete)),
    arriveeId: descend ? arete.id : arete.parentId,
  };
}

/**
 * Une impulsion quelque part : arête libre au hasard, descente le plus
 * souvent. Rend null quand tout est déjà allumé.
 */
export function impulsionAleatoire(
  aretes: AreteSynapse[],
  occupees: ReadonlySet<string>,
  rng: () => number = Math.random,
): Impulsion | null {
  const libres = aretes.filter((a) => !occupees.has(a.id));
  if (libres.length === 0) return null;
  const arete = libres[Math.floor(rng() * libres.length)];
  return fabriquer(arete, rng() < 0.7);
}

/**
 * Le relais : depuis un nœud atteint, l'information repart vers une arête
 * voisine libre — enfant ou parent, jamais celle d'où elle vient (elle est
 * encore occupée). Rend null quand le nœud est un cul-de-sac.
 */
export function relaisDepuis(
  noeudId: string,
  aretes: AreteSynapse[],
  occupees: ReadonlySet<string>,
  rng: () => number = Math.random,
): Impulsion | null {
  const voisines: Array<{ arete: AreteSynapse; descend: boolean }> = [];
  for (const a of aretes) {
    if (occupees.has(a.id)) continue;
    if (a.parentId === noeudId) voisines.push({ arete: a, descend: true });
    else if (a.id === noeudId) voisines.push({ arete: a, descend: false });
  }
  if (voisines.length === 0) return null;
  const { arete, descend } = voisines[Math.floor(rng() * voisines.length)];
  return fabriquer(arete, descend);
}
