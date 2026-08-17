import { useEffect, useRef } from 'react';
import { useAppStore } from '../../lib/store';

/** Digits are over-represented so the field reads as machine output rather
 * than as scrambled words. */
const GLYPHS = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'.split('');

const FONT_SIZE = 17;
/** Share of columns that climb instead of falling. */
const UPWARD_SHARE = 0.3;

type Rgb = [number, number, number];

interface Column {
  /** Leading cell, in rows. Fractional between steps. */
  head: number;
  /** Rows per second. */
  speed: number;
  direction: 1 | -1;
  /** Trail length, in cells. */
  length: number;
  /** Overall opacity of the strand — the depth cue. */
  bright: number;
  /** Seconds left before the strand re-enters. */
  idle: number;
  /** Glyph index per row, so a strand keeps its characters as it travels. */
  glyphs: Uint8Array;
  /** Row the head occupied last frame, to know when it steps. */
  lastRow: number;
}

/** Resolves any CSS colour (hex, rgb(), color-mix()) to channels by letting
 * the canvas normalise it. */
function resolveRgb(value: string, fallback: Rgb): Rgb {
  const context = document.createElement('canvas').getContext('2d');
  if (!context) return fallback;
  context.fillStyle = '#000000';
  context.fillStyle = value;
  const resolved = context.fillStyle as string;

  if (resolved.startsWith('#')) {
    const hex = resolved.slice(1);
    const full = hex.length === 3 ? hex.split('').map((c) => c + c).join('') : hex.slice(0, 6);
    const int = Number.parseInt(full, 16);
    if (Number.isNaN(int)) return fallback;
    return [(int >> 16) & 255, (int >> 8) & 255, int & 255];
  }

  const match = resolved.match(/rgba?\(([^)]+)\)/);
  if (!match) return fallback;
  const parts = match[1].split(',').map((n) => Number.parseFloat(n));
  if (parts.length < 3 || parts.some(Number.isNaN)) return fallback;
  return [parts[0], parts[1], parts[2]];
}

function readAccent(): Rgb {
  return resolveRgb(
    getComputedStyle(document.documentElement).getPropertyValue('--color-accent').trim(),
    [34, 211, 128],
  );
}

function mix(color: Rgb, toward: Rgb, amount: number): Rgb {
  return [
    Math.round(color[0] + (toward[0] - color[0]) * amount),
    Math.round(color[1] + (toward[1] - color[1]) * amount),
    Math.round(color[2] + (toward[2] - color[2]) * amount),
  ];
}

/** Pre-renders the alphabet once per colour. Blitting from an atlas costs a
 * fraction of what `fillText` does, which is what lets every cell of every
 * trail be drawn individually — and that is what keeps the glyphs crisp. */
function buildAtlas(
  cellWidth: number,
  cellHeight: number,
  ratio: number,
  color: Rgb,
  glow: number,
): HTMLCanvasElement {
  const atlas = document.createElement('canvas');
  atlas.width = Math.ceil(cellWidth * GLYPHS.length * ratio);
  atlas.height = Math.ceil(cellHeight * ratio);

  const context = atlas.getContext('2d');
  if (!context) return atlas;

  context.scale(ratio, ratio);
  context.font = `${FONT_SIZE}px 'VT323', ui-monospace, monospace`;
  context.textAlign = 'center';
  context.textBaseline = 'middle';
  context.fillStyle = `rgb(${color[0]}, ${color[1]}, ${color[2]})`;
  if (glow > 0) {
    context.shadowColor = `rgb(${color[0]}, ${color[1]}, ${color[2]})`;
    context.shadowBlur = glow;
  }

  GLYPHS.forEach((glyph, index) => {
    context.fillText(glyph, index * cellWidth + cellWidth / 2, cellHeight / 2);
  });

  return atlas;
}

function resetColumn(column: Column, rows: number, initial: boolean): void {
  const up = Math.random() < UPWARD_SHARE;
  column.direction = up ? -1 : 1;
  column.speed = 7 + Math.random() * 15;
  column.length = 10 + Math.floor(Math.random() * 24);
  column.bright = 0.3 + Math.random() * 0.7;
  column.idle = initial ? 0 : Math.random() * 1.8;
  // Entering strands start off-screen by their own length, so a trail is never
  // revealed already half-drawn at the edge.
  column.head = up ? rows + column.length * Math.random() : -column.length * Math.random();
  if (initial) column.head = Math.random() * rows;
  column.lastRow = Math.floor(column.head);
}

/**
 * Falling-code backdrop for the terminal theme's chat surface.
 *
 * Movement is quantised to the glyph grid: a strand holds a cell until it has
 * earned a full step. Advancing by sub-pixel amounts instead would smear
 * successive glyphs over one another and the field would read as streaks.
 *
 * The canvas stays genuinely transparent — it is cleared, never painted with a
 * backdrop — so the effect sits on any skin, the near-black Phosphor screen as
 * well as the beige Ardéchine one.
 */
export function MatrixRain() {
  const theme = useAppStore((s) => s.settings.theme);
  const skin = useAppStore((s) => s.settings.terminalSkin);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const active = theme === 'terminal';

  useEffect(() => {
    if (!active) return;
    const canvas = canvasRef.current;
    const host = canvas?.parentElement;
    if (!canvas || !host) return;

    const context = canvas.getContext('2d');
    if (!context) return;

    const motionQuery = window.matchMedia?.('(prefers-reduced-motion: reduce)');

    let columns: Column[] = [];
    let width = 0;
    let height = 0;
    let rows = 0;
    let cellWidth = 10;
    let cellHeight = FONT_SIZE;
    let ratio = 1;
    let trailAtlas: HTMLCanvasElement | null = null;
    let headAtlas: HTMLCanvasElement | null = null;
    let frame = 0;
    let last = 0;

    const measure = () => {
      context.font = `${FONT_SIZE}px 'VT323', ui-monospace, monospace`;
      // VT323 is narrow; measuring beats guessing an advance, and also keeps
      // the grid right if the font has not loaded and a fallback is in use.
      const advance = context.measureText('0').width || FONT_SIZE * 0.5;
      cellWidth = Math.max(6, advance + 2);
      cellHeight = Math.round(FONT_SIZE * 0.92);
    };

    const buildAtlases = () => {
      const accent = readAccent();
      trailAtlas = buildAtlas(cellWidth, cellHeight, ratio, accent, 0);
      headAtlas = buildAtlas(cellWidth, cellHeight, ratio, mix(accent, [255, 255, 255], 0.78), 7);
    };

    const build = () => {
      ratio = Math.min(window.devicePixelRatio || 1, 2);
      width = host.clientWidth;
      height = host.clientHeight;
      if (width === 0 || height === 0) return;

      canvas.width = Math.max(1, Math.round(width * ratio));
      canvas.height = Math.max(1, Math.round(height * ratio));
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      context.setTransform(ratio, 0, 0, ratio, 0, 0);

      measure();
      buildAtlases();

      rows = Math.ceil(height / cellHeight) + 1;
      const count = Math.max(1, Math.floor(width / cellWidth));
      columns = Array.from({ length: count }, () => {
        const column: Column = {
          head: 0,
          speed: 0,
          direction: 1,
          length: 0,
          bright: 1,
          idle: 0,
          glyphs: new Uint8Array(rows + 1),
          lastRow: 0,
        };
        for (let i = 0; i < column.glyphs.length; i += 1) {
          column.glyphs[i] = (Math.random() * GLYPHS.length) | 0;
        }
        resetColumn(column, rows, true);
        return column;
      });
    };

    const draw = (now: number) => {
      frame = requestAnimationFrame(draw);
      const dt = Math.min((now - last) / 1000, 0.05);
      last = now;

      context.clearRect(0, 0, width, height);
      if (!trailAtlas || !headAtlas) return;

      const sourceWidth = cellWidth * ratio;
      const sourceHeight = cellHeight * ratio;

      for (let c = 0; c < columns.length; c += 1) {
        const column = columns[c];

        if (column.idle > 0) {
          column.idle -= dt;
          continue;
        }

        column.head += column.speed * column.direction * dt;
        const headRow = Math.floor(column.head);

        // A fresh glyph is minted only when the head actually steps to a new
        // cell, so characters read as discrete rather than as a blur.
        if (headRow !== column.lastRow) {
          const slot = ((headRow % column.glyphs.length) + column.glyphs.length) % column.glyphs.length;
          column.glyphs[slot] = (Math.random() * GLYPHS.length) | 0;
          column.lastRow = headRow;
        }

        // A little flicker inside the trail keeps the field alive.
        if (Math.random() < 0.28) {
          const slot = (Math.random() * column.glyphs.length) | 0;
          column.glyphs[slot] = (Math.random() * GLYPHS.length) | 0;
        }

        const x = c * cellWidth;
        for (let i = 0; i < column.length; i += 1) {
          const row = headRow - i * column.direction;
          if (row < 0 || row >= rows) continue;

          const falloff = 1 - i / column.length;
          const alpha = falloff * falloff * column.bright;
          if (alpha <= 0.02) continue;

          const slot = ((row % column.glyphs.length) + column.glyphs.length) % column.glyphs.length;
          const atlas = i === 0 ? headAtlas : trailAtlas;

          context.globalAlpha = i === 0 ? Math.min(1, column.bright + 0.35) : alpha;
          context.drawImage(
            atlas,
            column.glyphs[slot] * sourceWidth,
            0,
            sourceWidth,
            sourceHeight,
            x,
            row * cellHeight,
            cellWidth,
            cellHeight,
          );
        }

        const tail = column.head - column.length * column.direction;
        if (column.direction === 1 ? tail > rows : tail < 0) {
          resetColumn(column, rows, false);
        }
      }

      context.globalAlpha = 1;
    };

    const start = () => {
      if (frame || motionQuery?.matches) return;
      last = performance.now();
      frame = requestAnimationFrame(draw);
    };

    const stop = () => {
      if (!frame) return;
      cancelAnimationFrame(frame);
      frame = 0;
    };

    build();
    start();

    // The metrics come from a webfont, so the grid is rebuilt once it lands.
    void document.fonts?.ready.then(build);

    const resizeObserver = new ResizeObserver(build);
    resizeObserver.observe(host);

    // The accent is a theme token: it moves when the theme class or the
    // terminal skin attribute does, and the atlases have to follow.
    const themeObserver = new MutationObserver(buildAtlases);
    themeObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['class', 'data-terminal-skin'],
    });

    const onMotionChange = () => {
      if (motionQuery?.matches) {
        stop();
        context.clearRect(0, 0, width, height);
      } else {
        start();
      }
    };
    motionQuery?.addEventListener('change', onMotionChange);

    const onVisibility = () => (document.hidden ? stop() : start());
    document.addEventListener('visibilitychange', onVisibility);

    return () => {
      stop();
      resizeObserver.disconnect();
      themeObserver.disconnect();
      motionQuery?.removeEventListener('change', onMotionChange);
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [active, skin]);

  if (!active) return null;

  return (
    <canvas
      ref={canvasRef}
      aria-hidden
      className="absolute inset-0 pointer-events-none"
      style={{ opacity: 0.42 }}
    />
  );
}
