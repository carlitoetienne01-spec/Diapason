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

const chartPerspective: CSSProperties = {
  transform: 'perspective(900px) rotateX(6deg)',
  transformOrigin: 'center bottom',
};

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

function ChartShell({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div
      className="rounded-2xl p-4 flex flex-col min-h-[260px]"
      style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
    >
      <h3 className="text-sm font-medium mb-3" style={{ color: 'var(--color-text-secondary)' }}>
        {title}
      </h3>
      <div className="flex-1 w-full" style={chartPerspective}>
        {children}
      </div>
    </div>
  );
}

export function CategoryDonutChart({ data }: { data: FinanceCategoryBreakdown[] }) {
  const slices = data.length
    ? data
    : [{ categoryId: '', name: 'Aucune dépense', icon: '—', color: 'var(--color-border)', amount: 1 }];
  const empty = !data.length;

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
            <Legend
              verticalAlign="bottom"
              height={36}
              formatter={(value) => (
                <span style={{ color: 'var(--color-text-secondary)', fontSize: 11 }}>{value}</span>
              )}
            />
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
            width={42}
            tickFormatter={(value: number) => `${Math.round(value)}`}
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
            width={42}
            tickFormatter={(value: number) => `${Math.round(value)}`}
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
