import { describe, expect, it } from 'vitest';

import {
  EVENEMENT_PANNEAU_OUVERT,
  FENETRE_OUVERTURE_MS,
  noterOuverture,
  ouvertureRecente,
  panneauVientDeSOuvrir,
  signalerPanneauOuvert,
} from './panneau';

describe('ouvertureRecente', () => {
  it('est faux tant qu’aucun signal n’est arrivé — la fenêtre principale ne l’émet jamais', () => {
    // Sans cette garde, ChatPage volerait le focus dans la fenêtre à chaque
    // retour sur la Discussion, alors que le mini-panneau seul est concerné.
    expect(ouvertureRecente(null, 1_000)).toBe(false);
  });

  it('est vrai dans la fenêtre, faux juste après', () => {
    const t0 = 10_000;
    expect(ouvertureRecente(t0, t0)).toBe(true);
    expect(ouvertureRecente(t0, t0 + FENETRE_OUVERTURE_MS - 1)).toBe(true);
    expect(ouvertureRecente(t0, t0 + FENETRE_OUVERTURE_MS)).toBe(false);
  });

  it('refuse un signal daté du futur — une horloge qui recule ne doit pas figer un « oui »', () => {
    expect(ouvertureRecente(10_000, 9_000)).toBe(false);
  });
});

describe('le signal de Rust est retenu pour la page qui se monte après lui', () => {
  it('retient l’heure du CustomEvent diapason:panneau-ouvert', () => {
    // Re-navigation : presenter_mini évalue le signal AVANT que ChatPage ne
    // soit montée ; sans mémoire, le compositeur restait sans focus.
    noterOuverture(0);
    expect(panneauVientDeSOuvrir(Date.now())).toBe(false);
    signalerPanneauOuvert();
    expect(panneauVientDeSOuvrir(Date.now())).toBe(true);
  });

  it('le signal se nomme comme Rust l’émet', () => {
    // lib.rs évalue exactement cette chaîne ; un renommage d'un seul côté
    // casserait le focus sans un mot d'erreur.
    expect(EVENEMENT_PANNEAU_OUVERT).toBe('diapason:panneau-ouvert');
  });
});
