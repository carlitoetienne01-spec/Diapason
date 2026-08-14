import { useState } from 'react';
import { useNavigate, useLocation } from 'react-router';
import {
  MessageSquare,
  Plus,
  BarChart3,
  Settings,
  Search,
  PanelLeftClose,
  PanelLeft,
  Cpu,
  Rocket,
  Bot,
  Sun,
  Moon,
  Monitor,
  Loader2,
  ScrollText,
  Database,
  CalendarRange,
  ListTodo,
} from 'lucide-react';
import { ConversationList } from './ConversationList';
import { useAppStore } from '../../lib/store';
import { useTranslation } from '../../i18n/useTranslation';

export function Sidebar() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const [searchQuery, setSearchQuery] = useState('');
  // ChatGPT-style: a magnifier in the header, the input appears on demand.
  const [searchOpen, setSearchOpen] = useState(false);

  const sidebarOpen = useAppStore((s) => s.sidebarOpen);
  const toggleSidebar = useAppStore((s) => s.toggleSidebar);
  const createConversation = useAppStore((s) => s.createConversation);
  const selectedModel = useAppStore((s) => s.selectedModel);
  const serverInfo = useAppStore((s) => s.serverInfo);
  const setCommandPaletteOpen = useAppStore((s) => s.setCommandPaletteOpen);
  const modelLoading = useAppStore((s) => s.modelLoading);
  const deepResearch = useAppStore((s) => s.deepResearch);

  const settings = useAppStore((s) => s.settings);
  const updateSettings = useAppStore((s) => s.updateSettings);

  const ThemeIcon = settings.theme === 'light' ? Sun : settings.theme === 'dark' ? Moon : Monitor;
  const nextTheme = settings.theme === 'light' ? 'dark' : settings.theme === 'dark' ? 'system' : 'light';
  const themeName = (theme: string) =>
    theme === 'light'
      ? t('settings.theme.light')
      : theme === 'dark'
        ? t('settings.theme.dark')
        : t('settings.theme.system');

  const conversations = useAppStore((s) => s.conversations);
  const selectConversation = useAppStore((s) => s.selectConversation);
  const handleNewChat = () => {
    // The button always lands on a fresh chat. Reusing an existing empty
    // conversation (instead of silently doing nothing, the old behavior)
    // keeps the list free of stacked blanks while never ignoring a click.
    // Only a TRULY blank one though: an empty conversation the user has
    // renamed or pinned is prepared work, not a blank to hijack.
    const blank = conversations.find(
      (c) => c.messages.length === 0 && !c.title && !c.pinned,
    );
    if (blank) {
      selectConversation(blank.id);
    } else {
      createConversation(selectedModel);
    }
    navigate('/');
  };

  const navItems = [
    { path: '/', icon: MessageSquare, label: t('nav.chat') },
    { path: '/succes/planner', icon: CalendarRange, label: t('nav.succesPlanner') },
    { path: '/succes/tasks', icon: ListTodo, label: t('nav.succesTasks') },
    { path: '/dashboard', icon: BarChart3, label: t('nav.dashboard') },
    { path: '/data-sources', icon: Database, label: t('nav.dataSources') },
    { path: '/agents', icon: Bot, label: t('nav.agents') },
    { path: '/logs', icon: ScrollText, label: t('nav.logs') },
    { path: '/settings', icon: Settings, label: t('nav.settings') },
    { path: '/get-started', icon: Rocket, label: t('nav.getStarted') },
  ];

  return (
    <>
      {/* Collapse button when sidebar is closed */}
      {!sidebarOpen && (
        <button
          onClick={toggleSidebar}
          className="fixed top-3 left-3 z-30 p-2 rounded-lg transition-colors cursor-pointer"
          style={{ color: 'var(--color-text-secondary)', background: 'var(--color-bg-secondary)' }}
          onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-bg-tertiary)')}
          onMouseLeave={(e) => (e.currentTarget.style.background = 'var(--color-bg-secondary)')}
          title={t('sidebar.expand')}
          aria-label={t('sidebar.expand')}
        >
          <PanelLeft size={18} />
        </button>
      )}

      <aside
        className={`
          flex flex-col h-full shrink-0 transition-all duration-200 ease-in-out overflow-hidden
          fixed md:relative z-30
          ${sidebarOpen ? 'w-[260px]' : 'w-0'}
        `}
        style={{
          background: 'var(--color-sidebar)',
          backdropFilter: 'blur(20px)',
          WebkitBackdropFilter: 'blur(20px)',
          borderRight: sidebarOpen ? '1px solid var(--color-border)' : 'none',
        }}
      >
        <div className="flex flex-col h-full w-[260px]">
          {/* Header — collapse and search side by side, theme on the right */}
          <div className="flex items-center justify-between px-3 pt-3 pb-2">
            <div className="flex items-center gap-1">
              <button
                onClick={toggleSidebar}
                className="p-2 rounded-lg transition-colors cursor-pointer"
                style={{ color: 'var(--color-text-secondary)' }}
                onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-bg-tertiary)')}
                onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                title={t('sidebar.collapse')}
                aria-label={t('sidebar.collapse')}
              >
                <PanelLeftClose size={18} />
              </button>
              <button
                onClick={() => {
                  setSearchOpen((open) => {
                    if (open) setSearchQuery('');
                    return !open;
                  });
                }}
                className="p-2 rounded-lg transition-colors cursor-pointer"
                style={{
                  color: searchOpen ? 'var(--color-accent)' : 'var(--color-text-secondary)',
                  background: searchOpen ? 'var(--color-accent-subtle)' : 'transparent',
                }}
                onMouseEnter={(e) => {
                  if (!searchOpen) e.currentTarget.style.background = 'var(--color-bg-tertiary)';
                }}
                onMouseLeave={(e) => {
                  if (!searchOpen) e.currentTarget.style.background = 'transparent';
                }}
                title={t('sidebar.searchPlaceholder')}
                aria-label={t('sidebar.searchPlaceholder')}
                aria-expanded={searchOpen}
              >
                <Search size={16} />
              </button>
            </div>
            <div className="flex items-center gap-1">
              <button
                onClick={() => updateSettings({ theme: nextTheme })}
                className="p-2 rounded-lg transition-colors cursor-pointer"
                style={{ color: 'var(--color-text-secondary)' }}
                onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-bg-tertiary)')}
                onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                title={t('sidebar.themeTooltip', {
                  current: themeName(settings.theme),
                  next: themeName(nextTheme),
                })}
              >
                <ThemeIcon size={16} />
              </button>
            </div>
          </div>

          {/* Search input, on demand from the header magnifier */}
          {searchOpen && (
            <div className="px-3 mb-2">
              <div
                className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm"
                style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
              >
                <Search size={14} style={{ color: 'var(--color-text-tertiary)' }} />
                <input
                  type="text"
                  autoFocus
                  placeholder={t('sidebar.searchPlaceholder')}
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Escape') {
                      setSearchQuery('');
                      setSearchOpen(false);
                    }
                  }}
                  className="flex-1 bg-transparent outline-none text-sm"
                  style={{ color: 'var(--color-text)' }}
                />
              </div>
            </div>
          )}

          {/* Model badge */}
          <button
            onClick={() => setCommandPaletteOpen(true)}
            className="mx-3 mb-2 flex items-center gap-2 px-3 py-2 rounded-lg text-xs transition-colors cursor-pointer"
            style={{
              background: 'var(--color-bg-secondary)',
              color: 'var(--color-text-secondary)',
              border: '1px solid var(--color-border)',
            }}
            onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-bg-tertiary)')}
            onMouseLeave={(e) => (e.currentTarget.style.background = 'var(--color-bg-secondary)')}
          >
            {modelLoading ? (
              <Loader2 size={14} className="animate-spin" style={{ color: 'var(--color-accent)' }} />
            ) : (
              <Cpu size={14} />
            )}
            <div className="flex-1 min-w-0">
              <span
                className="truncate block text-left"
                style={{ color: deepResearch ? 'var(--color-accent)' : 'var(--color-text)' }}
              >
                {deepResearch
                  ? t('common.deepResearch')
                  : selectedModel || serverInfo?.model || t('sidebar.selectModel')}
              </span>
              {modelLoading && (
                <span className="text-[10px] block text-left" style={{ color: 'var(--color-accent)' }}>
                  {t('sidebar.loadingModel')}
                </span>
              )}
            </div>
            {!modelLoading && (
              <kbd
                className="text-[10px] px-1.5 py-0.5 rounded font-mono"
                style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-text-tertiary)' }}
              >
                ⌘K
              </kbd>
            )}
          </button>

          {/* New conversation — a real, labeled button. The old tiny "+" was
              easy to miss and silently did nothing on an empty chat, which
              read as "I cannot create conversations". */}
          <button
            onClick={handleNewChat}
            className="mx-3 mb-2 flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-opacity cursor-pointer"
            style={{ background: 'var(--color-accent)', color: '#fff' }}
            onMouseEnter={(e) => (e.currentTarget.style.opacity = '0.88')}
            onMouseLeave={(e) => (e.currentTarget.style.opacity = '1')}
          >
            <Plus size={16} />
            {t('sidebar.newChat')}
          </button>

          {/* Primary navigation — at the top, ChatGPT-style */}
          <nav className="px-2 pb-2 flex flex-col gap-0.5">
            {navItems.map((item) => {
              const isActive = location.pathname === item.path;
              return (
                <button
                  key={item.path}
                  onClick={() => navigate(item.path)}
                  className="relative flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors w-full text-left cursor-pointer"
                  style={{
                    background: isActive ? 'var(--color-accent-subtle)' : 'transparent',
                    color: isActive ? 'var(--color-text)' : 'var(--color-text-secondary)',
                    fontWeight: isActive ? 500 : 400,
                  }}
                  onMouseEnter={(e) => {
                    if (!isActive) e.currentTarget.style.background = 'var(--color-bg-secondary)';
                  }}
                  onMouseLeave={(e) => {
                    if (!isActive) e.currentTarget.style.background = 'transparent';
                  }}
                >
                  {isActive && (
                    <span
                      aria-hidden="true"
                      className="absolute left-0 top-1.5 bottom-1.5 w-[2px] rounded-full"
                      style={{
                        background: 'var(--color-accent)',
                        boxShadow: '0 0 8px var(--color-accent-glow)',
                      }}
                    />
                  )}
                  <item.icon size={16} style={isActive ? { color: 'var(--color-accent)' } : undefined} />
                  {item.label}
                </button>
              );
            })}
          </nav>
          {/* Conversation list — everything below the fold scrolls */}
          <div
            className="flex-1 overflow-y-auto px-2 pt-1"
            style={{ borderTop: '1px solid var(--color-border)' }}
          >
            <ConversationList searchQuery={searchQuery} />
          </div>

        </div>
      </aside>
    </>
  );
}
