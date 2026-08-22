import { useMemo, useState, type DragEvent } from 'react';
import { ArrowLeft, ArrowRight, Check, Loader2, Plus } from 'lucide-react';

import type { SuccesTask } from './types';

type Props = {
  tasks: SuccesTask[];
  stages: string[];
  saving?: boolean;
  onMove: (task: SuccesTask, stage: string) => Promise<void>;
  onCreate: (input: { title: string; stage?: string }) => Promise<void>;
  onSelect?: (task: SuccesTask) => void;
};

export function PipelineBoard({
  tasks,
  stages,
  saving = false,
  onMove,
  onCreate,
  onSelect,
}: Props) {
  const [draggedId, setDraggedId] = useState<string | null>(null);
  const [dragOverStage, setDragOverStage] = useState<string | null>(null);

  const lastStage = stages.length > 0 ? stages[stages.length - 1] : '';

  const tasksByStage = useMemo(() => {
    const map = new Map<string, SuccesTask[]>();
    for (const stage of stages) map.set(stage, []);
    for (const task of tasks) {
      const bucket = map.has(task.stage) ? map.get(task.stage) : map.get(stages[0] ?? '');
      bucket?.push(task);
    }
    return map;
  }, [tasks, stages]);

  const total = tasks.length;
  const doneCount = tasksByStage.get(lastStage)?.length ?? 0;
  const pct = total > 0 ? Math.round((doneCount / total) * 100) : 0;

  /** L'étape où la carte est RÉELLEMENT affichée, pas celle qu'elle prétend. */
  const displayedStage = (task: SuccesTask) =>
    stages.includes(task.stage) ? task.stage : (stages[0] ?? '');

  const moveTask = (task: SuccesTask, stage: string) => {
    // Comparer à l'étape affichée, pas à l'étape stockée : une carte dont
    // l'étape est inconnue est montrée en première colonne, et l'y déposer
    // semblait un déplacement — ce qui, sur une tâche terminée, la décochait
    // en silence. Déposer une carte là où elle est déjà ne fait rien.
    if (displayedStage(task) === stage) return;
    void onMove(task, stage);
  };

  const handleDrop = (event: DragEvent<HTMLElement>, stage: string) => {
    event.preventDefault();
    setDragOverStage(null);
    const id = event.dataTransfer.getData('text/plain') || draggedId;
    setDraggedId(null);
    if (!id) return;
    const task = tasks.find((item) => item.id === id);
    if (task) moveTask(task, stage);
  };

  if (stages.length === 0) {
    return (
      <div
        className="rounded-2xl py-12 text-center"
        style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
      >
        <p className="font-medium" style={{ color: 'var(--color-text)' }}>
          Aucune étape configurée
        </p>
        <p className="text-sm mt-1" style={{ color: 'var(--color-text-tertiary)' }}>
          Définissez les étapes du pipeline dans les réglages du projet.
        </p>
      </div>
    );
  }

  return (
    <div className="grid gap-4">
      <div className="flex gap-3 overflow-x-auto pb-2 items-start">
        {stages.map((stage, stageIndex) => {
          const columnTasks = tasksByStage.get(stage) ?? [];
          const isDropTarget = dragOverStage === stage;
          return (
            <section
              key={`${stage}-${stageIndex}`}
              className="w-64 shrink-0 rounded-2xl flex flex-col"
              style={{
                border: `1px solid ${isDropTarget ? 'var(--color-accent)' : 'var(--color-border)'}`,
              }}
              onDragOver={(event) => {
                event.preventDefault();
                event.dataTransfer.dropEffect = 'move';
                if (dragOverStage !== stage) setDragOverStage(stage);
              }}
              onDragLeave={(event) => {
                if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
                  setDragOverStage((prev) => (prev === stage ? null : prev));
                }
              }}
              onDrop={(event) => handleDrop(event, stage)}
              aria-label={`Étape ${stage}`}
            >
              <header className="flex items-center justify-between gap-2 px-3 pt-3 pb-2">
                <h3
                  className="text-sm font-medium truncate"
                  style={{ color: 'var(--color-text)' }}
                  title={stage}
                >
                  {stage}
                </h3>
                <span
                  className="text-xs tabular-nums shrink-0"
                  style={{ color: 'var(--color-text-tertiary)' }}
                >
                  {columnTasks.length}
                </span>
              </header>
              <div className="grid gap-2 px-3 flex-1 content-start min-h-10">
                {columnTasks.length === 0 ? (
                  <p
                    className="text-xs italic py-2 text-center"
                    style={{ color: 'var(--color-text-tertiary)' }}
                  >
                    Aucune carte
                  </p>
                ) : (
                  columnTasks.map((task) => (
                    <PipelineCard
                      key={task.id}
                      task={task}
                      stages={stages}
                      stageIndex={stageIndex}
                      isLast={stageIndex === stages.length - 1}
                      saving={saving}
                      dragged={draggedId === task.id}
                      onDragStart={(event) => {
                        event.dataTransfer.setData('text/plain', task.id);
                        event.dataTransfer.effectAllowed = 'move';
                        setDraggedId(task.id);
                      }}
                      onDragEnd={() => {
                        setDraggedId(null);
                        setDragOverStage(null);
                      }}
                      onMoveTo={(nextStage) => moveTask(task, nextStage)}
                      onSelect={onSelect}
                    />
                  ))
                )}
              </div>
              <ColumnAddForm stage={stage} saving={saving} onCreate={onCreate} />
            </section>
          );
        })}
      </div>

      <div
        className="rounded-2xl p-4"
        style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
      >
        <div className="flex items-center justify-between gap-2 mb-2">
          <span className="text-xs font-medium" style={{ color: 'var(--color-text-secondary)' }}>
            Progression du pipeline
          </span>
          <span
            className="text-xs tabular-nums"
            style={{ color: 'var(--color-text-tertiary)' }}
          >
            {doneCount} / {total} ({pct}%)
          </span>
        </div>
        <div
          className="h-2 rounded-full overflow-hidden"
          style={{ background: 'var(--color-border)' }}
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={total}
          aria-valuenow={doneCount}
          aria-label="Cartes en dernière étape"
        >
          <div
            className="h-full rounded-full"
            style={{
              width: `${pct}%`,
              background: 'var(--color-accent)',
              transition: 'width 200ms ease',
            }}
          />
        </div>
      </div>
    </div>
  );
}

function PipelineCard({
  task,
  stages,
  stageIndex,
  isLast,
  saving,
  dragged,
  onDragStart,
  onDragEnd,
  onMoveTo,
  onSelect,
}: {
  task: SuccesTask;
  stages: string[];
  stageIndex: number;
  isLast: boolean;
  saving: boolean;
  dragged: boolean;
  onDragStart: (event: DragEvent<HTMLElement>) => void;
  onDragEnd: () => void;
  onMoveTo: (stage: string) => void;
  onSelect?: (task: SuccesTask) => void;
}) {
  const prevStage = stageIndex > 0 ? stages[stageIndex - 1] : null;
  const nextStage = stageIndex < stages.length - 1 ? stages[stageIndex + 1] : null;
  const showPriorityDot = task.priority === 'high' || task.priority === 'urgent';

  return (
    <article
      draggable
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      className="rounded-xl p-2.5 grid gap-1.5 cursor-grab"
      style={{
        background: 'var(--color-surface)',
        border: '1px solid var(--color-border)',
        opacity: dragged ? 0.4 : isLast ? 0.65 : 1,
      }}
    >
      <div className="flex items-start gap-1.5">
        {showPriorityDot && (
          <span
            className="mt-1.5 size-2 rounded-full shrink-0"
            style={{
              background: 'var(--color-accent)',
              opacity: task.priority === 'urgent' ? 1 : 0.55,
            }}
            title={task.priority === 'urgent' ? 'Priorité urgente' : 'Priorité haute'}
            aria-label={task.priority === 'urgent' ? 'Priorité urgente' : 'Priorité haute'}
            role="img"
          />
        )}
        <button
          type="button"
          onClick={() => onSelect?.(task)}
          className="flex-1 min-w-0 text-left text-sm font-medium cursor-pointer"
          style={{
            color: 'var(--color-text)',
            textDecoration: isLast ? 'line-through' : undefined,
          }}
        >
          {task.title}
        </button>
        {isLast && (
          <span
            className="mt-0.5 shrink-0"
            style={{ color: 'var(--color-accent)' }}
            aria-label="Terminé"
            role="img"
          >
            <Check size={14} />
          </span>
        )}
      </div>
      {task.notes ? (
        <p className="text-xs truncate" style={{ color: 'var(--color-text-tertiary)' }}>
          {task.notes}
        </p>
      ) : null}
      <div className="flex justify-end gap-1">
        <button
          type="button"
          disabled={!prevStage || saving}
          onClick={() => {
            if (prevStage) onMoveTo(prevStage);
          }}
          className="rounded-lg p-1 cursor-pointer disabled:opacity-30 disabled:cursor-default"
          style={{ color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
          aria-label={prevStage ? `Déplacer vers « ${prevStage} »` : 'Première étape'}
          title={prevStage ? `Déplacer vers « ${prevStage} »` : undefined}
        >
          <ArrowLeft size={13} />
        </button>
        <button
          type="button"
          disabled={!nextStage || saving}
          onClick={() => {
            if (nextStage) onMoveTo(nextStage);
          }}
          className="rounded-lg p-1 cursor-pointer disabled:opacity-30 disabled:cursor-default"
          style={{ color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
          aria-label={nextStage ? `Déplacer vers « ${nextStage} »` : 'Dernière étape'}
          title={nextStage ? `Déplacer vers « ${nextStage} »` : undefined}
        >
          <ArrowRight size={13} />
        </button>
      </div>
    </article>
  );
}

function ColumnAddForm({
  stage,
  saving,
  onCreate,
}: {
  stage: string;
  saving: boolean;
  onCreate: (input: { title: string; stage?: string }) => Promise<void>;
}) {
  const [title, setTitle] = useState('');
  const [pending, setPending] = useState(false);

  const submit = async () => {
    const trimmed = title.trim();
    if (!trimmed || pending) return;
    setPending(true);
    try {
      await onCreate({ title: trimmed, stage });
      setTitle('');
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="flex items-center gap-1.5 p-3">
      <input
        value={title}
        onChange={(event) => setTitle(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter') void submit();
        }}
        placeholder="+ Ajouter une carte…"
        maxLength={200}
        className="flex-1 min-w-0 rounded-lg px-2 py-1.5 text-sm bg-transparent outline-none"
        style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
        aria-label={`Ajouter une carte dans « ${stage} »`}
      />
      <button
        type="button"
        disabled={!title.trim() || saving || pending}
        onClick={() => void submit()}
        className="rounded-lg p-1.5 cursor-pointer disabled:opacity-40 shrink-0"
        style={{ background: 'var(--color-accent)', color: '#fff' }}
        aria-label={`Ajouter la carte dans « ${stage} »`}
      >
        {pending ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
      </button>
    </div>
  );
}
