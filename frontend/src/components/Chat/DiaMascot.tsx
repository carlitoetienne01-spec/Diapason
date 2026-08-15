import { useEffect, useRef, useState, type CSSProperties } from 'react';
import diaMascot from '../../assets/dia-mascot.png';

interface DiaMascotProps {
  label: string;
}

type DiaPosition = 'left' | 'center' | 'right';
type DiaAction = 'idle' | 'walk' | 'observe' | 'celebrate';
type DiaExpression = 'wave' | 'curious' | 'happy' | 'surprised';

interface DiaPhase {
  position: DiaPosition;
  action: DiaAction;
  expression: DiaExpression;
  duration: number;
}

const DIA_SEQUENCE: DiaPhase[] = [
  { position: 'center', action: 'idle', expression: 'wave', duration: 2400 },
  { position: 'left', action: 'walk', expression: 'wave', duration: 2800 },
  { position: 'left', action: 'observe', expression: 'curious', duration: 1700 },
  { position: 'right', action: 'walk', expression: 'happy', duration: 4700 },
  { position: 'right', action: 'celebrate', expression: 'happy', duration: 1900 },
  { position: 'center', action: 'walk', expression: 'wave', duration: 2700 },
  { position: 'center', action: 'idle', expression: 'surprised', duration: 1200 },
];

const LAYERS = ['leg-left', 'leg-right', 'arm-left', 'arm-right', 'torso'] as const;

/**
 * DIA keeps the approved 3D illustration, but renders it as an articulated
 * sprite rig. Each limb is a separately clipped layer of the same lossless
 * source image, so it can move around its real joint without changing DIA's
 * appearance.
 */
export function DiaMascot({ label }: DiaMascotProps) {
  const [phaseIndex, setPhaseIndex] = useState(0);
  const [isGreeting, setIsGreeting] = useState(false);
  const greetingTimer = useRef<number | null>(null);
  const phase = DIA_SEQUENCE[phaseIndex];

  useEffect(() => {
    const timer = window.setTimeout(
      () => setPhaseIndex((index) => (index + 1) % DIA_SEQUENCE.length),
      phase.duration,
    );
    return () => window.clearTimeout(timer);
  }, [phase.duration, phaseIndex]);

  useEffect(
    () => () => {
      if (greetingTimer.current !== null) window.clearTimeout(greetingTimer.current);
    },
    [],
  );

  const greet = () => {
    if (greetingTimer.current !== null) window.clearTimeout(greetingTimer.current);
    setIsGreeting(false);
    window.requestAnimationFrame(() => setIsGreeting(true));
    greetingTimer.current = window.setTimeout(() => setIsGreeting(false), 1900);
  };

  const style = {
    '--dia-travel-duration': `${phase.duration}ms`,
  } as CSSProperties;

  return (
    <button
      type="button"
      className={[
        'dia-rig-stage',
        `dia-position-${phase.position}`,
        `dia-action-${phase.action}`,
        `dia-expression-${phase.expression}`,
        isGreeting ? 'dia-rig-is-greeting' : '',
      ].join(' ')}
      style={style}
      onClick={greet}
      aria-label={label}
      title={label}
    >
      <span className="dia-rig-actor" aria-hidden="true">
        <span className="dia-rig-ground-shadow" />
        <span className="dia-rig-body-bob">
          {LAYERS.map((layer) => (
            <span className={`dia-sprite-layer dia-sprite-${layer}`} key={layer}>
              <img src={diaMascot} alt="" draggable={false} />
            </span>
          ))}

          <span className="dia-head-group">
            <span className="dia-sprite-layer dia-sprite-head">
              <img src={diaMascot} alt="" draggable={false} />
            </span>

            <span className="dia-face-screen">
              <svg viewBox="0 0 150 68" focusable="false">
                <defs>
                  <filter id="dia-face-glow" x="-70%" y="-70%" width="240%" height="240%">
                    <feGaussianBlur stdDeviation="2.5" result="glow" />
                    <feMerge><feMergeNode in="glow" /><feMergeNode in="SourceGraphic" /></feMerge>
                  </filter>
                </defs>
                <g className="dia-face-expression dia-face-wave" filter="url(#dia-face-glow)">
                  <path d="M18 35 C32 12 47 58 63 35 S94 12 108 35 S129 58 138 31" />
                </g>
                <g className="dia-face-expression dia-face-curious" filter="url(#dia-face-glow)">
                  <circle cx="48" cy="31" r="10" />
                  <circle cx="103" cy="34" r="6" />
                  <circle cx="76" cy="50" r="3.5" />
                </g>
                <g className="dia-face-expression dia-face-happy" filter="url(#dia-face-glow)">
                  <path d="M35 35 C41 22 52 22 59 35" />
                  <path d="M91 35 C98 22 109 22 115 35" />
                  <path d="M58 44 C68 54 82 54 92 44" />
                </g>
                <g className="dia-face-expression dia-face-surprised" filter="url(#dia-face-glow)">
                  <circle cx="48" cy="31" r="7" />
                  <circle cx="102" cy="31" r="7" />
                  <ellipse cx="75" cy="49" rx="5" ry="7" />
                </g>
              </svg>
            </span>

            <span className="dia-sound-pulse dia-sound-pulse-left" />
            <span className="dia-sound-pulse dia-sound-pulse-right" />
          </span>

          <span className="dia-chest-light" />
        </span>
      </span>
    </button>
  );
}
