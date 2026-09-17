import { describe, expect, it } from 'vitest';

import {
  ATTRIBUT_RACCOURCIS_GLOBAUX,
  estDansUneZoneDeSaisie,
  estUnMac,
  laissePasserLeRaccourci as laissePasserSelonPlateforme,
  type FrappeClavier,
} from './saisie';

// `setAttribute`, et non la propriété : c'est ce que React rend dans le DOM
// (`contentEditable` en JSX devient l'attribut `contenteditable="true"`), et
// jsdom n'écrit PAS l'attribut quand on affecte la propriété — il
// n'implémente pas non plus `isContentEditable`. Un test qui passerait par la
// propriété testerait donc une forme que le produit ne produit jamais.
const el = (balise: string, editable = false) => {
  const node = document.createElement(balise);
  if (editable) node.setAttribute('contenteditable', 'true');
  return node;
};

describe('estDansUneZoneDeSaisie', () => {
  it('reconnaît un contenteditable — le cas de l’éditeur de notes', () => {
    // Sans cette ligne, Cmd+I ouvre le panneau système au lieu de mettre en
    // italique, et l'utilisateur ne peut pas savoir pourquoi.
    expect(estDansUneZoneDeSaisie(el('div', true))).toBe(true);
  });

  it('reconnaît un champ, une zone de texte et un menu', () => {
    expect(estDansUneZoneDeSaisie(el('input'))).toBe(true);
    expect(estDansUneZoneDeSaisie(el('textarea'))).toBe(true);
    expect(estDansUneZoneDeSaisie(el('select'))).toBe(true);
  });

  it('laisse passer le reste de la page', () => {
    expect(estDansUneZoneDeSaisie(el('div'))).toBe(false);
    expect(estDansUneZoneDeSaisie(el('button'))).toBe(false);
    expect(estDansUneZoneDeSaisie(el('body'))).toBe(false);
  });

  it('ne casse pas sur une cible absente', () => {
    // `event.target` peut être null quand l'événement vient de window.
    expect(estDansUneZoneDeSaisie(null)).toBe(false);
  });
});

describe('la garde couvre les descendants, pas seulement l’hôte', () => {
  it('un paragraphe DANS un contenteditable compte', () => {
    // C'est le cas réel : la cible d'une frappe dans l'éditeur de notes est
    // presque toujours un <p>, jamais le div éditable lui-même.
    const hote = document.createElement('div');
    hote.setAttribute('contenteditable', 'true');
    const para = document.createElement('p');
    hote.appendChild(para);
    document.body.appendChild(hote);
    expect(estDansUneZoneDeSaisie(para)).toBe(true);
    hote.remove();
  });
});

describe('laissePasserLeRaccourci — l’exception du compositeur', () => {
  // Sur Mac, sauf mention contraire : jsdom n'a pas de `platform`, et le
  // défaut (« pas un Mac ») rendrait ⌘ muet dans tous les tests.
  const laissePasserLeRaccourci = (
    cible: EventTarget | null,
    frappe: FrappeClavier,
    surMac = true,
  ) => laissePasserSelonPlateforme(cible, frappe, surMac);
  const frappe = (key: string, extra: Partial<FrappeClavier> = {}): FrappeClavier => ({
    key,
    metaKey: true,
    ctrlKey: false,
    shiftKey: false,
    altKey: false,
    ...extra,
  });
  const compositeur = () => {
    const node = document.createElement('textarea');
    node.setAttribute(ATTRIBUT_RACCOURCIS_GLOBAUX, '');
    return node;
  };

  it('l’attribut se nomme comme InputArea l’écrit en JSX', () => {
    // Le textarea le pose en littéral (`data-raccourcis-globaux=""`) ; un
    // renommage d'un seul côté rendrait l'exception muette, sans erreur.
    expect(ATTRIBUT_RACCOURCIS_GLOBAUX).toBe('data-raccourcis-globaux');
  });

  it('laisse passer ⌘K, ⌘N et ⌘J depuis le textarea marqué', () => {
    // Sans cette exception, ⌘K était mort dès que le curseur était dans le
    // compositeur — presque toujours, dans le mini-panneau.
    for (const key of ['k', 'n', 'j', 'K']) {
      expect(laissePasserLeRaccourci(compositeur(), frappe(key))).toBe(true);
    }
  });

  it('laisse passer ⌘⇧[ et ⌘⇧] par la touche ou par sa position', () => {
    expect(laissePasserLeRaccourci(compositeur(), frappe('{', { shiftKey: true }))).toBe(true);
    expect(laissePasserLeRaccourci(compositeur(), frappe(']', { shiftKey: true }))).toBe(true);
    // Disposition française : `key` vaut « 5 » ou « ° » sur la touche des
    // crochets ; seul `code` dit encore de quelle touche il s'agit.
    expect(
      laissePasserLeRaccourci(compositeur(), frappe('°', { shiftKey: true, code: 'BracketRight' })),
    ).toBe(true);
    // Sans ⇧, ⌘[ n'est pas dans la liste.
    expect(laissePasserLeRaccourci(compositeur(), frappe('['))).toBe(false);
  });

  it('sur Mac, Ctrl+K et Ctrl+N restent au champ — ce sont les liaisons Cocoa', () => {
    // Contre-revue du 17 sept. 2026 : Ctrl+K « coupe jusqu'à la fin de la
    // ligne » et Ctrl+N « descend d'une ligne » dans toute zone de texte
    // macOS. Les laisser passer vidait le fil depuis un brouillon de trois
    // lignes — le raccourci confisqué du 30 août, sous un autre nom.
    const ctrl = { metaKey: false, ctrlKey: true };
    expect(laissePasserLeRaccourci(compositeur(), frappe('k', ctrl), true)).toBe(false);
    expect(laissePasserLeRaccourci(compositeur(), frappe('n', ctrl), true)).toBe(false);
    expect(laissePasserLeRaccourci(compositeur(), frappe('j', ctrl), true)).toBe(false);
  });

  it('hors Mac, Ctrl est le modificateur et ⌘ (touche Windows) ne l’est pas', () => {
    const ctrl = { metaKey: false, ctrlKey: true };
    expect(laissePasserLeRaccourci(compositeur(), frappe('k', ctrl), false)).toBe(true);
    expect(laissePasserLeRaccourci(compositeur(), frappe('n', ctrl), false)).toBe(true);
    expect(
      laissePasserLeRaccourci(compositeur(), frappe('{', { ...ctrl, shiftKey: true }), false),
    ).toBe(true);
    expect(laissePasserLeRaccourci(compositeur(), frappe('k'), false)).toBe(false);
  });

  it('refuse ⌥, et une frappe sans modificateur', () => {
    expect(laissePasserLeRaccourci(compositeur(), frappe('k', { altKey: true }))).toBe(false);
    expect(
      laissePasserLeRaccourci(compositeur(), frappe('k', { metaKey: false, ctrlKey: false })),
    ).toBe(false);
  });

  it('ne laisse rien passer d’un champ non marqué — l’éditeur de notes garde ⌘K', () => {
    // Le défaut du 30 août : un raccourci confisqué à quelqu'un qui écrit.
    // L'exception ne vaut que pour le champ qui la déclare.
    expect(laissePasserLeRaccourci(el('textarea'), frappe('k'))).toBe(false);
    expect(laissePasserLeRaccourci(el('div', true), frappe('k'))).toBe(false);
    expect(laissePasserLeRaccourci(null, frappe('k'))).toBe(false);
  });

  it('garde au compositeur ce qui n’est pas dans la liste', () => {
    // ⌘I n'ouvre pas le panneau système depuis le compositeur : la liste est
    // fermée, pas une passoire.
    expect(laissePasserLeRaccourci(compositeur(), frappe('i'))).toBe(false);
    expect(laissePasserLeRaccourci(compositeur(), frappe('a'))).toBe(false);
    expect(laissePasserLeRaccourci(compositeur(), frappe('Enter'))).toBe(false);
  });
});

describe('estUnMac', () => {
  it('reconnaît WebKit (platform) et Chromium (userAgentData)', () => {
    // WKWebView, fenêtre comme mini-panneau : `platform` vaut « MacIntel ».
    expect(estUnMac({ platform: 'MacIntel' })).toBe(true);
    expect(estUnMac({ platform: '', userAgentData: { platform: 'macOS' } })).toBe(true);
  });

  it('ne prend pas Windows ni Linux pour un Mac, et ne casse pas hors navigateur', () => {
    expect(estUnMac({ platform: 'Win32' })).toBe(false);
    expect(estUnMac({ platform: 'Linux x86_64', userAgentData: { platform: 'Linux' } })).toBe(false);
    expect(estUnMac(undefined)).toBe(false);
  });
});
