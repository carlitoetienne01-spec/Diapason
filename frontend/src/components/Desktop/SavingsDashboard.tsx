import { useState, useEffect, useCallback } from 'react';
import type React from 'react';
import { invoke } from '@tauri-apps/api/core';
import { useTranslation } from '../../i18n/useTranslation';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ProviderSavings {
  provider: string;
  label: string;
  input_cost: number;
  output_cost: number;
  total_cost: number;
  energy_wh: number;
  energy_joules: number;
  flops: number;
}

interface SavingsData {
  total_calls: number;
  total_prompt_tokens: number;
  total_completion_tokens: number;
  total_tokens: number;
  local_cost: number;
  per_provider: ProviderSavings[];
  monthly_projection: Record<string, number>;
  session_start_ts: number;
  session_duration_hours: number;
  avg_cost_per_query: Record<string, number>;
  cloud_agent_equivalent: {
    moderate_low: number;
    moderate_high: number;
    heavy_low: number;
    heavy_high: number;
  };
  token_counting_version?: number;
}

// ---------------------------------------------------------------------------
// Styles (Catppuccin)
// ---------------------------------------------------------------------------

const colors = {
  bg: '#1e1e2e',
  surface: '#282840',
  text: '#cdd6f4',
  textMuted: '#a6adc8',
  accent: '#89b4fa',
  green: '#a6e3a1',
  yellow: '#f9e2af',
  red: '#f38ba8',
  purple: '#cba6f7',
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
  sectionHeading: {
    fontSize: 14,
    fontWeight: 600,
    color: colors.textMuted,
    textTransform: 'uppercase' as const,
    letterSpacing: '0.05em',
    marginBottom: 12,
  },
  providersGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
    gap: 16,
    marginBottom: 24,
  },
  providerCard: {
    background: colors.surface,
    borderRadius: 10,
    padding: 20,
    border: `1px solid ${colors.border}`,
    position: 'relative' as const,
    overflow: 'hidden' as const,
  },
  providerName: {
    fontSize: 14,
    fontWeight: 600,
    marginBottom: 4,
  },
  providerModel: {
    fontSize: 12,
    color: colors.textMuted,
    marginBottom: 14,
  },
  savingsAmount: {
    fontSize: 32,
    fontWeight: 700,
    color: colors.green,
    marginBottom: 8,
  },
  breakdown: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: 12,
    marginTop: 14,
    paddingTop: 14,
    borderTop: `1px solid ${colors.border}`,
  },
  breakdownLabel: {
    fontSize: 11,
    color: colors.textMuted,
    textTransform: 'uppercase' as const,
    letterSpacing: '0.04em',
  },
  breakdownValue: {
    fontSize: 16,
    fontWeight: 600,
    marginTop: 2,
  },
  cloudAgentCard: {
    background: colors.surface,
    borderRadius: 10,
    padding: 20,
    border: `1px solid ${colors.border}`,
    borderTop: `3px solid ${colors.purple}`,
    marginBottom: 24,
  },
  cloudAgentGrid: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr 1fr',
    gap: 20,
    marginTop: 16,
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
};

const PROVIDER_COLORS: Record<string, string> = {
  'gpt-5.6-sol': colors.green,
  'claude-fable-5': colors.yellow,
  'gemini-3.1-pro': colors.accent,
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmtDollar(n: number): string {
  if (n >= 1000) return '$' + n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (n >= 1) return '$' + n.toFixed(2);
  if (n >= 0.01) return '$' + n.toFixed(3);
  if (n > 0) return '$' + n.toFixed(4);
  return '$0.00';
}

function fmtDuration(hours: number): string {
  if (hours < 1) return `${Math.round(hours * 60)}m`;
  if (hours < 24) return `${hours.toFixed(1)}h`;
  return `${(hours / 24).toFixed(1)}d`;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const REFRESH_INTERVAL_MS = 5000;

export function SavingsDashboard({ apiUrl }: { apiUrl: string }) {
  const { t } = useTranslation();
  const [data, setData] = useState<SavingsData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      const result = await invoke<SavingsData>('fetch_savings', { apiUrl });
      setData(result);
      setError(null);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [apiUrl]);

  useEffect(() => {
    fetchData();
    const timer = setInterval(fetchData, REFRESH_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [fetchData]);

  if (!loading && !data && !error) {
    return (
      <div style={styles.container}>
        <div style={styles.header}>
          <h2 style={styles.title}>{t('dashboard.savings.title')}</h2>
        </div>
        <div style={styles.emptyState}>
          <div style={{ fontSize: 40, opacity: 0.4 }}>$</div>
          <div style={styles.emptyText}>
            {t('dashboard.savings.empty.title')}<br />
            {t('dashboard.savings.empty.hint')}
          </div>
        </div>
      </div>
    );
  }

  const providers = data?.per_provider ?? [];
  const projection = data?.monthly_projection ?? {};
  const cloudAgent = data?.cloud_agent_equivalent;

  return (
    <div style={styles.container}>
      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.3; }
        }
      `}</style>

      {/* Header */}
      <div style={styles.header}>
        <h2 style={styles.title}>{t('dashboard.savings.title')}</h2>
        <span style={styles.liveBadge}>
          <span style={styles.liveDot} />
          {t('dashboard.savings.live', { seconds: REFRESH_INTERVAL_MS / 1000 })}
        </span>
      </div>

      {error && <div style={styles.errorBanner}>{error}</div>}

      {/* Stat cards row */}
      <div style={styles.statsGrid}>
        <div style={styles.statCard}>
          <div style={styles.statLabel}>{t('dashboard.savings.stat.requests')}</div>
          <div style={styles.statValue}>
            {(data?.total_calls ?? 0).toLocaleString()}
          </div>
        </div>
        <div style={styles.statCard}>
          <div style={styles.statLabel}>{t('dashboard.savings.stat.tokens')}</div>
          <div style={styles.statValue}>
            {(data?.total_tokens ?? 0).toLocaleString()}
          </div>
        </div>
        <div style={styles.statCard}>
          <div style={styles.statLabel}>{t('dashboard.savings.stat.duration')}</div>
          <div style={styles.statValue}>
            {fmtDuration(data?.session_duration_hours ?? 0)}
          </div>
        </div>
        <div style={styles.statCard}>
          <div style={styles.statLabel}>{t('dashboard.savings.stat.localCost')}</div>
          <div style={{ ...styles.statValue, color: colors.green }}>
            {fmtDollar(data?.local_cost ?? 0)}
          </div>
        </div>
      </div>

      {/* Provider savings cards */}
      <div style={styles.sectionHeading}>{t('dashboard.savings.section.providers')}*</div>
      <div style={styles.providersGrid}>
        {providers.map((p) => (
          <div
            key={p.provider}
            style={{
              ...styles.providerCard,
              borderTop: `3px solid ${PROVIDER_COLORS[p.provider] ?? colors.accent}`,
            }}
          >
            <div style={styles.providerName}>{p.label}</div>
            <div style={styles.providerModel}>{p.provider}</div>
            <div style={styles.savingsAmount}>{fmtDollar(p.total_cost)}</div>
            <div style={styles.breakdown}>
              <div>
                <div style={styles.breakdownLabel}>{t('dashboard.savings.breakdown.input')}</div>
                <div style={styles.breakdownValue}>{fmtDollar(p.input_cost)}</div>
              </div>
              <div>
                <div style={styles.breakdownLabel}>{t('dashboard.savings.breakdown.output')}</div>
                <div style={styles.breakdownValue}>{fmtDollar(p.output_cost)}</div>
              </div>
            </div>
          </div>
        ))}
      </div>

      <div style={{ fontSize: 11, color: colors.textMuted, marginTop: 8, lineHeight: 1.5 }}>
        *{t('dashboard.savings.footnote')}
      </div>

      {/* Cloud Agent Platforms */}
      {cloudAgent && (
        <>
          <div style={styles.sectionHeading}>{t('dashboard.savings.section.cloudAgents')}</div>
          <div style={styles.cloudAgentCard}>
            <div style={styles.providerName}>{t('dashboard.savings.cloudAgent.name')}</div>
            <div style={styles.providerModel}>{t('dashboard.savings.cloudAgent.basis')}</div>
            <div style={styles.cloudAgentGrid}>
              <div>
                <div style={styles.breakdownLabel}>{t('dashboard.savings.cloudAgent.moderate')}</div>
                <div style={{ ...styles.breakdownValue, color: colors.yellow, fontSize: 20 }}>
                  ${cloudAgent.moderate_low}&ndash;{cloudAgent.moderate_high}
                  {t('dashboard.savings.cloudAgent.perMonth')}
                </div>
              </div>
              <div>
                <div style={styles.breakdownLabel}>{t('dashboard.savings.cloudAgent.heavy')}</div>
                <div style={{ ...styles.breakdownValue, color: colors.red, fontSize: 20 }}>
                  ${cloudAgent.heavy_low}&ndash;{cloudAgent.heavy_high}+
                  {t('dashboard.savings.cloudAgent.perMonth')}
                </div>
              </div>
              <div>
                <div style={styles.breakdownLabel}>{t('dashboard.savings.cloudAgent.yourCost')}</div>
                <div style={{ ...styles.breakdownValue, color: colors.green, fontSize: 24 }}>
                  $0.00
                </div>
                <div style={{ fontSize: 12, color: colors.textMuted, marginTop: 2 }}>
                  {t('dashboard.savings.cloudAgent.localInference')}
                </div>
              </div>
            </div>
          </div>
        </>
      )}

      {/* Monthly Projection */}
      <div style={styles.sectionHeading}>{t('dashboard.savings.section.projection')}</div>
      <div style={styles.providersGrid}>
        {providers.map((p) => (
          <div
            key={`proj-${p.provider}`}
            style={{
              ...styles.providerCard,
              borderTop: `3px solid ${PROVIDER_COLORS[p.provider] ?? colors.accent}`,
            }}
          >
            <div style={styles.providerName}>
              {t('dashboard.savings.projection.vsProvider', { provider: p.label })}
            </div>
            <div style={styles.providerModel}>{t('dashboard.savings.projection.subtitle')}</div>
            <div style={styles.savingsAmount}>
              {fmtDollar(projection[p.provider] ?? 0)}
            </div>
            <div style={{ fontSize: 12, color: colors.textMuted }}>
              {t('dashboard.savings.projection.rate')}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
