import { describe, expect, it } from 'vitest';

import {
  ZOOM_MAX,
  ZOOM_NEUTRE,
  boiteDe,
  bornerZoom,
  cadreDepuisCoins,
  chargeUtile,
  composerCadres,
  deRecadrerAnnotations,
  deplacerVers,
  dimensionsReduites,
  dispositionPile,
  distanceCirculaire,
  estGlisserDePhoto,
  facteurMolette,
  idAnnotation,
  indexSuivant,
  libelleTaille,
  libelleZoom,
  nomFichierPdf,
  placeEventail,
  pointeFleche,
  recadrerAnnotations,
  tailleRetouchee,
  teinteAvecAlpha,
  teinteDominante,
  tournerAnnotations,
  tournerCadre,
  verifierFichierImage,
  zoomerAutour,
} from './photos';
import type { SuccesAnnotation, SuccesPhoto } from './types';

const photo = (id: string): SuccesPhoto => ({
  id,
  pileId: 'p',
  projectId: 'x',
  fileName: `${id}.jpg`,
  mime: 'image/jpeg',
  bytes: 10,
  width: 1,
  height: 1,
  tint: '',
  caption: '',
  taskId: '',
  position: 0,
  rotation: 0,
  crop: null,
  annotations: [],
  ocrText: '',
  thumb: '',
  createdAtMs: 1,
  updatedAtMs: 1,
});

describe('verifierFichierImage', () => {
  it('accepte tel quel ce que le serveur sait ranger', () => {
    expect(verifierFichierImage({ type: 'image/png', size: 10, name: 'a.png' })).toEqual({
      ok: true,
      convertir: false,
    });
  });

  it('convertit un HEIC d’iPhone, même quand le Finder ne dit pas son type', () => {
    expect(verifierFichierImage({ type: 'image/heic', size: 10, name: 'IMG_1.HEIC' }).convertir).toBe(true);
    expect(verifierFichierImage({ type: '', size: 10, name: 'IMG_1.heic' }).convertir).toBe(true);
  });

  it('refuse une vidéo et un fichier vide sans les lire', () => {
    expect(verifierFichierImage({ type: 'video/quicktime', size: 10, name: 'a.mov' }).ok).toBe(false);
    expect(verifierFichierImage({ type: 'image/png', size: 0, name: 'a.png' }).raison).toMatch(/vide/);
  });

  it('refuse ce qui dépasse la taille d’une photo', () => {
    const verdict = verifierFichierImage({ type: 'image/png', size: 30 * 1024 * 1024, name: 'a.png' });
    expect(verdict.ok).toBe(false);
    expect(verdict.raison).toMatch(/25 Mo/);
  });
});

describe('dimensionsReduites', () => {
  it('ne touche pas à ce qui tient déjà', () => {
    expect(dimensionsReduites(300, 200, 480)).toEqual({ largeur: 300, hauteur: 200 });
  });

  it('ramène le grand côté et garde les proportions', () => {
    expect(dimensionsReduites(4000, 3000, 480)).toEqual({ largeur: 480, hauteur: 360 });
    expect(dimensionsReduites(1000, 4000, 480)).toEqual({ largeur: 120, hauteur: 480 });
  });

  it('ne rend jamais zéro', () => {
    expect(dimensionsReduites(10000, 1, 480)).toEqual({ largeur: 480, hauteur: 1 });
  });
});

describe('chargeUtile', () => {
  it('retire le préfixe d’une URL de données et laisse le reste intact', () => {
    expect(chargeUtile('data:image/jpeg;base64,AAAA')).toBe('AAAA');
    expect(chargeUtile('AAAA')).toBe('AAAA');
  });
});

describe('teinteDominante', () => {
  const remplir = (couleurs: Array<[number, number, number, number]>) => {
    const px = new Uint8ClampedArray(couleurs.length * 4);
    couleurs.forEach((c, i) => px.set(c, i * 4));
    return px;
  };

  it('rend la couleur saturée la plus fréquente, pas la moyenne', () => {
    const px = remplir([
      ...Array.from({ length: 60 }, () => [30, 120, 220, 255] as [number, number, number, number]),
      ...Array.from({ length: 40 }, () => [220, 40, 40, 255] as [number, number, number, number]),
    ]);
    // Le bleu (30,120,220) tombe dans la case 1/7/13 → centre 24/120/216.
    expect(teinteDominante(px)).toBe('#1878d8');
  });

  it('ignore le blanc et le noir d’une capture d’écran', () => {
    const px = remplir([
      ...Array.from({ length: 900 }, () => [250, 250, 250, 255] as [number, number, number, number]),
      ...Array.from({ length: 50 }, () => [40, 160, 60, 255] as [number, number, number, number]),
    ]);
    expect(teinteDominante(px)).toBe('#28a838');
  });

  it('retombe sur la moyenne quand rien n’est coloré', () => {
    const px = remplir(Array.from({ length: 10 }, () => [30, 30, 30, 255] as [number, number, number, number]));
    expect(teinteDominante(px)).toBe('#1e1e1e');
  });

  it('ne se laisse pas teinter par un bouton rouge sur du gris', () => {
    const px = remplir([
      ...Array.from({ length: 1000 }, () => [128, 128, 128, 255] as [number, number, number, number]),
      ...Array.from({ length: 5 }, () => [255, 0, 0, 255] as [number, number, number, number]),
    ]);
    // La moyenne, rouge compris : un gris à peine chaud, pas un rouge.
    expect(teinteDominante(px)).toBe('#817f7f');
  });

  it('rend vide sans pixel opaque', () => {
    expect(teinteDominante(new Uint8ClampedArray(0))).toBe('');
    expect(teinteDominante(remplir([[255, 0, 0, 10]]))).toBe('');
  });
});

describe('teinteAvecAlpha', () => {
  it('convertit et borne l’alpha', () => {
    expect(teinteAvecAlpha('#1878d8', 0.5)).toBe('rgba(24, 120, 216, 0.5)');
    expect(teinteAvecAlpha('#1878D8', 2)).toBe('rgba(24, 120, 216, 1)');
  });

  it('refuse du texte libre — il irait dans un style', () => {
    expect(teinteAvecAlpha('red;x', 0.5)).toBeUndefined();
    expect(teinteAvecAlpha('', 0.5)).toBeUndefined();
  });
});

describe('dispositionPile', () => {
  it('peint la couverture en dernier, droite, au-dessus', () => {
    const cartes = dispositionPile([photo('couverture'), photo('b'), photo('c')]);
    expect(cartes.map((c) => c.photo.id)).toEqual(['c', 'b', 'couverture']);
    expect(cartes[2]).toMatchObject({ rotation: 0, dx: 0, dy: 0, z: 2 });
    expect(cartes[0].z).toBe(0);
  });

  it('une seule photo est droite ; deux photos, la couverture reste droite', () => {
    expect(dispositionPile([photo('a')])[0]).toMatchObject({ rotation: 0, z: 0 });
    const deux = dispositionPile([photo('couverture'), photo('b')]);
    expect(deux[1].photo.id).toBe('couverture');
    expect(deux[1].rotation).toBe(0);
    expect(deux[0].rotation).not.toBe(0);
  });

  it('n’en montre jamais plus de trois', () => {
    expect(dispositionPile([photo('1'), photo('2'), photo('3'), photo('4')])).toHaveLength(3);
  });

  it('rend vide pour une pile vide', () => {
    expect(dispositionPile([])).toEqual([]);
  });
});

describe('libelleTaille', () => {
  it('parle en Ko sous le méga, en Mo au-dessus', () => {
    expect(libelleTaille(340 * 1024)).toBe('340 Ko');
    expect(libelleTaille(500)).toBe('1 Ko');
    expect(libelleTaille(1.25 * 1024 * 1024)).toMatch(/^1,[23] Mo$/);
  });
});

describe('indexSuivant', () => {
  it('boucle aux deux bouts', () => {
    expect(indexSuivant(0, 5, -1)).toBe(4);
    expect(indexSuivant(4, 5, 1)).toBe(0);
    expect(indexSuivant(2, 5, 1)).toBe(3);
    expect(indexSuivant(0, 0, 1)).toBe(-1);
  });
});

describe('éventail', () => {
  it('mesure la distance la plus courte en boucle', () => {
    expect(distanceCirculaire(0, 6, 7)).toBe(1);
    expect(distanceCirculaire(6, 0, 7)).toBe(-1);
    expect(distanceCirculaire(3, 3, 7)).toBe(0);
    expect(distanceCirculaire(0, 0, 0)).toBe(0);
  });

  it('place le centre droit, les voisines décroissantes, le reste hors champ', () => {
    expect(placeEventail(0)).toMatchObject({ x: 0, echelle: 1, rotation: 0, opacite: 1, visible: true });
    expect(placeEventail(-1)).toMatchObject({ x: -1, rotation: -4, opacite: 0.7, visible: true });
    expect(placeEventail(2).echelle).toBeCloseTo(0.64);
    expect(placeEventail(3).visible).toBe(false);
    expect(placeEventail(-3).x).toBe(-3);
  });
});

describe('retouche', () => {
  it('échange les côtés à 90° et applique le cadre', () => {
    expect(tailleRetouchee(1600, 1000, 90, null)).toEqual({ largeur: 1000, hauteur: 1600 });
    expect(tailleRetouchee(1600, 1000, 180, { x: 0, y: 0, w: 0.5, h: 0.25 })).toEqual({
      largeur: 800,
      hauteur: 250,
    });
  });

  it('compose un cadre dessiné sur une image déjà cadrée', () => {
    const ancien = { x: 0.2, y: 0.2, w: 0.5, h: 0.5 };
    expect(composerCadres(ancien, { x: 0.5, y: 0, w: 0.5, h: 1 })).toEqual({
      x: 0.45,
      y: 0.2,
      w: 0.25,
      h: 0.5,
    });
    expect(composerCadres(null, { x: 0.1, y: 0.1, w: 0.3, h: 0.3 })).toEqual({ x: 0.1, y: 0.1, w: 0.3, h: 0.3 });
  });

  it('un cadre se dessine dans n’importe quel sens, et refuse le minuscule', () => {
    expect(cadreDepuisCoins({ x: 0.8, y: 0.9 }, { x: 0.2, y: 0.1 })).toEqual({ x: 0.2, y: 0.1, w: 0.6, h: 0.8 });
    expect(cadreDepuisCoins({ x: 0.5, y: 0.5 }, { x: 0.505, y: 0.9 })).toBeNull();
    expect(cadreDepuisCoins({ x: -1, y: -1 }, { x: 2, y: 2 })).toEqual({ x: 0, y: 0, w: 1, h: 1 });
  });

  const fleche = (): SuccesAnnotation => ({
    id: 'f',
    type: 'arrow',
    color: '#ff3b30',
    points: [
      [0.1, 0.2],
      [0.5, 0.2],
    ],
    width: 3,
  });

  it('les annotations tournent avec l’image', () => {
    const [t] = tournerAnnotations([fleche()], 1);
    expect(t.points[0][0]).toBeCloseTo(0.8);
    expect(t.points[0][1]).toBeCloseTo(0.1);
    // Quatre quarts de tour : retour au départ.
    const [q] = tournerAnnotations([fleche()], 4);
    expect(q.points).toEqual(fleche().points);
    expect(tournerAnnotations([fleche()], -1)[0].points[0][0]).toBeCloseTo(0.2);
  });

  it('un cadre tourne avec l’image, et quatre quarts le ramènent', () => {
    const c = { x: 0.1, y: 0.2, w: 0.5, h: 0.25 };
    expect(tournerCadre(c, 1)).toEqual({ x: 0.55, y: 0.1, w: 0.25, h: 0.5 });
    expect(tournerCadre(c, 4)).toEqual(c);
    expect(tournerCadre(tournerCadre(c, 1), -1)).toEqual(c);
    expect(tournerCadre(null, 1)).toBeNull();
  });

  it('dé-recadrer annule recadrer', () => {
    const cadre = { x: 0.2, y: 0.1, w: 0.5, h: 0.5 };
    const [aller] = recadrerAnnotations([fleche()], { ...cadre, w: 1, h: 1, x: 0, y: 0 });
    expect(aller.points).toEqual(fleche().points);
    const [retour] = deRecadrerAnnotations(recadrerAnnotations([fleche()], cadre), cadre);
    retour.points.forEach((p, i) => {
      expect(p[0]).toBeCloseTo(fleche().points[i][0]);
      expect(p[1]).toBeCloseTo(fleche().points[i][1]);
    });
  });

  it('les annotations suivent le cadre, et disparaissent si elles en sortent', () => {
    const cadre = { x: 0, y: 0, w: 0.5, h: 0.5 };
    const [dedans] = recadrerAnnotations([fleche()], cadre);
    expect(dedans.points[0]).toEqual([0.2, 0.4]);
    expect(dedans.points[1][0]).toBeCloseTo(1);
    const dehors = { ...fleche(), points: [[0.9, 0.9], [0.95, 0.95]] as Array<[number, number]> };
    expect(recadrerAnnotations([dehors], cadre)).toEqual([]);
  });
});

describe('annotations', () => {
  it('calcule la boîte de deux coins', () => {
    expect(boiteDe([[0.6, 0.1], [0.2, 0.5]])).toEqual({ x: 0.2, y: 0.1, w: 0.4, h: 0.4 });
  });

  it('la pointe de flèche a trois points, le premier étant la cible', () => {
    const p = pointeFleche({ x: 0, y: 0 }, { x: 100, y: 0 }, 3);
    expect(p).toHaveLength(3);
    expect(p[0]).toEqual({ x: 100, y: 0 });
    expect(p[1].x).toBeLessThan(100);
    // Les deux ailes s'écartent de part et d'autre du trait.
    expect(Math.sign(p[1].y)).toBe(-Math.sign(p[2].y));
    expect(Math.abs(p[1].y)).toBeGreaterThan(0);
  });

  it('deux identifiants ne se ressemblent pas', () => {
    expect(idAnnotation()).not.toBe(idAnnotation());
  });
});

describe('nomFichierPdf', () => {
  it('enlève les accents et ce qui n’a rien à faire dans un nom de fichier', () => {
    expect(nomFichierPdf('Décorateurs & générateurs / Python')).toBe('Decorateurs generateurs Python.pdf');
    expect(nomFichierPdf('   ')).toBe('photos.pdf');
  });
});

describe('deplacerVers', () => {
  it('la photo prend la place de la cible, les autres glissent', () => {
    expect(deplacerVers(['a', 'b', 'c', 'd'], 'd', 'b')).toEqual(['a', 'd', 'b', 'c']);
    expect(deplacerVers(['a', 'b', 'c', 'd'], 'a', 'c')).toEqual(['b', 'c', 'a', 'd']);
  });

  it('en première position, elle devient la grande', () => {
    expect(deplacerVers(['a', 'b', 'c'], 'c', 'a')[0]).toBe('c');
  });

  it('ne change rien sur elle-même ou sur un inconnu, et ne mute pas', () => {
    const ids = ['a', 'b'];
    expect(deplacerVers(ids, 'a', 'a')).toBe(ids);
    expect(deplacerVers(ids, 'x', 'a')).toBe(ids);
    deplacerVers(ids, 'a', 'b');
    expect(ids).toEqual(['a', 'b']);
  });
});

describe('estGlisserDePhoto', () => {
  it('distingue une photo de la grille de fichiers du Finder', () => {
    expect(estGlisserDePhoto(['text/x-diapason-photo'])).toBe(true);
    expect(estGlisserDePhoto(['Files'])).toBe(false);
    expect(estGlisserDePhoto(null)).toBe(false);
  });
});

describe('zoom', () => {
  const cadre = { largeur: 1000, hauteur: 600 };
  const image = { largeur: 800, hauteur: 500 };

  it('ne dépasse pas les bornes et reste centré quand l’image tient', () => {
    expect(bornerZoom({ echelle: 0.2, x: 50, y: 50 }, cadre, image)).toEqual({ echelle: 1, x: 0, y: 0 });
    expect(bornerZoom({ echelle: 40, x: 0, y: 0 }, cadre, image).echelle).toBe(ZOOM_MAX);
  });

  it('laisse dépasser sans laisser partir', () => {
    // À ×2, l'image fait 1600×1000 : 300 px de jeu en x, 200 en y.
    const z = bornerZoom({ echelle: 2, x: 999, y: -999 }, cadre, image);
    expect(z).toEqual({ echelle: 2, x: 300, y: -200 });
  });

  it('garde sous le curseur ce qui y était', () => {
    const point = { x: 700, y: 400 };
    const avant = { echelle: 1, x: 0, y: 0 };
    const apres = zoomerAutour(avant, 2, point, cadre, image);
    expect(apres.echelle).toBe(2);
    // Le point (700,400) est à (+200,+100) du centre. Dans l'image à ×1 :
    // u = (200,100). À ×2 il faut t = p − u·2 = (−200, −100).
    expect(apres.x).toBe(-200);
    expect(apres.y).toBe(-100);
  });

  it('revient exactement au neutre en dézoomant', () => {
    const z = zoomerAutour({ echelle: 2, x: -200, y: -100 }, 0.5, { x: 700, y: 400 }, cadre, image);
    expect(z).toEqual(ZOOM_NEUTRE);
  });

  it('la molette vers le haut agrandit, vers le bas réduit', () => {
    expect(facteurMolette(-100)).toBeGreaterThan(1);
    expect(facteurMolette(100)).toBeLessThan(1);
    expect(facteurMolette(0)).toBe(1);
  });

  it('s’affiche en pour cent', () => {
    expect(libelleZoom(2.5)).toBe('250 %');
  });
});
