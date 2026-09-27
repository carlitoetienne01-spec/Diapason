import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it, vi } from 'vitest';

import { IMAGES_ENTREE, OPTIONS_ENTREE, PLAFOND_RESTAURATION_MS } from './transitionPage';
import { creerSuiviDesPages, reprendrePosition, retenirSiDefileurDePage, type Horloge } from './suiviDesPages';
import { creerMemoireDefilement } from './transitionPage';

/**
 * Le suivi des pages, exécuté sous jsdom (27/09/2026, contre-épreuve du
 * chantier « soyeux », constats 12 et 13). Ces cinq mutations du crochet
 * survivaient à la suite complète : la position n'était plus posée (K1), on
 * rendait celle de la page QUITTÉE (K3), un défileur imbriqué écrasait celle
 * de la page (K5), un toucher n'annulait plus la reprise (K6), le chemin
 * courant n'était plus suivi (K7) — et « Supprimer les animations » n'était
 * plus transmis (K2). Chacune fait échouer un test ici.
 */

/** Une horloge qu'on avance à la main, image par image. */
function horlogeDeBanc() {
  let t = 0;
  let suivant = 1;
  const attente = new Map<number, () => void>();
  const horloge: Horloge = {
    maintenant: () => t,
    demanderImage: (suite) => {
      const id = suivant++;
      attente.set(id, suite);
      return id;
    },
    annulerImage: (id) => {
      attente.delete(id);
    },
  };
  const image = (ms = 16) => {
    t += ms;
    const lot = [...attente.values()];
    attente.clear();
    for (const suite of lot) suite();
  };
  return { horloge, image, enAttente: () => attente.size };
}

/** Un défileur de page dont on règle la hauteur (jsdom ne met rien en page). */
function defileur(hauteurContenu: number, hauteurVue = 812) {
  const el = document.createElement('div');
  el.className = 'overflow-y-auto';
  let haut = 0;
  let contenu = hauteurContenu;
  Object.defineProperty(el, 'scrollHeight', { get: () => contenu });
  Object.defineProperty(el, 'clientHeight', { get: () => hauteurVue });
  Object.defineProperty(el, 'scrollTop', {
    get: () => haut,
    set: (v: number) => {
      haut = Math.max(0, Math.min(v, contenu - hauteurVue));
    },
  });
  return Object.assign(el, {
    grandir(n: number) {
      contenu = n;
    },
  });
}

function colonneAvec(page: HTMLElement) {
  const colonne = document.createElement('div');
  colonne.setAttribute('data-colonne-page', '');
  colonne.append(page);
  document.body.append(colonne);
  return colonne;
}

/** Monte `page` à la place de la précédente, comme React change de route. */
function monter(colonne: HTMLElement, page: HTMLElement) {
  colonne.replaceChildren(page);
}

function defiler(suivi: ReturnType<typeof creerSuiviDesPages>, colonne: HTMLElement, el: HTMLElement, haut: number) {
  el.scrollTop = haut;
  const e = new Event('scroll');
  Object.defineProperty(e, 'target', { value: el });
  suivi.surDefilement(colonne, e);
}

describe('la position retenue au retour sur une page', () => {
  it('rend aux Tâches la position qu’on y avait laissée, dès la première image', () => {
    const { horloge } = horlogeDeBanc();
    const suivi = creerSuiviDesPages({ mobile: true, mouvementReduit: () => true, horloge });
    const taches = defileur(5000);
    const colonne = colonneAvec(taches);
    suivi.naviguer(colonne, '/vie/tasks');
    defiler(suivi, colonne, taches, 1567);

    const notes = defileur(12000);
    monter(colonne, notes);
    suivi.naviguer(colonne, '/vie/notes');
    defiler(suivi, colonne, notes, 2000);

    const tachesDeRetour = defileur(5000);
    monter(colonne, tachesDeRetour);
    suivi.naviguer(colonne, '/vie/tasks');
    expect(tachesDeRetour.scrollTop, 'la position des Tâches, pas celle des Notes quittées').toBe(1567);
  });

  it('suit le chemin courant : ce qu’on fait défiler sur une page est retenu sous CETTE page', () => {
    const { horloge } = horlogeDeBanc();
    const suivi = creerSuiviDesPages({ mobile: true, mouvementReduit: () => true, horloge });
    const a = defileur(5000);
    const colonne = colonneAvec(a);
    suivi.naviguer(colonne, '/a');
    defiler(suivi, colonne, a, 900);
    const b = defileur(5000);
    monter(colonne, b);
    suivi.naviguer(colonne, '/b');
    expect(suivi.chemin(), 'le suivi est passé sur la page arrivée').toBe('/b');
    defiler(suivi, colonne, b, 300);
    expect(suivi.memoire.lire('/a'), 'la page quittée garde SA position').toBe(900);
    expect(suivi.memoire.lire('/b'), 'la page arrivée a la sienne').toBe(300);
  });

  it('ne laisse jamais un défileur imbriqué écraser la position de la page', () => {
    const memoire = creerMemoireDefilement();
    const page = defileur(5000);
    const colonne = colonneAvec(page);
    const volet = defileur(2000, 300);
    page.append(volet);
    page.scrollTop = 1200;
    expect(retenirSiDefileurDePage(colonne, page, '/vie/projects', memoire), 'le défileur de la page est retenu').toBe(true);
    volet.scrollTop = 40;
    expect(retenirSiDefileurDePage(colonne, volet, '/vie/projects', memoire), 'le volet, lui, est ignoré').toBe(false);
    expect(memoire.lire('/vie/projects')).toBe(1200);
  });

  it('attend que la liste arrive, puis pose la position en entier', () => {
    const { horloge, image } = horlogeDeBanc();
    const page = defileur(0);
    const colonne = colonneAvec(page);
    reprendrePosition(colonne, 1567, horloge);
    image();
    expect(page.scrollTop, 'la liste charge : rien n’est posé à moitié').toBe(0);
    page.grandir(5000);
    image();
    expect(page.scrollTop, 'la liste est là : la position est rendue').toBe(1567);
  });

  it('un toucher pendant l’attente annule la reprise : rien ne saute sous le doigt', () => {
    const { horloge, image, enAttente } = horlogeDeBanc();
    const page = defileur(0);
    const colonne = colonneAvec(page);
    reprendrePosition(colonne, 1567, horloge);
    image();
    page.dispatchEvent(new Event('touchstart', { bubbles: true }));
    page.grandir(5000);
    image();
    image();
    expect(page.scrollTop, 'le doigt a repris la main : la page reste où il lit').toBe(0);
    expect(enAttente(), 'plus aucune image demandée').toBe(0);
  });

  it('renonce au plafond si la page ne peut toujours pas l’atteindre', () => {
    const { horloge, image, enAttente } = horlogeDeBanc();
    const page = defileur(0);
    const colonne = colonneAvec(page);
    reprendrePosition(colonne, 1567, horloge);
    image(PLAFOND_RESTAURATION_MS + 1);
    expect(enAttente(), 'au-delà du plafond, plus rien n’attend').toBe(0);
    page.grandir(5000);
    image();
    expect(page.scrollTop).toBe(0);
  });
});

describe('l’entrée de la page qui arrive', () => {
  function suiviAvecAnimation(reduit: boolean) {
    const { horloge } = horlogeDeBanc();
    const suivi = creerSuiviDesPages({ mobile: true, mouvementReduit: () => reduit, horloge });
    const colonne = colonneAvec(defileur(0));
    const animate = vi.fn(() => ({ cancel: vi.fn() }) as unknown as Animation);
    Object.assign(colonne, { animate });
    suivi.naviguer(colonne, '/vie/tasks');
    suivi.naviguer(colonne, '/vie/notes');
    return animate;
  }

  it('anime la colonne, avec les images et les options de l’entrée', () => {
    const animate = suiviAvecAnimation(false);
    expect(animate, 'une entrée par navigation').toHaveBeenCalledTimes(1);
    expect(animate).toHaveBeenCalledWith(IMAGES_ENTREE, OPTIONS_ENTREE);
  });

  it('une navigation arrivée pendant l’entrée de la précédente l’annule : jamais deux entrées empilées', () => {
    const { horloge } = horlogeDeBanc();
    const suivi = creerSuiviDesPages({ mobile: true, mouvementReduit: () => false, horloge });
    const colonne = colonneAvec(defileur(0));
    const entrees: { cancel: ReturnType<typeof vi.fn> }[] = [];
    Object.assign(colonne, {
      animate: vi.fn(() => {
        const e = { cancel: vi.fn() };
        entrees.push(e);
        return e as unknown as Animation;
      }),
    });
    suivi.naviguer(colonne, '/vie/tasks');
    suivi.naviguer(colonne, '/vie/notes');
    suivi.naviguer(colonne, '/vie/planner');
    expect(entrees.length).toBe(2);
    expect(entrees[0].cancel, 'l’entrée des Notes cède la place à celle du Planificateur').toHaveBeenCalledTimes(1);
    expect(entrees[1].cancel).not.toHaveBeenCalled();
  });

  it('sous « Supprimer les animations », n’anime rien', () => {
    expect(suiviAvecAnimation(true), 'bascule directe').not.toHaveBeenCalled();
  });

  it('le crochet transmet la vraie préférence du système, lue au moment de naviguer', () => {
    const crochet = readFileSync(join(__dirname, 'useTransitionDesPages.ts'), 'utf8');
    expect(crochet).toContain('creerSuiviDesPages({ mobile: estMobile, mouvementReduit })');
    expect(crochet).toContain("window.matchMedia('(prefers-reduced-motion: reduce)').matches");
  });
});
