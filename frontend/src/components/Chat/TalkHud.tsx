import { useMemo } from 'react';

import type { TerrainTelemetry } from '../VoiceTerrain/VoiceTerrain';

/**
 * L'habillage d'instrument autour du relief.
 *
 * Dense comme un relevé scientifique, et entièrement vrai. Aucune colonne
 * n'est remplie pour faire nombre : un cadran qui invente ses valeurs est pire
 * qu'un cadran vide, parce qu'on ne peut plus le distinguer d'un instrument qui
 * marche — et le jour où quelque chose ne va pas, il continuera d'afficher que
 * tout va bien.
 *
 * Rien n'est écrit en blanc en dur. Tout passe par les tokens du thème : les
 * peaux terminal écrasent les couleurs de statut sur une seule encre, et un
 * habillage codé en dur y deviendrait illisible ou criard.
 */

export interface TalkHudProps {
  telemetry: TerrainTelemetry | null;
  /** L'état de la session, tel que l'en-tête l'affiche déjà. */
  state: string;
  /** Secondes depuis l'ouverture. */
  elapsed: number;
  /** Fournisseur de voix (local, gemini…). */
  provider?: string;
  /** Modèle en service, s'il est connu. */
  model?: string;
}

/** Décibels pleine échelle. Le silence numérique n'a pas de logarithme, d'où
 * le plancher : −96 dB est en dessous de tout ce qu'un micro capte. */
function dbfs(level: number): number {
  if (level <= 0.00002) return -96;
  return Math.max(-96, 20 * Math.log10(level));
}

function hz(value: number): string {
  if (value <= 0) return '——————';
  if (value >= 1000) return `${(value / 1000).toFixed(2)} kHz`;
  return `${value.toFixed(1)} Hz`;
}

/** Les bandes affichées dans le tableau. Une sur quatre des soixante-quatre :
 * assez pour couvrir la voix de bout en bout, assez peu pour que chaque ligne
 * reste lisible plutôt que de défiler en bouillie. */
const TABLE_STEP = 4;

export function TalkHud({
  telemetry,
  state,
  elapsed,
  provider,
  model,
}: TalkHudProps) {
  const rows = useMemo(() => {
    if (!telemetry) return [];
    const out: { hz: number; value: number }[] = [];
    for (let i = 2; i < telemetry.bins.length; i += TABLE_STEP) {
      out.push({ hz: telemetry.edges[i], value: telemetry.bins[i] });
    }
    return out;
  }, [telemetry]);

  const level = telemetry?.level ?? 0;
  const db = dbfs(level);

  return (
    <div
      aria-hidden="true"
      className="absolute inset-0 pointer-events-none select-none talk-hud"
    >
      {/* ── haut gauche : la session ── */}
      <div className="talk-hud-block" style={{ top: 14, left: 16 }}>
        <Line label="ÉTAT" value={state.toUpperCase()} strong />
        <Line label="SOURCE" value={(provider || '—').toUpperCase()} />
        <Line label="MODÈLE" value={model || '—'} />
        <Line
          label="DURÉE"
          value={`${String(Math.floor(elapsed / 60)).padStart(2, '0')}:${String(
            elapsed % 60,
          ).padStart(2, '0')}`}
        />
      </div>

      {/* ── haut gauche, second bloc : le signal ── */}
      <div className="talk-hud-block" style={{ top: 106, left: 16 }}>
        <Line label="NIVEAU" value={`${Math.round(level * 100)}`.padStart(3, '0')} />
        <Line label="CRÊTE" value={hz(telemetry?.dominantHz ?? 0)} />
        <Line label="BANDES" value={`${telemetry?.bins.length ?? 0}`} />
      </div>

      {/* ── haut centre ── */}
      <div
        className="talk-hud-caption"
        style={{ top: 14, left: '50%', transform: 'translateX(-50%)' }}
      >
        <span>DIAPASON</span>
        <span style={{ marginLeft: 48 }}>RELIEF SPECTRAL</span>
      </div>

      {/* ── haut droite : le rendu ── */}
      <div className="talk-hud-block talk-hud-right" style={{ top: 14, right: 16 }}>
        <Line label="QUALITÉ" value={(telemetry?.quality || '—').toUpperCase()} align="right" />
        <Line
          label="POINTS"
          value={telemetry ? telemetry.points.toLocaleString('fr-CA') : '—'}
          align="right"
        />
        <Line
          label="IPS"
          // 0 avant que la première fenêtre de mesure se ferme : mieux vaut un
          // tiret qu'un 60 inventé.
          value={telemetry && telemetry.fps > 0 ? telemetry.fps.toFixed(0) : '—'}
          align="right"
        />
      </div>

      {/* ── colonne droite : le spectre, bande par bande ── */}
      <div className="talk-hud-table" style={{ top: 96, right: 16 }}>
        {rows.map((row) => (
          <div key={row.hz} className="talk-hud-row">
            <span className="talk-hud-row-hz">{hz(row.hz)}</span>
            <span
              className="talk-hud-row-bar"
              style={{
                // La barre EST la valeur : pas d'échelle inventée, pas de
                // minimum décoratif. Une bande muette est une barre absente.
                width: `${Math.min(100, row.value * 100)}%`,
              }}
            />
            <span className="talk-hud-row-value">
              {row.value.toFixed(3).slice(1)}
            </span>
          </div>
        ))}
      </div>

      {/* ── grand nombre : le niveau en décibels ── */}
      <div className="talk-hud-big" style={{ right: 16 }}>
        <span className="talk-hud-big-label">dBFS</span>
        <span className="talk-hud-big-value">
          {db <= -96 ? '−∞' : db.toFixed(1)}
        </span>
      </div>

      {/* ── graduations à gauche : l'échelle du relief ── */}
      <div className="talk-hud-scale">
        {[1, 0.75, 0.5, 0.25, 0].map((tick) => (
          <div key={tick} className="talk-hud-tick">
            <span>{tick.toFixed(2)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function Line({
  label,
  value,
  strong,
  align,
}: {
  label: string;
  value: string;
  strong?: boolean;
  align?: 'right';
}) {
  return (
    <div
      className="talk-hud-line"
      style={{ justifyContent: align === 'right' ? 'flex-end' : 'space-between' }}
    >
      <span className="talk-hud-label">{label}</span>
      <span className={strong ? 'talk-hud-value talk-hud-value-strong' : 'talk-hud-value'}>
        {value}
      </span>
    </div>
  );
}

export default TalkHud;
