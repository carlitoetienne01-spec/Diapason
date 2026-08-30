import { describe, expect, it } from 'vitest';

import { estDansUneZoneDeSaisie } from './saisie';

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
