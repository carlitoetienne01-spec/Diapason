import { describe, expect, it } from 'vitest';

import {
  HAUTEUR_LIBELLE_COULOIR,
  aretesDeChaine,
  aretesLiberees,
  categories,
  ceQueDebloque,
  ceQueRebloque,
  chaine,
  citer,
  chaineComplete,
  chaineLaPlusLongue,
  cibleClavier,
  colonnesInitiales,
  consigneLiaison,
  estVueReseau,
  lignesParNiveau,
  mentionLigne,
  compterCroisements,
  composantes,
  comptes,
  construireReseau,
  dispositionBouge,
  disposer,
  disposerParComposantes,
  disposerParCouloirs,
  estOrpheline,
  faisables,
  fermeraitUneBoucle,
  glypheStatut,
  goulots,
  impact,
  interpolerPositions,
  libelleEnTete,
  libelleRevue,
  ligneDeComptes,
  margeDe,
  niveaux,
  ordonnerColonnes,
  orphelines,
  phraseApresBascule,
  placeSurLeFil,
  positionner,
  statutDe,
  statuts,
  traitArete,
  voisinSuivant,
  voisinage,
  aDesDurees,
  dureeDe,
  finProjetee,
  joursDeChaine,
  lireDureeSaisie,
  margeJours,
  aBouge,
  cheminElastique,
  consigneTirage,
  phraseBoucle,
  phraseDepot,
  verdictDepot,
  SEUIL_TIRAGE_PX,
  actionLiaison,
  cheminCritique,
  debloqueDirectes,
  estimation,
  estimationComplete,
  libelleEstimation,
  motifCibleImpossible,
  type Point,
} from './reseau';
import type { SuccesTask, SuccesTaskEdge } from './types';

const tache = (id: string, title: string, done = false): SuccesTask => ({
  id,
  title,
  done,
  priority: 'medium',
  date: '',
  time: '',
  projectId: 'agri',
  parentTaskId: '',
  category: '',
  notes: '',
  emoji: '',
  templateId: '',
  groupId: '',
  order: 0,
  createdAt: '',
  completedDate: '',
  postponedCount: 0,
  estimateDays: 0,
  updatedAtMs: 0,
  stage: '',
  cadence: null,
  subtasks: [],
});

const arete = (fromTaskId: string, toTaskId: string): SuccesTaskEdge => ({
  projectId: 'agri',
  fromTaskId,
  toTaskId,
  updatedAtMs: 0,
});

/**
 * AgriCulture, tel qu'il est dans ~/.diapason/succes.db le 18 sept. 2026 :
 * sept tâches ouvertes, cinq arêtes, deux chaînes sans rapport.
 *
 *   agriculteurs → discuter → contrat
 *   riz → besoin → budget
 *                → tracteur
 */
const AGRI = [
  tache('tracteur', 'Avoir besoin d’un tracteur'),
  tache('agri', 'Avoir les bons agriculteurs pour le projet'),
  tache('budget', 'Avoir un budget bien detaillé ?'),
  tache('contrat', 'Contrat | Paiement par jours de travail ou commission'),
  tache('discuter', 'Discuter du contrat avec les agriculteurs'),
  tache('riz', 'Qu’est ce que nou allons commencer avec en premier | Riz ou Haricots ?'),
  tache('besoin', 'Qu’est-ce qu’on aura besoin en premier ?'),
];
const ARETES = [
  arete('agri', 'discuter'),
  arete('discuter', 'contrat'),
  arete('besoin', 'budget'),
  arete('riz', 'besoin'),
  arete('besoin', 'tracteur'),
];

const agriculture = () => construireReseau(AGRI, ARETES);

/** Le même projet, une fois « agriculteurs » cochée sur le serveur. */
const agricultureApresAgri = () =>
  construireReseau(
    AGRI.map((t) => (t.id === 'agri' ? { ...t, done: true } : t)),
    ARETES,
  );

describe('construireReseau', () => {
  it('écarte une arête dont un bout n’existe plus', () => {
    const reseau = construireReseau(AGRI, [...ARETES, arete('agri', 'fantome')]);
    expect(reseau.aretes).toHaveLength(5);
    expect(reseau.aval.get('agri')).toEqual(['discuter']);
  });
});

describe('niveaux', () => {
  it('place AgriCulture sur trois colonnes', () => {
    const n = niveaux(agriculture());
    expect(n.get('agri')).toBe(0);
    expect(n.get('riz')).toBe(0);
    expect(n.get('discuter')).toBe(1);
    expect(n.get('besoin')).toBe(1);
    expect(n.get('contrat')).toBe(2);
    expect(n.get('budget')).toBe(2);
    expect(n.get('tracteur')).toBe(2);
  });

  it('rend des niveaux finis sur une boucle relayée par un pair', () => {
    // test_structures.py : t1→t2 puis t2→t1 reçue d'un autre appareil, acceptée.
    const reseau = construireReseau(
      [tache('t1', 'un'), tache('t2', 'deux'), tache('t3', 'trois')],
      [arete('t1', 't2'), arete('t2', 't1'), arete('t2', 't3')],
    );
    const n = niveaux(reseau);
    for (const id of ['t1', 't2', 't3']) {
      expect(Number.isFinite(n.get(id)), `le niveau de ${id} doit être fini`).toBe(true);
    }
    expect(n.get('t3')).toBeGreaterThan(n.get('t2') ?? 0);
  });
});

describe('statuts', () => {
  it('deux faisables, cinq bloquées, aucune faite', () => {
    const st = statuts(agriculture());
    expect([...st.values()].filter((s) => s === 'faisable')).toHaveLength(2);
    expect([...st.values()].filter((s) => s === 'bloquee')).toHaveLength(5);
    expect(st.get('agri')).toBe('faisable');
    expect(st.get('riz')).toBe('faisable');
    expect(st.get('discuter')).toBe('bloquee');
  });

  it('une tâche faite ne bloque plus ce qu’elle débloquait', () => {
    const st = statuts(agricultureApresAgri());
    expect(st.get('agri')).toBe('faite');
    expect(st.get('discuter')).toBe('faisable');
    expect(st.get('contrat')).toBe('bloquee');
  });

  it('une tâche inconnue est traitée comme faite — elle ne bloque rien', () => {
    expect(statutDe(agriculture(), 'nulle-part')).toBe('faite');
  });

  it('les faisables se lisent par ce qu’elles libèrent : « riz » (3) avant « agriculteurs » (2)', () => {
    expect(faisables(agriculture()).map((t) => t.id)).toEqual(['riz', 'agri']);
  });

  it('à impact égal, les faisables se lisent par titre', () => {
    const reseau = construireReseau(
      [tache('z', 'zèbre'), tache('a', 'âne'), tache('c', 'cible')],
      [arete('z', 'c'), arete('a', 'c')],
    );
    expect(faisables(reseau).map((t) => t.id)).toEqual(['a', 'z']);
  });

  it('les glyphes disent l’état par la forme', () => {
    expect(glypheStatut('faite')).toBe('●');
    expect(glypheStatut('faisable')).toBe('○');
    expect(glypheStatut('bloquee')).toBe('◌');
  });
});

describe('voisinage', () => {
  it('« besoin » attend riz et débloque budget et tracteur', () => {
    const v = voisinage(agriculture(), 'besoin');
    expect(v.amont).toEqual(['riz']);
    expect(v.aval).toEqual(['tracteur', 'budget']);
    expect(v.amontTransitif).toEqual(['riz']);
    expect(v.avalTransitif).toEqual(['tracteur', 'budget']);
    expect(v.manquantes).toEqual(['riz']);
  });

  it('« contrat » remonte toute sa chaîne et ne débloque rien', () => {
    const v = voisinage(agriculture(), 'contrat');
    expect(v.amont).toEqual(['discuter']);
    expect(v.amontTransitif).toEqual(['discuter', 'agri']);
    expect(v.aval).toEqual([]);
    expect(v.avalTransitif).toEqual([]);
  });

  it('une attente faite n’est plus manquante, et passe après les ouvertes', () => {
    const reseau = construireReseau(
      [tache('a', 'zèbre', true), tache('b', 'âne'), tache('c', 'cible')],
      [arete('a', 'c'), arete('b', 'c')],
    );
    const v = voisinage(reseau, 'c');
    expect(v.amont).toEqual(['b', 'a']);
    expect(v.manquantes).toEqual(['b']);
  });

  it('la chaîne indente par profondeur et ne repasse jamais deux fois', () => {
    const c = chaine(agriculture(), 'riz', 'aval');
    expect(c).toEqual([
      { id: 'besoin', profondeur: 1 },
      { id: 'tracteur', profondeur: 2 },
      { id: 'budget', profondeur: 2 },
    ]);
    const boucle = construireReseau(
      [tache('t1', 'un'), tache('t2', 'deux')],
      [arete('t1', 't2'), arete('t2', 't1')],
    );
    expect(chaine(boucle, 't1', 'aval')).toEqual([{ id: 't2', profondeur: 1 }]);
  });

  it('← et → sautent à la première voisine, ou nulle part', () => {
    const reseau = agriculture();
    expect(voisinSuivant(reseau, 'besoin', 'amont')).toBe('riz');
    expect(voisinSuivant(reseau, 'besoin', 'aval')).toBe('tracteur');
    expect(voisinSuivant(reseau, 'agri', 'amont')).toBeNull();
    expect(voisinSuivant(reseau, 'contrat', 'aval')).toBeNull();
  });

  it('la chaîne complète est ce que le graphe garde net derrière la fiche', () => {
    expect([...chaineComplete(agriculture(), 'besoin')].sort()).toEqual(
      ['besoin', 'budget', 'riz', 'tracteur'],
    );
  });

  it('la ligne de comptes dit l’état puis ce que ça débloque', () => {
    const reseau = agriculture();
    expect(ligneDeComptes(reseau, 'agri')).toBe('Faisable maintenant · Débloque 1');
    expect(ligneDeComptes(reseau, 'besoin')).toBe('Attend 1 · Débloque 2');
    expect(ligneDeComptes(reseau, 'contrat')).toBe('Attend 1 · Débloque 0');
    expect(ligneDeComptes(agricultureApresAgri(), 'agri')).toBe('Faite · Débloque 1');
  });

  it('« débloque » ne compte que les successeures directes OUVERTES — le même nombre dans la fiche et la revue', () => {
    // §5, revue du 18 sept. 2026 : riz et budget faites, la fiche de « besoin »
    // disait « Débloque 2 » en comptant budget, déjà faite ; la revue « débloque 1 ».
    const reseau = construireReseau(
      AGRI.map((t) => (t.id === 'riz' || t.id === 'budget' ? { ...t, done: true } : t)),
      ARETES,
    );
    expect(debloqueDirectes(reseau, 'besoin')).toBe(1);
    expect(ligneDeComptes(reseau, 'besoin')).toBe('Faisable maintenant · Débloque 1');
    expect(goulots(agriculture())[0]).toEqual({ id: 'besoin', debloque: debloqueDirectes(agriculture(), 'besoin') });
    // L'aval transitif garde son mot : « riz » a 3 tâches en aval et n'en débloque qu'une.
    expect(impact(agriculture(), 'riz')).toBe(3);
    expect(debloqueDirectes(agriculture(), 'riz')).toBe(1);
  });
});

describe('ceQueDebloque et impact', () => {
  it('cocher « agriculteurs » ouvre « discuter » — calculé sur l’état rechargé', () => {
    expect(ceQueDebloque(agricultureApresAgri(), 'agri')).toEqual(['discuter']);
  });

  it('n’annonce rien quand une autre attente reste ouverte', () => {
    const reseau = construireReseau(
      [tache('a', 'a', true), tache('b', 'b'), tache('c', 'c')],
      [arete('a', 'c'), arete('b', 'c')],
    );
    expect(ceQueDebloque(reseau, 'a')).toEqual([]);
  });

  it('n’annonce jamais une tâche déjà faite', () => {
    const reseau = construireReseau(
      [tache('a', 'a', true), tache('c', 'c', true)],
      [arete('a', 'c')],
    );
    expect(ceQueDebloque(reseau, 'a')).toEqual([]);
  });

  it('« riz » pèse trois tâches, « agriculteurs » deux, « tracteur » rien', () => {
    const reseau = agriculture();
    expect(impact(reseau, 'riz')).toBe(3);
    expect(impact(reseau, 'agri')).toBe(2);
    expect(impact(reseau, 'tracteur')).toBe(0);
  });

  it('l’impact ne compte pas les tâches faites en aval', () => {
    const reseau = construireReseau(
      [tache('a', 'a'), tache('b', 'b', true), tache('c', 'c')],
      [arete('a', 'b'), arete('b', 'c')],
    );
    expect(impact(reseau, 'a')).toBe(1);
  });

  it('rouvrir « agriculteurs » rebloque « discuter », qui était devenue faisable', () => {
    expect(ceQueRebloque(agriculture(), 'agri')).toEqual(['discuter']);
  });
});

describe('phraseApresBascule — la phrase vient de l’état rechargé', () => {
  it('cite ce qui vient de s’ouvrir', () => {
    expect(phraseApresBascule(agricultureApresAgri(), 'agri')).toEqual({
      titre: 'Tâche terminée',
      description: 'Débloque « Discuter du contrat avec les agriculteurs ».',
    });
  });

  it('dit « rien de nouveau » et nomme ce que la successeure attend encore', () => {
    const reseau = construireReseau(
      [tache('a', 'Acheter', true), tache('b', 'Bêcher'), tache('c', 'Cultiver')],
      [arete('a', 'c'), arete('b', 'c')],
    );
    expect(phraseApresBascule(reseau, 'a')).toEqual({
      titre: 'Tâche terminée',
      description: 'Rien de nouveau : « Cultiver » attend encore « Bêcher ».',
    });
  });

  it('dit que rien ne l’attendait quand la tâche est une feuille', () => {
    const reseau = construireReseau(
      AGRI.map((t) => (t.id === 'tracteur' ? { ...t, done: true } : t)),
      ARETES,
    );
    expect(phraseApresBascule(reseau, 'tracteur').description).toBe('Rien ne l’attendait.');
  });

  it('rouvrir dit ce qui se rebloque, ou que rien ne bouge', () => {
    expect(phraseApresBascule(agriculture(), 'agri')).toEqual({
      titre: 'Tâche rouverte',
      description: 'Rebloque « Discuter du contrat avec les agriculteurs ».',
    });
    expect(phraseApresBascule(agriculture(), 'contrat').description).toBe('Rien ne se rebloque.');
  });

  it('ne prétend rien sur une tâche absente de l’état rechargé', () => {
    expect(phraseApresBascule(agriculture(), 'disparue').titre).toBe('Tâche mise à jour');
  });

  it('cite deux ou trois titres avec « et »', () => {
    expect(citer(['A'])).toBe('« A »');
    expect(citer(['A', 'B'])).toBe('« A » et « B »');
    expect(citer(['A', 'B', 'C'])).toBe('« A », « B » et « C »');
  });
});

describe('aretesLiberees — ce que l’impulsion parcourt', () => {
  it('trouve l’arête agriculteurs → discuter une fois la coche rechargée', () => {
    const avant = statuts(agriculture());
    expect(aretesLiberees(avant, agricultureApresAgri())).toEqual([{ from: 'agri', to: 'discuter' }]);
  });

  it('n’allume rien quand rien n’a changé, ni sur une tâche déjà faite avant', () => {
    expect(aretesLiberees(statuts(agriculture()), agriculture())).toEqual([]);
    const apres = agricultureApresAgri();
    expect(aretesLiberees(statuts(apres), apres)).toEqual([]);
  });

  it('n’allume rien vers une cible qui attend encore ailleurs', () => {
    const avant = construireReseau(
      [tache('a', 'a'), tache('b', 'b'), tache('c', 'c')],
      [arete('a', 'c'), arete('b', 'c')],
    );
    const apres = construireReseau(
      [tache('a', 'a', true), tache('b', 'b'), tache('c', 'c')],
      [arete('a', 'c'), arete('b', 'c')],
    );
    expect(aretesLiberees(statuts(avant), apres)).toEqual([]);
  });

  it('ignore une tâche inconnue de l’état précédent — un autre projet, pas une coche', () => {
    expect(aretesLiberees(new Map(), agricultureApresAgri())).toEqual([]);
  });
});

describe('fermeraitUneBoucle', () => {
  it('refuse ce que le serveur refuse : le retour vers l’amont', () => {
    const reseau = agriculture();
    expect(fermeraitUneBoucle(reseau, 'contrat', 'agri')).toBe(true);
    expect(fermeraitUneBoucle(reseau, 'discuter', 'agri')).toBe(true);
    expect(fermeraitUneBoucle(reseau, 'budget', 'riz')).toBe(true);
  });

  it('laisse passer ce qui ne boucle pas, dont un doublon', () => {
    const reseau = agriculture();
    expect(fermeraitUneBoucle(reseau, 'budget', 'tracteur')).toBe(false);
    expect(fermeraitUneBoucle(reseau, 'contrat', 'riz')).toBe(false);
    expect(fermeraitUneBoucle(reseau, 'agri', 'discuter')).toBe(false);
  });

  it('une tâche ne peut pas s’attendre elle-même', () => {
    expect(fermeraitUneBoucle(agriculture(), 'agri', 'agri')).toBe(true);
  });
});

describe('chaineLaPlusLongue', () => {
  it('sur AgriCulture : agriculteurs → discuter → contrat, trois tâches', () => {
    expect(chaineLaPlusLongue(agriculture())).toEqual(['agri', 'discuter', 'contrat']);
  });

  it('ne compte que les tâches ouvertes, et tranche l’égalité par les titres', () => {
    // « Avoir besoin d’un tracteur » passe avant « Avoir un budget » : la
    // chaîne choisie ne change pas d'un rendu à l'autre.
    expect(chaineLaPlusLongue(agricultureApresAgri())).toEqual(['riz', 'besoin', 'tracteur']);
  });

  it('est vide sans tâche ouverte', () => {
    const reseau = construireReseau([tache('a', 'a', true)], []);
    expect(chaineLaPlusLongue(reseau)).toEqual([]);
  });

  it('reste finie sur une boucle relayée', () => {
    const reseau = construireReseau(
      [tache('t1', 'un'), tache('t2', 'deux')],
      [arete('t1', 't2'), arete('t2', 't1')],
    );
    expect(chaineLaPlusLongue(reseau).length).toBeLessThanOrEqual(2);
  });

  it('ses arêtes portent la clé que la vue emploie', () => {
    expect([...aretesDeChaine(['agri', 'discuter', 'contrat'])]).toEqual([
      'agri->discuter',
      'discuter->contrat',
    ]);
    expect(aretesDeChaine(['seule']).size).toBe(0);
  });
});

describe('placeSurLeFil — sans inventer un chemin critique', () => {
  it('« contrat » est sur la chaîne la plus longue, « tracteur » sur une aussi longue', () => {
    const reseau = agriculture();
    expect(margeDe(reseau, 'contrat')).toBe(0);
    expect(placeSurLeFil(reseau, 'contrat')).toBe('Sur la chaîne la plus longue');
    expect(margeDe(reseau, 'tracteur')).toBe(0);
    expect(placeSurLeFil(reseau, 'tracteur')).toBe('Sur une chaîne aussi longue que le fil');
  });

  it('une tâche sans lien a deux tâches de marge sur AgriCulture', () => {
    const reseau = construireReseau([...AGRI, tache('x', 'Xylophone')], ARETES);
    expect(margeDe(reseau, 'x')).toBe(2);
    expect(placeSurLeFil(reseau, 'x')).toBe('Marge : 2 tâches');
  });

  it('accorde « tâche » au singulier, et se tait sur une tâche faite', () => {
    // a → b (2) face à s → t → u (3) : une tâche de marge.
    const courte = construireReseau(
      [tache('a', 'a'), tache('b', 'b'), tache('s', 's'), tache('t', 't'), tache('u', 'u')],
      [arete('a', 'b'), arete('s', 't'), arete('t', 'u')],
    );
    expect(placeSurLeFil(courte, 'a')).toBe('Marge : 1 tâche');
    const faite = construireReseau(
      [tache('a', 'a', true), tache('b', 'b')],
      [arete('a', 'b')],
    );
    expect(placeSurLeFil(faite, 'a')).toBeNull();
  });

  it('les tâches faites en amont ne rallongent pas la chaîne', () => {
    // Une fois « agriculteurs » faite, la chaîne de contrat ne fait plus que deux :
    // le fil passe à riz → besoin → tracteur, et contrat a une tâche de marge.
    const reseau = agricultureApresAgri();
    expect(placeSurLeFil(reseau, 'contrat')).toBe('Marge : 1 tâche');
    expect(placeSurLeFil(reseau, 'tracteur')).toBe('Sur la chaîne la plus longue');
  });

  it('sur une boucle relayée, la marge n’est jamais négative (§5)', () => {
    // t1→t2, t2→t1 (acceptée à la réception, test_structures.py) et t2→t3 :
    // la fiche écrivait « Marge : -1 tâche » (revue du réseau, 18 sept. 2026).
    const reseau = construireReseau(
      [tache('t1', 'un'), tache('t2', 'deux'), tache('t3', 'trois')],
      [arete('t1', 't2'), arete('t2', 't1'), arete('t2', 't3')],
    );
    for (const id of ['t1', 't2', 't3']) {
      const marge = margeDe(reseau, id);
      expect(marge, `marge de ${id}`).not.toBeNull();
      expect(marge as number, `marge de ${id}`).toBeGreaterThanOrEqual(0);
      expect(placeSurLeFil(reseau, id), `place de ${id}`).not.toMatch(/-/);
    }
  });
});

describe('comptes et en-tête', () => {
  it('AgriCulture : 2 faisables, 5 bloquées, 0 faite, profondeur 3', () => {
    expect(comptes(agriculture())).toEqual({
      faisables: 2,
      bloquees: 5,
      faites: 0,
      profondeur: 3,
      // Aucune durée sur AgriCulture : pas de fin projetée, pas de « chemin critique ».
      joursProjetes: null,
      estimees: 0,
      ouvertes: 7,
    });
    expect(libelleEnTete(comptes(agriculture()))).toBe('2 faisables · 5 bloquées · profondeur 3');
  });

  it('accorde le singulier', () => {
    const reseau = construireReseau([tache('a', 'a'), tache('b', 'b')], [arete('a', 'b')]);
    expect(libelleEnTete(comptes(reseau))).toBe('1 faisable · 1 bloquée · profondeur 2');
  });

  it('un projet fini a une profondeur de zéro', () => {
    const reseau = construireReseau([tache('a', 'a', true), tache('b', 'b', true)], [arete('a', 'b')]);
    expect(comptes(reseau)).toEqual({
      faisables: 0,
      bloquees: 0,
      faites: 2,
      profondeur: 0,
      joursProjetes: null,
      estimees: 0,
      ouvertes: 0,
    });
  });
});

describe('colonnes', () => {
  it('l’ordre alphabétique croise deux flèches sur cinq', () => {
    const reseau = agriculture();
    const colonnes = colonnesInitiales(reseau);
    expect(colonnes).toEqual([
      ['agri', 'riz'],
      ['discuter', 'besoin'],
      ['tracteur', 'budget', 'contrat'],
    ]);
    expect(compterCroisements(reseau, colonnes)).toBe(2);
  });

  it('le barycentre les décroise toutes', () => {
    const reseau = agriculture();
    const colonnes = ordonnerColonnes(reseau);
    expect(compterCroisements(reseau, colonnes)).toBe(0);
    expect(colonnes[0]).toEqual(['agri', 'riz']);
    expect(colonnes[2]).toEqual(['contrat', 'tracteur', 'budget']);
  });

  it('les faites descendent en bas de leur colonne', () => {
    const colonnes = colonnesInitiales(agricultureApresAgri());
    expect(colonnes[0]).toEqual(['riz', 'agri']);
  });

  it('une arête à cheval sur deux colonnes compte ses croisements', () => {
    const reseau = construireReseau(
      ['a', 'b', 'c', 'd', 'e'].map((id) => tache(id, id)),
      [arete('a', 'e'), arete('b', 'c'), arete('c', 'd')],
    );
    // a→e saute la colonne 1 et passe au travers de b→c quand a est au-dessus de b.
    expect(compterCroisements(reseau, [['a', 'b'], ['c'], ['d', 'e']])).toBe(1);
    expect(compterCroisements(reseau, [['b', 'a'], ['c'], ['d', 'e']])).toBe(0);
  });

  it('ne réordonne rien quand rien ne se croise', () => {
    // Un ordre déjà bon reste l'ordre alphabétique : stable d'un rendu à l'autre.
    const reseau = construireReseau(
      ['a', 'b', 'c', 'd'].map((id) => tache(id, id)),
      [arete('a', 'c'), arete('b', 'd')],
    );
    expect(ordonnerColonnes(reseau)).toEqual(colonnesInitiales(reseau));
  });

  it('garde chaque tâche une fois et une seule après le décroisement', () => {
    const colonnes = ordonnerColonnes(agriculture()).flat().sort();
    expect(colonnes).toEqual(AGRI.map((t) => t.id).sort());
  });

  it('positionner donne la géométrie et rien d’autre', () => {
    const d = positionner([['a', 'b'], ['c']], {
      largeurCarte: 100,
      hauteurCarte: 50,
      ecartX: 20,
      ecartY: 10,
      marge: 5,
    });
    expect(d.pos.get('b')).toEqual({ x: 5, y: 65 });
    expect(d.pos.get('c')).toEqual({ x: 125, y: 5 });
    expect(d.largeur).toBe(5 * 2 + 2 * 100 + 20);
    expect(d.hauteur).toBe(5 * 2 + 2 * 50 + 10);
  });
});

describe('glissement des cartes', () => {
  const depart = new Map([
    ['a', { x: 0, y: 0 }],
    ['b', { x: 0, y: 100 }],
  ]);
  const arrivee = new Map([
    ['a', { x: 0, y: 100 }],
    ['b', { x: 0, y: 0 }],
    ['c', { x: 50, y: 50 }],
  ]);

  it('à 0 les cartes sont au départ, à 1 à l’arrivée, entre les deux en sortie douce', () => {
    expect(interpolerPositions(depart, arrivee, 0).get('a')).toEqual({ x: 0, y: 0 });
    expect(interpolerPositions(depart, arrivee, 1).get('a')).toEqual({ x: 0, y: 100 });
    const milieu = interpolerPositions(depart, arrivee, 0.5).get('a') as { x: number; y: number };
    // Sortie cubique : à mi-temps, 87,5 % du chemin est fait — la carte
    // part vite et se pose lentement.
    expect(milieu.y).toBeCloseTo(87.5);
  });

  it('une carte nouvelle apparaît directement à l’arrivée, et t est borné', () => {
    expect(interpolerPositions(depart, arrivee, 0.2).get('c')).toEqual({ x: 50, y: 50 });
    expect(interpolerPositions(depart, arrivee, 7).get('b')).toEqual({ x: 0, y: 0 });
    expect(interpolerPositions(depart, arrivee, -1).get('b')).toEqual({ x: 0, y: 100 });
  });

  it('ne glisse pas quand aucune carte connue ne bouge', () => {
    expect(dispositionBouge(depart, arrivee)).toBe(true);
    expect(dispositionBouge(depart, new Map([['a', { x: 0, y: 0 }], ['z', { x: 9, y: 9 }]]))).toBe(false);
    expect(dispositionBouge(new Map(), arrivee)).toBe(false);
  });
});

describe('traitArete', () => {
  it('dit l’état par la forme : fin et creux, plein, pointillé', () => {
    expect(traitArete('faite')).toMatchObject({ etat: 'satisfaite', epaisseur: 1, pointe: 'creuse' });
    expect(traitArete('faite').pointilles).toBeUndefined();
    expect(traitArete('faisable')).toMatchObject({ etat: 'prochaine', epaisseur: 1.75, pointe: 'pleine' });
    expect(traitArete('bloquee')).toMatchObject({ etat: 'en-attente', pointilles: '4 3' });
  });

  it('sur AgriCulture, les arêtes des racines sont « prochaines », les autres en attente', () => {
    const reseau = agriculture();
    const st = statuts(reseau);
    const etats = ARETES.map((a) => traitArete(st.get(a.fromTaskId) ?? 'faisable').etat);
    expect(etats).toEqual(['prochaine', 'en-attente', 'en-attente', 'prochaine', 'en-attente']);
  });

  it('une fois « agriculteurs » faite, son arête est satisfaite et celle de « discuter » devient prochaine', () => {
    const reseau = agricultureApresAgri();
    const st = statuts(reseau);
    expect(traitArete(st.get('agri') ?? 'faisable').etat).toBe('satisfaite');
    expect(traitArete(st.get('discuter') ?? 'faisable').etat).toBe('prochaine');
  });
});

describe('revue du réseau', () => {
  it('AgriCulture a deux composantes, la plus grande d’abord, chacune par titre', () => {
    expect(composantes(agriculture())).toEqual([
      ['tracteur', 'budget', 'riz', 'besoin'],
      ['agri', 'contrat', 'discuter'],
    ]);
  });

  it('une tâche seule est une composante, et une orpheline si elle est ouverte', () => {
    const reseau = construireReseau([...AGRI, tache('x', 'Xylophone'), tache('f', 'Finie', true)], ARETES);
    expect(composantes(reseau)).toHaveLength(4);
    expect(orphelines(reseau)).toEqual(['x']);
    expect(estOrpheline(reseau, 'f')).toBe(true);
    expect(estOrpheline(reseau, 'agri')).toBe(false);
    expect(orphelines(agriculture())).toEqual([]);
  });

  it('« besoin » est le goulot d’AgriCulture : deux tâches l’attendent directement', () => {
    expect(goulots(agriculture())).toEqual([{ id: 'besoin', debloque: 2 }]);
    const apres = construireReseau(
      AGRI.map((t) => (t.id === 'besoin' ? { ...t, done: true } : t)),
      ARETES,
    );
    expect(goulots(apres)).toEqual([]);
  });

  it('la ligne de revue nomme le goulot', () => {
    expect(libelleRevue(agriculture())).toBe(
      '2 chaînes indépendantes · 0 orpheline · goulot : « Qu’est-ce qu’on aura besoin en premier ? » (débloque 2)',
    );
  });

  it('la ligne de revue s’accorde : une chaîne, deux orphelines, aucun goulot', () => {
    const reseau = construireReseau(
      [tache('a', 'a'), tache('b', 'b'), tache('x', 'x'), tache('y', 'y')],
      [arete('a', 'b')],
    );
    expect(libelleRevue(reseau)).toBe('1 chaîne · 2 orphelines · aucun goulot');
    expect(libelleRevue(construireReseau([tache('x', 'x')], []))).toBe('aucune chaîne · 1 orpheline · aucun goulot');
  });
});

describe('disposerParComposantes', () => {
  const dims = { largeurCarte: 100, hauteurCarte: 50, ecartX: 20, ecartY: 10, marge: 5 };

  it('empile les deux chaînes d’AgriCulture, la plus grande en haut, un filet entre', () => {
    const reseau = agriculture();
    const d = disposerParComposantes(reseau, dims);
    expect(d.separateurs).toHaveLength(1);
    const yRiz = d.pos.get('riz')?.y ?? Number.NaN;
    const yAgri = d.pos.get('agri')?.y ?? Number.NaN;
    expect(yRiz).toBeLessThan(d.separateurs[0]);
    expect(yAgri).toBeGreaterThan(d.separateurs[0]);
    expect(d.pos.size).toBe(7);
    // Chaque bande a trois colonnes : la largeur est celle d'une bande.
    expect(d.largeur).toBe(5 * 2 + 3 * 100 + 2 * 20);
    // Deux bandes de deux lignes (riz→besoin→{tracteur,budget}) et une ligne.
    expect(d.hauteur).toBe((5 * 2 + 2 * 50 + 10) + (5 * 2 + 50));
  });

  it('ne change rien à une seule composante', () => {
    const reseau = construireReseau(
      [tache('a', 'a'), tache('b', 'b'), tache('c', 'c')],
      [arete('a', 'b'), arete('b', 'c')],
    );
    const attendu = positionner(ordonnerColonnes(reseau), dims);
    const d = disposerParComposantes(reseau, dims);
    expect(d.separateurs).toEqual([]);
    expect([...d.pos.entries()]).toEqual([...attendu.pos.entries()]);
    expect(d.hauteur).toBe(attendu.hauteur);
  });

  it('range les tâches seules en grille dans une dernière bande', () => {
    const reseau = construireReseau(
      [tache('a', 'a'), tache('b', 'b'), tache('x', 'x'), tache('y', 'y'), tache('z', 'z')],
      [arete('a', 'b')],
    );
    const d = disposerParComposantes(reseau, dims);
    expect(d.separateurs).toHaveLength(1);
    // Deux colonnes (la chaîne a → b en a deux) : x et y sur une ligne, z dessous.
    expect(d.pos.get('x')).toEqual({ x: 5, y: d.separateurs[0] + 5 });
    expect(d.pos.get('y')).toEqual({ x: 125, y: d.separateurs[0] + 5 });
    expect(d.pos.get('z')).toEqual({ x: 5, y: d.separateurs[0] + 5 + 60 });
  });
});

describe('la Liste — les mêmes tâches par niveau', () => {
  it('range AgriCulture sur trois niveaux, la tâche qui libère le plus en tête', () => {
    // À 340 px un graphe est une illustration : sept tâches sur trois niveaux
    // se lisent en sept lignes, la première étant la tâche à faire ce soir.
    const niveaux = lignesParNiveau(agriculture());
    expect(niveaux.map((n) => n.niveau)).toEqual([0, 1, 2]);
    expect(niveaux.map((n) => n.lignes.map((l) => l.id))).toEqual([
      ['riz', 'agri'],
      ['besoin', 'discuter'],
      // Trois bloquées, par titre : « Avoir besoin d'un tracteur » avant « Avoir un budget… ».
      ['tracteur', 'budget', 'contrat'],
    ]);
    expect(niveaux.flatMap((n) => n.lignes)).toHaveLength(7);
  });

  it('dit ce qu’une bloquée attend et ce qu’une faisable libère, rien pour une faite', () => {
    const reseau = agricultureApresAgri();
    const lignes = lignesParNiveau(reseau).flatMap((n) => n.lignes);
    const de = (id: string) => lignes.find((l) => l.id === id) as (typeof lignes)[number];
    expect(de('agri').statut).toBe('faite');
    expect(mentionLigne(reseau, de('agri'))).toBeNull();
    expect(de('discuter').statut).toBe('faisable');
    expect(mentionLigne(reseau, de('discuter'))).toBe(
      'libère : Contrat | Paiement par jours de travail ou commission',
    );
    expect(de('contrat').statut).toBe('bloquee');
    expect(mentionLigne(reseau, de('contrat'))).toBe('attend : Discuter du contrat avec les agriculteurs');
    expect(de('besoin').aval).toBe(2);
  });

  it('place les faisables avant les bloquées et les faites dans un même niveau', () => {
    // Un niveau mêlé : « r » et « a » faisables (« r » libère « b », donc en
    // tête), « c » faite en dernier ; « b » attend « r » au niveau suivant.
    const reseau = construireReseau(
      [tache('c', 'c', true), tache('b', 'b'), tache('a', 'a'), tache('r', 'r')],
      [arete('r', 'b')],
    );
    const niveaux = lignesParNiveau(reseau);
    expect(niveaux[0].lignes.map((l) => l.id)).toEqual(['r', 'a', 'c']);
    expect(niveaux[1].lignes.map((l) => l.id)).toEqual(['b']);
    expect(mentionLigne(reseau, niveaux[1].lignes[0])).toBe('attend : r');
    // « a » n'ouvre rien seule : pas de mention, « ↓N » ne s'affiche pas non plus.
    expect(mentionLigne(reseau, niveaux[0].lignes[1])).toBeNull();
    expect(niveaux[0].lignes[1].aval).toBe(0);
    // « r » libère « b » : la mention le dit, en une seule tâche (pas de « ↓ »).
    expect(mentionLigne(reseau, niveaux[0].lignes[0])).toBe('libère : b');
    expect(niveaux[0].lignes[0].aval).toBe(1);
  });

  it('ne retient qu’un choix connu pour la vue', () => {
    expect(estVueReseau('graphe')).toBe(true);
    expect(estVueReseau('liste')).toBe(true);
    expect(estVueReseau('carte')).toBe(false);
    expect(estVueReseau(undefined)).toBe(false);
  });
});

describe('les couloirs par catégorie', () => {
  const dims = { largeurCarte: 100, hauteurCarte: 50, ecartX: 20, ecartY: 10, marge: 5 };
  /** AgriCulture, deux projets en un : la chaîne du contrat, celle du matériel, et « riz » sans catégorie. */
  const CATEGORIES: Record<string, string> = {
    agri: 'Contrat',
    discuter: 'Contrat',
    contrat: 'Contrat',
    besoin: 'Matériel',
    budget: 'Matériel',
    tracteur: ' Matériel ',
  };
  const agricultureEnCouloirs = () =>
    construireReseau(
      AGRI.map((t) => ({ ...t, category: CATEGORIES[t.id] ?? '' })),
      ARETES,
    );

  it('liste les catégories employées, sans doublon ni blanc, par titre', () => {
    expect(categories(agricultureEnCouloirs())).toEqual(['Contrat', 'Matériel']);
    expect(categories(agriculture())).toEqual([]);
  });

  it('empile un couloir par catégorie puis « — », le rang topologique restant global', () => {
    const d = disposerParCouloirs(agricultureEnCouloirs(), dims);
    expect(d.couloirs.map((c) => c.libelle)).toEqual(['Contrat', 'Matériel', '—']);
    // Contrat : une ligne (60 px + le libellé) ; Matériel : deux lignes ; « — » : une.
    expect(d.couloirs.map((c) => [c.y, c.hauteur])).toEqual([
      [0, HAUTEUR_LIBELLE_COULOIR + 60],
      [80, HAUTEUR_LIBELLE_COULOIR + 120],
      [220, HAUTEUR_LIBELLE_COULOIR + 60],
    ]);
    expect(d.separateurs).toEqual([80, 220]);
    expect(d.hauteur).toBe(300);
    // Trois colonnes globales, même quand un couloir n'en occupe qu'une.
    expect(d.largeur).toBe(5 * 2 + 3 * 100 + 2 * 20);
    // « riz » reste en colonne 0 dans son couloir, « besoin » en colonne 1
    // dans le sien : l'arête riz → besoin traverse le filet, c'est l'information.
    expect(d.pos.get('riz')).toEqual({ x: 5, y: 220 + HAUTEUR_LIBELLE_COULOIR + 5 });
    expect(d.pos.get('besoin')).toEqual({ x: 125, y: 80 + HAUTEUR_LIBELLE_COULOIR + 5 });
    expect(d.pos.get('contrat')?.x).toBe(245);
    expect(d.pos.size).toBe(7);
  });

  it('ne change rien sans catégorie : pas de chrome vide', () => {
    const reseau = agriculture();
    const attendu = disposerParComposantes(reseau, dims);
    const d = disposer(reseau, dims);
    expect(d.couloirs).toEqual([]);
    expect(d.separateurs).toEqual(attendu.separateurs);
    expect([...d.pos.entries()]).toEqual([...attendu.pos.entries()]);
  });

  it('passe aux couloirs dès qu’une seule tâche porte une catégorie', () => {
    const reseau = construireReseau(
      AGRI.map((t) => (t.id === 'contrat' ? { ...t, category: 'Contrat' } : t)),
      ARETES,
    );
    const d = disposer(reseau, dims);
    expect(d.couloirs.map((c) => c.libelle)).toEqual(['Contrat', '—']);
    expect(d.separateurs).toHaveLength(1);
  });
});

describe('le clavier suit les arêtes (§82)', () => {
  const dims = { largeurCarte: 100, hauteurCarte: 50, ecartX: 20, ecartY: 10, marge: 5 };

  it('→ va à ce que la carte débloque, ← à ce qu’elle attend', () => {
    const reseau = agriculture();
    const { pos } = disposer(reseau, dims);
    expect(cibleClavier(reseau, pos, 'riz', 'ArrowRight')).toBe('besoin');
    expect(cibleClavier(reseau, pos, 'besoin', 'ArrowLeft')).toBe('riz');
    expect(cibleClavier(reseau, pos, 'discuter', 'ArrowRight')).toBe('contrat');
    expect(cibleClavier(reseau, pos, 'contrat', 'ArrowLeft')).toBe('discuter');
  });

  it('entre deux successeures, → choisit la plus proche en hauteur', () => {
    const reseau = agriculture();
    const { pos } = disposer(reseau, dims);
    const cible = cibleClavier(reseau, pos, 'besoin', 'ArrowRight');
    expect(['tracteur', 'budget']).toContain(cible);
    expect(pos.get(cible as string)?.y).toBe(pos.get('besoin')?.y);
  });

  it('au bout d’une chaîne, la flèche ne mène nulle part', () => {
    const reseau = agriculture();
    const { pos } = disposer(reseau, dims);
    expect(cibleClavier(reseau, pos, 'agri', 'ArrowLeft')).toBeNull();
    expect(cibleClavier(reseau, pos, 'contrat', 'ArrowRight')).toBeNull();
    expect(cibleClavier(reseau, pos, 'tracteur', 'ArrowRight')).toBeNull();
  });

  it('↑ et ↓ parcourent la colonne, toutes bandes confondues', () => {
    const reseau = agriculture();
    const { pos } = disposer(reseau, dims);
    // « riz » et « agriculteurs » sont toutes deux en colonne 0, chacune
    // dans sa composante empilée (la plus grande, celle de « riz », en
    // haut) : ↓ passe de l'une à l'autre.
    expect(pos.get('riz')?.x).toBe(pos.get('agri')?.x);
    expect(cibleClavier(reseau, pos, 'riz', 'ArrowDown')).toBe('agri');
    expect(cibleClavier(reseau, pos, 'agri', 'ArrowUp')).toBe('riz');
    expect(cibleClavier(reseau, pos, 'riz', 'ArrowUp')).toBeNull();
    expect(cibleClavier(reseau, pos, 'agri', 'ArrowDown')).toBeNull();
  });

  it('sans arête de ce côté, → rejoint la colonne voisine : une orpheline n’est pas hors d’atteinte', () => {
    const reseau = construireReseau(
      [tache('a', 'amont'), tache('b', 'bout'), tache('o', 'orpheline')],
      [arete('a', 'b')],
    );
    const pos = new Map<string, Point>([
      ['a', { x: 0, y: 0 }],
      ['b', { x: 120, y: 0 }],
      ['o', { x: 0, y: 60 }],
    ]);
    expect(cibleClavier(reseau, pos, 'o', 'ArrowRight')).toBe('b');
    expect(cibleClavier(reseau, pos, 'b', 'ArrowLeft')).toBe('a');
    expect(cibleClavier(reseau, pos, 'a', 'ArrowDown')).toBe('o');
    expect(cibleClavier(reseau, pos, 'inconnue', 'ArrowDown')).toBeNull();
  });

  it('la consigne nomme la source et les deux chemins', () => {
    expect(consigneLiaison(null)).toBe(
      'Choisissez la tâche source : clic, ou L sur une carte. Échap pour annuler.',
    );
    expect(consigneLiaison('Avoir un budget bien detaillé ?')).toBe(
      'Source : « Avoir un budget bien detaillé ? ». Choisissez la tâche à débloquer (cible) : clic, ou flèches puis Entrée. Échap pour annuler.',
    );
  });
});

describe('tracer un lien en tirant une carte (18 sept. 2026)', () => {
  it('en deçà de 4 px le geste reste un clic, au-delà c’est un tirage', () => {
    // §11 : « le clic n'ouvre la fiche que si le pointeur n'a pas bougé de
    // plus de 4 px ». Au trackpad un clic dérive déjà de 1 à 3 px.
    expect(SEUIL_TIRAGE_PX).toBe(4);
    expect(aBouge({ x: 10, y: 10 }, { x: 12, y: 13 })).toBe(false);
    expect(aBouge({ x: 10, y: 10 }, { x: 14, y: 10 })).toBe(false);
    expect(aBouge({ x: 10, y: 10 }, { x: 14, y: 12 })).toBe(true);
  });

  it('le verdict du dépôt : rien, la même tâche, un doublon, une boucle, ou un lien', () => {
    const reseau = agriculture();
    expect(verdictDepot(reseau, 'besoin', null)).toBe('aucune');
    expect(verdictDepot(reseau, 'besoin', 'inconnue')).toBe('aucune');
    expect(verdictDepot(reseau, 'besoin', 'besoin')).toBe('meme-tache');
    expect(verdictDepot(reseau, 'besoin', 'budget')).toBe('deja');
    // « besoin » attend déjà « riz » : riz ← besoin fermerait une boucle.
    expect(verdictDepot(reseau, 'besoin', 'riz')).toBe('boucle');
    expect(verdictDepot(reseau, 'budget', 'tracteur')).toBe('ok');
    expect(verdictDepot(reseau, 'contrat', 'riz')).toBe('ok');
  });

  it('la boucle et le doublon sont dits sans rien envoyer ; un lien possible ne dit rien (la phrase viendra du serveur)', () => {
    const reseau = agriculture();
    expect(phraseBoucle(reseau, 'besoin', 'riz')).toBe(
      '« Qu’est-ce qu’on aura besoin en premier ? » attend déjà « Qu’est ce que nou allons commencer avec en premier | Riz ou Haricots ? », de près ou de loin : ce lien fermerait une boucle.',
    );
    expect(phraseDepot(reseau, 'besoin', 'riz')).toBe(phraseBoucle(reseau, 'besoin', 'riz'));
    expect(phraseDepot(reseau, 'besoin', 'budget')).toBe(
      '« Qu’est-ce qu’on aura besoin en premier ? » débloque déjà « Avoir un budget bien detaillé ? ».',
    );
    expect(phraseDepot(reseau, 'budget', 'tracteur')).toBeNull();
    expect(phraseDepot(reseau, 'budget', null)).toBeNull();
    expect(phraseDepot(reseau, 'budget', 'budget')).toBeNull();
  });

  it('le trait tiré a la forme des arêtes et garde 28 px de tangente quand on tire vers la gauche', () => {
    expect(cheminElastique({ x: 210, y: 38 }, { x: 410, y: 138 })).toBe(
      'M 210 38 C 310 38, 310 138, 410 138',
    );
    expect(cheminElastique({ x: 210, y: 38 }, { x: 200, y: 40 })).toBe(
      'M 210 38 C 238 38, 172 40, 200 40',
    );
  });

  it('la consigne du tirage nomme la source et dit le verdict AVANT le dépôt', () => {
    const reseau = agriculture();
    expect(consigneTirage(reseau, 'budget', null)).toBe(
      'Tirage depuis « Avoir un budget bien detaillé ? » : déposer sur la tâche à débloquer. Échap pour annuler.',
    );
    expect(consigneTirage(reseau, 'budget', 'tracteur')).toBe(
      'Tirage depuis « Avoir un budget bien detaillé ? » : déposer pour débloquer « Avoir besoin d’un tracteur ».',
    );
    expect(consigneTirage(reseau, 'besoin', 'riz')).toBe(
      'Tirage depuis « Qu’est-ce qu’on aura besoin en premier ? » : « Qu’est ce que nou allons commencer avec en premier | Riz ou Haricots ? » est impossible, ce lien fermerait une boucle.',
    );
    expect(consigneTirage(reseau, 'besoin', 'budget')).toBe(
      'Tirage depuis « Qu’est-ce qu’on aura besoin en premier ? » : « Avoir un budget bien detaillé ? » est déjà débloquée par elle.',
    );
  });
});

describe('une durée estimée en jours, et un chemin critique seulement quand chaque tâche ouverte en porte une (18 sept. 2026)', () => {
  /** AgriCulture avec des durées, 0 = non estimée. */
  const avecDurees = (jours: Record<string, number>) =>
    construireReseau(
      AGRI.map((t) => ({ ...t, estimateDays: jours[t.id] ?? 0 })),
      ARETES,
    );
  /** Les sept tâches d'AgriCulture estimées : riz → besoin → budget pèse 10 j, la chaîne agri → discuter → contrat 3 j. */
  const COMPLETE = { riz: 1, besoin: 5, budget: 4, tracteur: 2, agri: 1, discuter: 1, contrat: 1 };

  it('sans durée, rien ne change : pas de jours, la chaîne se compte en tâches', () => {
    const reseau = agriculture();
    expect(aDesDurees(reseau)).toBe(false);
    expect(estimationComplete(reseau)).toBe(false);
    expect(cheminCritique(reseau)).toBeNull();
    expect(finProjetee(reseau)).toBeNull();
    expect(margeJours(reseau, 'budget')).toBeNull();
    expect(chaineLaPlusLongue(reseau)).toEqual(['agri', 'discuter', 'contrat']);
    expect(placeSurLeFil(reseau, 'budget')).toBe('Sur une chaîne aussi longue que le fil');
    expect(libelleEnTete(comptes(reseau))).toBe('2 faisables · 5 bloquées · profondeur 3');
  });

  it('lit la durée en entier, jamais en flottant ni en négatif', () => {
    const reseau = construireReseau(
      [
        { ...tache('a', 'a'), estimateDays: 3 },
        { ...tache('b', 'b'), estimateDays: 2.9 },
        { ...tache('c', 'c'), estimateDays: -4 },
        { ...tache('d', 'd'), estimateDays: Number.NaN },
        // Une tâche lue dans le cache d'avant le champ n'en porte pas.
        { ...tache('e', 'e'), estimateDays: undefined as unknown as number },
      ],
      [],
    );
    expect(['a', 'b', 'c', 'd', 'e', 'inconnue'].map((id) => dureeDe(reseau, id))).toEqual([3, 2, 0, 0, 0, 0]);
  });

  it('une chaîne de quatre tâches sans durée reste « profondeur 4 » face à une tâche seule estimée à 1 j', () => {
    // Revue du réseau : `chaineLaPlusLongue` rendait ['z'] et l'en-tête
    // « profondeur 1 · fin projetée ~1 j » pour un graphe à quatre niveaux.
    const reseau = construireReseau(
      [
        tache('a', 'a'),
        tache('b', 'b'),
        tache('c', 'c'),
        tache('d', 'd'),
        { ...tache('z', 'z'), estimateDays: 1 },
      ],
      [arete('a', 'b'), arete('b', 'c'), arete('c', 'd')],
    );
    expect(chaineLaPlusLongue(reseau)).toEqual(['a', 'b', 'c', 'd']);
    expect(estimation(reseau)).toEqual({ estimees: 1, ouvertes: 5, complete: false });
    expect(cheminCritique(reseau)).toBeNull();
    expect(finProjetee(reseau)).toBeNull();
    const c = comptes(reseau);
    expect(c.profondeur).toBe(4);
    expect(c.joursProjetes).toBeNull();
    expect(libelleEstimation(c)).toBe('1 tâche estimée sur 5');
    expect(libelleEnTete(c)).toBe('2 faisables · 3 bloquées · profondeur 4 · 1 tâche estimée sur 5');
    // La fiche reste en tâches : pas de « chemin critique » sur z, pas de « Marge : 1 j » sur a.
    expect(margeJours(reseau, 'z')).toBeNull();
    expect(placeSurLeFil(reseau, 'z')).toBe('Marge : 3 tâches');
    expect(placeSurLeFil(reseau, 'a')).toBe('Sur la chaîne la plus longue');
  });

  it('une seule durée sur AgriCulture ne projette rien et ne pose de marge en jours sur personne', () => {
    // Revue du réseau : « ~ 3 j » sur « agriculteurs » seule donnait « fin
    // projetée ~3 j », « Marge : 3 j » sur riz et « Sur le chemin critique »
    // sur contrat, non estimée.
    const reseau = avecDurees({ agri: 3 });
    expect(aDesDurees(reseau)).toBe(true);
    expect(estimationComplete(reseau)).toBe(false);
    expect(libelleEnTete(comptes(reseau))).toBe('2 faisables · 5 bloquées · profondeur 3 · 1 tâche estimée sur 7');
    expect(placeSurLeFil(reseau, 'riz')).toBe('Sur une chaîne aussi longue que le fil');
    expect(placeSurLeFil(reseau, 'contrat')).toBe('Sur la chaîne la plus longue');
    expect(placeSurLeFil(reseau, 'budget')).toBe('Sur une chaîne aussi longue que le fil');
    expect(['riz', 'contrat', 'budget'].map((id) => placeSurLeFil(reseau, id))).not.toContain('Sur le chemin critique');
  });

  it('estimation complète : le chemin critique est la chaîne la plus lourde, la profondeur reste en tâches', () => {
    const reseau = avecDurees(COMPLETE);
    expect(estimationComplete(reseau)).toBe(true);
    expect(cheminCritique(reseau)).toEqual(['riz', 'besoin', 'budget']);
    expect(joursDeChaine(reseau, ['riz', 'besoin', 'budget'])).toBe(10);
    expect(finProjetee(reseau)).toBe(10);
    // Deux chaînes de 3 tâches : la plus longue en tâches est tranchée par les titres, pas par les jours.
    expect(chaineLaPlusLongue(reseau)).toEqual(['agri', 'discuter', 'contrat']);
    const c = comptes(reseau);
    expect(c.profondeur).toBe(3);
    expect(libelleEstimation(c)).toBeNull();
    expect(libelleEnTete(c)).toBe('2 faisables · 5 bloquées · profondeur 3 · fin projetée ~10 j');
  });

  it('à jours égaux, le chemin critique est la chaîne la plus longue en tâches, puis la première par titres', () => {
    // Deux chaînes de 6 j : la première est la plus longue en tâches (3 contre 2).
    const reseau = construireReseau(
      [
        { ...tache('a', 'a'), estimateDays: 2 },
        { ...tache('b', 'b'), estimateDays: 2 },
        { ...tache('c', 'c'), estimateDays: 2 },
        { ...tache('x', 'x'), estimateDays: 3 },
        { ...tache('y', 'y'), estimateDays: 3 },
      ],
      [arete('a', 'b'), arete('b', 'c'), arete('x', 'y')],
    );
    expect(cheminCritique(reseau)).toEqual(['a', 'b', 'c']);
  });

  it('la marge en jours est la marge totale du CPM, et zéro vaut « sur le chemin critique »', () => {
    // riz 1 → besoin 5 → budget 4 (10 j, critique) ; besoin → tracteur 2 (8 j via ce bras).
    const reseau = avecDurees(COMPLETE);
    expect(margeJours(reseau, 'besoin')).toBe(0);
    expect(margeJours(reseau, 'budget')).toBe(0);
    expect(margeJours(reseau, 'tracteur')).toBe(2);
    expect(margeJours(reseau, 'contrat')).toBe(7);
    expect(placeSurLeFil(reseau, 'riz')).toBe('Sur le chemin critique');
    expect(placeSurLeFil(reseau, 'tracteur')).toBe('Marge : 2 j');
    expect(placeSurLeFil(reseau, 'contrat')).toBe('Marge : 7 j');
  });

  it('une tâche faite ne compte ni dans l’estimation ni dans les jours', () => {
    // riz faite (9 j) : ses jours ne pèsent plus, et son absence d'estimation
    // n'aurait pas compté non plus. Les six ouvertes sont estimées : complet.
    const reseau = construireReseau(
      AGRI.map((t) =>
        t.id === 'riz' ? { ...t, done: true, estimateDays: 9 } : { ...t, estimateDays: COMPLETE[t.id as keyof typeof COMPLETE] },
      ),
      ARETES,
    );
    expect(estimation(reseau)).toEqual({ estimees: 6, ouvertes: 6, complete: true });
    // besoin 5 → budget 4 = 9 j, contre agri 1 → discuter 1 → contrat 1 = 3 j.
    expect(finProjetee(reseau)).toBe(9);
    expect(margeJours(reseau, 'riz')).toBeNull();
    expect(margeJours(reseau, 'budget')).toBe(0);
    expect(margeJours(reseau, 'contrat')).toBe(6);
    expect(placeSurLeFil(reseau, 'riz')).toBeNull();
  });

  it('un projet fini n’a rien à projeter : l’estimation n’y est pas « complète »', () => {
    const reseau = construireReseau(
      [{ ...tache('a', 'a', true), estimateDays: 2 }, { ...tache('b', 'b', true), estimateDays: 2 }],
      [arete('a', 'b')],
    );
    expect(estimation(reseau)).toEqual({ estimees: 0, ouvertes: 0, complete: false });
    expect(finProjetee(reseau)).toBeNull();
    expect(libelleEstimation(comptes(reseau))).toBeNull();
  });

  it('la saisie « ~ j » n\'accepte qu\'un entier de 0 à 3650, vide valant zéro', () => {
    expect(lireDureeSaisie('')).toBe(0);
    expect(lireDureeSaisie(' 12 ')).toBe(12);
    expect(lireDureeSaisie('0')).toBe(0);
    expect(lireDureeSaisie('3650')).toBe(3650);
    expect(lireDureeSaisie('3651')).toBeNull();
    expect(lireDureeSaisie('1,5')).toBeNull();
    expect(lireDureeSaisie('1.5')).toBeNull();
    expect(lireDureeSaisie('-1')).toBeNull();
    expect(lireDureeSaisie('deux')).toBeNull();
  });
});

describe('relier au clic, à Entrée ou depuis la fiche passe par le verdict du tirage (§100, revue du 18 sept. 2026)', () => {
  it('sans source, la carte devient la source ; la même carte l’annule', () => {
    const reseau = agriculture();
    expect(actionLiaison(reseau, null, 'riz')).toEqual({ type: 'choisir-source' });
    expect(actionLiaison(reseau, 'riz', 'riz')).toEqual({ type: 'annuler-source' });
  });

  it('un lien déjà présent est refusé sans rien envoyer — plus de « Dépendance ajoutée » pour un doublon', () => {
    const reseau = agriculture();
    expect(actionLiaison(reseau, 'riz', 'besoin')).toEqual({
      type: 'refus',
      phrase: '« Qu’est ce que nou allons commencer avec en premier | Riz ou Haricots ? » débloque déjà « Qu’est-ce qu’on aura besoin en premier ? ».',
    });
  });

  it('une boucle est refusée avant le clic, avec la phrase du tirage', () => {
    const reseau = agriculture();
    expect(actionLiaison(reseau, 'besoin', 'riz')).toEqual({
      type: 'refus',
      phrase: phraseBoucle(reseau, 'besoin', 'riz'),
    });
  });

  it('un lien possible part au serveur, et lui seul', () => {
    const reseau = agriculture();
    expect(actionLiaison(reseau, 'budget', 'tracteur')).toEqual({ type: 'lier', from: 'budget', to: 'tracteur' });
    expect(verdictDepot(reseau, 'budget', 'tracteur')).toBe('ok');
  });

  it('la cible dit pourquoi elle est impossible : boucle, ou déjà reliée', () => {
    const reseau = agriculture();
    expect(motifCibleImpossible(reseau, 'besoin', 'riz')).toBe('Impossible : fermerait une boucle');
    expect(motifCibleImpossible(reseau, 'riz', 'besoin')).toBe(
      'Déjà reliée : « Qu’est ce que nou allons commencer avec en premier | Riz ou Haricots ? » la débloque déjà',
    );
    expect(motifCibleImpossible(reseau, 'budget', 'tracteur')).toBeNull();
  });
});
