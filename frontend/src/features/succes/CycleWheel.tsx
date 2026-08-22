import { useMemo, useState, type KeyboardEvent } from 'react';
import { CirclePlus, Loader2, RotateCcw } from 'lucide-react';

import type { SuccesCadence, SuccesTask } from './types';

type Props = {
  tasks: SuccesTask[];
  saving?: boolean;
  onToggle: (task: SuccesTask) => Promise<void>;
  onReset: () => Promise<void>;
  onCreate: (input: { title: string; cadence?: SuccesCadence }) => Promise<void>;
  onSelect?: (task: SuccesTask) => void;
};

const WEEKDAY_LABELS = [
  'lundi',
  'mardi',
  'mercredi',
  'jeudi',
  'vendredi',
  'samedi',
  'dimanche',
];

const MONTH_DAYS = Array.from({ length: 28 }, (_, index) => index + 1);

const VIEW = 320;
const CENTER = VIEW / 2;
const R_OUTER = 150;
const R_INNER = 74;
const R_HUB = 64;
const R_LABEL = (R_OUTER + R_INNER) / 2;

function cadenceLabel(cadence: SuccesCadence | null): string {
  if (!cadence) return '';
  if (cadence.every === 'day') return 'chaque jour';
  if (cadence.every === 'week') {
    const day = WEEKDAY_LABELS[cadence.day ?? 0] ?? WEEKDAY_LABELS[0];
    return `chaque ${day}`;
  }
  const day = cadence.day ?? 1;
  return day === 1 ? 'le 1er du mois' : `le ${day} du mois`;
}

function cadenceRank(task: SuccesTask): number {
  const cadence = task.cadence;
  if (!cadence) return 3;
  if (cadence.every === 'day') return 0;
  if (cadence.every === 'week') return 1;
  return 2;
}

function sortCycleTasks(tasks: SuccesTask[]): SuccesTask[] {
  return [...tasks].sort((a, b) => {
    const rankA = cadenceRank(a);
    const rankB = cadenceRank(b);
    if (rankA !== rankB) return rankA - rankB;
    const dayA = a.cadence?.day ?? 0;
    const dayB = b.cadence?.day ?? 0;
    if (dayA !== dayB) return dayA - dayB;
    return a.title.localeCompare(b.title, 'fr');
  });
}

function shorten(text: string, max: number): string {
  const trimmed = text.trim();
  if (trimmed.length <= max) return trimmed;
  return `${trimmed.slice(0, Math.max(1, max - 1)).trimEnd()}…`;
}

function polarPoint(radius: number, angleDeg: number): { x: number; y: number } {
  const rad = ((angleDeg - 90) * Math.PI) / 180;
  return {
    x: CENTER + radius * Math.cos(rad),
    y: CENTER + radius * Math.sin(rad),
  };
}

/** Secteur d'anneau entre deux angles (en degrés, 0 = midi, sens horaire). */
function sectorPath(startAngle: number, endAngle: number): string {
  const largeArc = endAngle - startAngle > 180 ? 1 : 0;
  const outerStart = polarPoint(R_OUTER, startAngle);
  const outerEnd = polarPoint(R_OUTER, endAngle);
  const innerEnd = polarPoint(R_INNER, endAngle);
  const innerStart = polarPoint(R_INNER, startAngle);
  return [
    `M ${outerStart.x.toFixed(2)} ${outerStart.y.toFixed(2)}`,
    `A ${R_OUTER} ${R_OUTER} 0 ${largeArc} 1 ${outerEnd.x.toFixed(2)} ${outerEnd.y.toFixed(2)}`,
    `L ${innerEnd.x.toFixed(2)} ${innerEnd.y.toFixed(2)}`,
    `A ${R_INNER} ${R_INNER} 0 ${largeArc} 0 ${innerStart.x.toFixed(2)} ${innerStart.y.toFixed(2)}`,
    'Z',
  ].join(' ');
}

/** Anneau complet (cas d'une seule tâche), via fill-rule evenodd. */
function fullRingPath(): string {
  const top = CENTER - R_OUTER;
  const bottom = CENTER + R_OUTER;
  const innerTop = CENTER - R_INNER;
  const innerBottom = CENTER + R_INNER;
  return [
    `M ${CENTER} ${top}`,
    `A ${R_OUTER} ${R_OUTER} 0 1 1 ${CENTER} ${bottom}`,
    `A ${R_OUTER} ${R_OUTER} 0 1 1 ${CENTER} ${top}`,
    `M ${CENTER} ${innerTop}`,
    `A ${R_INNER} ${R_INNER} 0 1 0 ${CENTER} ${innerBottom}`,
    `A ${R_INNER} ${R_INNER} 0 1 0 ${CENTER} ${innerTop}`,
    'Z',
  ].join(' ');
}

type CadenceKind = 'none' | 'day' | 'week' | 'month';

export function CycleWheel({
  tasks,
  saving = false,
  onToggle,
  onReset,
  onCreate,
  onSelect,
}: Props) {
  const sorted = useMemo(() => sortCycleTasks(tasks), [tasks]);
  const doneCount = sorted.filter((task) => task.done).length;
  const total = sorted.length;

  const [confirmingReset, setConfirmingReset] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const [cadenceKind, setCadenceKind] = useState<CadenceKind>('none');
  const [weekDay, setWeekDay] = useState(0);
  const [monthDay, setMonthDay] = useState(1);

  const maxChars = total <= 4 ? 18 : total <= 8 ? 12 : 9;

  const handleSectorKey = (event: KeyboardEvent<SVGGElement>, task: SuccesTask) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      if (!saving) void onToggle(task);
    }
  };

  const submitCreate = async () => {
    const title = newTitle.trim();
    if (!title || saving) return;
    let cadence: SuccesCadence | undefined;
    if (cadenceKind === 'day') cadence = { every: 'day' };
    else if (cadenceKind === 'week') cadence = { every: 'week', day: weekDay };
    else if (cadenceKind === 'month') cadence = { every: 'month', day: monthDay };
    await onCreate({ title, cadence });
    setNewTitle('');
  };

  const confirmReset = async () => {
    if (saving) return;
    await onReset();
    setConfirmingReset(false);
  };

  const fieldStyle = {
    border: '1px solid var(--color-border)',
    color: 'var(--color-text)',
    background: 'transparent',
  } as const;

  return (
    <div className="grid gap-4">
      <section
        className="grid gap-3 rounded-2xl p-4"
        style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
      >
        {total === 0 ? (
          <div className="py-12 text-center">
            <p className="font-medium" style={{ color: 'var(--color-text)' }}>
              La roue est vide
            </p>
            <p className="text-sm mt-1" style={{ color: 'var(--color-text-tertiary)' }}>
              Ajoutez une première routine ci-dessous pour lancer le cycle.
            </p>
          </div>
        ) : (
          <svg
            viewBox={`0 0 ${VIEW} ${VIEW}`}
            width="100%"
            role="group"
            aria-label={`Roue des routines : ${doneCount} sur ${total} faites ce tour-ci`}
            style={{ maxWidth: 440, margin: '0 auto', display: 'block' }}
          >
            {sorted.map((task, index) => {
              const step = 360 / total;
              const pad = total > 1 ? Math.min(4, step * 0.08) : 0;
              const start = step * index + pad / 2;
              const end = step * (index + 1) - pad / 2;
              const mid = (start + end) / 2;
              const labelPoint = polarPoint(R_LABEL, mid);
              const label = cadenceLabel(task.cadence);
              const path = total === 1 ? fullRingPath() : sectorPath(start, end);
              const titleColor = task.done ? '#fff' : 'var(--color-text)';
              const cadenceColor = task.done ? '#fff' : 'var(--color-text-tertiary)';
              return (
                <g
                  key={task.id}
                  role="button"
                  tabIndex={0}
                  aria-label={`${task.title}${label ? `, ${label}` : ''} — ${
                    task.done ? 'faite, cliquer pour rouvrir' : 'à faire, cliquer pour cocher'
                  }`}
                  onClick={() => {
                    if (!saving) void onToggle(task);
                  }}
                  onKeyDown={(event) => handleSectorKey(event, task)}
                  style={{ cursor: saving ? 'wait' : 'pointer' }}
                >
                  <path
                    d={path}
                    fillRule="evenodd"
                    fill={task.done ? 'var(--color-accent)' : 'var(--color-surface)'}
                    fillOpacity={task.done ? 0.85 : 1}
                    stroke={task.done ? 'var(--color-accent)' : 'var(--color-border)'}
                    strokeWidth={1.5}
                  />
                  <text
                    x={labelPoint.x}
                    y={label ? labelPoint.y - 3 : labelPoint.y + 3}
                    textAnchor="middle"
                    fontSize={11}
                    fontWeight={600}
                    fill={titleColor}
                    style={{ pointerEvents: 'none', userSelect: 'none' }}
                  >
                    {shorten(task.title, maxChars)}
                  </text>
                  {label ? (
                    <text
                      x={labelPoint.x}
                      y={labelPoint.y + 10}
                      textAnchor="middle"
                      fontSize={8.5}
                      fill={cadenceColor}
                      fillOpacity={task.done ? 0.9 : 1}
                      style={{ pointerEvents: 'none', userSelect: 'none' }}
                    >
                      {label}
                    </text>
                  ) : null}
                </g>
              );
            })}
            <circle
              cx={CENTER}
              cy={CENTER}
              r={R_HUB}
              fill="var(--color-surface)"
              stroke="var(--color-border)"
              strokeWidth={1.5}
            />
            <text
              x={CENTER}
              y={CENTER - 2}
              textAnchor="middle"
              fontSize={26}
              fontWeight={700}
              fill="var(--color-text)"
              style={{ userSelect: 'none' }}
            >
              {doneCount} / {total}
            </text>
            <text
              x={CENTER}
              y={CENTER + 20}
              textAnchor="middle"
              fontSize={11}
              fill="var(--color-text-tertiary)"
              style={{ userSelect: 'none' }}
            >
              ce tour-ci
            </text>
          </svg>
        )}

        {onSelect && total > 0 ? (
          <ul className="grid gap-1" aria-label="Routines du cycle">
            {sorted.map((task) => {
              const label = cadenceLabel(task.cadence);
              return (
                <li key={task.id}>
                  <button
                    type="button"
                    onClick={() => onSelect(task)}
                    className="w-full flex items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm cursor-pointer"
                    style={{ color: 'var(--color-text)' }}
                  >
                    <span
                      aria-hidden="true"
                      className="size-2.5 rounded-full shrink-0"
                      style={{
                        background: task.done ? 'var(--color-accent)' : 'transparent',
                        border: task.done
                          ? '1px solid var(--color-accent)'
                          : '1px solid var(--color-border)',
                      }}
                    />
                    <span
                      className="truncate"
                      style={{ textDecoration: task.done ? 'line-through' : undefined }}
                    >
                      {task.title}
                    </span>
                    {label ? (
                      <span
                        className="ml-auto shrink-0 text-xs"
                        style={{ color: 'var(--color-text-tertiary)' }}
                      >
                        {label}
                      </span>
                    ) : null}
                  </button>
                </li>
              );
            })}
          </ul>
        ) : null}

        <div className="flex justify-center">
          {confirmingReset ? (
            <div className="flex flex-wrap items-center justify-center gap-2 text-sm">
              <span style={{ color: 'var(--color-text-secondary)' }}>
                Décoche tout — recommencer ?
              </span>
              <button
                type="button"
                disabled={saving}
                onClick={() => void confirmReset()}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium disabled:opacity-50 cursor-pointer"
                style={{ background: 'var(--color-accent)', color: '#fff' }}
              >
                {saving ? <Loader2 size={13} className="animate-spin" /> : null}
                Oui
              </button>
              <button
                type="button"
                disabled={saving}
                onClick={() => setConfirmingReset(false)}
                className="px-3 py-1.5 rounded-lg text-sm disabled:opacity-50 cursor-pointer"
                style={{
                  border: '1px solid var(--color-border)',
                  color: 'var(--color-text-secondary)',
                }}
              >
                Non
              </button>
            </div>
          ) : (
            <button
              type="button"
              disabled={saving || total === 0}
              onClick={() => setConfirmingReset(true)}
              className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm font-medium disabled:opacity-50 cursor-pointer"
              style={{
                border: '1px solid var(--color-border)',
                color: 'var(--color-text)',
              }}
            >
              <RotateCcw size={15} />
              Nouveau tour
            </button>
          )}
        </div>
      </section>

      <section
        className="grid gap-2 rounded-2xl p-4"
        style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
      >
        <p
          className="text-xs font-medium uppercase tracking-wide"
          style={{ color: 'var(--color-text-tertiary)' }}
        >
          Nouvelle routine
        </p>
        <input
          value={newTitle}
          onChange={(event) => setNewTitle(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') void submitCreate();
          }}
          placeholder="Titre de la routine…"
          maxLength={200}
          className="rounded-xl px-3 py-2.5 text-sm bg-transparent outline-none"
          style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
        />
        <div className="flex flex-wrap items-center gap-2">
          <label
            className="text-xs"
            style={{ color: 'var(--color-text-secondary)' }}
            htmlFor="cycle-cadence-kind"
          >
            Cadence
          </label>
          <select
            id="cycle-cadence-kind"
            value={cadenceKind}
            onChange={(event) => setCadenceKind(event.target.value as CadenceKind)}
            className="rounded-xl px-2 py-2 text-sm outline-none cursor-pointer"
            style={fieldStyle}
          >
            <option value="none">Aucune</option>
            <option value="day">Chaque jour</option>
            <option value="week">Chaque semaine</option>
            <option value="month">Chaque mois</option>
          </select>
          {cadenceKind === 'week' ? (
            <select
              aria-label="Jour de la semaine"
              value={weekDay}
              onChange={(event) => setWeekDay(Number(event.target.value))}
              className="rounded-xl px-2 py-2 text-sm outline-none cursor-pointer"
              style={fieldStyle}
            >
              {WEEKDAY_LABELS.map((label, index) => (
                <option key={label} value={index}>
                  {label.charAt(0).toUpperCase() + label.slice(1)}
                </option>
              ))}
            </select>
          ) : null}
          {cadenceKind === 'month' ? (
            <select
              aria-label="Jour du mois"
              value={monthDay}
              onChange={(event) => setMonthDay(Number(event.target.value))}
              className="rounded-xl px-2 py-2 text-sm outline-none cursor-pointer"
              style={fieldStyle}
            >
              {MONTH_DAYS.map((day) => (
                <option key={day} value={day}>
                  {day === 1 ? 'Le 1er' : `Le ${day}`}
                </option>
              ))}
            </select>
          ) : null}
        </div>
        <div className="flex justify-end">
          <button
            type="button"
            disabled={!newTitle.trim() || saving}
            onClick={() => void submitCreate()}
            className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm font-medium disabled:opacity-50 cursor-pointer"
            style={{ background: 'var(--color-accent)', color: '#fff' }}
          >
            {saving ? <Loader2 size={15} className="animate-spin" /> : <CirclePlus size={15} />}
            Ajouter
          </button>
        </div>
      </section>
    </div>
  );
}
