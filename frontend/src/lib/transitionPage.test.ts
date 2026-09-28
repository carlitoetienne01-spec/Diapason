import { describe, expect, it } from 'vitest';

import {
  DUREE_ENTREE_MS,
  GLISSEMENT_ENTREE_PX,
  IMAGES_ENTREE,
  OPTIONS_ENTREE,
  PLAFOND_RESTAURATION_MS,
  STABILITE_RESTAURATION_MS,
  creerMemoireDefilement,
  decisionRestauration,
  doitAnimerLEntree,
  pageRetientSaPosition,
} from './transitionPage';

/**
 * Les transitions entre pages du téléphone (chantier « soyeux », lot 2,
 * 27/09/2026). Décision de Carlito du 26/09/2026 : glissement vertical léger
 * (~12 px) et fondu, ~180 ms ; la page quittée retrouve sa position au
 * retour ; « Supprimer les animations » : aucun mouvement.
 */
describe('doitAnimerLEntree', () => {
  const base = { mobile: true, mouvementReduit: false, cheminPrecedent: '/vie/notes', chemin: '/vie/tasks' };

  it('anime la page qui arrive d’une autre page, au téléphone', () => {
    expect(doitAnimerLEntree(base), 'Notes → Tâches glisse et se révèle').toBe(true);
  });

  it('n’anime rien au bureau ni au mini-panneau', () => {
    expect(doitAnimerLEntree({ ...base, mobile: false }), 'le bureau ne change pas').toBe(false);
  });

  it('n’anime rien sous « Supprimer les animations »', () => {
    expect(doitAnimerLEntree({ ...base, mouvementReduit: true }), 'prefers-reduced-motion : bascule directe').toBe(false);
  });

  it('n’anime pas la première page de l’app ouverte', () => {
    // La première peinture ne doit pas être retenue à opacité nulle : le
    // relevé de l'ouverture (FCP) n'a pas à payer une transition.
    expect(doitAnimerLEntree({ ...base, cheminPrecedent: null }), 'rien n’arrive depuis une autre page').toBe(false);
  });

  it('n’anime pas quand l’adresse reste sur la même page', () => {
    expect(doitAnimerLEntree({ ...base, cheminPrecedent: '/vie/tasks' }), 'un volet ouvert par ?task= n’est pas une page').toBe(false);
  });
});

describe('les images de l’entrée', () => {
  it('ne touchent que transform et opacity, 12 px en 180 ms, sans rien laisser derrière', () => {
    const proprietes = new Set(IMAGES_ENTREE.flatMap((i) => Object.keys(i)));
    expect([...proprietes].sort(), 'aucune propriété qui force la mise en page').toEqual(['opacity', 'transform']);
    expect(IMAGES_ENTREE[0], 'la page part de 12 px plus bas, invisible').toEqual({
      opacity: 0,
      transform: `translateY(${GLISSEMENT_ENTREE_PX}px)`,
    });
    expect(GLISSEMENT_ENTREE_PX, 'glissement léger décidé le 26/09/2026').toBe(12);
    expect(OPTIONS_ENTREE.duration, 'le tempo du recul de la roue').toBe(DUREE_ENTREE_MS);
    expect(DUREE_ENTREE_MS).toBe(180);
    // Un transform laissé sur la colonne ferait d'elle le bloc contenant des
    // position:fixed de la page : le volet d'une tâche sauterait.
    expect(OPTIONS_ENTREE.fill, 'aucun transform ne reste une fois arrivée').toBe('none');
  });
});

describe('pageRetientSaPosition', () => {
  it('rend sa position à chaque page, sauf à la Discussion qui suit son fil', () => {
    expect(pageRetientSaPosition('/vie/tasks')).toBe(true);
    expect(pageRetientSaPosition('/settings')).toBe(true);
    expect(pageRetientSaPosition('/'), 'la Discussion reste collée au dernier message').toBe(false);
  });
});

describe('decisionRestauration', () => {
  it('pose la position dès que la page peut l’atteindre en entier', () => {
    expect(decisionRestauration({ cible: 2000, defilable: 9817, ecouleMs: 0 }), 'Notes → Tâches → Notes').toEqual({
      action: 'poser',
      haut: 2000,
    });
    expect(decisionRestauration({ cible: 1567, defilable: 1567, ecouleMs: 0 }), 'la limite exacte suffit').toEqual({
      action: 'poser',
      haut: 1567,
    });
  });

  it('attend une page qui grandit encore, sans jamais poser une position à moitié', () => {
    expect(
      decisionRestauration({ cible: 2000, defilable: 400, ecouleMs: 100, stableDepuisMs: 16 }),
      'deux sauts valent pire qu’un',
    ).toEqual({ action: 'attendre' });
  });

  it('descend au plus près une page devenue plus courte qui ne bouge plus', () => {
    // Des tâches cochées depuis : la page ne remontera jamais à 2000 px ; la
    // laisser en haut perdrait l'endroit où l'on était.
    expect(
      decisionRestauration({ cible: 2000, defilable: 1400, ecouleMs: 120, stableDepuisMs: STABILITE_RESTAURATION_MS }),
    ).toEqual({ action: 'poser', haut: 1400 });
  });

  it('attend une page vide : elle charge encore', () => {
    expect(
      decisionRestauration({ cible: 2000, defilable: 0, ecouleMs: 500, stableDepuisMs: 500 }),
      'une hauteur nulle n’est pas une page posée',
    ).toEqual({ action: 'attendre' });
  });

  it('renonce au plafond : une page qu’on lit déjà ne saute plus', () => {
    expect(decisionRestauration({ cible: 2000, defilable: 0, ecouleMs: PLAFOND_RESTAURATION_MS })).toEqual({
      action: 'renoncer',
    });
    expect(
      decisionRestauration({ cible: 2000, defilable: 400, ecouleMs: 50, stableDepuisMs: 0, plafondMs: 40 }),
    ).toEqual({ action: 'renoncer' });
  });

  it('ne fait rien pour une page laissée en haut', () => {
    expect(decisionRestauration({ cible: 0, defilable: 18000, ecouleMs: 0 }), 'rien à reprendre').toEqual({
      action: 'renoncer',
    });
    expect(decisionRestauration({ cible: Number.NaN, defilable: 18000, ecouleMs: 0 })).toEqual({ action: 'renoncer' });
  });
});

describe('creerMemoireDefilement', () => {
  it('retient la dernière position de chaque page', () => {
    const m = creerMemoireDefilement();
    m.retenir('/vie/tasks', 1200.4);
    m.retenir('/vie/tasks', 2000.6);
    m.retenir('/vie/notes', 300);
    expect(m.lire('/vie/tasks'), 'la dernière position, arrondie au pixel').toBe(2001);
    expect(m.lire('/vie/notes')).toBe(300);
    expect(m.lire('/settings'), 'une page jamais défilée n’a rien').toBeUndefined();
  });

  it('oublie la page la moins récemment défilée au-delà de sa capacité', () => {
    const m = creerMemoireDefilement(2);
    m.retenir('/a', 10);
    m.retenir('/b', 20);
    m.retenir('/a', 11);
    m.retenir('/c', 30);
    expect(m.taille(), 'bornée').toBe(2);
    expect(m.lire('/b'), 'la moins récente cède sa place').toBeUndefined();
    expect(m.lire('/a')).toBe(11);
    expect(m.lire('/c')).toBe(30);
  });

  it('ne retient jamais de position négative (rebond d’Android)', () => {
    const m = creerMemoireDefilement();
    m.retenir('/vie/tasks', -14);
    expect(m.lire('/vie/tasks')).toBe(0);
  });
});
