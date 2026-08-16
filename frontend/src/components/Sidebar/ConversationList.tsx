import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  Copy,
  MoreHorizontal,
  Pencil,
  Pin,
  PinOff,
  Trash2,
} from 'lucide-react';
import { useNavigate } from 'react-router';
import type { Conversation } from '../../types';
import { useAppStore } from '../../lib/store';
import { useConfirm } from '../ConfirmDialog';
import { useTranslation } from '../../i18n/useTranslation';

interface Props {
  searchQuery: string;
}

type Translate = ReturnType<typeof useTranslation>['t'];

// `t` is passed in rather than read from a hook: this runs per row inside the
// render, and a hook cannot be called from a plain helper.
function formatRelativeTime(timestamp: number, t: Translate): string {
  const diff = Date.now() - timestamp;
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return t('common.time.justNow');
  if (minutes < 60) return t('common.time.minutesAgo', { count: minutes });
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return t('common.time.hoursAgo', { count: hours });
  const days = Math.floor(hours / 24);
  if (days < 7) return t('common.time.daysAgo', { count: days });
  return new Date(timestamp).toLocaleDateString();
}

const DAY_MS = 86_400_000;

interface Section {
  label: string;
  items: Conversation[];
}

/** Pinned first, then the familiar date buckets — organisation the eye can scan. */
function sectionsOf(conversations: Conversation[], t: Translate): Section[] {
  const startOfToday = new Date().setHours(0, 0, 0, 0);
  const buckets: Record<string, Conversation[]> = {
    pinned: [],
    today: [],
    yesterday: [],
    week: [],
    month: [],
    older: [],
  };
  for (const conv of conversations) {
    if (conv.pinned) buckets.pinned.push(conv);
    else if (conv.updatedAt >= startOfToday) buckets.today.push(conv);
    else if (conv.updatedAt >= startOfToday - DAY_MS) buckets.yesterday.push(conv);
    else if (conv.updatedAt >= startOfToday - 7 * DAY_MS) buckets.week.push(conv);
    else if (conv.updatedAt >= startOfToday - 30 * DAY_MS) buckets.month.push(conv);
    else buckets.older.push(conv);
  }
  return [
    { label: t('sidebar.pinned'), items: buckets.pinned },
    { label: t('sidebar.today'), items: buckets.today },
    { label: t('sidebar.yesterday'), items: buckets.yesterday },
    { label: t('sidebar.previous7Days'), items: buckets.week },
    { label: t('sidebar.previous30Days'), items: buckets.month },
    { label: t('sidebar.older'), items: buckets.older },
  ].filter((s) => s.items.length > 0);
}

interface MenuState {
  convId: string;
  x: number;
  y: number;
}

export function ConversationList({ searchQuery }: Props) {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const navigate = useNavigate();
  const conversations = useAppStore((s) => s.conversations);
  const activeId = useAppStore((s) => s.activeId);
  const selectConversation = useAppStore((s) => s.selectConversation);
  const deleteConversation = useAppStore((s) => s.deleteConversation);
  const renameConversation = useAppStore((s) => s.renameConversation);
  const togglePinConversation = useAppStore((s) => s.togglePinConversation);
  const duplicateConversation = useAppStore((s) => s.duplicateConversation);

  const [menu, setMenu] = useState<MenuState | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState('');
  const menuRef = useRef<HTMLDivElement | null>(null);

  const closeMenu = () => {
    setMenu(null);
  };

  useEffect(() => {
    if (!menu) return;
    const onPointerDown = (e: MouseEvent) => {
      // A missing portal (row unmounted under an open menu) must also
      // close: the old `menuRef.current && …` guard kept the menu state
      // and both document listeners alive forever in that case.
      if (!menuRef.current || !menuRef.current.contains(e.target as Node)) {
        closeMenu();
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeMenu();
    };
    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [menu]);

  const displayTitle = (conv: Conversation) => conv.title || t('sidebar.untitled');

  const openMenuAt = (convId: string, x: number, y: number) => {
    // Keep the menu on screen when the row sits near the bottom edge.
    setMenu({ convId, x, y: Math.min(y, window.innerHeight - 190) });
  };

  const startRename = (conv: Conversation) => {
    setRenamingId(conv.id);
    // The RAW title, never the localized placeholder: committing untouched
    // would otherwise freeze « Sans titre » as a real title and disable the
    // auto-naming that fires on the first message.
    setRenameDraft(conv.title);
    closeMenu();
  };

  const commitRename = () => {
    if (renamingId) {
      const current = conversations.find((c) => c.id === renamingId);
      const next = renameDraft.trim();
      if (next && current && next !== current.title) {
        renameConversation(renamingId, next);
      }
    }
    setRenamingId(null);
  };

  const handleDuplicate = (conv: Conversation) => {
    const newTitle = t('sidebar.duplicateTitle', { title: displayTitle(conv) });
    duplicateConversation(conv.id, newTitle);
    closeMenu();
    navigate('/');
  };

  const filtered = searchQuery
    ? conversations.filter((c) =>
        displayTitle(c).toLowerCase().includes(searchQuery.toLowerCase()),
      )
    : conversations;

  if (filtered.length === 0) {
    return (
      <div className="px-3 py-8 text-center text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
        {searchQuery ? t('sidebar.noMatchingChats') : t('sidebar.noConversations')}
      </div>
    );
  }

  const menuConv = menu ? conversations.find((c) => c.id === menu.convId) : null;

  const renderRow = (conv: Conversation) => {
    const isActive = conv.id === activeId;
    const isRenaming = conv.id === renamingId;
    const menuOpenHere = menu?.convId === conv.id;
    return (
      <div
        key={conv.id}
        className="group flex items-center rounded-lg cursor-pointer transition-colors"
        style={{
          background: isActive ? 'var(--color-bg-tertiary)' : 'transparent',
        }}
        onMouseEnter={(e) => {
          if (!isActive) e.currentTarget.style.background = 'var(--color-bg-secondary)';
        }}
        onMouseLeave={(e) => {
          if (!isActive) e.currentTarget.style.background = 'transparent';
        }}
        onContextMenu={(e) => {
          e.preventDefault();
          // While a title is being edited, the menu would fight the input.
          if (!isRenaming) openMenuAt(conv.id, e.clientX, e.clientY);
        }}
      >
        {isRenaming ? (
          <input
            autoFocus
            placeholder={t('sidebar.untitled')}
            aria-label={t('sidebar.rename')}
            // Select everything on entry: the common rename is a full
            // replacement, and typing should not append to the old title.
            onFocus={(e) => e.currentTarget.select()}
            value={renameDraft}
            onChange={(e) => setRenameDraft(e.target.value)}
            onKeyDown={(e) => {
              // Composition Enter/Escape (IME, dead-key accents) belong to
              // the composer, not to the rename.
              if (e.nativeEvent.isComposing) return;
              if (e.key === 'Enter') commitRename();
              if (e.key === 'Escape') setRenamingId(null);
            }}
            onBlur={commitRename}
            className="flex-1 mx-2 my-1.5 px-2 py-1 text-sm rounded-md outline-none min-w-0"
            style={{
              background: 'var(--color-bg-secondary)',
              color: 'var(--color-text)',
              border: '1px solid var(--color-accent)',
            }}
          />
        ) : (
          <button
            onClick={() => {
              selectConversation(conv.id);
              navigate('/');
            }}
            className="flex-1 text-left px-3 py-2 min-w-0 cursor-pointer"
          >
            <div
              className="text-sm truncate"
              style={{
                color: isActive ? 'var(--color-text)' : 'var(--color-text-secondary)',
                fontWeight: isActive ? 500 : 400,
              }}
            >
              {displayTitle(conv)}
            </div>
            <div
              className="text-[11px] mt-0.5 flex items-center gap-1"
              style={{ color: 'var(--color-text-tertiary)' }}
            >
              {conv.pinned && <Pin size={10} style={{ color: 'var(--color-accent)' }} />}
              {formatRelativeTime(conv.updatedAt, t)}
            </div>
          </button>
        )}
        {!isRenaming && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              const rect = e.currentTarget.getBoundingClientRect();
              openMenuAt(conv.id, rect.right, rect.bottom + 4);
            }}
            className={`p-1.5 mr-1 rounded transition-opacity cursor-pointer ${
              menuOpenHere ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'
            }`}
            style={{ color: 'var(--color-text-tertiary)' }}
            onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--color-text)')}
            onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--color-text-tertiary)')}
            title={t('sidebar.conversationOptions')}
            aria-label={t('sidebar.conversationOptions')}
            aria-haspopup="menu"
            aria-expanded={menuOpenHere}
          >
            <MoreHorizontal size={14} />
          </button>
        )}
      </div>
    );
  };

  const menuItemClass =
    'flex items-center gap-2.5 w-full px-3 py-1.5 text-[13px] rounded-md text-left transition-colors cursor-pointer';

  return (
    <div className="flex flex-col py-1">
      {sectionsOf(filtered, t).map((section) => (
        <div key={section.label} className="mb-1">
          <div
            className="px-3 pt-2 pb-1 text-[10px] font-medium uppercase tracking-wider select-none"
            style={{ color: 'var(--color-text-tertiary)' }}
          >
            {section.label}
          </div>
          <div className="flex flex-col gap-0.5">{section.items.map(renderRow)}</div>
        </div>
      ))}

      {/* The context menu escapes the sidebar through a portal: the aside's
          backdrop-filter makes it a containing block for fixed descendants
          in WebKit, which would clip the menu to the sidebar. */}
      {menu && menuConv &&
        createPortal(
          <div
            ref={menuRef}
            role="menu"
            className="fixed z-50 py-1 px-1 rounded-xl min-w-[190px]"
            style={{
              // Right-align to the anchor, but never off the left edge.
              left: Math.max(8, menu.x - 190),
              top: menu.y,
              background: 'var(--color-bg-secondary)',
              border: '1px solid var(--color-border)',
              boxShadow: '0 8px 30px rgba(0,0,0,0.35)',
            }}
          >
            <button
              role="menuitem"
              className={menuItemClass}
              style={{ color: 'var(--color-text)' }}
              onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-bg-tertiary)')}
              onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
              onClick={() => startRename(menuConv)}
            >
              <Pencil size={14} style={{ color: 'var(--color-text-secondary)' }} />
              {t('sidebar.rename')}
            </button>
            <button
              role="menuitem"
              className={menuItemClass}
              style={{ color: 'var(--color-text)' }}
              onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-bg-tertiary)')}
              onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
              onClick={() => {
                togglePinConversation(menuConv.id);
                closeMenu();
              }}
            >
              {menuConv.pinned ? (
                <PinOff size={14} style={{ color: 'var(--color-text-secondary)' }} />
              ) : (
                <Pin size={14} style={{ color: 'var(--color-text-secondary)' }} />
              )}
              {menuConv.pinned ? t('sidebar.unpin') : t('sidebar.pin')}
            </button>
            <button
              role="menuitem"
              className={menuItemClass}
              style={{ color: 'var(--color-text)' }}
              onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-bg-tertiary)')}
              onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
              onClick={() => handleDuplicate(menuConv)}
            >
              <Copy size={14} style={{ color: 'var(--color-text-secondary)' }} />
              {t('sidebar.duplicate')}
            </button>
            <div className="my-1 mx-2" style={{ borderTop: '1px solid var(--color-border)' }} />
            <button
              role="menuitem"
              className={menuItemClass}
              style={{ color: 'var(--color-error)' }}
              onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-bg-tertiary)')}
              onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
              onClick={() => {
                void (async () => {
                  const confirmed = await confirm({
                    title: t('sidebar.deleteConversation'),
                    description: t('sidebar.confirmDelete'),
                    confirmLabel: t('common.delete'),
                    keepLabel: 'Garder',
                    tone: 'danger',
                  });
                  if (!confirmed) return;
                  deleteConversation(menuConv.id);
                  closeMenu();
                })();
              }}
            >
              <Trash2 size={14} />
              {t('sidebar.deleteConversation')}
            </button>
          </div>,
          document.body,
        )}
    </div>
  );
}
