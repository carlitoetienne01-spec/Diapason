import { lazy, Suspense, useEffect, useState, useCallback, useRef } from 'react';
import { Routes, Route, Navigate } from 'react-router';
import { Layout } from './components/Layout';
import { ChatPage } from './pages/ChatPage';
import { CommandPalette } from './components/CommandPalette';
import { SetupScreen } from './components/SetupScreen';
import { Toaster } from './components/ui/sonner';
import { useAppStore, isLightTerminalSkin } from './lib/store';
import { fetchModels, fetchServerInfo, fetchSavings, submitSavings, isTauri } from './lib/api';
import { OptInModal } from './components/OptInModal';
import { ConfirmProvider } from './components/ConfirmDialog';
import { UpdateChecker } from './components/Desktop/UpdateChecker';
import { MeshHost } from './components/MeshHost';
import { TalkToDiapasonHost } from './components/TalkToDiapasonHost';
import { track, hashId } from './lib/analytics';
import { startHabitReminderScheduler } from './features/succes/habitReminders';

const DashboardPage = lazy(() =>
  import('./pages/DashboardPage').then((module) => ({ default: module.DashboardPage })),
);
const SettingsPage = lazy(() =>
  import('./pages/SettingsPage').then((module) => ({ default: module.SettingsPage })),
);
const GetStartedPage = lazy(() =>
  import('./pages/GetStartedPage').then((module) => ({ default: module.GetStartedPage })),
);
const AgentsPage = lazy(() =>
  import('./pages/AgentsPage').then((module) => ({ default: module.AgentsPage })),
);
const DataSourcesPage = lazy(() =>
  import('./pages/DataSourcesPage').then((module) => ({ default: module.DataSourcesPage })),
);
const LogsPage = lazy(() =>
  import('./pages/LogsPage').then((module) => ({ default: module.LogsPage })),
);
const SuccesPlannerPage = lazy(() =>
  import('./pages/SuccesPlannerPage').then((module) => ({ default: module.SuccesPlannerPage })),
);
const SuccesDashboardPage = lazy(() =>
  import('./pages/SuccesDashboardPage').then((module) => ({ default: module.SuccesDashboardPage })),
);
const SuccesTasksPage = lazy(() =>
  import('./pages/SuccesTasksPage').then((module) => ({ default: module.SuccesTasksPage })),
);
const SuccesProjectsPage = lazy(() =>
  import('./pages/SuccesProjectsPage').then((module) => ({ default: module.SuccesProjectsPage })),
);
const SuccesHabitsPage = lazy(() =>
  import('./pages/SuccesHabitsPage').then((module) => ({ default: module.SuccesHabitsPage })),
);
const SuccesNotesPage = lazy(() =>
  import('./pages/SuccesNotesPage').then((module) => ({ default: module.SuccesNotesPage })),
);
const SuccesYearReviewPage = lazy(() =>
  import('./pages/SuccesYearReviewPage').then((module) => ({ default: module.SuccesYearReviewPage })),
);
const SuccesSyncPage = lazy(() =>
  import('./pages/SuccesSyncPage').then((module) => ({ default: module.SuccesSyncPage })),
);
const DevicesPage = lazy(() =>
  import('./pages/DevicesPage').then((module) => ({ default: module.DevicesPage })),
);

export default function App() {
  const [setupDone, setSetupDone] = useState(!isTauri());
  const handleSetupReady = useCallback(() => {
    setSetupDone(true);
    // Only fire once per install — guard against setup screen re-appearing
    // on reinstalls or dev reloads.
    if (!localStorage.getItem('diapason-setup-completed')) {
      localStorage.setItem('diapason-setup-completed', '1');
      track('setup_completed', { preset: 'default' });
    }
  }, []);
  const prevModelRef = useRef<string>('');
  const setModels = useAppStore((s) => s.setModels);
  const setModelsLoading = useAppStore((s) => s.setModelsLoading);
  const setSelectedModel = useAppStore((s) => s.setSelectedModel);
  const selectedModel = useAppStore((s) => s.selectedModel);
  const setServerInfo = useAppStore((s) => s.setServerInfo);
  const setSavings = useAppStore((s) => s.setSavings);
  const settings = useAppStore((s) => s.settings);
  const commandPaletteOpen = useAppStore((s) => s.commandPaletteOpen);
  const setCommandPaletteOpen = useAppStore((s) => s.setCommandPaletteOpen);
  const optInEnabled = useAppStore((s) => s.optInEnabled);
  const optInDisplayName = useAppStore((s) => s.optInDisplayName);
  const optInEmail = useAppStore((s) => s.optInEmail);
  const optInAnonId = useAppStore((s) => s.optInAnonId);
  const optInModalSeen = useAppStore((s) => s.optInModalSeen);
  const optInModalOpen = useAppStore((s) => s.optInModalOpen);
  const setOptInModalOpen = useAppStore((s) => s.setOptInModalOpen);
  const markOptInModalSeen = useAppStore((s) => s.markOptInModalSeen);
  const savings = useAppStore((s) => s.savings);

  // Apply theme class to <html>. Terminal rides on top of `dark` so every
  // `dark:` variant still resolves; its own class only re-skins the tokens.
  useEffect(() => {
    const root = document.documentElement;
    root.classList.remove('dark', 'light', 'terminal');
    if (settings.theme === 'dark') root.classList.add('dark');
    else if (settings.theme === 'light') root.classList.add('light');
    else if (settings.theme === 'terminal') {
      const skin = settings.terminalSkin ?? 'phosphor';
      // The companion class decides which way every `dark:` utility resolves,
      // so a reflective screen has to travel with `.light` or Tailwind would
      // paint dark surfaces over a pale panel.
      root.classList.add(isLightTerminalSkin(skin) ? 'light' : 'dark', 'terminal');
      root.dataset.terminalSkin = skin;
    }
    if (settings.theme !== 'terminal') delete root.dataset.terminalSkin;
  }, [settings.theme, settings.terminalSkin]);

  useEffect(() => {
    const root = document.documentElement;
    if (settings.fontSize === 'small' || settings.fontSize === 'large') {
      root.dataset.fontSize = settings.fontSize;
    } else {
      delete root.dataset.fontSize;
    }
  }, [settings.fontSize]);

  // Sync overlay conversations into the main app
  const importOverlay = useAppStore((s) => s.importOverlayConversation);
  useEffect(() => {
    if (!isTauri()) return;
    importOverlay();
    const interval = setInterval(importOverlay, 5000);
    return () => clearInterval(interval);
  }, [importOverlay]);

  // Fetch models on mount
  useEffect(() => {
    fetchModels()
      .then((m) => {
        setModels(m);
        if (!selectedModel && m.length > 0) setSelectedModel(m[0].id);
      })
      .catch(() => setModels([]))
      .finally(() => setModelsLoading(false));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch server info
  useEffect(() => {
    fetchServerInfo().then(setServerInfo).catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Poll savings and optionally share to Supabase
  useEffect(() => {
    const refresh = () =>
      fetchSavings()
        .then((data) => {
          setSavings(data);
          if (optInEnabled && optInDisplayName && data) {
            const claudeEntry = data.per_provider.find(
              (p) => p.provider === 'claude-fable-5',
            );
            const dollarSavings = claudeEntry ? claudeEntry.total_cost : 0;
            const energySaved = data.per_provider.reduce(
              (sum, p) => sum + (p.energy_wh || 0),
              0,
            );
            const flopsSaved = data.per_provider.reduce(
              (sum, p) => sum + (p.flops || 0),
              0,
            );
            submitSavings({
              anon_id: optInAnonId,
              display_name: optInDisplayName,
              email: optInEmail,
              total_calls: data.total_calls,
              total_tokens: data.total_tokens,
              dollar_savings: dollarSavings,
              energy_wh_saved: energySaved,
              flops_saved: flopsSaved,
              token_counting_version: data.token_counting_version ?? 1,
            });
          }
        })
        .catch(() => {});
    refresh();
    const interval = setInterval(refresh, 30000);
    return () => clearInterval(interval);
  }, [optInEnabled, optInDisplayName, optInAnonId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Show opt-in modal on first visit
  useEffect(() => {
    if (!optInModalSeen) {
      setOptInModalOpen(true);
      markOptInModalSeen();
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Fire model_changed when the user switches models. First mount is
  // not a "change" — only emit when both prev and current are real and
  // differ.
  useEffect(() => {
    const prev = prevModelRef.current;
    const curr = selectedModel || '';
    prevModelRef.current = curr;
    if (!prev || !curr || prev === curr) return;
    void (async () => {
      const [fromHash, toHash] = await Promise.all([
        hashId(prev),
        hashId(curr),
      ]);
      track('model_changed', {
        from_model_hash: fromHash,
        to_model_hash: toHash,
      });
    })();
  }, [selectedModel]);

  // app_opened — one-shot per app launch, fires after analytics has had
  // a chance to initialize. platform + version are super-properties
  // registered in analytics.ts initAnalytics, so no per-call props needed.
  useEffect(() => {
    const t = setTimeout(() => {
      track('app_opened', {});
    }, 500);
    return () => clearTimeout(t);
  }, []);

  // Succès habit OS reminders (desktop only; in-process timers + Tauri notify).
  useEffect(() => {
    if (!setupDone || !isTauri()) return;
    startHabitReminderScheduler();
  }, [setupDone]);

  const toggleSystemPanel = useAppStore((s) => s.toggleSystemPanel);

  // Global keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setCommandPaletteOpen(!commandPaletteOpen);
      }
      if ((e.metaKey || e.ctrlKey) && e.key === 'i') {
        e.preventDefault();
        toggleSystemPanel();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [commandPaletteOpen, setCommandPaletteOpen, toggleSystemPanel]);


  if (!setupDone) {
    return <SetupScreen onReady={handleSetupReady} />;
  }

  return (
    <ConfirmProvider>
      <UpdateChecker />
      <Suspense fallback={<div role="status" className="p-6">Chargement…</div>}>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<ChatPage />} />
            <Route path="dashboard" element={<DashboardPage />} />
            <Route path="settings" element={<SettingsPage />} />
            <Route path="get-started" element={<GetStartedPage />} />
            <Route path="data-sources" element={<DataSourcesPage />} />
            <Route path="agents" element={<AgentsPage />} />
            <Route path="logs" element={<LogsPage />} />
            <Route path="succes/planner" element={<SuccesPlannerPage />} />
            <Route path="succes/dashboard" element={<SuccesDashboardPage />} />
            <Route path="succes/tasks" element={<SuccesTasksPage />} />
            <Route path="succes/projects" element={<SuccesProjectsPage />} />
            <Route path="succes/habits" element={<SuccesHabitsPage />} />
            <Route path="succes/notes" element={<SuccesNotesPage />} />
            <Route path="succes/templates" element={<Navigate to="/succes/tasks" replace />} />
            <Route path="succes/year-review" element={<SuccesYearReviewPage />} />
            <Route path="succes/sync" element={<SuccesSyncPage />} />
            <Route path="devices" element={<DevicesPage />} />
          </Route>
        </Routes>
      </Suspense>
      <Toaster position="bottom-right" />
      <TalkToDiapasonHost />
      <MeshHost />
      {commandPaletteOpen && <CommandPalette />}
      {optInModalOpen && (
        <OptInModal onClose={() => setOptInModalOpen(false)} />
      )}
    </ConfirmProvider>
  );
}
