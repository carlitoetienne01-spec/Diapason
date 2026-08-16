import { useEffect, useId, useState, type PointerEvent } from 'react';

const FALLBACK_COLOR = '#6366f1';

function parseHex(hex: string): [number, number, number] {
  const clean = hex.replace('#', '').trim();
  const full =
    clean.length === 3
      ? clean
          .split('')
          .map((char) => char + char)
          .join('')
      : clean.padEnd(6, '0').slice(0, 6);
  return [
    parseInt(full.slice(0, 2), 16) || 0,
    parseInt(full.slice(2, 4), 16) || 0,
    parseInt(full.slice(4, 6), 16) || 0,
  ];
}

/** Blend towards white (amount > 0) or black (amount < 0), hex out. */
function shadeHex(hex: string, amount: number) {
  const target = amount > 0 ? 255 : 0;
  const ratio = Math.abs(amount);
  const channels = parseHex(hex).map((channel) =>
    Math.round(channel + (target - channel) * ratio),
  );
  return `#${channels.map((channel) => channel.toString(16).padStart(2, '0')).join('')}`;
}

function alpha(hex: string, opacity: number) {
  const [r, g, b] = parseHex(hex);
  return `rgba(${r}, ${g}, ${b}, ${opacity})`;
}

function resolveIsLight() {
  if (typeof document === 'undefined') return false;
  const root = document.documentElement;
  if (root.classList.contains('light')) return true;
  if (root.classList.contains('dark')) return false;
  return !window.matchMedia('(prefers-color-scheme: dark)').matches;
}

function useIsLightTheme() {
  const [isLight, setIsLight] = useState(resolveIsLight);

  useEffect(() => {
    const update = () => setIsLight(resolveIsLight());
    update();
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    media.addEventListener('change', update);
    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['class'],
    });
    return () => {
      media.removeEventListener('change', update);
      observer.disconnect();
    };
  }, []);

  return isLight;
}

/*
 * Geometry traced from the reference render on a 240x200 canvas. The back shell
 * is narrower than the front pocket, the sheets rise out of the shell's mouth,
 * and the pocket's tab sits on the left before stepping down to the right.
 */
const ART_VIEWBOX = '0 0 240 200';

const SHELL_PATH =
  'M 56 40 H 184 A 16 16 0 0 1 200 56 V 160 A 16 16 0 0 1 184 176 H 56 A 16 16 0 0 1 40 160 V 56 A 16 16 0 0 1 56 40 Z';

const POCKET_PATH =
  'M 44 74 H 112 A 8 8 0 0 1 117.7 76.4 L 134.3 93 A 8 8 0 0 0 140 95.4 H 196 A 10 10 0 0 1 206 105.4 V 162 A 14 14 0 0 1 192 176 H 48 A 14 14 0 0 1 34 162 V 84 A 10 10 0 0 1 44 74 Z';

const POCKET_MASK = `url("data:image/svg+xml,${encodeURIComponent(
  `<svg xmlns='http://www.w3.org/2000/svg' viewBox='${ART_VIEWBOX}'><path fill='white' d='${POCKET_PATH}'/></svg>`,
)}")`;

/**
 * Sheets, front-most first. The front sheet carries two columns of text as in
 * the reference; the ones behind only show their left margin through the fan.
 */
const SHEETS = [
  {
    x: 62,
    y: 30,
    rotate: -11,
    width: 68,
    height: 104,
    lines: [
      { x: 11, y: 16, width: 46, height: 5 },
      { x: 11, y: 30, width: 20, height: 3 },
      { x: 36, y: 30, width: 21, height: 3 },
      { x: 11, y: 38, width: 20, height: 3 },
      { x: 36, y: 38, width: 21, height: 3 },
      { x: 11, y: 46, width: 20, height: 3 },
      { x: 36, y: 46, width: 21, height: 3 },
      { x: 11, y: 54, width: 20, height: 3 },
      { x: 36, y: 54, width: 21, height: 3 },
      { x: 11, y: 62, width: 20, height: 3 },
      { x: 36, y: 62, width: 21, height: 3 },
    ],
  },
  {
    x: 104,
    y: 26,
    rotate: -2,
    width: 62,
    height: 100,
    lines: [
      { x: 10, y: 20, width: 24, height: 4 },
      { x: 10, y: 32, width: 16, height: 4 },
      { x: 10, y: 44, width: 20, height: 4 },
      { x: 10, y: 56, width: 14, height: 4 },
    ],
  },
  {
    x: 138,
    y: 36,
    rotate: 8,
    width: 58,
    height: 94,
    lines: [
      { x: 10, y: 22, width: 22, height: 4 },
      { x: 10, y: 34, width: 15, height: 4 },
      { x: 10, y: 46, width: 19, height: 4 },
    ],
  },
] as const;

/**
 * One lighting rig, two grounds. The shell stays near-black in both themes —
 * that is the reference look — but the rim and contact shadow swap so the
 * silhouette never dissolves into a white page nor floats on a dark one.
 */
function folderPalette(tone: string, isLight: boolean) {
  return {
    shellTop: shadeHex(tone, -0.6),
    shellMid: shadeHex(tone, -0.76),
    shellBottom: shadeHex(tone, -0.88),
    shellTopEdge: alpha(shadeHex(tone, 0.25), 0.42),
    shellRim: isLight ? alpha(shadeHex(tone, -0.3), 0.5) : 'rgba(255,255,255,0.16)',
    dropOpacity: isLight ? 0.3 : 0.55,
    contactOpacity: isLight ? 0.26 : 0.42,
    // Smoky glass: mostly white over the dark shell, carrying a hint of the hue.
    pocketFill: `linear-gradient(162deg,
      rgba(255,255,255,0.40) 0%,
      rgba(255,255,255,0.24) 26%,
      ${alpha(tone, 0.14)} 58%,
      rgba(255,255,255,0.10) 78%,
      rgba(10,12,20,0.16) 100%)`,
    pocketBlur: 'blur(6px) saturate(135%)',
    pocketRim: [
      'rgba(255,255,255,0.72)',
      'rgba(255,255,255,0.30)',
      alpha(tone, 0.34),
      'rgba(255,255,255,0.16)',
    ],
    pocketBevel: 'rgba(255,255,255,0.26)',
    pocketBase: 'rgba(0,0,0,0.34)',
    specularPeak: 'rgba(255,255,255,0.26)',
    specularSoft: 'rgba(255,255,255,0.06)',
    hotspotIdle: 0.05,
    hotspotActive: 0.18,
  };
}

type Props = {
  color: string;
  /** Pages in the note: 1, 2 or 3+ sheets. */
  sheets: number;
  height?: string;
};

/**
 * Folder icon for a note: an opaque tinted shell, paper sheets fanned out of
 * its mouth, then a real backdrop-filtered pocket masked to the front panel,
 * finished with rim light, specular sweep and a pointer-driven hotspot.
 */
export function NoteFolderVisual({ color, sheets, height = 'h-40' }: Props) {
  const isLight = useIsLightTheme();
  const tone = color || FALLBACK_COLOR;
  const palette = folderPalette(tone, isLight);
  const rawId = useId();
  const uid = rawId.replace(/[^a-zA-Z0-9]/g, '');
  const ref = (name: string) => `${uid}-${name}`;
  const visible = SHEETS.slice(0, Math.min(3, Math.max(1, sheets)));
  const [tilt, setTilt] = useState({ x: 0, y: 0, glareX: 42, glareY: 32 });
  const [active, setActive] = useState(false);

  const followPointer = (event: PointerEvent<HTMLDivElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    const glareX = ((event.clientX - bounds.left) / bounds.width) * 100;
    const glareY = ((event.clientY - bounds.top) / bounds.height) * 100;
    setTilt({
      x: (glareX / 100 - 0.5) * 7,
      y: -(glareY / 100 - 0.5) * 5,
      glareX,
      glareY,
    });
  };

  const reset = () => {
    setActive(false);
    setTilt({ x: 0, y: 0, glareX: 42, glareY: 32 });
  };

  return (
    <div
      aria-hidden="true"
      className={`relative grid w-full place-items-center ${height}`}
      onPointerEnter={() => setActive(true)}
      onPointerMove={followPointer}
      onPointerLeave={reset}
      style={{ perspective: '760px', background: 'transparent' }}
    >
      <div
        className="relative h-full"
        style={{
          aspectRatio: '6 / 5',
          maxWidth: '100%',
          transform: `rotateX(${tilt.y}deg) rotateY(${tilt.x}deg) scale(${active ? 1.03 : 1})`,
          transformStyle: 'preserve-3d',
          transition: active ? 'transform 90ms linear' : 'transform 460ms cubic-bezier(.2,.8,.2,1)',
          willChange: 'transform',
        }}
      >
        {/* Shell + sheets */}
        <svg viewBox={ART_VIEWBOX} className="absolute inset-0 h-full w-full">
          <defs>
            <linearGradient id={ref('shell')} x1="0.12" y1="0" x2="0.62" y2="1">
              <stop offset="0%" stopColor={palette.shellTop} />
              <stop offset="46%" stopColor={palette.shellMid} />
              <stop offset="100%" stopColor={palette.shellBottom} />
            </linearGradient>
            <linearGradient id={ref('sheet')} x1="0.1" y1="0" x2="0.5" y2="1">
              <stop offset="0%" stopColor="#ffffff" />
              <stop offset="62%" stopColor="#f4f5f7" />
              <stop offset="100%" stopColor="#dfe2e8" />
            </linearGradient>
            <filter id={ref('drop')} x="-45%" y="-35%" width="190%" height="190%">
              <feDropShadow
                dx="0"
                dy="9"
                stdDeviation="10"
                floodColor="#080b14"
                floodOpacity={palette.dropOpacity}
              />
            </filter>
            <filter id={ref('sheetShadow')} x="-45%" y="-35%" width="190%" height="190%">
              <feDropShadow dx="-1" dy="3" stdDeviation="3" floodColor="#080b14" floodOpacity="0.34" />
            </filter>
            <filter id={ref('contact')} x="-60%" y="-200%" width="220%" height="500%">
              <feGaussianBlur stdDeviation="9" />
            </filter>
          </defs>

          {/* Contact shadow grounds the icon without any card behind it */}
          <ellipse
            cx="120"
            cy="182"
            rx="72"
            ry="9"
            fill="#0b1020"
            filter={`url(#${ref('contact')})`}
            opacity={active ? palette.contactOpacity + 0.1 : palette.contactOpacity}
            style={{ transition: 'opacity 320ms ease' }}
          />

          <g filter={`url(#${ref('drop')})`}>
            <path d={SHELL_PATH} fill={`url(#${ref('shell')})`} />
          </g>
          {/* Lit top edge of the shell's back wall */}
          <path
            d="M 56 41.5 H 184"
            stroke={palette.shellTopEdge}
            strokeWidth="2"
            strokeLinecap="round"
          />
          <path d={SHELL_PATH} fill="none" stroke={palette.shellRim} strokeWidth="1.1" />

          {/* Sheets: draw the back of the fan first so the front one sits on top */}
          <g filter={`url(#${ref('sheetShadow')})`}>
            {[...visible].reverse().map((sheet) => (
              <g
                key={sheet.x}
                transform={`translate(${sheet.x} ${sheet.y}) rotate(${sheet.rotate} ${sheet.width / 2} ${sheet.height / 2})`}
              >
                <rect
                  width={sheet.width}
                  height={sheet.height}
                  rx="5"
                  fill={`url(#${ref('sheet')})`}
                />
                {sheet.lines.map((line) => (
                  <rect
                    key={`${line.x}-${line.y}`}
                    x={line.x}
                    y={line.y}
                    width={line.width}
                    height={line.height}
                    rx={line.height / 2}
                    fill="rgba(148,163,184,0.5)"
                  />
                ))}
              </g>
            ))}
          </g>
        </svg>

        {/* Real glass: backdrop-filter masked to the front pocket */}
        <div
          className="absolute inset-0"
          style={{
            backdropFilter: palette.pocketBlur,
            WebkitBackdropFilter: palette.pocketBlur,
            background: palette.pocketFill,
            maskImage: POCKET_MASK,
            WebkitMaskImage: POCKET_MASK,
            maskSize: '100% 100%',
            WebkitMaskSize: '100% 100%',
            maskRepeat: 'no-repeat',
            WebkitMaskRepeat: 'no-repeat',
            transform: 'translateZ(16px)',
          }}
        />

        {/* Glass finishing: frost, specular sweep, bevel, rim */}
        <svg
          viewBox={ART_VIEWBOX}
          className="pointer-events-none absolute inset-0 h-full w-full"
          style={{ transform: 'translateZ(18px)' }}
        >
          <defs>
            <linearGradient id={ref('rim')} x1="0.18" y1="0" x2="0.62" y2="1">
              <stop offset="0%" stopColor={palette.pocketRim[0]} />
              <stop offset="34%" stopColor={palette.pocketRim[1]} />
              <stop offset="70%" stopColor={palette.pocketRim[2]} />
              <stop offset="100%" stopColor={palette.pocketRim[3]} />
            </linearGradient>
            <linearGradient id={ref('specular')} x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stopColor="rgba(255,255,255,0)" />
              <stop offset="44%" stopColor={palette.specularPeak} />
              <stop offset="58%" stopColor={palette.specularSoft} />
              <stop offset="100%" stopColor="rgba(255,255,255,0)" />
            </linearGradient>
            <filter id={ref('frost')} x="0%" y="0%" width="100%" height="100%">
              <feTurbulence type="fractalNoise" baseFrequency="1.6" numOctaves="2" result="noise" />
              <feColorMatrix in="noise" type="saturate" values="0" />
            </filter>
            <clipPath id={ref('pocketClip')}>
              <path d={POCKET_PATH} />
            </clipPath>
          </defs>

          <g clipPath={`url(#${ref('pocketClip')})`}>
            <rect x="0" y="0" width="240" height="200" filter={`url(#${ref('frost')})`} opacity="0.05" />
            <rect
              x="-40"
              y="50"
              width="150"
              height="200"
              fill={`url(#${ref('specular')})`}
              transform="rotate(-18 120 130)"
            />
            {/* Inner bevel: bright under the top edge, dark along the base */}
            <path
              d={POCKET_PATH}
              fill="none"
              stroke={palette.pocketBevel}
              strokeWidth="2.2"
              transform="translate(0, 1.4)"
            />
            <path
              d={POCKET_PATH}
              fill="none"
              stroke={palette.pocketBase}
              strokeWidth="6"
              transform="translate(0, -4)"
            />
          </g>

          {/* Outer rim: the crisp edge that gives the pocket its thickness */}
          <path d={POCKET_PATH} fill="none" stroke={`url(#${ref('rim')})`} strokeWidth="1.3" />
        </svg>

        {/* Pointer-driven specular hotspot */}
        <div
          className="pointer-events-none absolute inset-0"
          style={{
            background: `radial-gradient(circle at ${tilt.glareX}% ${tilt.glareY}%, rgba(255,255,255,${active ? palette.hotspotActive : palette.hotspotIdle}) 0%, transparent 32%)`,
            mixBlendMode: 'screen',
            maskImage: POCKET_MASK,
            WebkitMaskImage: POCKET_MASK,
            maskSize: '100% 100%',
            WebkitMaskSize: '100% 100%',
            maskRepeat: 'no-repeat',
            WebkitMaskRepeat: 'no-repeat',
            transform: 'translateZ(22px)',
            transition: active ? 'none' : 'background 300ms ease',
          }}
        />
      </div>
    </div>
  );
}
