import { describe, expect, it } from 'vitest';

import {
  BORD_PX,
  DUREE_MAX_MS,
  DUREE_MIN_MS,
  ECART_PX,
  INERTIE_MAX,
  RAYON_MAX_PX,
  RAYON_MIN_PX,
  RESSORT_MAX,
  chargeBordRoue,
  cibleAimantation,
  BANDE_BORD_PX,
  commenceAuBord,
  commenceDansLaBande,
  decisionDuBord,
  dureeAimantation,
  geometrieRoue,
  glisseOuvreLaRoue,
  indexAllume,
  issueDuRelache,
  placerElement,
  rotationAuTemps,
  rotationDuGlisse,
  vitesseDuGlisse,
} from './geometrieRoue';

/** Le téléphone du banc : 375 × 812, la roue sous un en-tête de 96 px. */
const TELEPHONE = { largeur: 375, hauteur: 812, haut: 96, bas: 812 };
const droite = geometrieRoue({ ...TELEPHONE, cote: 'droite' });
const gauche = geometrieRoue({ ...TELEPHONE, cote: 'gauche' });

describe("L'arc a son centre hors de l'écran, du côté de la main", () => {
  it('à droite, le centre est au-delà du bord droit ; à gauche, au-delà du bord gauche', () => {
    // Échec évité (décision du 26/09/2026, proposition A) : un centre dans
    // l'écran dessine un cercle entier, pas un arc au bord du pouce.
    expect(droite.centreX, 'le centre doit être hors de l’écran à droite').toBeGreaterThan(375);
    const centreGauche = placerElement(0, 0, gauche).x - gauche.rayon;
    expect(centreGauche, 'le miroir doit mettre le centre hors de l’écran à gauche').toBeLessThan(0);
  });

  it('l’élément allumé est au milieu vertical de la zone de la roue', () => {
    const p = placerElement(5, 5, droite);
    expect(p.y, 'l’élément allumé doit être au centre de la zone').toBeCloseTo((96 + 812) / 2, 5);
    expect(p.allume, 'l’élément au centre doit être allumé').toBe(true);
    expect(p.x, 'la pastille allumée tombe à xAllume').toBeCloseTo(droite.xAllume, 5);
  });

  it('les voisins s’écartent vers le bord de la roue, jamais vers l’intérieur', () => {
    const centre = placerElement(5, 5, droite).x;
    for (const i of [3, 4, 6, 7]) {
      expect(placerElement(i, 5, droite).x, `le voisin ${i} doit être plus à droite`).toBeGreaterThan(centre);
    }
    const centreG = placerElement(5, 5, gauche).x;
    for (const i of [3, 4, 6, 7]) {
      expect(placerElement(i, 5, gauche).x, `à gauche, le voisin ${i} doit être plus à gauche`).toBeLessThan(centreG);
    }
  });

  it('la gauche est le miroir exact de la droite', () => {
    for (const r of [0, 2.4, 7]) {
      for (let i = 0; i < 17; i += 1) {
        const d = placerElement(i, r, droite);
        const g = placerElement(i, r, gauche);
        expect(g.x, 'x miroir').toBeCloseTo(375 - d.x, 6);
        expect(g.y, 'y identique').toBeCloseTo(d.y, 6);
        expect(g.opacite, 'opacité identique').toBeCloseTo(d.opacite, 6);
      }
    }
  });

  it('deux éléments voisins sont à ECART_PX l’un de l’autre sur l’arc', () => {
    const a = placerElement(4, 4, droite);
    const b = placerElement(5, 4, droite);
    const corde = Math.hypot(b.x - a.x, b.y - a.y);
    // La corde est un peu plus courte que l'arc ; à ce rayon, de moins d'un pixel.
    expect(corde, 'l’écart entre voisins doit être ~64 px').toBeGreaterThan(ECART_PX - 1);
    expect(corde).toBeLessThanOrEqual(ECART_PX);
  });

  it('le rayon est borné, du petit écran à la tablette', () => {
    expect(geometrieRoue({ largeur: 320, hauteur: 400, cote: 'droite' }).rayon).toBe(RAYON_MIN_PX);
    expect(geometrieRoue({ largeur: 800, hauteur: 1400, cote: 'droite' }).rayon).toBe(RAYON_MAX_PX);
  });
});

describe('Les autres éléments s’estompent avec la distance', () => {
  it('l’opacité décroît strictement avec l’écart, et l’allumé est le seul plein', () => {
    const opacites = [0, 1, 2, 3, 4].map((d) => placerElement(8 + d, 8, droite).opacite);
    expect(opacites[0], 'l’allumé est pleinement opaque').toBe(1);
    for (let i = 1; i < opacites.length; i += 1) {
      expect(opacites[i], `l’écart ${i} doit être plus pâle que l’écart ${i - 1}`).toBeLessThan(opacites[i - 1]);
    }
  });

  it('la pastille allumée grandit, ses voisines non', () => {
    expect(placerElement(3, 3, droite).echelle).toBeCloseTo(1.3, 6);
    expect(placerElement(4, 3, droite).echelle).toBe(1);
    expect(placerElement(3, 3.5, droite).echelle, 'à mi-chemin, à mi-taille').toBeCloseTo(1.15, 6);
  });

  it('un élément sous le titre « Aller à » ou hors de la zone ne se touche pas', () => {
    // Loin au-dessus : le premier élément quand le dernier est allumé.
    const haut = placerElement(0, 16, droite);
    expect(haut.visible, 'un élément hors de la zone ne doit pas être touchable').toBe(false);
    expect(haut.opacite).toBe(0);
  });
});

describe('La rotation suit le pouce et résiste aux bouts', () => {
  it('le pouce qui monte d’un écart amène l’élément suivant au centre', () => {
    expect(rotationDuGlisse(3, -ECART_PX, 17)).toBeCloseTo(4, 6);
    expect(rotationDuGlisse(3, ECART_PX * 2, 17)).toBeCloseTo(1, 6);
  });

  it('au-delà des bouts, un ressort borné à RESSORT_MAX', () => {
    const tresHaut = rotationDuGlisse(0, 10_000, 17);
    expect(tresHaut, 'la roue ne passe pas sous le premier élément de plus de RESSORT_MAX').toBeGreaterThan(-RESSORT_MAX);
    expect(tresHaut).toBeLessThan(0);
    const tresBas = rotationDuGlisse(16, -10_000, 17);
    expect(tresBas).toBeLessThan(16 + RESSORT_MAX);
    expect(tresBas).toBeGreaterThan(16);
  });

  it('l’élément allumé reste dans la liste, même tiré au-delà des bouts', () => {
    expect(indexAllume(-0.3, 17)).toBe(0);
    expect(indexAllume(16.3, 17)).toBe(16);
    expect(indexAllume(4.49, 17)).toBe(4);
    expect(indexAllume(4.51, 17)).toBe(5);
  });

  it('la vitesse se lit sur les 100 dernières millisecondes', () => {
    // Le pouce monte de 64 px en 50 ms : +20 éléments par seconde.
    const v = vitesseDuGlisse([
      { t: 0, y: 900 },
      { t: 500, y: 500 },
      { t: 550, y: 500 - ECART_PX },
    ]);
    expect(v).toBeCloseTo(20, 6);
    expect(vitesseDuGlisse([{ t: 0, y: 0 }]), 'un seul échantillon : aucune vitesse').toBe(0);
  });
});

describe('L’aimantation : inertie courte, bascule directe sans mouvement', () => {
  it('un lancer projette la rotation, borné à INERTIE_MAX éléments', () => {
    expect(cibleAimantation(3.2, 0, 17, false), 'sans vitesse, le plus proche').toBe(3);
    expect(cibleAimantation(3.2, 20, 17, false), '20 éléments/s × 120 ms = 2,4').toBe(6);
    expect(cibleAimantation(3, 1000, 17, false), 'l’inertie est bornée').toBe(3 + INERTIE_MAX);
    expect(cibleAimantation(15, 1000, 17, false), 'jamais au-delà du dernier').toBe(16);
  });

  it('prefers-reduced-motion : aucune inertie', () => {
    expect(cibleAimantation(3.2, 20, 17, true)).toBe(3);
  });

  it('150 à 250 ms, et 0 sans mouvement', () => {
    expect(dureeAimantation(3, 3.1, false)).toBeGreaterThanOrEqual(DUREE_MIN_MS);
    expect(dureeAimantation(0, 16, false)).toBe(DUREE_MAX_MS);
    expect(dureeAimantation(0, 16, true), 'bascule directe').toBe(0);
  });

  it('la courbe part de la rotation courante et finit exactement sur la cible', () => {
    expect(rotationAuTemps(2, 5, 0, 200)).toBe(2);
    expect(rotationAuTemps(2, 5, 200, 200)).toBe(5);
    expect(rotationAuTemps(2, 5, 300, 200)).toBe(5);
    expect(rotationAuTemps(2, 5, 10, 0), 'durée nulle : la cible tout de suite').toBe(5);
    const mi = rotationAuTemps(2, 5, 100, 200);
    expect(mi, 'sortie cubique : plus de la moitié du trajet à mi-temps').toBeGreaterThan(3.5);
    expect(mi).toBeLessThan(5);
  });
});

describe('Le glissé depuis le bord, en un seul geste', () => {
  it('seule la bande du bord de la roue compte', () => {
    expect(commenceAuBord(375 - BORD_PX + 1, 375, 'droite')).toBe(true);
    expect(commenceAuBord(375 - BORD_PX - 1, 375, 'droite')).toBe(false);
    expect(commenceAuBord(BORD_PX - 1, 375, 'gauche')).toBe(true);
    expect(commenceAuBord(370, 375, 'gauche'), 'le bord droit n’ouvre pas la roue de gauche').toBe(false);
  });

  it('il faut glisser vers l’intérieur, plus à l’horizontale qu’à la verticale', () => {
    expect(glisseOuvreLaRoue(-20, 4, 'droite')).toBe(true);
    expect(glisseOuvreLaRoue(20, 4, 'droite'), 'vers l’extérieur : rien').toBe(false);
    expect(glisseOuvreLaRoue(-14, 30, 'droite'), 'un défilement le long du bord : rien').toBe(false);
    expect(glisseOuvreLaRoue(-6, 0, 'droite'), 'un tremblement : rien').toBe(false);
    expect(glisseOuvreLaRoue(20, 4, 'gauche')).toBe(true);
  });

  it('le relâché d’un geste continu ouvre la page, sauf si le pouce n’a pas tourné', () => {
    expect(issueDuRelache({ continu: true, deplacementPx: 40 })).toBe('ouvrir');
    expect(issueDuRelache({ continu: true, deplacementPx: 2 }), 'ouverte pour regarder').toBe('garder');
    expect(issueDuRelache({ continu: false, deplacementPx: 200 }), 'dans la roue ouverte, le toucher ouvre').toBe('garder');
  });
});

describe('Le bord écoute sans rien poser sur la page', () => {
  // 26/09/2026, contre-épreuve : une bande fixe de 16 × 200 px posée sur la
  // page empêchait de la faire défiler au pouce depuis le bord (scrollTop 0).
  it('un glissé vertical parti du bord reste un défilement', () => {
    expect(decisionDuBord(0, -10, 'droite'), 'le pouce monte : la page défile').toBe('laisser');
    expect(decisionDuBord(-3, -40, 'droite'), 'un peu vers l’intérieur, surtout vers le haut').toBe('laisser');
    expect(decisionDuBord(0, 30, 'gauche')).toBe('laisser');
  });

  it('vers l’intérieur, la roue s’ouvre ; un tremblement attend', () => {
    expect(decisionDuBord(-20, 4, 'droite')).toBe('ouvrir');
    expect(decisionDuBord(20, 4, 'gauche')).toBe('ouvrir');
    expect(decisionDuBord(-4, 2, 'droite'), 'rien de décidé sous 8 px').toBe('attendre');
    expect(decisionDuBord(12, 0, 'droite'), 'vers l’extérieur : jamais').toBe('laisser');
  });

  it('seuls les 200 px du bas ouvrent : plus haut, c’est le retour d’Android', () => {
    expect(BANDE_BORD_PX).toBe(200);
    expect(commenceDansLaBande(370, 700, 375, 812, 'droite')).toBe(true);
    expect(commenceDansLaBande(370, 400, 375, 812, 'droite'), 'à 400 px du haut').toBe(false);
    expect(commenceDansLaBande(340, 700, 375, 812, 'droite'), 'hors du bord').toBe(false);
    expect(commenceDansLaBande(5, 700, 375, 812, 'gauche')).toBe(true);
  });
});

describe('La coquille apprend le bord de la roue', () => {
  it('le verbe bordRoue ne porte que le côté', () => {
    // Échec évité (26/09/2026) : en navigation par gestes, Android prenait
    // le glissé depuis le bord pour un « retour » ; la coquille doit savoir
    // QUEL bord retirer à ses gestes, et rien d'autre ne doit voyager.
    expect(chargeBordRoue('droite')).toEqual({ cote: 'droite' });
    expect(Object.keys(chargeBordRoue('gauche')), 'aucun autre champ').toEqual(['cote']);
  });
});
