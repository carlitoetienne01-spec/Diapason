import { useState, useEffect, useCallback } from 'react';
import {
  Zap,
  Activity,
  Thermometer,
  TrendingDown,
  Cloud,
  HardDrive,
  Hash,
  X,
} from 'lucide-react';
import { useAppStore } from '../../lib/store';
import { getBase } from '../../lib/api';
import { useTranslation } from '../../i18n/useTranslation';
import { CarteVitree } from '../Glass/CarteVitree';

interface EnergyData {
  total_energy_j?: number;
  energy_per_token_j?: number;
  avg_power_w?: number;
  cpu_temp_c?: number | null;
  gpu_temp_c?: number | null;
}

interface TelemetryStats {
  total_requests?: number;
  total_tokens?: number;
}

const CLOUD_PRICING = [
  { name: 'GPT-5.6 Sol', input: 5.00, output: 30.00, primary: true },
  { name: 'Claude Fable 5', input: 10.00, output: 50.00, primary: false },
  { name: 'Gemini 3.1 Pro', input: 2.00, output: 12.00, primary: false },
];

export function SystemPanel() {
  const { t } = useTranslation();
  const savings = useAppStore((s) => s.savings);
  const toggleSystemPanel = useAppStore((s) => s.toggleSystemPanel);
  const liveEnergy = useAppStore((s) => s.liveEnergy);
  const [energy, setEnergy] = useState<EnergyData | null>(null);
  const [telemetry, setTelemetry] = useState<TelemetryStats | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const base = getBase();
      const [energyRes, telRes] = await Promise.allSettled([
        fetch(`${base}/v1/telemetry/energy`).then((r) => (r.ok ? r.json() : null)),
        fetch(`${base}/v1/telemetry/stats`).then((r) => (r.ok ? r.json() : null)),
      ]);
      if (energyRes.status === 'fulfilled' && energyRes.value) {
        setEnergy(energyRes.value as EnergyData);
      }
      if (telRes.status === 'fulfilled' && telRes.value) {
        setTelemetry(telRes.value as TelemetryStats);
      }
    } catch {
      // best-effort
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 3000);
    return () => clearInterval(interval);
  }, [fetchData]);

  // Re-fetch energy/telemetry when savings updates (after a chat message)
  useEffect(() => {
    if (savings) fetchData();
  }, [savings, fetchData]);

  const promptK = (savings?.total_prompt_tokens ?? 0) / 1000;
  const completionK = (savings?.total_completion_tokens ?? 0) / 1000;

  return (
    <div
      className="flex flex-col h-full overflow-y-auto"
      data-verre-defilement
      style={{
        width: 280,
        minWidth: 280,
        background: 'var(--color-bg)',
        borderLeft: '1px solid var(--color-border)',
      }}
    >
      {/* Header. La cloche des validations est fixée en haut à droite de la
          FENÊTRE (Layout), au pixel près où ce bouton × se dessine : on
          voyait « une croix dans la cloche » (13 septembre 2026). Le × se
          range à gauche du groupe fixe, dont Layout publie la largeur. */}
      <div
        className="flex items-center justify-between pl-4 py-3 shrink-0"
        style={{
          borderBottom: '1px solid var(--color-border)',
          paddingRight: 'calc(var(--top-right-cluster, 33px) + 22px)',
        }}
      >
        <span className="text-xs font-semibold tracking-wide uppercase" style={{ color: 'var(--color-text-secondary)' }}>
          {t('chat.system.title')}
        </span>
        <button
          onClick={toggleSystemPanel}
          className="p-1 rounded-md transition-colors cursor-pointer"
          style={{ color: 'var(--color-text-tertiary)' }}
          title={t('chat.system.closePanel')}
          aria-label={t('chat.system.closePanel')}
        >
          <X size={14} />
        </button>
      </div>

      <div className="flex flex-col gap-4 p-4">
        {/* Session Stats */}
        <section>
          <h4 className="text-[11px] font-medium uppercase tracking-wide mb-2" style={{ color: 'var(--color-text-tertiary)' }}>
            {t('chat.system.session')}
          </h4>
          <div className="grid grid-cols-2 gap-2">
            <MiniStat icon={Hash} label={t('chat.system.requests')} value={String(savings?.total_calls ?? telemetry?.total_requests ?? 0)} />
            <MiniStat icon={Hash} label={t('chat.system.outputTokens')} value={formatNumber(savings?.total_completion_tokens ?? telemetry?.total_tokens ?? 0)} />
          </div>
        </section>

        {/* Device */}
        <section>
          <h4 className="text-[11px] font-medium uppercase tracking-wide mb-2" style={{ color: 'var(--color-text-tertiary)' }}>
            {t('chat.system.device')}
          </h4>
          <div className="grid grid-cols-2 gap-2">
            {energy?.cpu_temp_c != null && (
              <MiniStat icon={Thermometer} label={t('chat.system.cpuTemp')} value={String(Math.round(energy.cpu_temp_c))} unit="°C" />
            )}
            {energy?.gpu_temp_c != null && (
              <MiniStat icon={Thermometer} label={t('chat.system.gpuTemp')} value={String(Math.round(energy.gpu_temp_c))} unit="°C" />
            )}
            <MiniStat
              icon={Zap}
              label={t('chat.system.power')}
              value={(liveEnergy?.power_w ?? energy?.avg_power_w ?? 0).toFixed(1)}
              unit="W"
            />
            <MiniStat
              icon={Activity}
              label={t('chat.system.energy')}
              value={(
                ((liveEnergy?.energy_j ?? energy?.total_energy_j ?? 0) / 1000)
              ).toFixed(1)}
              unit="kJ"
            />
          </div>
        </section>


        {/* Cost Comparison */}
        <section>
          <h4 className="text-[11px] font-medium uppercase tracking-wide mb-2" style={{ color: 'var(--color-text-tertiary)' }}>
            {t('chat.system.costComparison')}
          </h4>

          {/* Local */}
          <CarteVitree className="mb-2" contenuClassName="flex items-center gap-2 px-3 py-2">
            <HardDrive size={14} style={{ color: 'var(--color-accent)' }} />
            <div className="flex-1 min-w-0">
              <div className="text-xs font-medium truncate" style={{ color: 'var(--color-text)' }}>{t('chat.system.local')}</div>
            </div>
            <div className="text-sm font-semibold" style={{ color: 'var(--color-success)' }}>
              ${(savings?.local_cost ?? 0).toFixed(4)}
            </div>
          </CarteVitree>

          {/* Cloud providers */}
          <div className="flex flex-col gap-1.5">
            {CLOUD_PRICING.map((provider) => {
              const cost = (promptK * provider.input) / 1000 + (completionK * provider.output) / 1000;
              const saved = cost - (savings?.local_cost ?? 0);
              return (
                <CarteVitree
                  key={provider.name}
                  contenuClassName="flex items-center gap-2 px-3 py-2"
                >
                  <Cloud size={14} style={{ color: 'var(--color-text-tertiary)' }} />
                  <div className="flex-1 min-w-0">
                    <div
                      className="text-xs truncate"
                      style={{
                        color: provider.primary ? 'var(--color-text)' : 'var(--color-text-secondary)',
                        fontWeight: provider.primary ? 500 : 400,
                      }}
                    >
                      {provider.name}
                    </div>
                  </div>
                  <div className="text-right shrink-0">
                    <div className="text-xs font-mono" style={{ color: 'var(--color-text)' }}>
                      ${cost.toFixed(4)}
                    </div>
                    {saved > 0.0001 && (
                      <div className="text-[9px] flex items-center gap-0.5 justify-end" style={{ color: 'var(--color-success)' }}>
                        <TrendingDown size={8} />
                        ${saved.toFixed(4)}
                      </div>
                    )}
                  </div>
                </CarteVitree>
              );
            })}
          </div>


        </section>
      </div>
    </div>
  );
}

function MiniStat({
  icon: Icon,
  label,
  value,
  unit,
}: {
  icon: typeof Zap;
  label: string;
  value: string;
  unit?: string;
}) {
  return (
    <CarteVitree contenuClassName="px-2.5 py-2">
      <div className="flex items-center gap-1 mb-0.5">
        <Icon size={10} style={{ color: 'var(--color-accent)' }} />
        <span className="text-[10px]" style={{ color: 'var(--color-text-tertiary)' }}>
          {label}
        </span>
      </div>
      <div className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>
        {value}
        {unit && (
          <span className="text-[10px] font-normal ml-0.5" style={{ color: 'var(--color-text-tertiary)' }}>
            {unit}
          </span>
        )}
      </div>
    </CarteVitree>
  );
}

function formatNumber(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
  return String(n);
}
