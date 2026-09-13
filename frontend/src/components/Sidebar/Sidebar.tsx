import { useEffect, useRef, useState } from 'react';
import { useNavigate, useLocation } from 'react-router';
import {
  Plus,
  Gauge,
  Settings,
  Search,
  PanelLeftClose,
  PanelLeft,
  Rocket,
  Bot,
  Sun,
  Moon,
  Monitor,
  TerminalSquare,
  ScrollText,
  Database,
  CalendarRange,
  LayoutDashboard,
  ListTodo,
  BriefcaseBusiness,
  Wallet,
  Repeat2,
  NotebookPen,
  Dices,
  Trophy,
  MonitorSmartphone,
  RefreshCw,
  ChevronLeft,
} from 'lucide-react';
import { ConversationList } from './ConversationList';
import { GlassNav } from './GlassNav';
import { TalkButton } from '../TalkButton';
import { BandeauMiseAJour } from '../Desktop/BandeauMiseAJour';
import { useAppStore, type ThemeMode, type TerminalSkin } from '../../lib/store';
import { useTranslation } from '../../i18n/useTranslation';

/** Pages that live behind the Réglages drawer, so a deep link opens it. */
const SETTINGS_PATHS = [
  '/settings',
  '/get-started',
  '/data-sources',
  '/agents',
  '/logs',
  '/succes/sync',
  '/devices',
  '/dashboard',
];

export function Sidebar() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const [searchQuery, setSearchQuery] = useState('');
  // ChatGPT-style: a magnifier in the header, the input appears on demand.
  const [searchOpen, setSearchOpen] = useState(false);
  const onSettingsRoute = SETTINGS_PATHS.includes(location.pathname);
  const [settingsOpen, setSettingsOpen] = useState(onSettingsRoute);

  const sidebarOpen = useAppStore((s) => s.sidebarOpen);
  const toggleSidebar = useAppStore((s) => s.toggleSidebar);
  const createConversation = useAppStore((s) => s.createConversation);
  const selectedModel = useAppStore((s) => s.selectedModel);

  const settings = useAppStore((s) => s.settings);
  const updateSettings = useAppStore((s) => s.updateSettings);

  // Each terminal screen is its own stop, so the shortcut walks all seven
  // looks rather than treating Terminal as a single destination.
  const THEME_CYCLE: { theme: ThemeMode; skin?: TerminalSkin }[] = [
    { theme: 'light' },
    { theme: 'dark' },
    { theme: 'system' },
    { theme: 'terminal', skin: 'phosphor' },
    { theme: 'terminal', skin: 'ardechine' },
    { theme: 'terminal', skin: 'oxblood' },
    { theme: 'terminal', skin: 'sage' },
  ];
  const TERMINAL_SKIN_NAMES: Record<TerminalSkin, string> = {
    phosphor: 'Phosphore',
    ardechine: 'Ardéchine',
    oxblood: 'Oxblood',
    sage: 'Sauge',
  };
  const THEME_ICONS: Record<ThemeMode, typeof Sun> = {
    light: Sun,
    dark: Moon,
    system: Monitor,
    terminal: TerminalSquare,
  };
  const ThemeIcon = THEME_ICONS[settings.theme] ?? Monitor;
  const activeSkin = settings.terminalSkin ?? 'phosphor';
  const currentIndex = THEME_CYCLE.findIndex(
    (stop) =>
      stop.theme === settings.theme &&
      (stop.theme !== 'terminal' || stop.skin === activeSkin),
  );
  const nextStop = THEME_CYCLE[(currentIndex + 1) % THEME_CYCLE.length];
  const themeName = (stop: { theme: ThemeMode; skin?: TerminalSkin }) =>
    stop.theme === 'light'
      ? t('settings.theme.light')
      : stop.theme === 'dark'
        ? t('settings.theme.dark')
        : stop.theme === 'terminal'
          ? `${t('settings.theme.terminal')} · ${TERMINAL_SKIN_NAMES[stop.skin ?? 'phosphor']}`
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

  // The drawer follows the route, in both directions.
  //
  // Only the opening half used to be enforced, which was invisible as long as
  // every way in and out went through openSettings/closeSettings. A remote
  // command from another appareil navigates without touching either, and left
  // the Réglages drawer standing over a Succès page.
  useEffect(() => {
    setSettingsOpen(onSettingsRoute);
  }, [onSettingsRoute]);

  // The page the drawer interrupted, so closing it can hand the view back.
  const routeBeforeSettings = useRef<string | null>(null);

  const openSettings = () => {
    setSearchOpen(false);
    setSearchQuery('');
    setSettingsOpen(true);
    // Land on Général so the drawer never opens onto a blank pane.
    if (!onSettingsRoute) {
      routeBeforeSettings.current = location.pathname;
      navigate('/settings');
    }
  };

  const closeSettings = () => {
    setSettingsOpen(false);
    const back = routeBeforeSettings.current;
    routeBeforeSettings.current = null;
    // Leaving the drawer has to move the content too: the sidebar was showing
    // the app again while the pane still displayed Réglages. Deep links have no
    // page to return to, so they fall back to the chat.
    if (onSettingsRoute) {
      navigate(back && !SETTINGS_PATHS.includes(back) ? back : '/');
    }
  };

  // Discussion is not a nav tab: "Nouvelle discussion" and the conversation
  // list already cover opening and switching chats.
  const succesNavItems = [
    { path: '/succes/dashboard', icon: LayoutDashboard, label: t('nav.succesDashboard') },
    { path: '/succes/planner', icon: CalendarRange, label: t('nav.succesPlanner') },
    { path: '/succes/tasks', icon: ListTodo, label: t('nav.succesTasks') },
    { path: '/succes/projects', icon: BriefcaseBusiness, label: t('nav.succesProjects') },
    { path: '/succes/finances', icon: Wallet, label: t('nav.succesFinances') },
    { path: '/succes/habits', icon: Repeat2, label: t('nav.succesHabits') },
    { path: '/succes/notes', icon: NotebookPen, label: t('nav.succesNotes') },
    { path: '/succes/year-review', icon: Trophy, label: t('nav.succesYearReview') },
    { path: '/loterie', icon: Dices, label: t('nav.loterie') },
  ];

  // Réglages is administration, not a workspace: its tabs are grouped by what
  // they govern — the app itself, what feeds it, then what it leaves behind.
  const settingsGroups = [
    {
      label: t('sidebar.settingsGroupConfig'),
      items: [
        { path: '/settings', icon: Settings, label: t('nav.settingsGeneral') },
        { path: '/get-started', icon: Rocket, label: t('nav.getStarted') },
      ],
    },
    {
      label: t('sidebar.settingsGroupConnections'),
      items: [
        { path: '/data-sources', icon: Database, label: t('nav.dataSources') },
        { path: '/agents', icon: Bot, label: t('nav.agents') },
        { path: '/succes/sync', icon: RefreshCw, label: t('nav.succesSync') },
        { path: '/devices', icon: MonitorSmartphone, label: t('nav.devices') },
      ],
    },
    {
      label: t('sidebar.settingsGroupObservability'),
      items: [
        { path: '/dashboard', icon: Gauge, label: t('nav.dashboard') },
        { path: '/logs', icon: ScrollText, label: t('nav.logs') },
      ],
    },
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
              {!settingsOpen && (
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
              )}
            </div>
            <div className="flex items-center gap-1">
              <button
                onClick={() =>
                  updateSettings(
                    nextStop.skin
                      ? { theme: nextStop.theme, terminalSkin: nextStop.skin }
                      : { theme: nextStop.theme },
                  )
                }
                className="p-2 rounded-lg transition-colors cursor-pointer"
                style={{ color: 'var(--color-text-secondary)' }}
                onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-bg-tertiary)')}
                onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                title={t('sidebar.themeTooltip', {
                  current: themeName({ theme: settings.theme, skin: activeSkin }),
                  next: themeName(nextStop),
                })}
              >
                <ThemeIcon size={16} />
              </button>
            </div>
          </div>

          {/* Search input, on demand from the header magnifier */}
          {searchOpen && !settingsOpen && (
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

          {settingsOpen ? (
            /* Réglages takes over the sidebar, grouped so the tabs read as a
               short table of contents rather than a flat list */
            <div id="settings-nav" className="flex-1 overflow-y-auto pt-1">
              <button
                onClick={closeSettings}
                className="mx-3 mb-1 flex items-center gap-2 px-3 py-2 rounded-xl text-sm font-medium cursor-pointer transition-colors"
                style={{ color: 'var(--color-text)' }}
                onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-bg-tertiary)')}
                onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                title={t('sidebar.settingsBack')}
              >
                <ChevronLeft size={16} style={{ color: 'var(--color-accent)' }} />
                <span className="flex-1 text-left">{t('sidebar.settingsBack')}</span>
              </button>
              {settingsGroups.map((group) => (
                <div key={group.label}>
                  <div
                    className="px-5 pt-2 pb-1 text-[11px] font-medium uppercase tracking-wider"
                    style={{ color: 'var(--color-text-tertiary)' }}
                  >
                    {group.label}
                  </div>
                  <GlassNav items={group.items} groupLabel={group.label} />
                </div>
              ))}
            </div>
          ) : (
            <>
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

              {/* Succès tabs. Nav and conversations scroll together so a long
                  history does not squeeze the tabs. */}
              <div className="flex-1 min-h-0 overflow-y-auto">
                <GlassNav items={succesNavItems} />
                {/* Conversation list — everything below the fold scrolls */}
                <div
                  className="px-2 pt-1"
                  style={{ borderTop: '1px solid var(--color-border)' }}
                >
                  <ConversationList searchQuery={searchQuery} />
                </div>
              </div>
            </>
          )}

          {/* Une nouvelle version se signale ici, juste au-dessus du pied de
              page, dans les couleurs de la barre — et non plus en
              surimpression en haut de la fenêtre. Rien à installer : rien. */}
          <BandeauMiseAJour />

          {/* Réglages left, Parler to its right — one quiet footer so neither
              floats over the workspace. Talk stays reachable while the
              settings drawer is open; Réglages yields to the back row. */}
          <div
            className="flex items-stretch shrink-0"
            style={{ borderTop: '1px solid var(--color-border)' }}
          >
            {!settingsOpen && (
              <>
                <button
                  onClick={openSettings}
                  className="flex flex-1 items-center gap-2 px-4 py-3 text-sm transition-colors cursor-pointer min-w-0"
                  style={{
                    color: 'var(--color-text-secondary)',
                    background: 'transparent',
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-bg-tertiary)')}
                  onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                  aria-controls="settings-nav"
                  title={t('nav.settings')}
                >
                  <Settings size={16} className="shrink-0" />
                  <span className="flex-1 text-left truncate">{t('nav.settings')}</span>
                </button>
                <span
                  aria-hidden="true"
                  className="w-px self-stretch my-2 shrink-0"
                  style={{ background: 'var(--color-border)' }}
                />
              </>
            )}
            <TalkButton />
          </div>
        </div>
      </aside>
    </>
  );
}
