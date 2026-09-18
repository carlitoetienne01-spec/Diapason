import { describe, expect, it } from 'vitest';

import {
  aretesDeChaine,
  aretesLiberees,
  ceQueDebloque,
  ceQueRebloque,
  chaine,
  citer,
  chaineComplete,
  chaineLaPlusLongue,
  colonnesInitiales,
  compterCroisements,
  comptes,
  construireReseau,
  dispositionBouge,
  faisables,
  fermeraitUneBoucle,
  glypheStatut,
  impact,
  interpolerPositions,
  libelleEnTete,
  ligneDeComptes,
  margeDe,
  niveaux,
  ordonnerColonnes,
  phraseApresBascule,
  placeSurLeFil,
  positionner,
  statutDe,
  statuts,
  traitArete,
  voisinSuivant,
  voisinage,
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
});

describe('comptes et en-tête', () => {
  it('AgriCulture : 2 faisables, 5 bloquées, 0 faite, profondeur 3', () => {
    expect(comptes(agriculture())).toEqual({ faisables: 2, bloquees: 5, faites: 0, profondeur: 3 });
    expect(libelleEnTete(comptes(agriculture()))).toBe('2 faisables · 5 bloquées · profondeur 3');
  });

  it('accorde le singulier', () => {
    const reseau = construireReseau([tache('a', 'a'), tache('b', 'b')], [arete('a', 'b')]);
    expect(libelleEnTete(comptes(reseau))).toBe('1 faisable · 1 bloquée · profondeur 2');
  });

  it('un projet fini a une profondeur de zéro', () => {
    const reseau = construireReseau([tache('a', 'a', true), tache('b', 'b', true)], [arete('a', 'b')]);
    expect(comptes(reseau)).toEqual({ faisables: 0, bloquees: 0, faites: 2, profondeur: 0 });
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
