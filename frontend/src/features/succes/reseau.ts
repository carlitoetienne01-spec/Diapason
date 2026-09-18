// Le raisonnement du réseau — niveaux, statuts, voisinage, impact, boucle,
// chaîne la plus longue, ordre des colonnes. Pur : (tâches, arêtes) en
// entrée, jamais le DOM.
//
// Chantier réseau du 18 septembre 2026. Jusque-là tout vivait dans
// NetworkView.tsx, non exporté et sans un test : la garde anti-cycle de
// `computeLevels` était PORTEUSE (une arête relayée par un pair peut fermer
// une boucle, test_structures.py l. 373) et rien ne le vérifiait ; la fiche,
// la voix, le tri des faisables et le décroisement des flèches avaient tous
// besoin de « ce que X attend » et « ce que X débloque », qui n'existaient
// nulle part. Une arête se lit « from débloque to » : `to` attend `from`.

import type { SuccesTask, SuccesTaskEdge } from './types';

export type StatutTache = 'faite' | 'faisable' | 'bloquee';

/** Le sens d'un parcours : vers ce qu'on attend, ou vers ce qu'on débloque. */
export type Sens = 'amont' | 'aval';

export interface Reseau {
  taches: SuccesTask[];
  /** Les arêtes dont les deux bouts existent — les autres sont des fantômes. */
  aretes: SuccesTaskEdge[];
  parId: Map<string, SuccesTask>;
  /** id → ce qu'il attend (prédécesseures directes), dans l'ordre des arêtes. */
  amont: Map<string, string[]>;
  /** id → ce qu'il débloque (successeures directes), dans l'ordre des arêtes. */
  aval: Map<string, string[]>;
}

export interface Voisinage {
  amont: string[];
  aval: string[];
  amontTransitif: string[];
  avalTransitif: string[];
  /** Les prédécesseures directes encore ouvertes — les vraies raisons du blocage. */
  manquantes: string[];
}

export interface Maillon {
  id: string;
  /** 1 pour une voisine directe, 2 pour la voisine de la voisine, etc. */
  profondeur: number;
}

const compareTitres = (a: SuccesTask, b: SuccesTask) => a.title.localeCompare(b.title, 'fr');

export function construireReseau(tasks: SuccesTask[], edges: SuccesTaskEdge[]): Reseau {
  const parId = new Map(tasks.map((task) => [task.id, task]));
  const amont = new Map<string, string[]>();
  const aval = new Map<string, string[]>();
  for (const task of tasks) {
    amont.set(task.id, []);
    aval.set(task.id, []);
  }
  const aretes: SuccesTaskEdge[] = [];
  for (const edge of edges) {
    if (!parId.has(edge.fromTaskId) || !parId.has(edge.toTaskId)) continue;
    aretes.push(edge);
    amont.get(edge.toTaskId)?.push(edge.fromTaskId);
    aval.get(edge.fromTaskId)?.push(edge.toTaskId);
  }
  return { taches: tasks, aretes, parId, amont, aval };
}

/**
 * Niveau = longueur du plus long chemin depuis une source.
 *
 * La garde `visiting` est porteuse : une boucle relayée par un pair (t1→t2
 * ET t2→t1, acceptée à la réception pour ne pas figer les appareils) ferait
 * sinon une récursion sans fin. Ici l'arête qui referme le cycle est comptée
 * comme une source : les niveaux restent finis, le graphe se dessine.
 */
export function niveaux(reseau: Reseau): Map<string, number> {
  const levels = new Map<string, number>();
  const visiting = new Set<string>();
  const levelOf = (id: string): number => {
    const known = levels.get(id);
    if (known !== undefined) return known;
    if (visiting.has(id)) return 0;
    visiting.add(id);
    const sources = reseau.amont.get(id) ?? [];
    const value =
      sources.length === 0 ? 0 : Math.max(...sources.map((sourceId) => levelOf(sourceId))) + 1;
    visiting.delete(id);
    levels.set(id, value);
    return value;
  };
  for (const task of reseau.taches) levelOf(task.id);
  return levels;
}

/** Faite, faisable (rien d'ouvert en amont), ou bloquée (au moins une attente ouverte). */
export function statuts(reseau: Reseau): Map<string, StatutTache> {
  const map = new Map<string, StatutTache>();
  for (const task of reseau.taches) {
    if (task.done) {
      map.set(task.id, 'faite');
      continue;
    }
    const attend = (reseau.amont.get(task.id) ?? []).some((id) => !reseau.parId.get(id)?.done);
    map.set(task.id, attend ? 'bloquee' : 'faisable');
  }
  return map;
}

export function statutDe(reseau: Reseau, id: string): StatutTache {
  const task = reseau.parId.get(id);
  if (!task || task.done) return 'faite';
  const attend = (reseau.amont.get(id) ?? []).some((pid) => !reseau.parId.get(pid)?.done);
  return attend ? 'bloquee' : 'faisable';
}

/**
 * Les faisables maintenant, celles qui libèrent le plus en premier, puis par
 * titre. Triées par titre (jusqu'au 18 sept. 2026), « Qu'est-ce qu'on aura
 * besoin en premier ? » (3 tâches en aval) passait après « Avoir les bons
 * agriculteurs » : la première puce doit être la tâche à faire ce soir.
 */
export function faisables(reseau: Reseau): SuccesTask[] {
  const st = statuts(reseau);
  return reseau.taches
    .filter((task) => st.get(task.id) === 'faisable')
    .sort((a, b) => impact(reseau, b.id) - impact(reseau, a.id) || compareTitres(a, b));
}

/** Parcours en largeur dans un sens, sans le départ, chaque tâche une seule fois. */
export function chaine(reseau: Reseau, id: string, sens: Sens): Maillon[] {
  const voisins = sens === 'amont' ? reseau.amont : reseau.aval;
  const vus = new Set<string>([id]);
  const resultat: Maillon[] = [];
  let frontiere = [id];
  let profondeur = 0;
  while (frontiere.length > 0) {
    profondeur += 1;
    const suivante: string[] = [];
    for (const courant of frontiere) {
      const proches = [...(voisins.get(courant) ?? [])]
        .map((vid) => reseau.parId.get(vid))
        .filter((t): t is SuccesTask => t !== undefined)
        .sort(compareTitres);
      for (const proche of proches) {
        if (vus.has(proche.id)) continue;
        vus.add(proche.id);
        resultat.push({ id: proche.id, profondeur });
        suivante.push(proche.id);
      }
    }
    frontiere = suivante;
  }
  return resultat;
}

/**
 * Les voisines directes, dans l'ordre où la fiche les lit : en amont, les
 * ouvertes d'abord (ce sont les vraies raisons du blocage), puis par titre ;
 * en aval, par titre.
 */
function voisinesOrdonnees(reseau: Reseau, id: string, sens: Sens): SuccesTask[] {
  const ids = (sens === 'amont' ? reseau.amont : reseau.aval).get(id) ?? [];
  const taches = ids
    .map((vid) => reseau.parId.get(vid))
    .filter((t): t is SuccesTask => t !== undefined);
  return taches.sort((a, b) => {
    if (sens === 'amont' && a.done !== b.done) return a.done ? 1 : -1;
    return compareTitres(a, b);
  });
}

export function voisinage(reseau: Reseau, id: string): Voisinage {
  const amont = voisinesOrdonnees(reseau, id, 'amont');
  const aval = voisinesOrdonnees(reseau, id, 'aval');
  return {
    amont: amont.map((t) => t.id),
    aval: aval.map((t) => t.id),
    amontTransitif: chaine(reseau, id, 'amont').map((m) => m.id),
    avalTransitif: chaine(reseau, id, 'aval').map((m) => m.id),
    manquantes: amont.filter((t) => !t.done).map((t) => t.id),
  };
}

/** La première voisine dans un sens — la cible de ← et → dans la fiche. */
export function voisinSuivant(reseau: Reseau, id: string, sens: Sens): string | null {
  return voisinesOrdonnees(reseau, id, sens)[0]?.id ?? null;
}

/**
 * Les successeures qu'achever `id` ouvre : celles dont toutes les autres
 * attentes sont déjà faites. Calculé sur l'état RECHARGÉ après la coche,
 * `id` y est déjà faite et le résultat dit ce qui vient de devenir faisable
 * (§100 : la phrase vient du serveur, pas du clic).
 */
export function ceQueDebloque(reseau: Reseau, id: string): string[] {
  const resultat: string[] = [];
  for (const sid of reseau.aval.get(id) ?? []) {
    const succ = reseau.parId.get(sid);
    if (!succ || succ.done) continue;
    const autres = (reseau.amont.get(sid) ?? []).filter((pid) => pid !== id);
    if (autres.every((pid) => reseau.parId.get(pid)?.done)) resultat.push(sid);
  }
  return resultat
    .map((sid) => reseau.parId.get(sid) as SuccesTask)
    .sort(compareTitres)
    .map((t) => t.id);
}

/**
 * Les successeures que ROUVRIR `id` vient de rebloquer : celles dont `id`
 * est la seule attente ouverte. Même ensemble que `ceQueDebloque` — le
 * calcul ne regarde pas l'état de `id`, seulement celui des autres attentes —
 * mais lu sur l'état rechargé après une réouverture, il dit ce qui vient de
 * repasser de faisable à bloquée.
 */
export function ceQueRebloque(reseau: Reseau, id: string): string[] {
  return ceQueDebloque(reseau, id);
}

/** Combien de tâches ouvertes attendent, de près ou de loin, que `id` soit faite. */
export function impact(reseau: Reseau, id: string): number {
  return chaine(reseau, id, 'aval').filter((m) => !reseau.parId.get(m.id)?.done).length;
}

/** « A », « A » et « B », « A », « B » et « C ». */
export function citer(titres: string[]): string {
  const guillemets = titres.map((t) => `« ${t} »`);
  if (guillemets.length <= 1) return guillemets.join('');
  return `${guillemets.slice(0, -1).join(', ')} et ${guillemets[guillemets.length - 1]}`;
}

export interface PhraseBascule {
  titre: string;
  description: string;
}

/**
 * Ce que le toast dit après une coche ou une réouverture, calculé sur l'état
 * RECHARGÉ (§100 : la phrase vient du serveur, jamais du clic). Jusqu'au
 * 18 sept. 2026 le toast disait « Tâche terminée » comme pour une liste
 * plate : l'information pour laquelle le réseau existe — ce qui vient de
 * s'ouvrir — n'était ni dite ni montrée. « Rien de nouveau » nomme la
 * successeure qui attend encore, et ce qu'elle attend.
 */
export function phraseApresBascule(reseau: Reseau, id: string): PhraseBascule {
  const tache = reseau.parId.get(id);
  const titreDe = (tid: string) => reseau.parId.get(tid)?.title ?? '';
  if (!tache) {
    return { titre: 'Tâche mise à jour', description: 'Elle n’est plus dans ce projet.' };
  }
  if (tache.done) {
    const ouvertes = ceQueDebloque(reseau, id);
    if (ouvertes.length > 0) {
      return { titre: 'Tâche terminée', description: `Débloque ${citer(ouvertes.map(titreDe))}.` };
    }
    const encoreBloquees = (reseau.aval.get(id) ?? [])
      .map((sid) => reseau.parId.get(sid))
      .filter((t): t is SuccesTask => t !== undefined && !t.done)
      .sort(compareTitres);
    const premiere = encoreBloquees[0];
    if (!premiere) {
      return { titre: 'Tâche terminée', description: 'Rien ne l’attendait.' };
    }
    const attend = voisinage(reseau, premiere.id).manquantes.map(titreDe);
    const autres = encoreBloquees.length > 1 ? ` (et ${encoreBloquees.length - 1} autre${encoreBloquees.length > 2 ? 's' : ''})` : '';
    return {
      titre: 'Tâche terminée',
      description: `Rien de nouveau : « ${premiere.title} » attend encore ${citer(attend)}${autres}.`,
    };
  }
  const rebloquees = ceQueRebloque(reseau, id);
  return {
    titre: 'Tâche rouverte',
    description:
      rebloquees.length > 0 ? `Rebloque ${citer(rebloquees.map(titreDe))}.` : 'Rien ne se rebloque.',
  };
}

/**
 * Les arêtes qui viennent de se libérer entre deux états : la source vient
 * de passer faite, et la cible est devenue faisable par là. C'est ce que
 * l'impulsion parcourt dans le graphe — calculé sur l'état rechargé, jamais
 * sur le clic : une coche refusée par le serveur n'allume rien.
 */
export function aretesLiberees(
  statutsAvant: ReadonlyMap<string, StatutTache>,
  reseau: Reseau,
): Array<{ from: string; to: string }> {
  const resultat: Array<{ from: string; to: string }> = [];
  for (const task of reseau.taches) {
    if (!task.done) continue;
    const avant = statutsAvant.get(task.id);
    if (avant === undefined || avant === 'faite') continue;
    for (const to of ceQueDebloque(reseau, task.id)) resultat.push({ from: task.id, to });
  }
  return resultat;
}

/**
 * Même parcours que `create_task_edge` (workspace.py) : une boucle se
 * formerait si `from` est déjà atteignable depuis `to`. Le serveur reste le
 * juge ; le client ne fait que prévenir avant le clic.
 */
export function fermeraitUneBoucle(reseau: Reseau, from: string, to: string): boolean {
  if (from === to) return true;
  const atteints = new Set<string>([to]);
  const frontiere = [to];
  while (frontiere.length > 0) {
    const courant = frontiere.pop() as string;
    for (const suivant of reseau.aval.get(courant) ?? []) {
      if (suivant === from) return true;
      if (!atteints.has(suivant)) {
        atteints.add(suivant);
        frontiere.push(suivant);
      }
    }
  }
  return false;
}

// ── La durée estimée, en jours entiers (18 sept. 2026) ──────────────────────
//
// Sans durée, le réseau ne peut ni projeter une fin ni distinguer la marge de
// « budget » de l'absence de marge de « paiement » ; mais un « chemin
// critique » sans durée serait faire semblant (§5). On ne parle de jours que
// si l'estimation est COMPLÈTE : toutes les tâches ouvertes en portent une.
// La revue du réseau (18 sept. 2026) a mesuré ce que « dès qu'UNE durée
// existe » produisait : « ~ 3 j » sur « agriculteurs » seule, et l'en-tête
// annonçait « fin projetée ~3 j » pour un projet dont six tâches ouvertes
// sur sept pesaient 0 j faute d'estimation, la fiche de « riz » disait
// « Marge : 3 j » pour une chaîne que personne n'avait estimée, et « Sur le
// chemin critique » se posait sur des tâches à 0 j — « 0 » y était l'absence
// de donnée, pas une durée. Pire, une chaîne a→b→c→d sans durée plus une
// tâche z estimée à 1 j donnaient « profondeur 1 » : la chaîne la plus LOURDE
// avait remplacé la plus LONGUE sous le même mot. Ici la profondeur reste en
// tâches, toujours ; le chemin critique, la fin projetée et la marge en
// jours n'existent que quand chaque tâche ouverte a été estimée. 0 = pas
// d'estimation. Toujours un entier : le client Dart signe des enveloppes
// canoniques où `1e-07` (Python) et `1e-7` (Dart) divergent.

/** La durée estimée d'une tâche, en jours entiers ; 0 sans estimation ou pour une inconnue. */
export function dureeDe(reseau: Reseau, id: string): number {
  const n = Number(reseau.parId.get(id)?.estimateDays ?? 0);
  return Number.isFinite(n) && n > 0 ? Math.trunc(n) : 0;
}

/** Vrai dès qu'une tâche OUVERTE porte une durée — de quoi dire « 3 estimées sur 7 », pas de quoi compter des jours. */
export function aDesDurees(reseau: Reseau): boolean {
  return reseau.taches.some((t) => !t.done && dureeDe(reseau, t.id) > 0);
}

export interface Estimation {
  /** Les tâches ouvertes qui portent une durée. */
  estimees: number;
  /** Les tâches ouvertes, en tout. */
  ouvertes: number;
  /** Vrai quand chaque tâche ouverte est estimée, et qu'il en reste au moins une : le seul cas où l'on parle de jours. */
  complete: boolean;
}

/** Combien de tâches ouvertes sont estimées, sur combien — et si l'on peut compter des jours. */
export function estimation(reseau: Reseau): Estimation {
  let estimees = 0;
  let ouvertes = 0;
  for (const t of reseau.taches) {
    if (t.done) continue;
    ouvertes += 1;
    if (dureeDe(reseau, t.id) > 0) estimees += 1;
  }
  // Un projet fini n'a rien à projeter : « complète » sur zéro tâche
  // donnerait « fin projetée ~0 j », un chiffre pour rien.
  return { estimees, ouvertes, complete: ouvertes > 0 && estimees === ouvertes };
}

/**
 * Vrai quand TOUTES les tâches ouvertes portent une durée. La règle est
 * volontairement simple : une seule tâche non estimée sur une chaîne et
 * toute marge en jours qui la traverse serait fausse ; plutôt que de
 * décider chaîne par chaîne, le réseau entier passe en jours ou reste en
 * tâches.
 */
export function estimationComplete(reseau: Reseau): boolean {
  return estimation(reseau).complete;
}

/** Les jours d'une chaîne : la somme des durées de ses tâches. */
export function joursDeChaine(reseau: Reseau, chaine: string[]): number {
  return chaine.reduce((somme, id) => somme + dureeDe(reseau, id), 0);
}

/**
 * Entre deux chaînes : la plus lourde selon `poids`, puis la plus longue en
 * tâches, puis la première par titres. Avec un poids de 1 par tâche, c'est
 * la plus longue tout court.
 */
function meilleureChaine(
  reseau: Reseau,
  poids: (id: string) => number,
  a: string[],
  b: string[],
): boolean {
  const pa = a.reduce((s, id) => s + poids(id), 0);
  const pb = b.reduce((s, id) => s + poids(id), 0);
  if (pa !== pb) return pa > pb;
  if (a.length !== b.length) return a.length > b.length;
  return plusTot(reseau, a, b);
}

/**
 * La chaîne de tâches OUVERTES la plus lourde selon `poids`, dans l'ordre —
 * ex æquo par le nombre de tâches, puis la chaîne dont les titres viennent
 * en premier (stable d'un rendu à l'autre). Les tâches faites sont hors du
 * sous-graphe : une chaîne finie ne compte plus.
 */
function chaineLaPlusLourde(reseau: Reseau, poids: (id: string) => number): string[] {
  const ouvertes = reseau.taches.filter((t) => !t.done);
  const memo = new Map<string, string[]>();
  const visiting = new Set<string>();
  const meilleure = (id: string): string[] => {
    const connue = memo.get(id);
    if (connue) return connue;
    // Une boucle relayée : l'arête qui la referme est traitée comme une
    // source, sinon la chaîne se rallongerait d'un tour à chaque passage.
    if (visiting.has(id)) return [];
    visiting.add(id);
    let best: string[] = [];
    for (const pid of reseau.amont.get(id) ?? []) {
      const pred = reseau.parId.get(pid);
      if (!pred || pred.done) continue;
      const candidate = meilleure(pid);
      if (meilleureChaine(reseau, poids, candidate, best)) best = candidate;
    }
    visiting.delete(id);
    const chemin = [...best, id];
    memo.set(id, chemin);
    return chemin;
  };
  let resultat: string[] = [];
  for (const task of ouvertes) {
    const chemin = meilleure(task.id);
    if (meilleureChaine(reseau, poids, chemin, resultat)) resultat = chemin;
  }
  return resultat;
}

/**
 * La plus longue chaîne de tâches OUVERTES, EN TÂCHES, dans l'ordre : la
 * « profondeur » de l'en-tête, vraie avec ou sans durée. Ce n'est pas un
 * « chemin critique » — lui vit dans `cheminCritique`, et seulement quand
 * l'estimation est complète.
 */
export function chaineLaPlusLongue(reseau: Reseau): string[] {
  return chaineLaPlusLourde(reseau, () => 1);
}

/**
 * Le chemin critique : la chaîne ouverte la plus lourde en jours (passe
 * avant du CPM), seulement quand chaque tâche ouverte est estimée — sinon
 * null, parce qu'une tâche à « 0 j » y pèserait l'absence de donnée comme
 * une durée.
 */
export function cheminCritique(reseau: Reseau): string[] | null {
  if (!estimationComplete(reseau)) return null;
  return chaineLaPlusLourde(reseau, (id) => dureeDe(reseau, id));
}

/**
 * La fin projetée : les jours du chemin critique, depuis aujourd'hui —
 * « ~9 j », jamais une date promise. Null tant que l'estimation n'est pas
 * complète.
 */
export function finProjetee(reseau: Reseau): number | null {
  const critique = cheminCritique(reseau);
  return critique === null ? null : joursDeChaine(reseau, critique);
}

// Le séparateur est un saut de ligne : la collation ICU IGNORE U+0000 (et
// tout contrôle C0), si bien que « a » puis « ab » se lisaient « aab »
// contre « aab » — l'égalité tombait sur l'ordre d'itération, pas sur les
// titres (contre-revue du réseau, 18 sept. 2026). '\n' compte pour la
// collation et trie avant toute lettre ; il ne peut pas venir d'un titre
// (le serveur les borne à une ligne).
function plusTot(reseau: Reseau, a: string[], b: string[]): boolean {
  if (b.length === 0) return true;
  const ta = a.map((id) => reseau.parId.get(id)?.title ?? '').join('\n');
  const tb = b.map((id) => reseau.parId.get(id)?.title ?? '').join('\n');
  return ta.localeCompare(tb, 'fr') < 0;
}

/** Les arêtes d'une chaîne, sous la clé `from->to` que la vue emploie. */
export function aretesDeChaine(chaine: string[]): Set<string> {
  const aretes = new Set<string>();
  for (let i = 1; i < chaine.length; i += 1) aretes.add(`${chaine[i - 1]}->${chaine[i]}`);
  return aretes;
}

/**
 * Le nombre de tâches ouvertes sur la plus longue chaîne qui part de `id`
 * (elle comprise) dans un sens. 0 pour une tâche faite ou inconnue. Même
 * garde que `chaineLaPlusLongue` : une boucle relayée compte comme un bout.
 */
function longueurOuverte(reseau: Reseau, id: string, sens: Sens): number {
  const voisins = sens === 'amont' ? reseau.amont : reseau.aval;
  const memo = new Map<string, number>();
  const visiting = new Set<string>();
  const longueur = (tid: string): number => {
    const tache = reseau.parId.get(tid);
    if (!tache || tache.done) return 0;
    const connue = memo.get(tid);
    if (connue !== undefined) return connue;
    if (visiting.has(tid)) return 0;
    visiting.add(tid);
    let best = 0;
    for (const vid of voisins.get(tid) ?? []) best = Math.max(best, longueur(vid));
    visiting.delete(tid);
    memo.set(tid, best + 1);
    return best + 1;
  };
  return longueur(id);
}

/**
 * De combien de tâches la chaîne qui passe par `id` est plus courte que la
 * plus longue : 0 quand elle est aussi longue. Null pour une tâche faite,
 * qui n'est plus sur aucune chaîne ouverte. C'est la marge du CPM réduite
 * en tâches : sans durée, ce compte-là est vrai, un « chemin critique » ne
 * le serait pas (§5).
 *
 * Jamais négative. Sur une boucle relayée (t1→t2, t2→t1, t2→t3), la garde
 * anti-cycle coupe la chaîne à un endroit différent selon la tâche d'où l'on
 * part : `chaineLaPlusLongue` comptait 2 tâches, `longueurOuverte(t3, amont)`
 * en traversait 3, et la fiche écrivait « Marge : -1 tâche » (revue du
 * réseau, 18 sept. 2026). Une marge est un écart à un maximum : au-dessous
 * de zéro, c'est la boucle qui parle, pas la tâche.
 */
export function margeDe(reseau: Reseau, id: string): number | null {
  const tache = reseau.parId.get(id);
  if (!tache || tache.done) return null;
  const traverse =
    longueurOuverte(reseau, id, 'amont') + longueurOuverte(reseau, id, 'aval') - 1;
  return Math.max(0, chaineLaPlusLongue(reseau).length - traverse);
}

/** Les jours de la chaîne ouverte la plus lourde qui part de `id` (elle comprise) dans un sens. */
function joursOuverts(reseau: Reseau, id: string, sens: Sens): number {
  const voisins = sens === 'amont' ? reseau.amont : reseau.aval;
  const memo = new Map<string, number>();
  const visiting = new Set<string>();
  const jours = (tid: string): number => {
    const tache = reseau.parId.get(tid);
    if (!tache || tache.done) return 0;
    const connue = memo.get(tid);
    if (connue !== undefined) return connue;
    if (visiting.has(tid)) return 0;
    visiting.add(tid);
    let best = 0;
    for (const vid of voisins.get(tid) ?? []) best = Math.max(best, jours(vid));
    visiting.delete(tid);
    const total = best + dureeDe(reseau, tid);
    memo.set(tid, total);
    return total;
  };
  return jours(id);
}

/**
 * La marge totale du CPM, en jours : de combien la chaîne la plus lourde qui
 * passe par `id` est plus courte que le chemin critique. 0 = sur le chemin
 * critique. Null pour une tâche faite, ou tant que l'estimation n'est pas
 * complète — une marge en jours qui traverse une tâche non estimée
 * compterait « 0 » là où personne n'a rien dit.
 */
export function margeJours(reseau: Reseau, id: string): number | null {
  const tache = reseau.parId.get(id);
  if (!tache || tache.done) return null;
  const critique = cheminCritique(reseau);
  if (critique === null) return null;
  const traverse =
    joursOuverts(reseau, id, 'amont') + joursOuverts(reseau, id, 'aval') - dureeDe(reseau, id);
  return Math.max(0, joursDeChaine(reseau, critique) - traverse);
}

/**
 * Ce que la fiche dit de la place d'une tâche. Estimation complète : « Sur
 * le chemin critique » (marge nulle — le mot n'apparaît qu'ici, quand il
 * est vrai) ou « Marge : 2 j ». Sinon, en tâches : sur le fil (la chaîne que
 * la vue met en évidence), sur une chaîne aussi longue (AgriCulture en a
 * deux de trois tâches : « tracteur » n'est pas sur le fil et n'a pourtant
 * aucune marge), ou sa marge en tâches. Rien pour une tâche faite.
 */
export function placeSurLeFil(reseau: Reseau, id: string): string | null {
  const jours = margeJours(reseau, id);
  if (jours !== null) {
    return jours === 0 ? 'Sur le chemin critique' : `Marge : ${jours} j`;
  }
  const marge = margeDe(reseau, id);
  if (marge === null) return null;
  if (chaineLaPlusLongue(reseau).includes(id)) return 'Sur la chaîne la plus longue';
  if (marge === 0) return 'Sur une chaîne aussi longue que le fil';
  return `Marge : ${marge} tâche${marge > 1 ? 's' : ''}`;
}

export interface Comptes {
  faisables: number;
  bloquees: number;
  faites: number;
  /** La chaîne la plus longue, en tâches ouvertes — pas un « chemin critique ». */
  profondeur: number;
  /** Les jours du chemin critique, depuis aujourd'hui ; null tant que l'estimation n'est pas complète. */
  joursProjetes: number | null;
  /** Les tâches ouvertes estimées, sur les ouvertes : ce que l'en-tête dit à la place d'une fin qu'il ne peut pas projeter. */
  estimees: number;
  ouvertes: number;
}

export function comptes(reseau: Reseau): Comptes {
  const st = statuts(reseau);
  let faisables = 0;
  let bloquees = 0;
  let faites = 0;
  for (const statut of st.values()) {
    if (statut === 'faisable') faisables += 1;
    else if (statut === 'bloquee') bloquees += 1;
    else faites += 1;
  }
  const est = estimation(reseau);
  return {
    faisables,
    bloquees,
    faites,
    profondeur: chaineLaPlusLongue(reseau).length,
    joursProjetes: finProjetee(reseau),
    estimees: est.estimees,
    ouvertes: est.ouvertes,
  };
}

/**
 * « 3 tâches estimées sur 7 » : ce que l'en-tête dit quand des durées
 * existent sans qu'il puisse projeter une fin ; rien quand aucune n'existe
 * (un projet qui n'estime pas n'a pas à lire « 0 sur 7 » en permanence),
 * rien non plus quand l'estimation est complète — la fin projetée le dit.
 */
export function libelleEstimation(c: Comptes): string | null {
  if (c.estimees === 0 || c.joursProjetes !== null) return null;
  return `${c.estimees} tâche${c.estimees > 1 ? 's' : ''} estimée${c.estimees > 1 ? 's' : ''} sur ${c.ouvertes}`;
}

/**
 * L'en-tête du réseau : « 2 faisables · 5 bloquées · profondeur 3 », puis
 * « · fin projetée ~9 j » quand chaque tâche ouverte est estimée — projetée
 * depuis aujourd'hui, jamais une date promise — ou « · 3 tâches estimées
 * sur 7 » quand l'estimation est entamée sans être complète. Le seul chiffre
 * affiché jusqu'au 18 sept. 2026 était « Faisable maintenant : N » ; rien
 * ne disait combien attendaient ni jusqu'où le projet s'enchaîne.
 */
export function libelleEnTete(c: Comptes): string {
  const faisables = `${c.faisables} faisable${c.faisables > 1 ? 's' : ''}`;
  const bloquees = `${c.bloquees} bloquée${c.bloquees > 1 ? 's' : ''}`;
  const est = libelleEstimation(c);
  const fin = c.joursProjetes !== null ? ` · fin projetée ~${c.joursProjetes} j` : est ? ` · ${est}` : '';
  return `${faisables} · ${bloquees} · profondeur ${c.profondeur}${fin}`;
}

/**
 * La durée telle qu'on la saisit dans le « ⋯ » de la fiche : un entier de
 * jours entre 0 et 3650 (la borne du serveur), ou null quand le texte n'en
 * est pas un — « 1,5 », « deux », un négatif. Vide = 0, pas d'estimation.
 */
export function lireDureeSaisie(texte: string): number | null {
  const brut = texte.trim();
  if (brut === '') return 0;
  if (!/^\d{1,4}$/.test(brut)) return null;
  const n = Number(brut);
  return n <= 3650 ? n : null;
}

/** Les colonnes telles que la vue les dessinait : par niveau, faites en bas, puis par titre. */
export function colonnesInitiales(reseau: Reseau): string[][] {
  const levels = niveaux(reseau);
  const parNiveau = new Map<number, SuccesTask[]>();
  for (const task of reseau.taches) {
    const level = levels.get(task.id) ?? 0;
    const colonne = parNiveau.get(level);
    if (colonne) colonne.push(task);
    else parNiveau.set(level, [task]);
  }
  return [...parNiveau.keys()]
    .sort((a, b) => a - b)
    .map((level) =>
      (parNiveau.get(level) ?? [])
        .sort((a, b) => (a.done === b.done ? compareTitres(a, b) : a.done ? 1 : -1))
        .map((t) => t.id),
    );
}

/**
 * Combien de flèches se croisent. Chaque arête est un segment de sa colonne
 * de départ à sa colonne d'arrivée ; deux arêtes qui partagent un intervalle
 * de colonnes se croisent si leur ordre vertical s'inverse entre les deux
 * bouts de cet intervalle. Une arête qui remonte (boucle relayée) est
 * ignorée : elle n'a pas de direction à croiser.
 */
export function compterCroisements(reseau: Reseau, colonnes: string[][]): number {
  const colonneDe = new Map<string, number>();
  const rangDe = new Map<string, number>();
  colonnes.forEach((ids, c) => ids.forEach((id, r) => {
    colonneDe.set(id, c);
    rangDe.set(id, r);
  }));
  const segments = reseau.aretes
    .map((edge) => {
      const c1 = colonneDe.get(edge.fromTaskId);
      const c2 = colonneDe.get(edge.toTaskId);
      const r1 = rangDe.get(edge.fromTaskId);
      const r2 = rangDe.get(edge.toTaskId);
      if (c1 === undefined || c2 === undefined || r1 === undefined || r2 === undefined) return null;
      if (c1 >= c2) return null;
      return { c1, c2, r1, r2 };
    })
    .filter((s): s is { c1: number; c2: number; r1: number; r2: number } => s !== null);
  const yA = (s: { c1: number; c2: number; r1: number; r2: number }, c: number) =>
    s.r1 + ((s.r2 - s.r1) * (c - s.c1)) / (s.c2 - s.c1);
  let croisements = 0;
  for (let i = 0; i < segments.length; i += 1) {
    for (let j = i + 1; j < segments.length; j += 1) {
      const a = segments[i];
      const b = segments[j];
      const debut = Math.max(a.c1, b.c1);
      const fin = Math.min(a.c2, b.c2);
      if (debut >= fin) continue;
      const d1 = yA(a, debut) - yA(b, debut);
      const d2 = yA(a, fin) - yA(b, fin);
      if (d1 * d2 < 0) croisements += 1;
    }
  }
  return croisements;
}

/**
 * Ordonnancement barycentrique (Sugiyama, phase 2) : quatre balayages
 * aller-retour, chaque tâche placée à la moyenne des rangs de ses voisines
 * dans la colonne de référence, ex æquo par titre pour rester stable. On
 * garde le balayage au moins de croisements — le dernier n'est pas toujours
 * le meilleur. Les colonnes du départ étaient triées par alphabet : sur
 * AgriCulture, 5 arêtes suffisaient à en croiser deux.
 */
export function ordonnerColonnes(reseau: Reseau, balayages = 4): string[][] {
  let colonnes = colonnesInitiales(reseau);
  let meilleures = colonnes;
  let moins = compterCroisements(reseau, colonnes);
  if (moins === 0 || colonnes.length < 2) return colonnes;

  const titreDe = (id: string) => reseau.parId.get(id)?.title ?? '';
  const trier = (ids: string[], reference: string[], voisins: Map<string, string[]>) => {
    const rang = new Map(reference.map((id, i) => [id, i]));
    const bary = new Map<string, number>();
    ids.forEach((id, i) => {
      const rangs = (voisins.get(id) ?? [])
        .map((vid) => rang.get(vid))
        .filter((r): r is number => r !== undefined);
      bary.set(id, rangs.length === 0 ? i : rangs.reduce((s, r) => s + r, 0) / rangs.length);
    });
    return [...ids].sort((a, b) => {
      const d = (bary.get(a) ?? 0) - (bary.get(b) ?? 0);
      return d !== 0 ? d : titreDe(a).localeCompare(titreDe(b), 'fr');
    });
  };

  for (let passe = 0; passe < balayages; passe += 1) {
    const suivantes = colonnes.map((ids) => [...ids]);
    if (passe % 2 === 0) {
      for (let c = 1; c < suivantes.length; c += 1) {
        suivantes[c] = trier(suivantes[c], suivantes[c - 1], reseau.amont);
      }
    } else {
      for (let c = suivantes.length - 2; c >= 0; c -= 1) {
        suivantes[c] = trier(suivantes[c], suivantes[c + 1], reseau.aval);
      }
    }
    colonnes = suivantes;
    const croisements = compterCroisements(reseau, colonnes);
    if (croisements < moins) {
      moins = croisements;
      meilleures = colonnes;
      if (moins === 0) break;
    }
  }
  return meilleures;
}

export interface DimensionsDisposition {
  largeurCarte: number;
  hauteurCarte: number;
  ecartX: number;
  ecartY: number;
  marge: number;
}

export interface Disposition {
  pos: Map<string, Point>;
  largeur: number;
  hauteur: number;
}

/** Les positions des cartes à partir des colonnes ordonnées — la seule géométrie. */
export function positionner(colonnes: string[][], dims: DimensionsDisposition): Disposition {
  const pos = new Map<string, Point>();
  let maxRangs = 1;
  colonnes.forEach((ids, c) => {
    maxRangs = Math.max(maxRangs, ids.length);
    ids.forEach((id, r) => {
      pos.set(id, {
        x: dims.marge + c * (dims.largeurCarte + dims.ecartX),
        y: dims.marge + r * (dims.hauteurCarte + dims.ecartY),
      });
    });
  });
  const nbColonnes = Math.max(colonnes.length, 1);
  return {
    pos,
    largeur: dims.marge * 2 + nbColonnes * dims.largeurCarte + (nbColonnes - 1) * dims.ecartX,
    hauteur: dims.marge * 2 + maxRangs * dims.hauteurCarte + (maxRangs - 1) * dims.ecartY,
  };
}

export type Point = { x: number; y: number };

/**
 * Les composantes connexes, sens des arêtes ignoré : deux chaînes sans
 * rapport (AgriCulture en a deux) partageaient les mêmes colonnes,
 * entrelacées. Les plus grandes d'abord, ex æquo par le premier titre ;
 * dans chacune, les tâches par titre. Une tâche seule est une composante.
 */
export function composantes(reseau: Reseau): string[][] {
  const vues = new Set<string>();
  const resultat: string[][] = [];
  for (const depart of reseau.taches) {
    if (vues.has(depart.id)) continue;
    const membres: string[] = [];
    const frontiere = [depart.id];
    vues.add(depart.id);
    while (frontiere.length > 0) {
      const courant = frontiere.pop() as string;
      membres.push(courant);
      for (const vid of [...(reseau.amont.get(courant) ?? []), ...(reseau.aval.get(courant) ?? [])]) {
        if (!vues.has(vid)) {
          vues.add(vid);
          frontiere.push(vid);
        }
      }
    }
    resultat.push(
      membres
        .map((id) => reseau.parId.get(id) as SuccesTask)
        .sort(compareTitres)
        .map((t) => t.id),
    );
  }
  const titreDe = (id: string) => reseau.parId.get(id)?.title ?? '';
  return resultat.sort(
    (a, b) => b.length - a.length || titreDe(a[0]).localeCompare(titreDe(b[0]), 'fr'),
  );
}

export function estOrpheline(reseau: Reseau, id: string): boolean {
  return (reseau.amont.get(id)?.length ?? 0) + (reseau.aval.get(id)?.length ?? 0) === 0;
}

/** Les tâches ouvertes sans aucun lien, par titre : elles passent pour faisables sans que rien ne les ait placées. */
export function orphelines(reseau: Reseau): string[] {
  return reseau.taches
    .filter((t) => !t.done && estOrpheline(reseau, t.id))
    .sort(compareTitres)
    .map((t) => t.id);
}

export interface Goulot {
  id: string;
  /** Combien de tâches ouvertes attendent directement celle-ci. */
  debloque: number;
}

/** Les tâches ouvertes qu'au moins deux tâches ouvertes attendent directement ; la plus attendue d'abord. */
export function goulots(reseau: Reseau): Goulot[] {
  return reseau.taches
    .filter((t) => !t.done)
    .map((t) => ({ id: t.id, debloque: debloqueDirectes(reseau, t.id) }))
    .filter((g) => g.debloque >= 2)
    .sort(
      (a, b) =>
        b.debloque - a.debloque ||
        compareTitres(reseau.parId.get(a.id) as SuccesTask, reseau.parId.get(b.id) as SuccesTask),
    );
}

export interface Revue {
  /** Les composantes d'au moins deux tâches. */
  chaines: number;
  orphelines: string[];
  goulots: Goulot[];
}

export function revue(reseau: Reseau): Revue {
  return {
    chaines: composantes(reseau).filter((c) => c.length >= 2).length,
    orphelines: orphelines(reseau),
    goulots: goulots(reseau),
  };
}

/**
 * « 2 chaînes indépendantes · 0 orpheline · goulot : « Qu'est-ce qu'on aura
 * besoin en premier ? » (débloque 2) ». Avant le 18 sept. 2026, le goulot
 * d'AgriCulture n'était nommé nulle part.
 */
export function libelleRevue(reseau: Reseau, r: Revue = revue(reseau)): string {
  const chaines =
    r.chaines === 0
      ? 'aucune chaîne'
      : r.chaines === 1
        ? '1 chaîne'
        : `${r.chaines} chaînes indépendantes`;
  const orphs = `${r.orphelines.length} orpheline${r.orphelines.length > 1 ? 's' : ''}`;
  const titreDe = (id: string) => reseau.parId.get(id)?.title ?? '';
  const gs =
    r.goulots.length === 0
      ? 'aucun goulot'
      : `goulot${r.goulots.length > 1 ? 's' : ''} : ${r.goulots
          .map((g) => `« ${titreDe(g.id)} » (débloque ${g.debloque})`)
          .join(', ')}`;
  return `${chaines} · ${orphs} · ${gs}`;
}

export interface DispositionEmpilee extends Disposition {
  /** Les ordonnées des filets pointillés entre deux composantes. */
  separateurs: number[];
}

/**
 * Les composantes empilées l'une sous l'autre, chacune décroisée pour elle
 * seule, un filet entre deux ; les tâches seules forment une dernière bande
 * en grille, aussi large que la composante la plus large. Une seule
 * composante donne exactement `positionner(ordonnerColonnes(...))`.
 */
export function disposerParComposantes(reseau: Reseau, dims: DimensionsDisposition): DispositionEmpilee {
  const comps = composantes(reseau);
  if (comps.length <= 1) {
    return { ...positionner(ordonnerColonnes(reseau), dims), separateurs: [] };
  }
  const groupes = comps.filter((c) => c.length >= 2);
  const seules = comps.filter((c) => c.length === 1).flat();
  const bandes: string[][][] = groupes.map((membres) => {
    const ids = new Set(membres);
    const sous = construireReseau(
      membres.map((id) => reseau.parId.get(id) as SuccesTask),
      reseau.aretes.filter((e) => ids.has(e.fromTaskId) && ids.has(e.toTaskId)),
    );
    return ordonnerColonnes(sous);
  });
  if (seules.length > 0) {
    const nbColonnes = Math.max(1, ...bandes.map((b) => b.length));
    const grille: string[][] = [];
    seules.forEach((id, i) => {
      const c = i % nbColonnes;
      if (!grille[c]) grille[c] = [];
      grille[c].push(id);
    });
    bandes.push(grille);
  }
  const pos = new Map<string, Point>();
  const separateurs: number[] = [];
  let largeur = 0;
  let hauteur = 0;
  bandes.forEach((colonnes, k) => {
    const d = positionner(colonnes, dims);
    if (k > 0) separateurs.push(hauteur);
    for (const [id, p] of d.pos) pos.set(id, { x: p.x, y: p.y + hauteur });
    largeur = Math.max(largeur, d.largeur);
    hauteur += d.hauteur;
  });
  return { pos, largeur, hauteur, separateurs };
}

/** Les catégories que portent les tâches du projet, par titre ; vide : aucun couloir. */
export function categories(reseau: Reseau): string[] {
  const vues = new Set<string>();
  for (const task of reseau.taches) {
    const c = (task.category ?? '').trim();
    if (c) vues.add(c);
  }
  return [...vues].sort((a, b) => a.localeCompare(b, 'fr'));
}

export interface Couloir {
  /** La catégorie ; vide pour la bande des tâches sans catégorie. */
  categorie: string;
  /** Ce qu'on écrit en marge : la catégorie, ou « — ». */
  libelle: string;
  y: number;
  hauteur: number;
}

export interface DispositionCouloirs extends DispositionEmpilee {
  /** Vide quand aucune tâche ne porte de catégorie : pas de chrome vide. */
  couloirs: Couloir[];
}

/** La hauteur réservée au libellé d'un couloir, au-dessus de sa première ligne. */
export const HAUTEUR_LIBELLE_COULOIR = 20;

/**
 * Les couloirs par catégorie (18 sept. 2026) : quand au moins une tâche
 * porte une `category`, les lignes se regroupent en bandes horizontales —
 * une par catégorie, par titre, puis « — » pour les autres — avec un filet
 * entre deux. Le rang topologique reste GLOBAL (`ordonnerColonnes` sur tout
 * le réseau, chaque bande n'en garde que ses tâches, colonnes vides
 * comprises) : une arête peut traverser un couloir, et c'est l'information.
 * AgriCulture est deux projets en un (contrat / matériel) que la vue
 * mélangeait sans le dire ; `SuccesTask.category` existait et ne servait
 * nulle part dans le réseau.
 */
export function disposerParCouloirs(reseau: Reseau, dims: DimensionsDisposition): DispositionCouloirs {
  const colonnes = ordonnerColonnes(reseau);
  const categorieDe = (id: string) => (reseau.parId.get(id)?.category ?? '').trim();
  const bandes = categories(reseau).map((c) => ({ categorie: c, libelle: c }));
  if (reseau.taches.some((t) => !(t.category ?? '').trim())) {
    bandes.push({ categorie: '', libelle: '—' });
  }
  const pos = new Map<string, Point>();
  const separateurs: number[] = [];
  const couloirs: Couloir[] = [];
  let largeur = 0;
  let hauteur = 0;
  bandes.forEach(({ categorie, libelle }, k) => {
    const d = positionner(
      colonnes.map((ids) => ids.filter((id) => categorieDe(id) === categorie)),
      dims,
    );
    if (k > 0) separateurs.push(hauteur);
    const y = hauteur;
    for (const [id, p] of d.pos) pos.set(id, { x: p.x, y: p.y + y + HAUTEUR_LIBELLE_COULOIR });
    largeur = Math.max(largeur, d.largeur);
    hauteur += HAUTEUR_LIBELLE_COULOIR + d.hauteur;
    couloirs.push({ categorie, libelle, y, hauteur: hauteur - y });
  });
  return { pos, largeur, hauteur, separateurs, couloirs };
}

/**
 * La disposition du dessin : par couloirs dès qu'une catégorie existe,
 * sinon par composantes empilées — sans catégorie, rien ne change.
 */
export function disposer(reseau: Reseau, dims: DimensionsDisposition): DispositionCouloirs {
  if (categories(reseau).length > 0) return disposerParCouloirs(reseau, dims);
  return { ...disposerParComposantes(reseau, dims), couloirs: [] };
}

/**
 * Les positions à l'instant `t` (0 → départ, 1 → arrivée) d'un glissement
 * de cartes, en sortie douce (cubique) : quand une arête change et que le
 * barycentre réordonne une colonne, une carte qui saute d'une ligne à
 * l'autre sans transition se perd de vue. Une carte sans position de départ
 * (nouvelle) apparaît directement à l'arrivée.
 */
export function interpolerPositions(
  depart: Map<string, Point>,
  arrivee: Map<string, Point>,
  t: number,
): Map<string, Point> {
  const k = Math.min(1, Math.max(0, t));
  const e = 1 - (1 - k) ** 3;
  const resultat = new Map<string, Point>();
  for (const [id, cible] of arrivee) {
    const origine = depart.get(id);
    if (!origine || k >= 1) {
      resultat.set(id, cible);
      continue;
    }
    resultat.set(id, {
      x: origine.x + (cible.x - origine.x) * e,
      y: origine.y + (cible.y - origine.y) * e,
    });
  }
  return resultat;
}

/** Vrai si une carte connue des deux dispositions change de place. */
export function dispositionBouge(depart: Map<string, Point>, arrivee: Map<string, Point>): boolean {
  for (const [id, cible] of arrivee) {
    const origine = depart.get(id);
    if (origine && (origine.x !== cible.x || origine.y !== cible.y)) return true;
  }
  return false;
}

export type EtatArete = 'satisfaite' | 'prochaine' | 'en-attente';

export interface TraitArete {
  etat: EtatArete;
  epaisseur: number;
  /** Le motif `stroke-dasharray`, ou rien pour un trait continu. */
  pointilles: string | undefined;
  pointe: 'creuse' | 'pleine';
}

/**
 * Trois traits par la FORME, selon l'état de la SOURCE (18 sept. 2026).
 * Jusque-là deux teintes seulement (accent si la source n'est pas faite,
 * bordure sinon) : en Ardéchine, où l'accent est l'encre, une arête
 * satisfaite et une arête en attente se ressemblaient. Fin et pointe creuse
 * = satisfaite, la source est faite ; plein et pointe pleine = « prochaine »,
 * la source est faisable, ce lien se libère au prochain geste ; pointillé
 * 4 3 = en attente, la source est elle-même bloquée, c'est encore loin.
 */
export function traitArete(statutSource: StatutTache): TraitArete {
  if (statutSource === 'faite') {
    return { etat: 'satisfaite', epaisseur: 1, pointilles: undefined, pointe: 'creuse' };
  }
  if (statutSource === 'faisable') {
    return { etat: 'prochaine', epaisseur: 1.75, pointilles: undefined, pointe: 'pleine' };
  }
  return { etat: 'en-attente', epaisseur: 1.25, pointilles: '4 3', pointe: 'pleine' };
}

/** Le glyphe d'état par la FORME — en Ardéchine, la teinte ne dit rien. */
export function glypheStatut(statut: StatutTache): string {
  return statut === 'faite' ? '●' : statut === 'faisable' ? '○' : '◌';
}

/**
 * « Débloque » a UN sens dans tout le réseau (revue du 18 sept. 2026) : les
 * successeures directes encore ouvertes — celles que `goulots` compte, celles
 * que l'arête « A débloque B » nomme. Trois comptes se partageaient le verbe
 * à un clic de distance : la puce « Faisable maintenant » disait « débloque
 * 3 » pour l'aval TRANSITIF de « riz », la revue « débloque 2 » pour les
 * directes ouvertes de « besoin », et la fiche « Débloque 2 » puis « 3 » dès
 * qu'une successeure était faite. L'aval transitif garde son mot : « en
 * aval » (`impact`).
 */
export function debloqueDirectes(reseau: Reseau, id: string): number {
  return (reseau.aval.get(id) ?? []).filter((sid) => reseau.parId.get(sid)?.done === false).length;
}

/** La ligne sous le titre de la fiche : « Attend 2 · Débloque 1 », « Faisable maintenant · Débloque 3 » — les successeures directes ouvertes. */
export function ligneDeComptes(reseau: Reseau, id: string): string {
  const statut = statutDe(reseau, id);
  const v = voisinage(reseau, id);
  const tete =
    statut === 'faite'
      ? 'Faite'
      : statut === 'faisable'
        ? 'Faisable maintenant'
        : `Attend ${v.manquantes.length}`;
  return `${tete} · Débloque ${debloqueDirectes(reseau, id)}`;
}

/** La chaîne d'une tâche, elle comprise : ce que la vue garde net quand le reste s'estompe. */
export function chaineComplete(reseau: Reseau, id: string): Set<string> {
  const v = voisinage(reseau, id);
  return new Set([id, ...v.amontTransitif, ...v.avalTransitif]);
}

/** La forme sous laquelle on lit le réseau : le dessin, ou les mêmes tâches en lignes. */
export type VueReseau = 'graphe' | 'liste';

export function estVueReseau(valeur: unknown): valeur is VueReseau {
  return valeur === 'graphe' || valeur === 'liste';
}

export interface LigneListe {
  id: string;
  statut: StatutTache;
  /** Bloquée : les prédécesseures directes encore ouvertes, par titre. */
  attend: string[];
  /** Faisable : ce que la terminer ouvrirait, par titre. */
  libere: string[];
  /** Les tâches ouvertes en aval, de près ou de loin. */
  aval: number;
}

export interface NiveauListe {
  /** 0 pour les racines. */
  niveau: number;
  lignes: LigneListe[];
}

const RANG_STATUT: Record<StatutTache, number> = { faisable: 0, bloquee: 1, faite: 2 };

/**
 * Le réseau en lignes, par niveau (18 sept. 2026) : à 340 px le graphe est
 * une illustration, pas un outil, et même large il ne dit pas « par quoi je
 * commence ce matin ». Sept tâches sur trois niveaux se lisent en sept
 * lignes. Dans un niveau : les faisables d'abord (celles qui libèrent le
 * plus en tête), puis les bloquées, puis les faites, ex æquo par titre —
 * la première ligne du premier niveau est la tâche à faire ce soir.
 */
export function lignesParNiveau(reseau: Reseau): NiveauListe[] {
  const levels = niveaux(reseau);
  const st = statuts(reseau);
  const parNiveau = new Map<number, LigneListe[]>();
  for (const task of reseau.taches) {
    const statut = st.get(task.id) ?? 'faisable';
    const ligne: LigneListe = {
      id: task.id,
      statut,
      attend: statut === 'bloquee' ? voisinage(reseau, task.id).manquantes : [],
      libere: statut === 'faisable' ? ceQueDebloque(reseau, task.id) : [],
      aval: task.done ? 0 : impact(reseau, task.id),
    };
    const niveau = levels.get(task.id) ?? 0;
    const lignes = parNiveau.get(niveau);
    if (lignes) lignes.push(ligne);
    else parNiveau.set(niveau, [ligne]);
  }
  const titreDe = (id: string) => reseau.parId.get(id)?.title ?? '';
  return [...parNiveau.keys()]
    .sort((a, b) => a - b)
    .map((niveau) => ({
      niveau,
      lignes: (parNiveau.get(niveau) ?? []).sort(
        (a, b) =>
          RANG_STATUT[a.statut] - RANG_STATUT[b.statut] ||
          b.aval - a.aval ||
          titreDe(a.id).localeCompare(titreDe(b.id), 'fr'),
      ),
    }));
}

/**
 * La mention grise sous un titre de la Liste : « attend : X, Y » pour une
 * bloquée, « libère : Z » pour une faisable ; rien pour une faite, ni pour
 * une faisable qui n'ouvre rien seule (« ↓N » le dit déjà quand N ≥ 2).
 */
export function mentionLigne(reseau: Reseau, ligne: LigneListe): string | null {
  const titreDe = (id: string) => reseau.parId.get(id)?.title ?? '';
  if (ligne.statut === 'bloquee' && ligne.attend.length > 0) {
    return `attend : ${ligne.attend.map(titreDe).join(', ')}`;
  }
  if (ligne.statut === 'faisable' && ligne.libere.length > 0) {
    return `libère : ${ligne.libere.map(titreDe).join(', ')}`;
  }
  return null;
}

// ── Le clavier suit les arêtes (§82, 18 sept. 2026) ─────────────────────────
//
// Tab suivait l'ordre du DOM — celui du tableau de tâches, sans rapport avec
// les liens — et aucune flèche ne faisait rien : au clavier, le réseau était
// une liste dans le désordre. Ici, ← et → suivent les arêtes (ce qu'on attend,
// ce qu'on débloque), ↑ et ↓ parcourent une colonne. Pur : le composant ne
// fait que donner le focus à la carte rendue.

export type ToucheFleche = 'ArrowLeft' | 'ArrowRight' | 'ArrowUp' | 'ArrowDown';

const compareTitresParId = (reseau: Reseau) => (a: string, b: string) =>
  (reseau.parId.get(a)?.title ?? '').localeCompare(reseau.parId.get(b)?.title ?? '', 'fr');

/** Parmi `ids`, la carte la plus proche en hauteur de `y` ; ex æquo par titre. */
function laPlusProcheEnY(reseau: Reseau, pos: Map<string, Point>, ids: string[], y: number): string | null {
  const parTitre = compareTitresParId(reseau);
  let meilleure: string | null = null;
  let distance = Number.POSITIVE_INFINITY;
  for (const id of [...ids].sort(parTitre)) {
    const p = pos.get(id);
    if (!p) continue;
    const d = Math.abs(p.y - y);
    if (d < distance) {
      distance = d;
      meilleure = id;
    }
  }
  return meilleure;
}

/**
 * La carte que la flèche atteint depuis `id`, ou null s'il n'y a rien dans
 * cette direction. ← et → vont d'abord à la voisine par arête la plus
 * proche en hauteur ; sans arête de ce côté (une racine, une feuille, une
 * orpheline), à la carte la plus proche de la colonne voisine, pour que
 * rien ne soit hors d'atteinte. ↑ et ↓ restent dans la colonne (même x),
 * toutes bandes confondues.
 */
export function cibleClavier(
  reseau: Reseau,
  pos: Map<string, Point>,
  id: string,
  touche: ToucheFleche,
): string | null {
  const ici = pos.get(id);
  if (!ici) return null;
  if (touche === 'ArrowLeft' || touche === 'ArrowRight') {
    const sens: Sens = touche === 'ArrowLeft' ? 'amont' : 'aval';
    const voisines = ((sens === 'amont' ? reseau.amont : reseau.aval).get(id) ?? []).filter((v) =>
      pos.has(v),
    );
    const parArete = laPlusProcheEnY(reseau, pos, voisines, ici.y);
    if (parArete) return parArete;
    // La colonne voisine : la plus proche en x de ce côté, puis en y.
    let xVoisin: number | null = null;
    for (const [autre, p] of pos) {
      if (autre === id) continue;
      const deCeCote = sens === 'amont' ? p.x < ici.x : p.x > ici.x;
      if (!deCeCote) continue;
      if (xVoisin === null || Math.abs(p.x - ici.x) < Math.abs(xVoisin - ici.x)) xVoisin = p.x;
    }
    if (xVoisin === null) return null;
    const colonne = [...pos.entries()].filter(([, p]) => p.x === xVoisin).map(([k]) => k);
    return laPlusProcheEnY(reseau, pos, colonne, ici.y);
  }
  const parTitre = compareTitresParId(reseau);
  let meilleure: string | null = null;
  let distance = Number.POSITIVE_INFINITY;
  for (const [autre, p] of [...pos.entries()].sort(([a], [b]) => parTitre(a, b))) {
    if (autre === id || p.x !== ici.x) continue;
    const d = touche === 'ArrowUp' ? ici.y - p.y : p.y - ici.y;
    if (d > 0 && d < distance) {
      distance = d;
      meilleure = autre;
    }
  }
  return meilleure;
}

/**
 * La consigne du mode liaison, lue par `aria-live` : elle nomme la source
 * dès qu'elle est choisie (au clic, à L, ou depuis la fiche) et dit les
 * deux chemins, souris et clavier. « Cliquez la tâche à débloquer » ne
 * disait ni laquelle était la source ni qu'Entrée suffisait.
 */
export function consigneLiaison(titreSource: string | null): string {
  if (titreSource === null) {
    return 'Choisissez la tâche source : clic, ou L sur une carte. Échap pour annuler.';
  }
  return `Source : « ${titreSource} ». Choisissez la tâche à débloquer (cible) : clic, ou flèches puis Entrée. Échap pour annuler.`;
}

// ── Tracer un lien en tirant une carte vers l'autre (18 sept. 2026) ─────────
//
// Relier = bouton, clic source, clic cible, en lisant une consigne : trois
// gestes pour un trait, et sur quinze tâches c'est le geste répété le plus
// lent de la vue. Ici, une poignée au bord droit de la carte se tire jusqu'à
// la cible ; le dépôt appelle le même `onLink`, le serveur reste le juge.
// Le bouton, la touche L et la voix restent (§82) : le tirage n'est jamais
// l'unique chemin. Pur : le composant ne fait que lire le pointeur.

/**
 * En deçà de 4 px, un pointeur qui bouge est une main qui tremble : le
 * geste reste un clic (la fiche s'ouvre, la poignée entre en mode liaison).
 * Au-delà, c'est un tirage. 4 et non 2 : au trackpad, un clic sans intention
 * dérive déjà de 1 à 3 px.
 */
export const SEUIL_TIRAGE_PX = 4;

export function aBouge(depart: Point, arrivee: Point, seuil = SEUIL_TIRAGE_PX): boolean {
  return Math.hypot(arrivee.x - depart.x, arrivee.y - depart.y) > seuil;
}

export type VerdictDepot = 'aucune' | 'meme-tache' | 'boucle' | 'deja' | 'ok';

/**
 * Ce que déposer le trait sur `to` ferait. `deja` : le serveur est idempotent
 * sur un doublon et ne l'enregistre pas — le dire ici évite un toast
 * « Dépendance ajoutée » pour un lien qui existait (§100).
 */
export function verdictDepot(reseau: Reseau, from: string, to: string | null): VerdictDepot {
  if (to === null || !reseau.parId.has(to)) return 'aucune';
  if (to === from) return 'meme-tache';
  if ((reseau.aval.get(from) ?? []).includes(to)) return 'deja';
  if (fermeraitUneBoucle(reseau, from, to)) return 'boucle';
  return 'ok';
}

/** « « A » attend déjà « B », de près ou de loin : ce lien fermerait une boucle. » */
export function phraseBoucle(reseau: Reseau, from: string, to: string): string {
  const titreDe = (id: string) => reseau.parId.get(id)?.title ?? '';
  return `« ${titreDe(from)} » attend déjà « ${titreDe(to)} », de près ou de loin : ce lien fermerait une boucle.`;
}

/** Ce que le dépôt dit quand il ne crée rien ; null quand il crée (la phrase vient alors du serveur). */
export function phraseDepot(reseau: Reseau, from: string, to: string | null): string | null {
  const titreDe = (id: string) => reseau.parId.get(id)?.title ?? '';
  switch (verdictDepot(reseau, from, to)) {
    case 'boucle':
      return phraseBoucle(reseau, from, to as string);
    case 'deja':
      return `« ${titreDe(from)} » débloque déjà « ${titreDe(to as string)} ».`;
    default:
      return null;
  }
}

/**
 * Ce qu'une cible dit d'elle-même, une fois la source choisie (Relier,
 * L, « Relier depuis ici », tirage) : pourquoi elle est impossible, ou null
 * quand elle ne l'est pas. Jusqu'à la revue du 18 sept. 2026, seule la
 * boucle était dite avant le clic ; une cible déjà reliée restait libellée
 * « Choisir comme cible ».
 */
export function motifCibleImpossible(reseau: Reseau, from: string, to: string): string | null {
  const titreDe = (id: string) => reseau.parId.get(id)?.title ?? '';
  switch (verdictDepot(reseau, from, to)) {
    case 'boucle':
      return 'Impossible : fermerait une boucle';
    case 'deja':
      return `Déjà reliée : « ${titreDe(from)} » la débloque déjà`;
    default:
      return null;
  }
}

export type ActionLiaison =
  | { type: 'choisir-source' }
  | { type: 'annuler-source' }
  | { type: 'refus'; phrase: string }
  | { type: 'lier'; from: string; to: string };

/**
 * Ce qu'activer une carte fait en mode liaison — au clic, à Entrée, depuis
 * la Liste : le MÊME verdict que le tirage (`verdictDepot`). Jusqu'à la
 * revue du 18 sept. 2026, ce chemin ne regardait que la boucle : sur une
 * arête déjà présente, il envoyait un POST que le serveur rendait sans rien
 * enregistrer, et le toast disait « Dépendance ajoutée » pour un lien qui
 * existait — la phrase venait de l'émetteur (§100), là où le tirage disait
 * déjà « débloque déjà ». Ici un doublon ou une boucle est un refus, sans
 * rien envoyer ; seul `lier` part au serveur, qui reste le juge.
 */
export function actionLiaison(reseau: Reseau, from: string | null, id: string): ActionLiaison {
  if (from === null) return { type: 'choisir-source' };
  if (from === id) return { type: 'annuler-source' };
  const phrase = phraseDepot(reseau, from, id);
  if (phrase !== null) return { type: 'refus', phrase };
  return { type: 'lier', from, to: id };
}

/**
 * La courbe du trait tiré, du bord droit de la source au pointeur — même
 * forme que les arêtes (`cheminArete`), pour que le trait posé ressemble à
 * celui qu'on tire. Quand le pointeur est à gauche de la source, la courbe
 * se replie sans s'écraser : `dx` garde 28 px de tangente.
 */
export function cheminElastique(depart: Point, arrivee: Point): string {
  const dx = Math.max(28, Math.abs(arrivee.x - depart.x) / 2);
  return `M ${depart.x} ${depart.y} C ${depart.x + dx} ${depart.y}, ${arrivee.x - dx} ${arrivee.y}, ${arrivee.x} ${arrivee.y}`;
}

/**
 * La consigne du tirage, lue par `aria-live` : la source, puis ce qu'un
 * dépôt sur la cible survolée ferait. Une cible impossible est dite AVANT
 * le dépôt, comme en mode liaison.
 */
export function consigneTirage(reseau: Reseau, from: string, to: string | null): string {
  const titreDe = (id: string) => reseau.parId.get(id)?.title ?? '';
  const tete = `Tirage depuis « ${titreDe(from)} »`;
  switch (verdictDepot(reseau, from, to)) {
    case 'ok':
      return `${tete} : déposer pour débloquer « ${titreDe(to as string)} ».`;
    case 'boucle':
      return `${tete} : « ${titreDe(to as string)} » est impossible, ce lien fermerait une boucle.`;
    case 'deja':
      return `${tete} : « ${titreDe(to as string)} » est déjà débloquée par elle.`;
    default:
      return `${tete} : déposer sur la tâche à débloquer. Échap pour annuler.`;
  }
}
