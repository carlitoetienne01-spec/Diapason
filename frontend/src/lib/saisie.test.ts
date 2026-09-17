import { describe, expect, it } from 'vitest';

import {
  ATTRIBUT_RACCOURCIS_GLOBAUX,
  estDansUneZoneDeSaisie,
  laissePasserLeRaccourci,
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

  it('accepte Ctrl à la place de ⌘, mais refuse ⌥', () => {
    expect(
      laissePasserLeRaccourci(compositeur(), frappe('k', { metaKey: false, ctrlKey: true })),
    ).toBe(true);
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
