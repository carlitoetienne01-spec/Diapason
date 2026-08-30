import { describe, expect, it } from 'vitest';

import { sanitizeNoteHtml } from './noteSanitize';
import {
  countNotePages,
  overflowGapHeight,
  overflowGapPlan,
  PAGE_BREAK_HTML,
  PAGE_GUTTER_PX,
} from './notePages';

const GUTTER = PAGE_GUTTER_PX;
const MARGIN = 32;
const CONTENT = 200;

/**
 * Les vraies mesures d'une page A4 à marges normales, pour que les seuils
 * testés soient ceux que Carlito rencontre : 297 mm − 2 × 1 po = 930,52 px de
 * contenu, et une ligne de 24,75 px (15 px × 1,65).
 */
const A4 = 930.52;
const LIGNE = 24.75;

/** Un paragraphe de `n` lignes, avec le haut de chacune. */
function para(top: number, n: number, kind: 'block' | 'heading' = 'block') {
  return {
    top,
    height: n * LIGNE,
    kind,
    lines: Array.from({ length: n }, (_, i) => top + i * LIGNE),
  };
}

describe('overflowGapPlan', () => {
  it('ne coupe pas une feuille trop courte', () => {
    expect(
      overflowGapPlan([{ top: 0, height: 120, kind: 'block' }], CONTENT, GUTTER, MARGIN),
    ).toEqual([]);
  });

  it('refuse une hauteur de page aberrante plutôt que de gouttiérer chaque ligne', () => {
    const blocks = Array.from({ length: 40 }, (_, index) => ({
      top: index * 20,
      height: 18,
      kind: 'block' as const,
    }));
    expect(overflowGapPlan(blocks, 1, GUTTER, MARGIN)).toEqual([]);
  });

  it('trente-sept lignes courtes tiennent sur UNE feuille', () => {
    // Le seuil exact du défaut du 30 août 2026 : 37 × 24,75 = 915,75 px pour
    // 930,52 px utiles — cela TIENT. L'ancien code posait pourtant une feuille
    // blanche entière avant le premier mot, parce que tout bloc de moins de
    // 52 px était pris pour un titre à ne pas laisser seul en bas de page.
    const blocs = Array.from({ length: 37 }, (_, i) => para(i * LIGNE, 1));
    expect(overflowGapPlan(blocs, A4, GUTTER, MARGIN)).toEqual([]);
  });

  it('quatre cents lignes courtes ne mettent aucune feuille blanche devant le premier mot', () => {
    // Mesuré sur l'ancien code : 25 cales, dont 14 devant le bloc 0 — le
    // premier mot de la note commençait à la feuille 68,8.
    const blocs = Array.from({ length: 400 }, (_, i) => para(i * LIGNE, 1));
    const plan = overflowGapPlan(blocs, A4, GUTTER, MARGIN);
    expect(plan.filter((gap) => gap.beforeIndex === 0)).toHaveLength(0);
    // Et le nombre de coupes doit ressembler au nombre de pages : 9 900 px de
    // texte sur 930,52 px utiles font 11 feuilles, donc 10 coupes.
    expect(plan.length).toBeLessThanOrEqual(12);
  });

  it('un paragraphe de trois lignes ne se coupe jamais', () => {
    // 1+2 et 2+1 laissent une ligne seule : Word refuse les deux.
    const plan = overflowGapPlan(
      [para(0, 36), para(36 * LIGNE, 3)],
      A4,
      GUTTER,
      MARGIN,
    );
    expect(plan).toHaveLength(1);
    expect(plan[0].beforeIndex).toBe(1);
    expect(plan[0].atLine).toBeUndefined();
  });

  it('un paragraphe de quatre lignes se coupe en 2+2, jamais en 1+3', () => {
    // 35 lignes remplies, il reste de la place pour 2 lignes : la coupe
    // naturelle serait à k=2, et elle est admissible.
    const plan = overflowGapPlan(
      [para(0, 35), para(35 * LIGNE, 4)],
      A4,
      GUTTER,
      MARGIN,
    );
    const coupe = plan.find((gap) => gap.beforeIndex === 1);
    expect(coupe?.atLine).toBe(2);
  });

  it('un bloc de soixante lignes se coupe au lieu de traverser le bureau', () => {
    // Remplace le test qui exigeait l'inverse. 60 × 24,75 = 1 485 px, soit une
    // page et demie : l'ancien code ne posait AUCUNE cale et laissait le
    // paragraphe peint en travers de la gouttière.
    const plan = overflowGapPlan([para(0, 60)], A4, GUTTER, MARGIN);
    expect(plan.length).toBeGreaterThanOrEqual(1);
    expect(plan[0].atLine).toBeGreaterThanOrEqual(2);
  });

  it('un titre part avec le paragraphe qui ne tient pas', () => {
    // « Paragraphe solidaire » exige que le titre soit sur la page de la
    // PREMIÈRE LIGNE du paragraphe suivant — pas du paragraphe entier. Il faut
    // donc que ce paragraphe n'obtienne AUCUNE ligne admissible ici : avec le
    // titre à 891 px, sa deuxième ligne tomberait à 940,5 px pour 930,52 px
    // utiles, donc une seule ligne — refusée par la règle des orphelines.
    // (Un premier jet de ce test plaçait le titre à 866 px : deux lignes
    // tenaient encore, la contrainte était satisfaite, et couper était le bon
    // comportement. Le test avait tort, pas le code.)
    const plan = overflowGapPlan(
      [para(0, 36), para(36 * LIGNE, 1, 'heading'), para(37 * LIGNE, 6)],
      A4,
      GUTTER,
      MARGIN,
    );
    expect(plan[0].beforeIndex).toBe(1);
    expect(plan[0].atLine).toBeUndefined();
  });

  it("un titre n'emmène rien si la grappe ne tient pas dans une page", () => {
    // Le garde-fou absent de l'ancien code : un H2 suivi d'un paragraphe de
    // cinquante lignes. Emmener le titre ne sauverait rien — le paragraphe
    // déborde de toute façon — et l'ancienne remontée sans borne posait des
    // cales en cascade.
    const plan = overflowGapPlan(
      [para(0, 35), para(35 * LIGNE, 1, 'heading'), para(36 * LIGNE, 50)],
      A4,
      GUTTER,
      MARGIN,
    );
    expect(plan.some((gap) => gap.beforeIndex === 2 && gap.atLine !== undefined)).toBe(
      true,
    );
  });

  it('aucune cale ne dépasse la hauteur d’une feuille entière', () => {
    // L'emballement mesuré valait 462 968 px pour une seule série. Une cale
    // légitime vaut au plus une page vide plus les marges et la gouttière.
    const blocs = Array.from({ length: 300 }, (_, i) => para(i * LIGNE, 1));
    const plafond = A4 + MARGIN + GUTTER + MARGIN;
    for (const gap of overflowGapPlan(blocs, A4, GUTTER, MARGIN)) {
      expect(overflowGapHeight(gap, GUTTER, MARGIN)).toBeLessThanOrEqual(plafond + 1);
    }
  });

  it('un titre insécable part entier plutôt que d’être coupé', () => {
    const plan = overflowGapPlan(
      [para(0, 36), para(36 * LIGNE, 4, 'heading')],
      A4,
      GUTTER,
      MARGIN,
    );
    expect(plan[0].atLine).toBeUndefined();
  });

  it('reprend le compte après un saut manuel', () => {
    const plan = overflowGapPlan(
      [
        { top: 0, height: 80, kind: 'block' },
        { top: 80, height: 36, kind: 'break' },
        { top: 116, height: 80, kind: 'block' },
      ],
      CONTENT,
      GUTTER,
      MARGIN,
    );
    expect(plan).toEqual([{ beforeIndex: 1, fill: 120, mode: 'fill' }]);
  });

  it('enchaîne plusieurs feuilles dans un long document', () => {
    const plan = overflowGapPlan(
      [
        { top: 0, height: 180, kind: 'block' },
        { top: 180, height: 80, kind: 'block' },
        { top: 260, height: 80, kind: 'block' },
        { top: 340, height: 80, kind: 'block' },
      ],
      CONTENT,
      GUTTER,
      MARGIN,
    );
    expect(plan.length).toBeGreaterThanOrEqual(2);
    expect(plan.every((gap) => gap.mode === 'sheet')).toBe(true);
    expect(plan[0].beforeIndex).toBe(1);
  });
});

describe('countNotePages', () => {
  it('compte un saut de page comme une nouvelle feuille', () => {
    expect(countNotePages(`abc${PAGE_BREAK_HTML}def`)).toBe(2);
  });
});

describe('sanitizeNoteHtml', () => {
  it('le banc exécute vraiment le nettoyeur, et non son filet de secours', () => {
    // 30 août 2026. `vite.config.ts` ne déclarait aucun environnement de test :
    // vitest tournait donc en `node`, où `DOMParser` n'existe pas.
    // `sanitizeNoteHtml` partait dans son `catch` et rendait du TEXTE NU —
    // « <p><b>gras</b></p> » ressortait « gras ». Les deux tests ci-dessous
    // passaient sans jamais exécuter la liste blanche : « ne contient pas
    // succes-overflow-gap » est trivialement vrai quand TOUTES les balises
    // ont disparu, et « contient Rust » l'est tout autant.
    //
    // Cette assertion est la seule qui distingue les deux mondes : elle exige
    // que des balises SURVIVENT. Elle rougit sans jsdom (§100).
    expect(sanitizeNoteHtml('<p><b>gras</b></p>')).toBe('<p><b>gras</b></p>');
  });

  it("n'enregistre pas les gouttières de pagination", () => {
    const html =
      '<p>a</p><div class="succes-overflow-gap"><div class="succes-overflow-gutter"></div></div><h2>b</h2>';
    const cleaned = sanitizeNoteHtml(html);
    expect(cleaned).not.toContain('succes-overflow-gap');
    // Et le voisinage doit être INTACT : sans ces deux-là, un nettoyeur qui
    // jette tout passerait le test qui garde la note.
    expect(cleaned).toContain('<p>a</p>');
    expect(cleaned).toContain('<h2>b</h2>');
  });

  it('conserve la structure d’un tableau collé, pas seulement son texte', () => {
    const html =
      '<table><tbody><tr><th>Langage</th></tr><tr><td>Rust</td></tr></tbody></table>';
    const cleaned = sanitizeNoteHtml(html);
    expect(cleaned).toContain('<table>');
    expect(cleaned).toContain('<td>Rust</td>');
    expect(cleaned).toContain('<th>Langage</th>');
  });

  it('jette ce qui doit être jeté, sans emporter le reste', () => {
    expect(sanitizeNoteHtml('<p>ok</p><script>alert(1)</script>')).toBe('<p>ok</p>');
  });
});
