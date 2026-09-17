import { describe, expect, it } from 'vitest';

import {
  EVENEMENT_FOCUS_COMPOSITEUR,
  EVENEMENT_PANNEAU_OUVERT,
  EVENEMENT_PANNEAU_REPRIS,
  FENETRE_OUVERTURE_MS,
  brouillonDuCompositeur,
  consommerLaDemandeDeFocus,
  demanderLeFocusDuCompositeur,
  consommerLAtterrissage,
  noterOuverture,
  ouvertureRecente,
  panneauVientDeSOuvrir,
  publierLeBrouillon,
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

describe('« repris » n’est pas « ouvert »', () => {
  it('les deux signaux se nomment comme Rust les émet, et diffèrent', () => {
    // presenter_mini émet « ouvert » quand le panneau était caché, « repris »
    // quand il était déjà visible (re-clic du rail) ; agrandir_mini émet
    // « repris ». Un même nom des deux côtés ferait rejouer l'atterrissage.
    expect(EVENEMENT_PANNEAU_REPRIS).toBe('diapason:panneau-repris');
    expect(EVENEMENT_PANNEAU_REPRIS).not.toBe(EVENEMENT_PANNEAU_OUVERT);
  });

  it('un « repris » ne compte pas comme une ouverture, mais demande le focus', () => {
    // Contre-revue du 17 sept. 2026 : déplier la pastille rejouait
    // l'atterrissage et abandonnait le fil choisi par ⌘J, brouillon compris.
    noterOuverture(0);
    consommerLaDemandeDeFocus();
    let demandes = 0;
    const compter = () => {
      demandes += 1;
    };
    window.addEventListener(EVENEMENT_FOCUS_COMPOSITEUR, compter);
    window.dispatchEvent(new CustomEvent(EVENEMENT_PANNEAU_REPRIS));
    window.removeEventListener(EVENEMENT_FOCUS_COMPOSITEUR, compter);
    expect(panneauVientDeSOuvrir(Date.now()), 'pas une ouverture').toBe(false);
    expect(demandes, 'mais le curseur revient').toBe(1);
  });
});

describe('la demande de focus survit au montage du compositeur', () => {
  it('est gardée, consommée une seule fois, puis oubliée', () => {
    // « Nouvelle discussion » depuis Tâches : l'événement partait avant que
    // InputArea existe ; même différé d'un tour, il arrivait 50 ms trop tôt.
    consommerLaDemandeDeFocus();
    expect(consommerLaDemandeDeFocus(), 'rien en attente').toBe(false);
    demanderLeFocusDuCompositeur(10_000);
    expect(consommerLaDemandeDeFocus(10_050)).toBe(true);
    expect(consommerLaDemandeDeFocus(10_060), 'une seule fois').toBe(false);
  });

  it('expire avec la fenêtre d’ouverture : revenir sur la Discussion plus tard ne vole pas le curseur', () => {
    demanderLeFocusDuCompositeur(10_000);
    expect(consommerLaDemandeDeFocus(10_000 + FENETRE_OUVERTURE_MS)).toBe(false);
  });
});

describe('le brouillon publié par le compositeur', () => {
  it('est vide tant que rien n’est publié, et rend la dernière publication', () => {
    publierLeBrouillon('');
    expect(brouillonDuCompositeur()).toBe('');
    publierLeBrouillon('et la suite du plan ?');
    expect(brouillonDuCompositeur()).toBe('et la suite du plan ?');
    publierLeBrouillon('');
  });
});

describe('l’atterrissage en attente', () => {
  it('se consomme une seule fois par ouverture, quel que soit le délai', () => {
    // Contre-revue du 17 sept. 2026 : panneau ouvert sur Tâches, Discussion
    // cliquée 4 s plus tard → la fenêtre de 2 s disait « pas d’ouverture ».
    consommerLAtterrissage();
    noterOuverture(0);
    expect(consommerLAtterrissage(), 'la première Discussion montée atterrit').toBe(true);
    expect(consommerLAtterrissage(), 'la seconde ne ré-atterrit pas').toBe(false);
  });
});
