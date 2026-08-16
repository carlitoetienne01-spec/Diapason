import { useCallback, useEffect, useState } from 'react';
import {
  CalendarClock,
  CirclePlus,
  Loader2,
  Pause,
  Pencil,
  Play,
  Sparkles,
  Trash2,
  X,
} from 'lucide-react';
import { toast } from 'sonner';

import {
  createSuccesTemplate,
  deleteSuccesTemplate,
  listSuccesProjects,
  listSuccesTemplates,
  materializeSuccesTemplates,
  updateSuccesTemplate,
} from './api';
import type {
  SuccesPriority,
  SuccesProject,
  SuccesTemplate,
  SuccesTemplateFrequency,
  SuccesTemplateKind,
} from './types';
import { useConfirm } from '../../components/ConfirmDialog';

const DAYS = ['D', 'L', 'M', 'M', 'J', 'V', 'S'];
const DAY_LABELS = ['Dim', 'Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam'];

function localIsoDate(value = new Date()) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, '0');
  const day = String(value.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function addDays(iso: string, count: number) {
  const [year, month, day] = iso.split('-').map(Number);
  const value = new Date(year, month - 1, day);
  value.setDate(value.getDate() + count);
  return localIsoDate(value);
}

function addMonths(iso: string, count: number) {
  const [year, month, day] = iso.split('-').map(Number);
  const value = new Date(year, month - 1, day);
  value.setMonth(value.getMonth() + count);
  return localIsoDate(value);
}

function startOfWeekMonday(iso: string) {
  const [year, month, day] = iso.split('-').map(Number);
  const value = new Date(year, month - 1, day);
  const mondayBased = (value.getDay() + 6) % 7;
  value.setDate(value.getDate() - mondayBased);
  return localIsoDate(value);
}

function endOfMonth(iso: string) {
  const [year, month] = iso.split('-').map(Number);
  return localIsoDate(new Date(year, month, 0));
}

type Draft = {
  title: string;
  emoji: string;
  frequency: SuccesTemplateFrequency;
  priority: SuccesPriority;
  weeklyDays: number[];
  monthSlots: Array<number | 'last'>;
  monthDow: number;
  projectId: string;
  startDate: string;
  endDate: string;
};

function emptyDraft(_kind: SuccesTemplateKind): Draft {
  const today = localIsoDate();
  return {
    title: '',
    emoji: '',
    frequency: 'weekly',
    priority: 'medium',
    weeklyDays: [1],
    monthSlots: [1],
    monthDow: 1,
    projectId: '',
    startDate: today,
    endDate: addMonths(today, 3),
  };
}

function draftFromTemplate(item: SuccesTemplate): Draft {
  return {
    title: item.title,
    emoji: item.emoji || '',
    frequency: item.frequency,
    priority: item.priority,
    weeklyDays: item.weeklyDays?.length ? item.weeklyDays : item.daysOfWeek?.length ? item.daysOfWeek : [1],
    monthSlots: item.monthWeekSlots?.length ? item.monthWeekSlots : [1],
    monthDow: item.monthWeekDow ?? 1,
    projectId: item.projectId || '',
    startDate: item.startDate,
    endDate: item.endDate,
  };
}

function frequencyLabel(item: SuccesTemplate) {
  if (item.frequency === 'daily') return 'Tous les jours';
  if (item.frequency === 'weekly') {
    const days = (item.weeklyDays?.length ? item.weeklyDays : item.daysOfWeek || [])
      .map((day) => DAY_LABELS[day] || '?')
      .join(', ');
    return days ? `Chaque semaine (${days})` : 'Chaque semaine';
  }
  const slots = (item.monthWeekSlots || [])
    .map((slot) => (slot === 'last' ? 'dernier' : `${slot}e`))
    .join(', ');
  const dow = DAY_LABELS[item.monthWeekDow] || '?';
  return `Chaque mois (${slots || '?'} ${dow})`;
}

export function RecurrencesPanel({
  kind,
  embedded = false,
}: {
  kind: SuccesTemplateKind;
  embedded?: boolean;
}) {
  const confirm = useConfirm();
  const today = localIsoDate();
  const [templates, setTemplates] = useState<SuccesTemplate[]>([]);
  const [projects, setProjects] = useState<SuccesProject[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState(() => emptyDraft(kind));
  const [showMaterialize, setShowMaterialize] = useState(false);
  const [materializeFrom, setMaterializeFrom] = useState(today);
  const [materializeTo, setMaterializeTo] = useState(addDays(today, 13));

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [nextTemplates, nextProjects] = await Promise.all([
        listSuccesTemplates(),
        listSuccesProjects(),
      ]);
      setTemplates(nextTemplates.filter((item) => item.templateKind === kind));
      setProjects(nextProjects);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      toast.error('Les récurrences ne peuvent pas être chargées.', { description: message });
    } finally {
      setLoading(false);
    }
  }, [kind]);

  useEffect(() => {
    void load();
  }, [load]);

  const closeEditorNow = () => {
    setShowCreate(false);
    setEditingId(null);
    setDraft(emptyDraft(kind));
  };

  const closeEditor = async () => {
    const blank = emptyDraft(kind);
    const dirty =
      Boolean(draft.title.trim()) ||
      draft.emoji !== blank.emoji ||
      draft.priority !== blank.priority ||
      draft.projectId !== blank.projectId ||
      draft.frequency !== blank.frequency ||
      draft.startDate !== blank.startDate ||
      draft.endDate !== blank.endDate ||
      JSON.stringify(draft.weeklyDays) !== JSON.stringify(blank.weeklyDays) ||
      editingId !== null;
    if (dirty) {
      const confirmed = await confirm({
        title: editingId ? 'Annuler les modifications ?' : 'Annuler la création ?',
        description: 'Les changements non enregistrés seront perdus.',
        confirmLabel: 'Annuler',
        keepLabel: 'Garder',
        tone: 'warning',
      });
      if (!confirmed) return;
    }
    closeEditorNow();
  };

  const openCreate = () => {
    setEditingId(null);
    setDraft(emptyDraft(kind));
    setShowCreate(true);
  };

  const openEdit = (item: SuccesTemplate) => {
    setShowCreate(false);
    setEditingId(item.id);
    setDraft(draftFromTemplate(item));
  };

  const validateDraft = () => {
    if (!draft.title.trim()) {
      toast.warning('Indiquez un titre.');
      return false;
    }
    if (!draft.startDate || !draft.endDate) {
      toast.warning('Indiquez une période de début et de fin.');
      return false;
    }
    if (draft.endDate < draft.startDate) {
      toast.warning('La date de fin doit suivre la date de début.');
      return false;
    }
    if (draft.frequency === 'weekly' && !draft.weeklyDays.length) {
      toast.warning('Choisissez au moins un jour de la semaine.');
      return false;
    }
    if (draft.frequency === 'monthly' && !draft.monthSlots.length) {
      toast.warning('Choisissez au moins une occurrence mensuelle.');
      return false;
    }
    return true;
  };

  const payloadFromDraft = () => ({
    title: draft.title.trim(),
    emoji: draft.emoji,
    frequency: draft.frequency,
    templateKind: kind,
    priority: draft.priority,
    projectId: draft.projectId,
    weeklyDays: draft.frequency === 'weekly' ? draft.weeklyDays : [],
    monthWeekSlots: draft.frequency === 'monthly' ? draft.monthSlots : [],
    monthWeekDow: draft.monthDow,
    startDate: draft.startDate,
    endDate: draft.endDate,
  });

  const save = async () => {
    if (!validateDraft()) return;
    setSaving(true);
    try {
      if (editingId) {
        await updateSuccesTemplate(editingId, payloadFromDraft());
        toast.success('Récurrence mise à jour');
      } else {
        await createSuccesTemplate(payloadFromDraft());
        toast.success(`Récurrence créée : ${draft.title.trim()}`);
      }
      closeEditorNow();
      await load();
    } catch (error) {
      toast.error("La récurrence n'a pas été enregistrée.", {
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setSaving(false);
    }
  };

  const toggleActive = async (item: SuccesTemplate) => {
    setSaving(true);
    try {
      await updateSuccesTemplate(item.id, { active: !item.active });
      toast.success(item.active ? 'Récurrence mise en pause' : 'Récurrence activée');
      await load();
    } catch (error) {
      toast.error("L'état n'a pas été modifié.", {
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setSaving(false);
    }
  };

  const removeTemplate = async (item: SuccesTemplate) => {
    const confirmed = await confirm({
      title: `Supprimer « ${item.title} » ?`,
      description: 'Toutes ses occurrences générées seront également retirées.',
      confirmLabel: 'Supprimer',
      keepLabel: 'Garder',
      tone: 'danger',
    });
    if (!confirmed) return;
    setSaving(true);
    try {
      const removed = await deleteSuccesTemplate(item.id);
      if (editingId === item.id) closeEditorNow();
      await load();
      toast.success(`Récurrence supprimée (${removed} occurrence(s))`);
    } catch (error) {
      toast.error("La récurrence n'a pas été supprimée.", {
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setSaving(false);
    }
  };

  const materialize = async () => {
    if (!materializeFrom || !materializeTo || materializeTo < materializeFrom) {
      toast.warning('Indiquez une période de matérialisation valide.');
      return;
    }
    setSaving(true);
    try {
      const count = await materializeSuccesTemplates(materializeFrom, materializeTo);
      toast.success(
        count ? `${count} occurrence(s) générée(s)` : 'Aucune nouvelle occurrence',
        {
          description: count
            ? `Du ${materializeFrom} au ${materializeTo}, sans doublon.`
            : 'Les tâches actives de cette période existaient déjà.',
        },
      );
      setShowMaterialize(false);
    } catch (error) {
      toast.error('La matérialisation a échoué.', {
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setSaving(false);
    }
  };

  const editing = editingId ? templates.find((item) => item.id === editingId) : null;
  const showForm = showCreate || Boolean(editingId);
  const isTask = kind === 'task';

  return (
    <section
      className={embedded ? 'grid gap-3 pt-3' : 'mb-6 grid gap-3'}
      style={embedded ? { borderTop: '1px solid var(--color-border)' } : undefined}
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
            Récurrences {isTask ? 'de tâches' : 'd’habitudes'}
          </h2>
          <p className="text-xs mt-0.5" style={{ color: 'var(--color-text-tertiary)' }}>
            {isTask
              ? 'Règles qui génèrent des tâches sur une période — sans doublon.'
              : 'Règles qui créent et synchronisent des habitudes récurrentes.'}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {saving && <Loader2 size={14} className="animate-spin self-center" style={{ color: 'var(--color-accent)' }} />}
          {isTask && (
            <button
              type="button"
              onClick={() => setShowMaterialize((value) => !value)}
              className="flex items-center gap-2 px-3 py-1.5 rounded-xl text-xs cursor-pointer"
              style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
            >
              <Sparkles size={14} /> Matérialiser
            </button>
          )}
          <button
            type="button"
            onClick={() => {
              if (showForm && !editingId) void closeEditor();
              else openCreate();
            }}
            className="flex items-center gap-2 px-3 py-1.5 rounded-xl text-xs font-medium cursor-pointer"
            style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent, #fff)' }}
          >
            <CirclePlus size={14} /> Nouvelle récurrence
          </button>
        </div>
      </div>

      {isTask && showMaterialize && (
        <div
          className="rounded-2xl p-4 grid gap-3"
          style={{ background: 'var(--color-surface)', border: '1px solid var(--color-accent)' }}
        >
          <div className="flex items-start justify-between gap-3">
            <div>
              <h3 className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
                Matérialiser les tâches récurrentes
              </h3>
              <p className="text-xs mt-1" style={{ color: 'var(--color-text-tertiary)' }}>
                Génère les occurrences manquantes des récurrences actives de type tâche.
              </p>
            </div>
            <button
              type="button"
              onClick={() => setShowMaterialize(false)}
              className="p-1.5 cursor-pointer"
              style={{ color: 'var(--color-text-tertiary)' }}
              aria-label="Fermer"
            >
              <X size={16} />
            </button>
          </div>
          <div className="flex flex-wrap gap-2">
            <PresetChip
              label="Aujourd’hui"
              onClick={() => {
                setMaterializeFrom(today);
                setMaterializeTo(today);
              }}
            />
            <PresetChip
              label="Cette semaine"
              onClick={() => {
                const start = startOfWeekMonday(today);
                setMaterializeFrom(start);
                setMaterializeTo(addDays(start, 6));
              }}
            />
            <PresetChip
              label="14 jours"
              onClick={() => {
                setMaterializeFrom(today);
                setMaterializeTo(addDays(today, 13));
              }}
            />
            <PresetChip
              label="Ce mois"
              onClick={() => {
                const start = `${today.slice(0, 7)}-01`;
                setMaterializeFrom(start);
                setMaterializeTo(endOfMonth(today));
              }}
            />
          </div>
          <div className="grid sm:grid-cols-[1fr_1fr_auto] gap-3 items-end">
            <label className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
              Du
              <input
                type="date"
                value={materializeFrom}
                onChange={(event) => setMaterializeFrom(event.target.value)}
                className="mt-1 w-full rounded-xl px-3 py-2 bg-transparent"
                style={{ color: 'var(--color-text)', border: '1px solid var(--color-border)' }}
              />
            </label>
            <label className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
              Au
              <input
                type="date"
                value={materializeTo}
                onChange={(event) => setMaterializeTo(event.target.value)}
                className="mt-1 w-full rounded-xl px-3 py-2 bg-transparent"
                style={{ color: 'var(--color-text)', border: '1px solid var(--color-border)' }}
              />
            </label>
            <button
              type="button"
              disabled={saving}
              onClick={() => void materialize()}
              className="h-10 px-4 rounded-xl text-sm font-medium disabled:opacity-50 cursor-pointer"
              style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent, #fff)' }}
            >
              Générer
            </button>
          </div>
        </div>
      )}

      {showForm && (
        <TemplateForm
          draft={draft}
          setDraft={setDraft}
          projects={projects}
          saving={saving}
          mode={editingId ? 'edit' : 'create'}
          titleHint={editing ? editing.title : undefined}
          showPriority={isTask}
          onCancel={() => void closeEditor()}
          onSave={() => void save()}
        />
      )}

      {loading ? (
        <div className="py-8 flex justify-center">
          <Loader2 className="animate-spin" style={{ color: 'var(--color-accent)' }} />
        </div>
      ) : (
        <div className="grid gap-2">
          {!templates.length && (
            <div
              className="rounded-2xl py-10 text-center"
              style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
            >
              <CalendarClock className="mx-auto mb-2" size={22} style={{ color: 'var(--color-accent)' }} />
              <p className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
                Aucune récurrence
              </p>
              <p className="text-xs mt-1" style={{ color: 'var(--color-text-tertiary)' }}>
                Créez votre première règle ci-dessus.
              </p>
            </div>
          )}
          {templates.map((item) =>
            editingId === item.id ? null : (
              <article
                key={item.id}
                className="rounded-2xl p-3 flex items-center gap-3"
                style={{
                  background: 'var(--color-surface)',
                  border: '1px solid var(--color-border)',
                  opacity: item.active ? 1 : 0.62,
                }}
              >
                <div
                  className="size-10 rounded-xl flex items-center justify-center text-lg shrink-0"
                  style={{ background: 'var(--color-bg-secondary)' }}
                >
                  {item.emoji || (kind === 'habit' ? '🏃' : '✓')}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="font-medium truncate text-sm" style={{ color: 'var(--color-text)' }}>
                    {item.title}
                  </p>
                  <p className="text-xs mt-0.5 truncate" style={{ color: 'var(--color-text-tertiary)' }}>
                    {frequencyLabel(item)}
                    {item.projectId
                      ? ` · ${projects.find((project) => project.id === item.projectId)?.name || 'Projet'}`
                      : ''}
                    {' · '}
                    {item.startDate} → {item.endDate}
                    {!item.active ? ' · en pause' : ''}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => openEdit(item)}
                  aria-label="Modifier"
                  className="size-8 rounded-lg flex items-center justify-center cursor-pointer"
                  style={{ color: 'var(--color-text-secondary)', background: 'var(--color-bg-secondary)' }}
                >
                  <Pencil size={14} />
                </button>
                <button
                  type="button"
                  onClick={() => void toggleActive(item)}
                  aria-label={item.active ? 'Mettre en pause' : 'Activer'}
                  className="size-8 rounded-lg flex items-center justify-center cursor-pointer"
                  style={{ color: 'var(--color-text-secondary)', background: 'var(--color-bg-secondary)' }}
                >
                  {item.active ? <Pause size={14} /> : <Play size={14} />}
                </button>
                <button
                  type="button"
                  onClick={() => void removeTemplate(item)}
                  aria-label="Supprimer la récurrence"
                  className="size-8 rounded-lg flex items-center justify-center cursor-pointer"
                  style={{ color: 'var(--color-error)', background: 'var(--color-bg-secondary)' }}
                >
                  <Trash2 size={14} />
                </button>
              </article>
            ),
          )}
        </div>
      )}
    </section>
  );
}

function PresetChip({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="px-3 h-8 rounded-lg text-xs cursor-pointer"
      style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
    >
      {label}
    </button>
  );
}

function TemplateForm({
  draft,
  setDraft,
  projects,
  saving,
  mode,
  titleHint,
  showPriority,
  onCancel,
  onSave,
}: {
  draft: Draft;
  setDraft: (value: Draft | ((prev: Draft) => Draft)) => void;
  projects: SuccesProject[];
  saving: boolean;
  mode: 'create' | 'edit';
  titleHint?: string;
  showPriority: boolean;
  onCancel: () => void;
  onSave: () => void;
}) {
  return (
    <div
      className="rounded-2xl p-4 grid gap-4"
      style={{ background: 'var(--color-surface)', border: '1px solid var(--color-accent)' }}
    >
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
          {mode === 'edit' ? `Modifier${titleHint ? ` — ${titleHint}` : ''}` : 'Nouvelle récurrence'}
        </h3>
        <button
          type="button"
          onClick={onCancel}
          className="p-1.5 cursor-pointer"
          style={{ color: 'var(--color-text-tertiary)' }}
          aria-label="Fermer"
        >
          <X size={16} />
        </button>
      </div>
      <div className="grid grid-cols-[70px_1fr] gap-3">
        <input
          value={draft.emoji}
          onChange={(event) => setDraft({ ...draft, emoji: event.target.value.slice(0, 4) })}
          placeholder="✨"
          className="rounded-xl px-3 py-2 bg-transparent text-center outline-none"
          style={{ color: 'var(--color-text)', border: '1px solid var(--color-border)' }}
        />
        <input
          autoFocus
          value={draft.title}
          onChange={(event) => setDraft({ ...draft, title: event.target.value })}
          placeholder="Titre de la récurrence"
          maxLength={200}
          className="rounded-xl px-3 py-2 bg-transparent outline-none"
          style={{ color: 'var(--color-text)', border: '1px solid var(--color-border)' }}
        />
      </div>
      <div className={`grid gap-3 ${showPriority ? 'sm:grid-cols-3' : 'sm:grid-cols-2'}`}>
        <select
          value={draft.frequency}
          onChange={(event) =>
            setDraft({ ...draft, frequency: event.target.value as SuccesTemplateFrequency })
          }
          className="rounded-xl px-3 py-2 bg-transparent"
          style={{ color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
        >
          <option value="daily">Tous les jours</option>
          <option value="weekly">Chaque semaine</option>
          <option value="monthly">Chaque mois</option>
        </select>
        {showPriority && (
          <select
            value={draft.priority}
            onChange={(event) => setDraft({ ...draft, priority: event.target.value as SuccesPriority })}
            className="rounded-xl px-3 py-2 bg-transparent"
            style={{ color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
          >
            <option value="low">Basse</option>
            <option value="medium">Moyenne</option>
            <option value="high">Haute</option>
            <option value="urgent">Urgente</option>
          </select>
        )}
        <select
          value={draft.projectId}
          onChange={(event) => setDraft({ ...draft, projectId: event.target.value })}
          className="rounded-xl px-3 py-2 bg-transparent"
          style={{ color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
        >
          <option value="">Sans projet</option>
          {projects.map((project) => (
            <option key={project.id} value={project.id}>
              {project.name}
            </option>
          ))}
        </select>
      </div>
      {draft.frequency === 'weekly' && (
        <div className="flex gap-2" aria-label="Jours de la semaine">
          {DAYS.map((label, day) => (
            <button
              key={`${label}-${day}`}
              type="button"
              aria-pressed={draft.weeklyDays.includes(day)}
              onClick={() =>
                setDraft({
                  ...draft,
                  weeklyDays: draft.weeklyDays.includes(day)
                    ? draft.weeklyDays.filter((item) => item !== day)
                    : [...draft.weeklyDays, day].sort(),
                })
              }
              className="size-9 rounded-full text-xs cursor-pointer"
              style={{
                color: draft.weeklyDays.includes(day) ? 'var(--color-on-accent, #fff)' : 'var(--color-text-secondary)',
                background: draft.weeklyDays.includes(day)
                  ? 'var(--color-accent)'
                  : 'var(--color-bg-secondary)',
                border: '1px solid var(--color-border)',
              }}
            >
              {label}
            </button>
          ))}
        </div>
      )}
      {draft.frequency === 'monthly' && (
        <div className="flex flex-wrap items-center gap-2">
          {([1, 2, 3, 4, 'last'] as Array<number | 'last'>).map((slot) => (
            <button
              key={String(slot)}
              type="button"
              aria-pressed={draft.monthSlots.includes(slot)}
              onClick={() =>
                setDraft({
                  ...draft,
                  monthSlots: draft.monthSlots.includes(slot)
                    ? draft.monthSlots.filter((item) => item !== slot)
                    : [...draft.monthSlots, slot],
                })
              }
              className="px-3 h-9 rounded-xl text-xs cursor-pointer"
              style={{
                color: draft.monthSlots.includes(slot) ? 'var(--color-on-accent, #fff)' : 'var(--color-text-secondary)',
                background: draft.monthSlots.includes(slot)
                  ? 'var(--color-accent)'
                  : 'var(--color-bg-secondary)',
                border: '1px solid var(--color-border)',
              }}
            >
              {slot === 'last' ? 'Dernier' : `${slot}e`}
            </button>
          ))}
          <select
            value={draft.monthDow}
            onChange={(event) => setDraft({ ...draft, monthDow: Number(event.target.value) })}
            className="h-9 rounded-xl px-3 bg-transparent text-xs"
            style={{ color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
          >
            {DAY_LABELS.map((label, day) => (
              <option key={day} value={day}>
                {label}
              </option>
            ))}
          </select>
        </div>
      )}
      <div className="grid sm:grid-cols-2 gap-3">
        <label className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
          Début
          <input
            type="date"
            value={draft.startDate}
            onChange={(event) => setDraft({ ...draft, startDate: event.target.value })}
            className="mt-1 w-full rounded-xl px-3 py-2 bg-transparent"
            style={{ color: 'var(--color-text)', border: '1px solid var(--color-border)' }}
          />
        </label>
        <label className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
          Fin
          <input
            type="date"
            value={draft.endDate}
            onChange={(event) => setDraft({ ...draft, endDate: event.target.value })}
            className="mt-1 w-full rounded-xl px-3 py-2 bg-transparent"
            style={{ color: 'var(--color-text)', border: '1px solid var(--color-border)' }}
          />
        </label>
      </div>
      <div className="flex justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="px-4 py-2 rounded-xl text-sm cursor-pointer"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          Annuler
        </button>
        <button
          type="button"
          disabled={saving}
          onClick={onSave}
          className="px-4 py-2 rounded-xl text-sm font-medium disabled:opacity-50 cursor-pointer"
          style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent, #fff)' }}
        >
          {mode === 'edit' ? 'Enregistrer' : 'Créer'}
        </button>
      </div>
    </div>
  );
}
