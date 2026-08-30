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

  it('pousse un bloc entier à la page suivante au lieu de le trancher', () => {
    const plan = overflowGapPlan(
      [
        { top: 0, height: 180, kind: 'block' },
        { top: 180, height: 50, kind: 'heading' },
      ],
      CONTENT,
      GUTTER,
      MARGIN,
    );
    expect(plan).toEqual([{ beforeIndex: 1, fill: 20, mode: 'sheet' }]);
    expect(overflowGapHeight(plan[0], GUTTER, MARGIN)).toBe(20 + MARGIN + GUTTER + MARGIN);
  });

  it('emmène les lignes courtes (N2 + titre) avec le paragraphe qui suit', () => {
    const plan = overflowGapPlan(
      [
        { top: 0, height: 160, kind: 'block' },
        { top: 160, height: 22, kind: 'block' },
        { top: 182, height: 24, kind: 'block' },
        { top: 206, height: 40, kind: 'block' },
      ],
      CONTENT,
      GUTTER,
      MARGIN,
    );
    expect(plan).toEqual([{ beforeIndex: 1, fill: 40, mode: 'sheet' }]);
  });

  it('emmène le titre avec le paragraphe qui ne tient pas en bas de page', () => {
    const plan = overflowGapPlan(
      [
        { top: 0, height: 170, kind: 'block' },
        { top: 170, height: 25, kind: 'heading' },
        { top: 195, height: 40, kind: 'block' },
      ],
      CONTENT,
      GUTTER,
      MARGIN,
    );
    expect(plan).toEqual([{ beforeIndex: 1, fill: 30, mode: 'sheet' }]);
  });

  it('laisse un bloc plus haut que la page entier (pas de tranchage)', () => {
    expect(
      overflowGapPlan([{ top: 0, height: 500, kind: 'block' }], CONTENT, GUTTER, MARGIN),
    ).toEqual([]);
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
  it("n'enregistre pas les gouttières de pagination", () => {
    const html =
      '<p>a</p><div class="succes-overflow-gap"><div class="succes-overflow-gutter"></div></div><h2>b</h2>';
    const cleaned = sanitizeNoteHtml(html);
    expect(cleaned).not.toContain('succes-overflow-gap');
    expect(cleaned).toContain('a');
    expect(cleaned).toContain('b');
  });

  it('conserve le texte d’un tableau collé', () => {
    const html =
      '<table><tbody><tr><th>Langage</th></tr><tr><td>Rust</td></tr></tbody></table>';
    const cleaned = sanitizeNoteHtml(html);
    expect(cleaned).toContain('Rust');
    expect(cleaned).toContain('Langage');
  });
});
