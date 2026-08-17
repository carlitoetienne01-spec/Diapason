import { useState, useEffect, useCallback } from 'react';
import type React from 'react';
import { invoke } from '@tauri-apps/api/core';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';

import { useTranslation } from '../../i18n/useTranslation';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface EnergySample {
  timestamp: string;
  power_w: number;
  energy_j: number;
}

interface EnergyData {
  total_energy_j?: number;
  energy_per_token_j?: number;
  avg_power_w?: number;
  samples?: EnergySample[];
}

interface TelemetryStats {
  total_requests?: number;
  avg_latency_ms?: number;
  total_tokens?: number;
}

interface ChartPoint {
  time: string;
  power: number;
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const colors = {
  bg: '#1e1e2e',
  surface: '#282840',
  surfaceHover: '#313150',
  text: '#cdd6f4',
  textMuted: '#a6adc8',
  accent: '#89b4fa',
  green: '#a6e3a1',
  yellow: '#f9e2af',
  red: '#f38ba8',
  border: '#45475a',
} as const;

const styles: Record<string, React.CSSProperties> = {
  container: {
    background: colors.bg,
    color: colors.text,
    padding: 24,
    fontFamily: "'Inter', 'Segoe UI', system-ui, sans-serif",
    height: '100%',
    overflowY: 'auto',
    boxSizing: 'border-box',
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 24,
  },
  title: {
    fontSize: 22,
    fontWeight: 600,
    margin: 0,
    color: colors.text,
  },
  liveBadge: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 6,
    fontSize: 12,
    color: colors.green,
    background: 'rgba(166,227,161,0.1)',
    padding: '4px 10px',
    borderRadius: 12,
    fontWeight: 500,
  },
  liveDot: {
    width: 6,
    height: 6,
    borderRadius: '50%',
    background: colors.green,
    animation: 'pulse 2s infinite',
  },
  statsGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
    gap: 16,
    marginBottom: 24,
  },
  statCard: {
    background: colors.surface,
    borderRadius: 10,
    padding: 16,
    border: `1px solid ${colors.border}`,
  },
  statLabel: {
    fontSize: 12,
    color: colors.textMuted,
    marginBottom: 6,
    textTransform: 'uppercase' as const,
    letterSpacing: '0.05em',
  },
  statValue: {
    fontSize: 26,
    fontWeight: 700,
    color: colors.accent,
    lineHeight: 1.1,
  },
  statUnit: {
    fontSize: 13,
    fontWeight: 400,
    color: colors.textMuted,
    marginLeft: 4,
  },
  chartContainer: {
    background: colors.surface,
    borderRadius: 10,
    padding: 20,
    border: `1px solid ${colors.border}`,
    marginBottom: 24,
  },
  chartTitle: {
    fontSize: 14,
    fontWeight: 600,
    marginBottom: 16,
    color: colors.text,
  },
  emptyState: {
    display: 'flex',
    flexDirection: 'column' as const,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 64,
    color: colors.textMuted,
    gap: 12,
  },
  emptyIcon: {
    fontSize: 40,
    opacity: 0.4,
  },
  emptyText: {
    fontSize: 15,
    textAlign: 'center' as const,
  },
  errorBanner: {
    background: 'rgba(243,139,168,0.1)',
    border: `1px solid ${colors.red}`,
    borderRadius: 8,
    padding: '10px 16px',
    marginBottom: 16,
    fontSize: 13,
    color: colors.red,
  },
  powerLoad: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 6,
    fontSize: 14,
    fontWeight: 600,
  },
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatEnergy(joules: number): string {
  if (joules >= 1000) {
    return `${(joules / 1000).toFixed(2)} kJ`;
  }
  return `${joules.toFixed(2)} J`;
}

function formatTimestamp(ts: string): string {
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch {
    return ts;
  }
}

// The label is picked here but translated at render: this helper runs outside a
// component, where a hook cannot be called, so it hands back a catalogue key.
//
// This was "Thermal Status" / « État thermique », with Cool/Warm/Hot — a
// temperature, to anyone reading it. It is derived from average power alone.
// The API's cpu_temp_c and gpu_temp_c are null here, so there is no
// temperature to report; the honest reading of this number is power draw.
type LoadKey =
  | 'dashboard.energy.loadIdle'
  | 'dashboard.energy.loadModerate'
  | 'dashboard.energy.loadHeavy';

function powerLoadIndicator(avgPower: number): { labelKey: LoadKey; color: string } {
  if (avgPower < 50) return { labelKey: 'dashboard.energy.loadIdle', color: colors.green };
  if (avgPower < 150) return { labelKey: 'dashboard.energy.loadModerate', color: colors.yellow };
  return { labelKey: 'dashboard.energy.loadHeavy', color: colors.red };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const REFRESH_INTERVAL_MS = 5000;

export function EnergyDashboard({ apiUrl }: { apiUrl: string }) {
  const { t } = useTranslation();
  const [energyData, setEnergyData] = useState<EnergyData | null>(null);
  const [telemetry, setTelemetry] = useState<TelemetryStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      const [energy, telem] = await Promise.allSettled([
        invoke<EnergyData>('fetch_energy', { apiUrl }),
        invoke<TelemetryStats>('fetch_telemetry', { apiUrl }),
      ]);

      if (energy.status === 'fulfilled') {
        setEnergyData(energy.value);
        setError(null);
      } else {
        setEnergyData(null);
        setError(String(energy.reason));
      }

      if (telem.status === 'fulfilled') {
        setTelemetry(telem.value);
      } else {
        setTelemetry(null);
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
    } finally {
      setLoading(false);
    }
  }, [apiUrl]);

  useEffect(() => {
    fetchData();
    const timer = setInterval(fetchData, REFRESH_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [fetchData]);

  // Build chart data from samples
  const chartData: ChartPoint[] = (energyData?.samples ?? []).map((s) => ({
    time: formatTimestamp(s.timestamp),
    power: s.power_w,
  }));

  const hasEnergyData =
    energyData !== null &&
    (energyData.total_energy_j !== undefined ||
      (energyData.samples !== undefined && energyData.samples.length > 0));

  // --- Empty / error states ---

  if (!loading && !hasEnergyData && !error) {
    return (
      <div style={styles.container}>
        <div style={styles.header}>
          <h2 style={styles.title}>{t('dashboard.energy.title')}</h2>
        </div>
        <div style={styles.emptyState}>
          <div style={styles.emptyIcon}>&#x26A1;</div>
          <div style={styles.emptyText}>
            {t('dashboard.energy.emptyTitle')}<br />
            {t('dashboard.energy.emptyHint')}
          </div>
        </div>
      </div>
    );
  }

  const powerLoad = powerLoadIndicator(energyData?.avg_power_w ?? 0);

  return (
    <div style={styles.container}>
      {/* Pulse animation injected once */}
      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.3; }
        }
      `}</style>

      {/* Header */}
      <div style={styles.header}>
        <h2 style={styles.title}>{t('dashboard.energy.title')}</h2>
        <span style={styles.liveBadge}>
          <span style={styles.liveDot} />
          {t('dashboard.energy.live', { seconds: REFRESH_INTERVAL_MS / 1000 })}
        </span>
      </div>

      {/* Error banner */}
      {error && <div style={styles.errorBanner}>{error}</div>}

      {/* Summary cards */}
      <div style={styles.statsGrid}>
        <div style={styles.statCard}>
          <div style={styles.statLabel}>{t('dashboard.energy.totalEnergy')}</div>
          <div style={styles.statValue}>
            {energyData?.total_energy_j !== undefined
              ? formatEnergy(energyData.total_energy_j)
              : '--'}
          </div>
        </div>

        <div style={styles.statCard}>
          <div style={styles.statLabel}>{t('dashboard.energy.energyPerToken')}</div>
          <div style={styles.statValue}>
            {energyData?.energy_per_token_j !== undefined ? (
              <>
                {(energyData.energy_per_token_j * 1000).toFixed(3)}
                <span style={styles.statUnit}>mJ</span>
              </>
            ) : (
              '--'
            )}
          </div>
        </div>

        <div style={styles.statCard}>
          <div style={styles.statLabel}>{t('dashboard.energy.avgPower')}</div>
          <div style={styles.statValue}>
            {energyData?.avg_power_w !== undefined ? (
              <>
                {energyData.avg_power_w.toFixed(1)}
                <span style={styles.statUnit}>W</span>
              </>
            ) : (
              '--'
            )}
          </div>
        </div>

        <div style={styles.statCard}>
          <div style={styles.statLabel}>{t('dashboard.energy.powerLoad')}</div>
          <div style={{ ...styles.powerLoad, color: powerLoad.color }}>
            {t(powerLoad.labelKey)}
          </div>
        </div>

        {telemetry?.total_requests !== undefined && (
          <div style={styles.statCard}>
            <div style={styles.statLabel}>{t('dashboard.energy.totalRequests')}</div>
            <div style={styles.statValue}>{telemetry.total_requests.toLocaleString()}</div>
          </div>
        )}

        {telemetry?.total_tokens !== undefined && (
          <div style={styles.statCard}>
            <div style={styles.statLabel}>{t('dashboard.energy.totalTokens')}</div>
            <div style={styles.statValue}>{telemetry.total_tokens.toLocaleString()}</div>
          </div>
        )}
      </div>

      {/* Power chart */}
      {chartData.length > 0 && (
        <div style={styles.chartContainer}>
          <div style={styles.chartTitle}>{t('dashboard.energy.powerChartTitle')}</div>
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={chartData} margin={{ top: 4, right: 20, left: 0, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={colors.border} />
              <XAxis
                dataKey="time"
                stroke={colors.textMuted}
                tick={{ fill: colors.textMuted, fontSize: 11 }}
              />
              <YAxis
                stroke={colors.textMuted}
                tick={{ fill: colors.textMuted, fontSize: 11 }}
                unit=" W"
              />
              <Tooltip
                contentStyle={{
                  background: colors.surface,
                  border: `1px solid ${colors.border}`,
                  borderRadius: 6,
                  color: colors.text,
                  fontSize: 13,
                }}
                labelStyle={{ color: colors.textMuted }}
              />
              <Line
                type="monotone"
                dataKey="power"
                stroke={colors.accent}
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 4, fill: colors.accent }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
