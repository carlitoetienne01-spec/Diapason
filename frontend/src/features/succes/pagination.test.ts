import { describe, expect, it } from 'vitest';

import {
  ELLIPSE,
  TAILLE_PAGE_DEFAUT,
  bornerPage,
  estTaillePage,
  fenetrePages,
  nombreDePages,
  pageApresRetaille,
  pageDe,
  pageParFleche,
  paginer,
} from './pagination';

const GARDE_LIBRE = { modifieur: false, saisie: false, surcouche: false };

describe('la tranche d’une page (demande de Carlito, 17 sept. 2026)', () => {
  const liste = Array.from({ length: 12 }, (_, i) => `t${i + 1}`);

  it('rend cinq tâches par page par défaut, et la dernière page ce qui reste', () => {
    expect(TAILLE_PAGE_DEFAUT).toBe(5);
    const p1 = paginer(liste, 1, 5);
    expect(p1.tranche).toEqual(['t1', 't2', 't3', 't4', 't5']);
    expect([p1.debut, p1.fin, p1.nbPages, p1.total]).toEqual([1, 5, 3, 12]);
    const p3 = paginer(liste, 3, 5);
    // La dernière page ne porte que le reste.
    expect(p3.tranche).toEqual(['t11', 't12']);
    expect([p3.debut, p3.fin]).toEqual([11, 12]);
  });

  it('ramène dans les bornes une page retenue qui n’existe plus', () => {
    // La page 12 d'une visite à 20 pages, après un filtre qui en laisse 3 :
    // « Aucune tâche ici » sous un pageur qui disait le contraire.
    expect(paginer(liste, 12, 5).page).toBe(3);
    expect(paginer(liste, 0, 5).page).toBe(1);
    expect(paginer(liste, -4, 5).page).toBe(1);
    expect(bornerPage(Number.NaN, 3)).toBe(1);
  });

  it('a toujours une page, même vide, pour que rien ne divise par zéro', () => {
    const vide = paginer([], 3, 5);
    expect([vide.page, vide.nbPages, vide.debut, vide.fin]).toEqual([1, 1, 0, 0]);
    expect(nombreDePages(0, 5)).toBe(1);
    expect(nombreDePages(473, 5)).toBe(95);
  });

  it('ne reconnaît que les trois tailles offertes — une préférence corrompue retombe sur 5', () => {
    expect(estTaillePage(5) && estTaillePage(10) && estTaillePage(20)).toBe(true);
    expect(estTaillePage(7)).toBe(false);
    expect(estTaillePage('10')).toBe(false);
  });

  it('garde le premier élément visible quand la taille change', () => {
    // Page 7 à 5 par page = éléments 31–35 ; à 20 par page, c'est la page 2.
    expect(pageApresRetaille(7, 5, 20)).toBe(2);
    // Page 2 à 20 par page = éléments 21–40 ; à 5 par page, la page 5.
    expect(pageApresRetaille(2, 20, 5)).toBe(5);
    expect(pageApresRetaille(1, 5, 10)).toBe(1);
  });

  it('dit sur quelle page tombe un élément — pour y aller quand un toast le désigne', () => {
    expect(pageDe(liste, (t) => t === 't6', 5)).toBe(2);
    expect(pageDe(liste, (t) => t === 't1', 5)).toBe(1);
    expect(pageDe(liste, (t) => t === 'absente', 5)).toBeNull();
  });
});

describe('la fenêtre de numéros du pageur', () => {
  it('montre tout quand il y a peu de pages', () => {
    expect(fenetrePages(1, 1)).toEqual([1]);
    expect(fenetrePages(2, 4)).toEqual([1, 2, 3, 4]);
  });

  it('garde la première, la dernière, la courante et ses voisines, une ellipse par trou', () => {
    expect(fenetrePages(50, 95)).toEqual([1, ELLIPSE, 49, 50, 51, ELLIPSE, 95]);
    expect(fenetrePages(1, 95)).toEqual([1, 2, ELLIPSE, 95]);
    expect(fenetrePages(95, 95)).toEqual([1, ELLIPSE, 94, 95]);
  });

  it('comble un trou d’une seule page par son numéro : une ellipse qui cache un chiffre prend sa place en disant moins', () => {
    expect(fenetrePages(4, 95)).toEqual([1, 2, 3, 4, 5, ELLIPSE, 95]);
    expect(fenetrePages(3, 6)).toEqual([1, 2, 3, 4, 5, 6]);
  });

  it('ne dépasse jamais sept cases — ce qui tient à 340 px avec les deux flèches', () => {
    for (let page = 1; page <= 95; page += 1) {
      expect(fenetrePages(page, 95).length).toBeLessThanOrEqual(7);
    }
  });

  it('borne une page hors champ avant de la fenêtrer', () => {
    expect(fenetrePages(40, 3)).toEqual([1, 2, 3]);
  });
});

describe('les flèches du clavier', () => {
  it('avancent et reculent d’une page', () => {
    expect(pageParFleche('ArrowRight', 2, 5, GARDE_LIBRE)).toBe(3);
    expect(pageParFleche('ArrowLeft', 2, 5, GARDE_LIBRE)).toBe(1);
  });

  it('rendent la touche au bout de la liste — ni page 0 ni page 6', () => {
    expect(pageParFleche('ArrowLeft', 1, 5, GARDE_LIBRE)).toBeNull();
    expect(pageParFleche('ArrowRight', 5, 5, GARDE_LIBRE)).toBeNull();
  });

  it('ignorent toute autre touche et toute flèche avec modificateur', () => {
    expect(pageParFleche('ArrowDown', 2, 5, GARDE_LIBRE)).toBeNull();
    expect(pageParFleche('ArrowRight', 2, 5, { ...GARDE_LIBRE, modifieur: true })).toBeNull();
  });

  it('laissent les flèches au champ de recherche et à la modale ouverte', () => {
    // Dans « Rechercher », ← déplace le caret ; dans ConfirmDialog, rien ne
    // doit changer de page derrière le voile (§82 : le clavier reste sûr).
    expect(pageParFleche('ArrowLeft', 2, 5, { ...GARDE_LIBRE, saisie: true })).toBeNull();
    expect(pageParFleche('ArrowRight', 2, 5, { ...GARDE_LIBRE, surcouche: true })).toBeNull();
  });
});
