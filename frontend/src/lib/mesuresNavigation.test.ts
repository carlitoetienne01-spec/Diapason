// Le relevé de fluidité du téléphone (chantier de la fluidité, lot 2,
// 26/09/2026) : Carlito doit lire les vrais chiffres de SON téléphone dans
// Réglages, et ces chiffres ne doivent jamais flatter.

import { describe, expect, it } from 'vitest';

import {
  CLE_STOCKAGE,
  PAR_SERIE_MAX,
  PLAFOND_MS,
  ReleveNavigation,
  borner,
  centile,
  mediane,
  resumer,
  routeDe,
  type Echantillon,
  type StockageMesures,
} from './mesuresNavigation';

function stockageEnMemoire(): StockageMesures & { donnees: Map<string, string> } {
  const donnees = new Map<string, string>();
  return {
    donnees,
    getItem: (cle) => donnees.get(cle) ?? null,
    setItem: (cle, valeur) => void donnees.set(cle, valeur),
    removeItem: (cle) => void donnees.delete(cle),
  };
}

/** Un monde réglable : l'horloge, les images, le contenu, la visibilité. */
function monde() {
  const etat = { t: 0, pret: false, visible: true, images: [] as ((t: number) => void)[] };
  const stockage = stockageEnMemoire();
  const releve = new ReleveNavigation({
    maintenant: () => etat.t,
    horodatage: () => 1_758_900_000_000,
    image: (rappel) => void etat.images.push(rappel),
    contenuPret: () => etat.pret,
    visible: () => etat.visible,
    stockage: () => stockage,
  });
  /** Avance l'horloge et joue l'image suivante à cet instant. */
  const image = (t: number) => {
    etat.t = t;
    const lot = etat.images.splice(0);
    for (const rappel of lot) rappel(t);
  };
  return { etat, releve, stockage, image };
}

describe('centile et mediane', () => {
  it('rend une valeur réellement mesurée pour le 90e centile, jamais une interpolation', () => {
    const valeurs = [10, 20, 30, 40, 50, 60, 70, 80, 90, 1000];
    expect(centile(valeurs, 90), 'le 9e sur 10').toBe(90);
    expect(centile([5], 90), 'un seul relevé est son propre centile').toBe(5);
    expect(centile([], 90), 'rien à dire sans relevé').toBeNull();
  });

  it('prend la moyenne des deux du milieu pour un nombre pair de relevés', () => {
    expect(mediane([40, 10, 30, 20])).toBe(25);
    expect(mediane([3, 1, 2])).toBe(2);
  });
});

describe('routeDe', () => {
  it('ne fait pas deux pages d’une barre finale, d’une requête ou d’une ancre', () => {
    expect(routeDe('/vie/tasks/')).toBe('/vie/tasks');
    expect(routeDe('/vie/tasks?vue=liste#haut')).toBe('/vie/tasks');
    expect(routeDe('/')).toBe('/');
  });
});

describe('ReleveNavigation', () => {
  it("mesure l'ouverture de l'app depuis l'origine du document, pas depuis le premier rendu", () => {
    const { etat, releve, image } = monde();
    etat.t = 900;
    releve.debut('k0', '/', 900);
    releve.montee('k0');
    etat.pret = true;
    image(1_234);
    const [e] = releve.echantillons();
    expect(e.genre, 'la première navigation est l’ouverture').toBe('ouverture');
    expect(e.ms, 'comptée depuis 0, l’origine du document').toBe(1_234);
  });

  it('distingue la première visite d’une page de ses retours', () => {
    const { etat, releve, image } = monde();
    etat.pret = true;
    for (const [cle, chemin, t0] of [
      ['k0', '/', 0],
      ['k1', '/vie/tasks', 1000],
      ['k2', '/', 2000],
      ['k3', '/vie/tasks', 3000],
    ] as const) {
      releve.debut(cle, chemin, t0);
      releve.montee(cle);
      image(t0 + 40);
    }
    expect(releve.echantillons().map((e) => `${e.route} ${e.genre}`)).toEqual([
      '/ ouverture',
      '/vie/tasks premiere',
      '/ revisite',
      '/vie/tasks revisite',
    ]);
  });

  it("attend que la page soit montée ET qu'aucun chargement ne soit affiché", () => {
    const { etat, releve, image } = monde();
    releve.debut('k0', '/', 0);
    releve.montee('k0');
    image(10);
    releve.debut('k1', '/vie/notes', 100);
    image(150);
    expect(etat.images.length, 'rien n’est guetté avant la montée de la page').toBe(0);
    releve.montee('k1');
    image(300);
    image(420);
    expect(releve.echantillons().filter((e) => e.route === '/vie/notes'), 'toujours « Chargement… »').toEqual([]);
    etat.pret = true;
    image(612);
    const notes = releve.echantillons().find((e) => e.route === '/vie/notes');
    expect(notes?.ms, 'la première image où le contenu est là').toBe(512);
  });

  it('ne garde aucun chiffre pour une page quittée avant son contenu', () => {
    const { etat, releve, image } = monde();
    releve.debut('k0', '/', 0);
    releve.montee('k0');
    releve.debut('k1', '/vie/projects', 50);
    image(120);
    etat.pret = true;
    image(200);
    expect(releve.echantillons().map((e) => e.route), 'ni la Discussion ni les Projets, quittés trop tôt').toEqual([]);
  });

  it("ne garde aucun chiffre quand l'écran s'éteint pendant l'attente : la veille n'est pas de la lenteur", () => {
    const { etat, releve, image } = monde();
    releve.debut('k0', '/', 0);
    releve.montee('k0');
    etat.visible = false;
    etat.pret = true;
    image(45_000);
    expect(releve.echantillons(), 'aucune durée qui contient une mise en veille').toEqual([]);
  });

  it('garde au plafond, marquée, une page qui ne montre jamais son contenu — elle ne sort pas du relevé', () => {
    const { releve, image } = monde();
    releve.debut('k0', '/vie/finances', 0);
    releve.montee('k0');
    image(5_000);
    image(PLAFOND_MS + 16);
    const [e] = releve.echantillons();
    expect(e.ms, 'comptée au plafond').toBe(PLAFOND_MS);
    expect(e.plafond, 'et marquée comme telle').toBe(true);
  });

  it('ne compte pas un changement de requête sur la même page comme une navigation', () => {
    const { etat, releve, image } = monde();
    etat.pret = true;
    releve.debut('k0', '/vie/tasks', 0);
    releve.montee('k0');
    image(30);
    releve.debut('k1', '/vie/tasks?vue=liste', 100);
    releve.montee('k1');
    image(130);
    expect(releve.echantillons().length, 'un seul relevé pour la page').toBe(1);
  });

  it('est idempotent au double rendu de StrictMode', () => {
    const { etat, releve, image } = monde();
    etat.pret = true;
    releve.debut('k0', '/', 0);
    releve.debut('k0', '/', 5);
    releve.montee('k0');
    releve.montee('k0');
    image(20);
    image(40);
    expect(releve.echantillons().length, 'un seul relevé malgré deux rendus et deux montées').toBe(1);
  });

  it('persiste les relevés pour que Carlito les lise sur plusieurs jours, et les efface sur demande', () => {
    const { etat, releve, stockage, image } = monde();
    etat.pret = true;
    releve.debut('k0', '/', 0);
    releve.montee('k0');
    image(700);
    expect(JSON.parse(stockage.donnees.get(CLE_STOCKAGE) ?? '[]'), 'écrit au stockage').toHaveLength(1);
    const relu = new ReleveNavigation({
      maintenant: () => 0,
      horodatage: () => 0,
      image: () => {},
      contenuPret: () => true,
      visible: () => true,
      stockage: () => stockage,
    });
    expect(relu.echantillons()[0]?.ms, 'relu par un nouveau lancement').toBe(700);
    relu.effacer();
    expect(stockage.donnees.has(CLE_STOCKAGE), 'effacé du stockage').toBe(false);
    expect(relu.echantillons(), 'et de la mémoire').toEqual([]);
  });

  it('ignore un stockage corrompu au lieu de casser les Réglages', () => {
    const stockage = stockageEnMemoire();
    stockage.setItem(CLE_STOCKAGE, '{pas du json');
    const releve = new ReleveNavigation({
      maintenant: () => 0,
      horodatage: () => 0,
      image: () => {},
      contenuPret: () => true,
      visible: () => true,
      stockage: () => stockage,
    });
    expect(releve.echantillons()).toEqual([]);
  });
});

describe('borner et resumer', () => {
  it(`ne garde que les ${PAR_SERIE_MAX} derniers relevés de chaque série`, () => {
    const serie: Echantillon[] = Array.from({ length: PAR_SERIE_MAX + 5 }, (_, i) => ({
      route: '/vie/tasks',
      genre: 'revisite',
      ms: i,
      quand: i,
    }));
    const autre: Echantillon = { route: '/', genre: 'ouverture', ms: 1500, quand: 0 };
    const gardes = borner([autre, ...serie]);
    expect(gardes.filter((e) => e.route === '/vie/tasks').map((e) => e.ms)[0], 'les plus anciens tombent').toBe(5);
    expect(gardes.includes(autre), 'une autre série n’est pas rognée par celle-ci').toBe(true);
  });

  it('résume par page et par genre avec médiane, 90e centile, dernier et relevés au plafond', () => {
    const e = (ms: number, genre: Echantillon['genre'] = 'revisite', plafond?: boolean): Echantillon => ({
      route: '/vie/tasks',
      genre,
      ms,
      quand: 0,
      ...(plafond ? { plafond } : {}),
    });
    const lignes = resumer([e(700, 'premiere'), e(20), e(40), e(30), e(PLAFOND_MS, 'revisite', true)]);
    expect(lignes).toEqual([
      { route: '/vie/tasks', genre: 'premiere', n: 1, medianeMs: 700, p90Ms: 700, dernierMs: 700, auPlafond: 0 },
      { route: '/vie/tasks', genre: 'revisite', n: 4, medianeMs: 35, p90Ms: PLAFOND_MS, dernierMs: PLAFOND_MS, auPlafond: 1 },
    ]);
  });
});
