import { useMemo, useState, type Dispatch, type SetStateAction } from 'react';
import {
  Check,
  ChevronDown,
  ChevronRight,
  CirclePlus,
  Loader2,
  Lock,
  Plus,
  Trash2,
} from 'lucide-react';

import type { SuccesTask } from './types';
import type { Verrous } from './verrou';

export type ProjectTreeNode = SuccesTask & { children: ProjectTreeNode[] };

export function buildProjectTaskTree(tasks: SuccesTask[]): ProjectTreeNode[] {
  const byId = new Map<string, ProjectTreeNode>();
  for (const task of tasks) {
    byId.set(task.id, { ...task, parentTaskId: task.parentTaskId || '', children: [] });
  }
  const roots: ProjectTreeNode[] = [];
  for (const node of byId.values()) {
    const parentId = node.parentTaskId;
    const parent = parentId ? byId.get(parentId) : undefined;
    if (parent) parent.children.push(node);
    else roots.push(node);
  }
  // Le rang d'abord, et RIEN d'autre. L'ancien tri rangeait par titre puis
  // poussait les tâches faites en fin de fratrie : dans une généalogie où
  // l'ordre EST l'information, la première branche d'un parcours se
  // retrouvait au milieu de l'alphabet, et cocher une station la déplaçait
  // sous les yeux. Le titre ne sert plus que de départage à rang égal, pour
  // que deux tâches créées dans la même seconde ne dansent pas d'un rendu à
  // l'autre.
  const sortNodes = (items: ProjectTreeNode[]) => {
    items.sort(
      (a, b) =>
        (a.order ?? 0) - (b.order ?? 0) || a.title.localeCompare(b.title, 'fr'),
    );
    for (const item of items) sortNodes(item.children);
  };
  sortNodes(roots);
  return roots;
}

type Props = {
  tasks: SuccesTask[];
  saving?: boolean;
  /** Les branches encore fermées, avec ce qui les débloque. Voir `verrou.ts`. */
  verrous?: Verrous;
  onCreate: (input: { title: string; notes?: string; parentTaskId?: string }) => Promise<void>;
  onToggle: (task: SuccesTask) => Promise<void>;
  onUpdate: (task: SuccesTask, patch: { title?: string; notes?: string }) => Promise<void>;
  onDelete: (task: SuccesTask) => Promise<void>;
};

export function ProjectTreeView({
  tasks,
  saving = false,
  verrous,
  onCreate,
  onToggle,
  onUpdate,
  onDelete,
}: Props) {
  const roots = useMemo(() => buildProjectTaskTree(tasks), [tasks]);
  const [rootTitle, setRootTitle] = useState('');
  const [rootNotes, setRootNotes] = useState('');
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const isExpanded = (id: string) => expanded[id] !== false;

  const addRoot = async () => {
    if (!rootTitle.trim()) return;
    await onCreate({
      title: rootTitle.trim(),
      notes: rootNotes.trim() || undefined,
    });
    setRootTitle('');
    setRootNotes('');
  };

  return (
    <div className="grid gap-4">
      <section
        className="grid gap-2 rounded-2xl p-4"
        style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
      >
        <p className="text-xs font-medium uppercase tracking-wide" style={{ color: 'var(--color-text-tertiary)' }}>
          Nouvelle branche racine
        </p>
        <input
          value={rootTitle}
          onChange={(event) => setRootTitle(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') void addRoot();
          }}
          placeholder="Titre de la branche…"
          maxLength={200}
          className="rounded-xl px-3 py-2.5 text-sm bg-transparent outline-none"
          style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
        />
        <textarea
          value={rootNotes}
          onChange={(event) => setRootNotes(event.target.value)}
          rows={2}
          maxLength={2000}
          placeholder="Petite description (optionnel)…"
          className="rounded-xl px-3 py-2 text-sm bg-transparent outline-none resize-none"
          style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
        />
        <div className="flex justify-end">
          <button
            type="button"
            disabled={!rootTitle.trim() || saving}
            onClick={() => void addRoot()}
            className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm font-medium disabled:opacity-50 cursor-pointer"
            style={{ background: 'var(--color-accent)', color: '#fff' }}
          >
            {saving ? <Loader2 size={15} className="animate-spin" /> : <CirclePlus size={15} />}
            Ajouter
          </button>
        </div>
      </section>

      {roots.length === 0 ? (
        <div
          className="rounded-2xl py-12 text-center"
          style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
        >
          <p className="font-medium" style={{ color: 'var(--color-text)' }}>
            Aucune branche pour l’instant
          </p>
          <p className="text-sm mt-1" style={{ color: 'var(--color-text-tertiary)' }}>
            Créez la première racine ci-dessus, puis ajoutez des sous-branches.
          </p>
        </div>
      ) : (
        <div className="grid gap-2">
          {roots.map((node) => (
            <TreeNodeRow
              key={node.id}
              node={node}
              depth={0}
              expanded={isExpanded(node.id)}
              saving={saving}
              verrous={verrous}
              onToggleExpand={() =>
                setExpanded((prev) => ({ ...prev, [node.id]: !isExpanded(node.id) }))
              }
              isExpanded={isExpanded}
              setExpanded={setExpanded}
              onCreate={onCreate}
              onToggle={onToggle}
              onUpdate={onUpdate}
              onDelete={onDelete}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function TreeNodeRow({
  node,
  depth,
  expanded,
  saving,
  verrous,
  onToggleExpand,
  isExpanded,
  setExpanded,
  onCreate,
  onToggle,
  onUpdate,
  onDelete,
}: {
  node: ProjectTreeNode;
  depth: number;
  expanded: boolean;
  saving: boolean;
  verrous: Verrous | undefined;
  onToggleExpand: () => void;
  isExpanded: (id: string) => boolean;
  setExpanded: Dispatch<SetStateAction<Record<string, boolean>>>;
  onCreate: Props['onCreate'];
  onToggle: Props['onToggle'];
  onUpdate: Props['onUpdate'];
  onDelete: Props['onDelete'];
}) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(node.title);
  const [notes, setNotes] = useState(node.notes || '');
  const [addingChild, setAddingChild] = useState(false);
  const [childTitle, setChildTitle] = useState('');
  const [childNotes, setChildNotes] = useState('');
  const hasChildren = node.children.length > 0;
  // Le mode « Éditer les branches » n'est PAS un contournement du verrou : le
  // magasin refuserait la coche de toute façon, et un bouton qui déclenche un
  // refus est pire qu'un bouton éteint. Le texte, lui, reste visible ici —
  // c'est l'atelier du projet, on doit pouvoir réparer ce qu'on a écrit.
  const verrouillePar = verrous?.get(node.id);

  const saveEdit = async () => {
    const nextTitle = title.trim();
    if (!nextTitle) return;
    await onUpdate(node, {
      title: nextTitle !== node.title ? nextTitle : undefined,
      notes: notes !== (node.notes || '') ? notes : undefined,
    });
    setEditing(false);
  };

  const addChild = async () => {
    if (!childTitle.trim()) return;
    await onCreate({
      title: childTitle.trim(),
      notes: childNotes.trim() || undefined,
      parentTaskId: node.id,
    });
    setChildTitle('');
    setChildNotes('');
    setAddingChild(false);
    setExpanded((prev) => ({ ...prev, [node.id]: true }));
  };

  return (
    <div className="grid gap-2" style={{ marginLeft: depth === 0 ? 0 : 16 }}>
      <div
        className="rounded-xl p-3"
        style={{
          background: 'var(--color-surface)',
          border: '1px solid var(--color-border)',
          opacity: node.done ? 0.72 : 1,
        }}
      >
        <div className="flex items-start gap-2">
          {hasChildren ? (
            <button
              type="button"
              onClick={onToggleExpand}
              className="mt-0.5 p-0.5 cursor-pointer"
              style={{ color: 'var(--color-text-tertiary)' }}
              aria-label={expanded ? 'Replier' : 'Déplier'}
            >
              {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
            </button>
          ) : (
            <span className="mt-0.5 size-4" />
          )}
          <button
            type="button"
            onClick={() => void onToggle(node)}
            disabled={saving || Boolean(verrouillePar)}
            className="mt-0.5 size-5 rounded-full border flex items-center justify-center cursor-pointer shrink-0 disabled:cursor-default"
            style={{
              borderColor: node.done ? 'var(--color-accent)' : 'var(--color-border)',
              background: node.done ? 'var(--color-accent)' : 'transparent',
              color: '#fff',
            }}
            aria-label={
              verrouillePar
                ? `Verrouillée — termine d'abord « ${verrouillePar} »`
                : node.done
                  ? 'Rouvrir'
                  : 'Terminer'
            }
            title={verrouillePar ? `Termine d'abord « ${verrouillePar} »` : undefined}
          >
            {node.done ? (
              <Check size={12} />
            ) : verrouillePar ? (
              <Lock size={10} style={{ color: 'var(--color-text-tertiary)' }} />
            ) : null}
          </button>
          <div className="flex-1 min-w-0 grid gap-1">
            {editing ? (
              <>
                <input
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                  maxLength={200}
                  className="rounded-lg px-2 py-1.5 text-sm bg-transparent outline-none"
                  style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                />
                <textarea
                  value={notes}
                  onChange={(event) => setNotes(event.target.value)}
                  rows={2}
                  maxLength={2000}
                  placeholder="Description…"
                  className="rounded-lg px-2 py-1.5 text-sm bg-transparent outline-none resize-none"
                  style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
                />
                <div className="flex gap-2 justify-end">
                  <button
                    type="button"
                    onClick={() => {
                      setTitle(node.title);
                      setNotes(node.notes || '');
                      setEditing(false);
                    }}
                    className="text-xs cursor-pointer"
                    style={{ color: 'var(--color-text-secondary)' }}
                  >
                    Annuler
                  </button>
                  <button
                    type="button"
                    disabled={!title.trim() || saving}
                    onClick={() => void saveEdit()}
                    className="text-xs font-medium cursor-pointer disabled:opacity-50"
                    style={{ color: 'var(--color-accent)' }}
                  >
                    Enregistrer
                  </button>
                </div>
              </>
            ) : (
              <>
                <button
                  type="button"
                  onClick={() => setEditing(true)}
                  className="text-left text-sm font-medium cursor-pointer"
                  style={{
                    color: 'var(--color-text)',
                    textDecoration: node.done ? 'line-through' : undefined,
                  }}
                >
                  {node.title}
                </button>
                {node.notes ? (
                  <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                    {node.notes}
                  </p>
                ) : (
                  <button
                    type="button"
                    onClick={() => setEditing(true)}
                    className="text-xs text-left cursor-pointer"
                    style={{ color: 'var(--color-text-quaternary, var(--color-text-tertiary))' }}
                  >
                    Ajouter une description…
                  </button>
                )}
              </>
            )}
          </div>
          <div className="flex gap-1 shrink-0">
            <button
              type="button"
              onClick={() => setAddingChild((value) => !value)}
              className="rounded-lg p-1.5 cursor-pointer"
              style={{ color: 'var(--color-text-tertiary)', background: 'var(--color-bg-secondary)' }}
              aria-label="Ajouter une sous-branche"
              title="Ajouter une sous-branche"
            >
              <Plus size={14} />
            </button>
            <button
              type="button"
              onClick={() => void onDelete(node)}
              className="rounded-lg p-1.5 cursor-pointer"
              style={{ color: 'var(--color-text-tertiary)', background: 'var(--color-bg-secondary)' }}
              aria-label="Supprimer"
            >
              <Trash2 size={14} />
            </button>
          </div>
        </div>
        {addingChild && (
          <div className="mt-3 ml-7 grid gap-2">
            <input
              autoFocus
              value={childTitle}
              onChange={(event) => setChildTitle(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') void addChild();
              }}
              placeholder="Titre de la sous-branche…"
              maxLength={200}
              className="rounded-lg px-2 py-1.5 text-sm bg-transparent outline-none"
              style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
            />
            <textarea
              value={childNotes}
              onChange={(event) => setChildNotes(event.target.value)}
              rows={2}
              maxLength={2000}
              placeholder="Petite description (optionnel)…"
              className="rounded-lg px-2 py-1.5 text-sm bg-transparent outline-none resize-none"
              style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
            />
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setAddingChild(false)}
                className="text-xs cursor-pointer"
                style={{ color: 'var(--color-text-secondary)' }}
              >
                Annuler
              </button>
              <button
                type="button"
                disabled={!childTitle.trim() || saving}
                onClick={() => void addChild()}
                className="text-xs font-medium cursor-pointer disabled:opacity-50"
                style={{ color: 'var(--color-accent)' }}
              >
                Ajouter la branche
              </button>
            </div>
          </div>
        )}
      </div>
      {expanded &&
        node.children.map((child) => (
          <TreeNodeRow
            key={child.id}
            node={child}
            depth={depth + 1}
            expanded={isExpanded(child.id)}
            saving={saving}
            verrous={verrous}
            onToggleExpand={() =>
              setExpanded((prev) => ({ ...prev, [child.id]: !isExpanded(child.id) }))
            }
            isExpanded={isExpanded}
            setExpanded={setExpanded}
            onCreate={onCreate}
            onToggle={onToggle}
            onUpdate={onUpdate}
            onDelete={onDelete}
          />
        ))}
    </div>
  );
}
