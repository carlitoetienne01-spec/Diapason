// Les synapses — la planification des rafales lumineuses de l'arbre.
//
// Demandé le 23 août 2026 : « des fines lumières qui passent dans les
// branches, comme un cerveau où les neurones envoient de l'information ».
// Choix arrêtés : comète fine couleur accent, rythme en rafales (une pensée
// se propage de proche en proche), halo bref sur la carte atteinte.
//
// Ce module ne touche pas au DOM : il PLANIFIE. Une rafale est une liste
// d'impulsions datées, chacune parcourant une arête dans un sens, et le
// composant n'a plus qu'à les jouer. Le hasard s'injecte, pour les tests.

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
  departMs: number;
  dureeMs: number;
  /** Le nœud atteint — celui dont la carte recevra le halo. */
  arriveeId: string;
}

/** Longueur approchée de la courbe en S — l'hypoténuse suffit largement. */
export function longueurApprochee(a: Pick<AreteSynapse, 'x1' | 'y1' | 'x2' | 'y2'>): number {
  return Math.hypot(a.x2 - a.x1, a.y2 - a.y1) * 1.1;
}

/** Durée de voyage : vitesse constante, bornée pour rester lisible. */
export function dureeImpulsion(longueur: number): number {
  return Math.min(1300, Math.max(500, Math.round(longueur * 2.4)));
}

const IMPULSIONS_MAX = 5;
const PROFONDEUR_MAX = 3;
const EMBRANCHEMENTS_MAX = 2;
const RELAIS_MS = 90; // le souffle entre l'arrivée et la repropagation

/**
 * Une pensée se propage : une arête s'allume au hasard, puis l'information
 * repart du nœud atteint vers 1-2 arêtes voisines, et ainsi de suite.
 * Jamais de demi-tour immédiat, jamais deux passages sur la même arête.
 */
export function planifierRafale(
  aretes: AreteSynapse[],
  rng: () => number = Math.random,
): Impulsion[] {
  if (aretes.length === 0) return [];
  const parEnfant = new Map(aretes.map((a) => [a.id, a]));
  const parParent = new Map<string, AreteSynapse[]>();
  for (const a of aretes) {
    const liste = parParent.get(a.parentId) ?? [];
    liste.push(a);
    parParent.set(a.parentId, liste);
  }

  const graine = aretes[Math.floor(rng() * aretes.length)];
  const descend = rng() < 0.7; // l'information descend le plus souvent
  const utilisees = new Set<string>([graine.id]);
  const impulsions: Impulsion[] = [];

  const premiere: Impulsion = {
    areteId: graine.id,
    descend,
    departMs: 0,
    dureeMs: dureeImpulsion(longueurApprochee(graine)),
    arriveeId: descend ? graine.id : graine.parentId,
  };
  impulsions.push(premiere);

  let front = [premiere];
  for (let etage = 1; etage < PROFONDEUR_MAX && impulsions.length < IMPULSIONS_MAX; etage += 1) {
    const prochain: Impulsion[] = [];
    for (const venue of front) {
      const noeud = venue.arriveeId;
      const voisines: Array<{ arete: AreteSynapse; descend: boolean }> = [];
      for (const a of parParent.get(noeud) ?? []) {
        if (!utilisees.has(a.id)) voisines.push({ arete: a, descend: true });
      }
      const versParent = parEnfant.get(noeud);
      if (versParent && !utilisees.has(versParent.id)) {
        voisines.push({ arete: versParent, descend: false });
      }
      // mélange de Fisher-Yates sur ce petit tableau
      for (let i = voisines.length - 1; i > 0; i -= 1) {
        const j = Math.floor(rng() * (i + 1));
        [voisines[i], voisines[j]] = [voisines[j], voisines[i]];
      }
      const combien = Math.min(
        voisines.length,
        1 + Math.floor(rng() * EMBRANCHEMENTS_MAX),
        IMPULSIONS_MAX - impulsions.length,
      );
      for (const { arete, descend: sens } of voisines.slice(0, combien)) {
        utilisees.add(arete.id);
        const impulsion: Impulsion = {
          areteId: arete.id,
          descend: sens,
          departMs: venue.departMs + venue.dureeMs + RELAIS_MS,
          dureeMs: dureeImpulsion(longueurApprochee(arete)),
          arriveeId: sens ? arete.id : arete.parentId,
        };
        impulsions.push(impulsion);
        prochain.push(impulsion);
        if (impulsions.length >= IMPULSIONS_MAX) break;
      }
      if (impulsions.length >= IMPULSIONS_MAX) break;
    }
    if (prochain.length === 0) break;
    front = prochain;
  }
  return impulsions;
}
