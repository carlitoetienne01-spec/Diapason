import { ResponsiveContainer, LineChart, BarChart, AreaChart, PieChart, Line, Bar, Area, Pie, Cell, XAxis, YAxis, CartesianGrid, Tooltip, Legend } from 'recharts';
import type { Graphique } from './formatVisuel';
import type { PaletteVisuel } from './svgSur';

export default function GraphiqueDiscussion({ graphique: g, palette: p }: { graphique: Graphique; palette: PaletteVisuel }) {
  const couleurs = [p.accent, p.texte, p.secondaire, '#6085ba', '#bd874b', '#9982ae', '#5b9a87', '#b96c7b'];
  const communs = <>
    <CartesianGrid stroke={p.bord} strokeDasharray="3 5" vertical={false} />
    <XAxis dataKey={g.xKey} tick={{ fill: p.texte, fontSize: 12 }} stroke={p.bord} />
    <YAxis tick={{ fill: p.texte, fontSize: 12 }} stroke={p.bord} width={65} />
    <Tooltip cursor={{ fill: p.accent, fillOpacity: .06 }} contentStyle={{ background: p.fond, color: p.texte, borderColor: p.bord }} />
    <Legend wrapperStyle={{ color: p.texte, fontSize: 12 }} />
  </>;
  return <div className="visuel-graphique" role="img" aria-label={g.title}>
    <ResponsiveContainer width="100%" height={320}>
      {g.type === 'pie' ? <PieChart><Pie data={g.data} dataKey={g.series[0].key} nameKey={g.xKey} isAnimationActive={false}>
        {g.data.map((_, i) => <Cell key={i} fill={couleurs[i % couleurs.length]} stroke={p.fond} />)}
      </Pie><Tooltip cursor={{ fill: p.accent, fillOpacity: .06 }} contentStyle={{ background: p.fond, borderColor: p.bord }} /><Legend /></PieChart>
        : g.type === 'bar' ? <BarChart data={g.data}>{communs}{g.series.map((s, i) => <Bar key={s.key} dataKey={s.key} name={s.label} fill={couleurs[i]} isAnimationActive={false} />)}</BarChart>
          : g.type === 'area' ? <AreaChart data={g.data}>{communs}{g.series.map((s, i) => <Area key={s.key} dataKey={s.key} name={s.label} stroke={couleurs[i]} fill={couleurs[i]} fillOpacity={0.16} isAnimationActive={false} />)}</AreaChart>
            : <LineChart data={g.data}>{communs}{g.series.map((s, i) => <Line key={s.key} dataKey={s.key} name={s.label} stroke={couleurs[i]} strokeWidth={2} dot={g.data.length < 30} isAnimationActive={false} />)}</LineChart>}
    </ResponsiveContainer>
  </div>;
}
