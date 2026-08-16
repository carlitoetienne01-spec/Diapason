import { useCallback, useEffect, useLayoutEffect, useRef, type ComponentType } from 'react';
import { useLocation, useNavigate } from 'react-router';

export type GlassNavItem = {
  path: string;
  icon: ComponentType<{ size?: number | string; style?: React.CSSProperties }>;
  label: string;
};

type Row = { top: number; height: number };

/** Resting opacity of a label sitting far from the lens. */
const DIM = 0.55;
/** How far the magnification field reaches, in row heights. */
const REACH = 1.55;

const smoothstep = (t: number) => t * t * (3 - 2 * t);
const clamp = (v: number, min: number, max: number) => Math.min(max, Math.max(min, v));

/**
 * The shared glass recipe, so the Succès button and the nav lens are cut from
 * the same material. `lit` is the pressed/active variant.
 */
export function glassSurface(lit: boolean): React.CSSProperties {
  return {
    backdropFilter: 'blur(14px) saturate(180%) brightness(1.08)',
    WebkitBackdropFilter: 'blur(14px) saturate(180%) brightness(1.08)',
    background: lit
      ? 'linear-gradient(157deg, rgba(255,255,255,0.13) 0%, rgba(255,255,255,0.035) 46%, rgba(255,255,255,0.085) 100%)'
      : 'linear-gradient(157deg, rgba(255,255,255,0.07) 0%, rgba(255,255,255,0.02) 46%, rgba(255,255,255,0.045) 100%)',
    border: '1px solid rgba(255,255,255,0.11)',
    boxShadow: [
      // A single crisp bevel reads as thickness without shouting
      'inset 0 1px 0 rgba(255,255,255,0.28)',
      'inset 0 -1px 0 rgba(255,255,255,0.05)',
      // Chromatic fringing: glass splits light cool on one edge, warm on the other
      'inset 1px 0 0 rgba(150,205,255,0.10)',
      'inset -1px 0 0 rgba(255,196,160,0.08)',
      lit ? '0 10px 24px -16px rgba(0,0,0,0.7)' : '0 8px 20px -18px rgba(0,0,0,0.6)',
    ].join(', '),
  };
}

/**
 * Sidebar navigation built around one lens of liquid glass.
 *
 * The lens is driven by a spring rather than a CSS transition, which lets it
 * overshoot and settle like a real drop of liquid, and lets every label react
 * to its live position: rows swell and brighten as the glass passes over them,
 * the way type does under a moving magnifier.
 */
export function GlassNav({ items, groupLabel }: { items: GlassNavItem[]; groupLabel?: string }) {
  const navigate = useNavigate();
  const location = useLocation();

  const listRef = useRef<HTMLElement | null>(null);
  const lensRef = useRef<HTMLDivElement | null>(null);
  const buttonRefs = useRef(new Map<string, HTMLButtonElement>());
  const contentRefs = useRef(new Map<string, HTMLSpanElement>());
  const tintRefs = useRef(new Map<string, HTMLSpanElement>());
  const rows = useRef(new Map<string, Row>());

  // Everything the animation needs lives in refs: the lens never re-renders,
  // so it cannot fight React or drift out of sync with a render loop.
  const lens = useRef({ y: 0, velocity: 0, target: 0, height: 0, visible: false, settled: true });
  const frame = useRef<number | null>(null);

  const activePath = items.find((item) => item.path === location.pathname)?.path ?? null;

  const paint = useCallback(() => {
    const node = lensRef.current;
    const state = lens.current;
    if (node) {
      node.style.opacity = state.visible ? '1' : '0';
      if (state.visible) {
        // Momentum stretches the lens along its travel and pinches it across,
        // conserving volume the way a liquid would.
        const stretch = clamp(Math.abs(state.velocity) / 34, 0, 0.13);
        node.style.height = `${state.height}px`;
        node.style.transform = `translate3d(0, ${state.y.toFixed(2)}px, 0) scaleY(${(1 + stretch).toFixed(3)}) scaleX(${(1 - stretch * 0.5).toFixed(3)})`;
      }
    }

    const center = state.y + state.height / 2;
    rows.current.forEach((row, path) => {
      const content = contentRefs.current.get(path);
      if (!content) return;
      const distance = Math.abs(row.top + row.height / 2 - center);
      const falloff = state.visible ? clamp(1 - distance / (row.height * REACH), 0, 1) : 0;
      const field = smoothstep(falloff);
      // Magnify, and push sideways a touch — a lens displaces what it shows.
      content.style.transform = `translateX(${(field * 2.4).toFixed(2)}px) scale(${(1 + field * 0.05).toFixed(3)})`;
      content.style.opacity = (DIM + field * (1 - DIM)).toFixed(3);
      const tint = tintRefs.current.get(path);
      if (tint) tint.style.opacity = field.toFixed(3);
    });
  }, []);

  const run = useCallback(() => {
    if (frame.current !== null) return;
    const step = () => {
      const state = lens.current;
      const distance = state.target - state.y;
      state.velocity = (state.velocity + distance * 0.155) * 0.74;
      state.y += state.velocity;
      if (Math.abs(distance) < 0.15 && Math.abs(state.velocity) < 0.15) {
        state.y = state.target;
        state.velocity = 0;
        state.settled = true;
      }
      paint();
      frame.current = state.settled ? null : requestAnimationFrame(step);
    };
    frame.current = requestAnimationFrame(step);
  }, [paint]);

  const measure = useCallback(
    (animate: boolean) => {
      const list = listRef.current;
      if (!list) return;
      const listBox = list.getBoundingClientRect();
      rows.current.clear();
      buttonRefs.current.forEach((button, path) => {
        const box = button.getBoundingClientRect();
        rows.current.set(path, { top: box.top - listBox.top, height: box.height });
      });

      const state = lens.current;
      const target = activePath ? rows.current.get(activePath) : undefined;
      if (!target) {
        state.visible = false;
        paint();
        return;
      }

      const reduced =
        typeof window !== 'undefined' &&
        window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      const first = !state.visible;
      state.visible = true;
      state.height = target.height;
      state.target = target.top;

      if (first || reduced || !animate) {
        state.y = target.top;
        state.velocity = 0;
        state.settled = true;
        paint();
        return;
      }
      state.settled = false;
      run();
    },
    [activePath, paint, run],
  );

  useLayoutEffect(() => {
    measure(true);
  }, [measure, items.length]);

  useEffect(() => {
    const list = listRef.current;
    if (!list || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(() => measure(false));
    observer.observe(list);
    return () => observer.disconnect();
  }, [measure]);

  useEffect(
    () => () => {
      if (frame.current !== null) cancelAnimationFrame(frame.current);
    },
    [],
  );

  // The specular highlight tracks the pointer, so the glass looks wet under the
  // cursor instead of carrying a highlight painted at a fixed angle.
  const trackSheen = (event: React.MouseEvent<HTMLElement>) => {
    const list = listRef.current;
    const node = lensRef.current;
    if (!list || !node) return;
    node.style.setProperty('--sheen-x', `${event.clientX - list.getBoundingClientRect().left}px`);
  };
  const resetSheen = () => lensRef.current?.style.setProperty('--sheen-x', '50%');

  return (
    <nav
      ref={listRef}
      aria-label={groupLabel}
      className="relative isolate px-2 pb-2 flex flex-col gap-0.5"
      onMouseMove={trackSheen}
      onMouseLeave={resetSheen}
    >
      <div
        ref={lensRef}
        aria-hidden="true"
        className="pointer-events-none absolute left-2 right-2 top-0 rounded-xl"
        style={{
          ...glassSurface(true),
          // Under the labels, always: a backdrop filter painted on top would
          // smear the very text it is meant to magnify.
          zIndex: 0,
          opacity: 0,
          transition: 'opacity 240ms ease',
          willChange: 'transform',
          ['--sheen-x' as string]: '50%',
        }}
      >
        <span
          className="absolute inset-0 rounded-xl"
          style={{
            background:
              'radial-gradient(90px 34px at var(--sheen-x) 45%, rgba(255,255,255,0.16), transparent 72%)',
          }}
        />
        <span
          className="absolute inset-x-3 -bottom-px h-px rounded-full"
          style={{
            background:
              'linear-gradient(90deg, transparent, color-mix(in srgb, var(--color-accent) 55%, transparent), transparent)',
          }}
        />
      </div>

      {items.map((item) => {
        const isActive = item.path === activePath;
        return (
          <button
            key={item.path}
            ref={(node) => {
              if (node) buttonRefs.current.set(item.path, node);
              else buttonRefs.current.delete(item.path);
            }}
            onClick={() => navigate(item.path)}
            aria-current={isActive ? 'page' : undefined}
            className="relative z-[1] flex items-center px-3 py-2 rounded-xl text-sm w-full text-left cursor-pointer transition-colors hover:bg-white/[0.035]"
            style={{ color: 'var(--color-text)' }}
          >
            <span
              ref={(node) => {
                if (node) contentRefs.current.set(item.path, node);
                else contentRefs.current.delete(item.path);
              }}
              className="flex items-center gap-3"
              style={{ transformOrigin: 'left center', opacity: DIM }}
            >
              <span className="relative inline-flex items-center justify-center w-4 h-4">
                <item.icon size={16} />
                <span
                  ref={(node) => {
                    if (node) tintRefs.current.set(item.path, node);
                    else tintRefs.current.delete(item.path);
                  }}
                  className="absolute inset-0 inline-flex items-center justify-center"
                  style={{ color: 'var(--color-accent)', opacity: 0 }}
                >
                  <item.icon size={16} />
                </span>
              </span>
              {item.label}
            </span>
          </button>
        );
      })}
    </nav>
  );
}
