import { CadreVitre } from '../../components/Glass/CadreVitre';
import type { CSSProperties, ReactNode } from 'react';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import type { FinanceCategoryBreakdown, FinanceSeriesPoint } from './types';

// L'inclinaison 3D (perspective + rotateX 6°) n'existe qu'à partir de `sm` :
// dans le mini-panneau (~140 px de haut utile), elle floutait les ticks de
// 10 px sans rien apporter — constaté à l'audit du 16 sept. 2026.
const chartPerspectiveClass =
  'flex-1 w-full min-w-0 origin-bottom sm:[transform:perspective(900px)_rotateX(6deg)]';

const tooltipStyle: CSSProperties = {
  background: 'var(--color-surface)',
  border: '1px solid var(--color-border)',
  borderRadius: 12,
  color: 'var(--color-text)',
  fontSize: 12,
};

function formatCad(value: number) {
  return new Intl.NumberFormat('fr-CA', {
    style: 'currency',
    currency: 'CAD',
    maximumFractionDigits: 0,
  }).format(value);
}

function shortDate(iso: string) {
  const [, month, day] = iso.split('-');
  return `${day}/${month}`;
}

// L'axe vertical réservait 42 px pour écrire « 12500 » : 12 % d'un panneau
// de 340 px, pris sur les barres. Une graduation compacte (« 12,5k ») tient
// dans 32 px sans perdre l'ordre de grandeur — les montants exacts sont
// dans l'info-bulle. Audit du mini-panneau, 16 sept. 2026.
export const AXIS_WIDTH = 32;

export function compactAxisTick(value: number): string {
  const abs = Math.abs(value);
  if (abs < 1000) return `${Math.round(value)}`;
  const sign = value < 0 ? '-' : '';
  const [divisor, suffix] = abs >= 1_000_000 ? [1_000_000, 'M'] : [1000, 'k'];
  const scaled = Math.round((abs / divisor) * 10) / 10;
  const text = Number.isInteger(scaled) ? `${scaled}` : `${scaled}`.replace('.', ',');
  return `${sign}${text}${suffix}`;
}

/** Une entrée de légende : les catégories les plus lourdes, le reste agrégé. */
export interface LegendSlice {
  /** Clé React : l'id de catégorie — deux catégories peuvent porter le même
      nom (aucune unicité côté serveur), et l'entrée « Autres » a la sienne. */
  key: string;
  name: string;
  color: string;
}

// La légende du camembert avait 36 px de haut, fixes : au-delà de quatre
// catégories, elle débordait de la boîte de 210 px et recouvrait le disque.
// On n'en montre que les plus lourdes, le reste devient une entrée « Autres ».
export const LEGEND_MAX = 4;

export function legendSlices(data: FinanceCategoryBreakdown[], max = LEGEND_MAX): LegendSlice[] {
  const slice = ({ categoryId, name, color }: FinanceCategoryBreakdown): LegendSlice => ({
    key: categoryId || name,
    name,
    color,
  });
  if (data.length <= max) return data.map(slice);
  const sorted = [...data].sort((a, b) => b.amount - a.amount);
  const kept = sorted.slice(0, max - 1).map(slice);
  const rest = sorted.length - (max - 1);
  return [...kept, { key: '__autres', name: `Autres (${rest})`, color: 'var(--color-text-tertiary)' }];
}

function DonutLegend({ items }: { items: LegendSlice[] }) {
  // Sous `sm`, l'info-bulle suffit : la légende est cachée, mais l'espace que
  // Recharts lui réserve reste — le disque (156 px) tient encore dans 174 px.
  return (
    <ul className="hidden sm:flex flex-wrap justify-center gap-x-3 gap-y-1 pt-1 m-0 p-0 list-none">
      {items.map((item) => (
        <li key={item.key} className="flex items-center gap-1 min-w-0">
          <span
            aria-hidden
            className="size-2 rounded-full shrink-0"
            style={{ background: item.color }}
          />
          <span className="truncate" style={{ color: 'var(--color-text-secondary)', fontSize: 11 }}>
            {item.name}
          </span>
        </li>
      ))}
    </ul>
  );
}

function ChartShell({ title, children }: { title: string; children: ReactNode }) {
  return (
    <CadreVitre
      className="rounded-2xl p-3 sm:p-4 flex flex-col min-h-[220px] sm:min-h-[260px] min-w-0"
      style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
    >
      <h3 className="text-sm font-medium mb-2 sm:mb-3" style={{ color: 'var(--color-text-secondary)' }}>
        {title}
      </h3>
      <div className={chartPerspectiveClass}>{children}</div>
    </CadreVitre>
  );
}

export function CategoryDonutChart({ data }: { data: FinanceCategoryBreakdown[] }) {
  const slices = data.length
    ? data
    : [{ categoryId: '', name: 'Aucune dépense', icon: '—', color: 'var(--color-border)', amount: 1 }];
  const empty = !data.length;
  const legend = legendSlices(data);

  return (
    <ChartShell title="Répartition des dépenses">
      <ResponsiveContainer width="100%" height={210}>
        <PieChart>
          <Pie
            data={slices}
            dataKey="amount"
            nameKey="name"
            innerRadius={52}
            outerRadius={78}
            paddingAngle={empty ? 0 : 2}
            stroke="transparent"
          >
            {slices.map((slice) => (
              <Cell key={`${slice.categoryId}-${slice.name}`} fill={slice.color} />
            ))}
          </Pie>
          {!empty && (
            <Tooltip
              contentStyle={tooltipStyle}
              formatter={(value) => formatCad(Number(value ?? 0))}
            />
          )}
          {!empty && (
            <Legend verticalAlign="bottom" height={36} content={() => <DonutLegend items={legend} />} />
          )}
        </PieChart>
      </ResponsiveContainer>
    </ChartShell>
  );
}

export function IncomeExpenseBarChart({ data }: { data: FinanceSeriesPoint[] }) {
  const chartData = data.map((point) => ({
    ...point,
    label: shortDate(point.date),
  }));

  return (
    <ChartShell title="Revenus vs dépenses">
      <ResponsiveContainer width="100%" height={210}>
        <BarChart data={chartData} barGap={2} barCategoryGap="18%">
          <CartesianGrid stroke="color-mix(in srgb, var(--color-border) 70%, transparent)" vertical={false} />
          <XAxis
            dataKey="label"
            tick={{ fill: 'var(--color-text-tertiary)', fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            interval="preserveStartEnd"
          />
          <YAxis
            tick={{ fill: 'var(--color-text-tertiary)', fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            width={AXIS_WIDTH}
            tickFormatter={compactAxisTick}
          />
          <Tooltip
            contentStyle={tooltipStyle}
            labelFormatter={(_, payload) => payload?.[0]?.payload?.date ?? ''}
            formatter={(value) => formatCad(Number(value ?? 0))}
          />
          <Bar dataKey="income" name="Revenus" fill="var(--color-success)" radius={[4, 4, 0, 0]} />
          <Bar dataKey="expense" name="Dépenses" fill="var(--color-error)" radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </ChartShell>
  );
}

export function NetEvolutionChart({ data }: { data: FinanceSeriesPoint[] }) {
  let running = 0;
  const chartData = data.map((point) => {
    running += point.income - point.expense;
    return {
      date: point.date,
      label: shortDate(point.date),
      net: Math.round(running * 100) / 100,
    };
  });

  return (
    <ChartShell title="Évolution du solde net">
      <ResponsiveContainer width="100%" height={210}>
        <AreaChart data={chartData}>
          <defs>
            <linearGradient id="financeNetFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--color-accent)" stopOpacity={0.35} />
              <stop offset="100%" stopColor="var(--color-accent)" stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="color-mix(in srgb, var(--color-border) 70%, transparent)" vertical={false} />
          <XAxis
            dataKey="label"
            tick={{ fill: 'var(--color-text-tertiary)', fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            interval="preserveStartEnd"
          />
          <YAxis
            tick={{ fill: 'var(--color-text-tertiary)', fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            width={AXIS_WIDTH}
            tickFormatter={compactAxisTick}
          />
          <Tooltip
            contentStyle={tooltipStyle}
            labelFormatter={(_, payload) => payload?.[0]?.payload?.date ?? ''}
            formatter={(value) => formatCad(Number(value ?? 0))}
          />
          <Area
            type="monotone"
            dataKey="net"
            name="Net cumulé"
            stroke="var(--color-accent)"
            fill="url(#financeNetFill)"
            strokeWidth={2}
          />
        </AreaChart>
      </ResponsiveContainer>
    </ChartShell>
  );
}
