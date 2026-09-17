import { lazy, Suspense, useEffect, useState, useCallback, useRef } from 'react';
import { estDansUneZoneDeSaisie, laissePasserLeRaccourci } from './lib/saisie';
import { Routes, Route, Navigate, useLocation, useNavigate } from 'react-router';
import { Layout } from './components/Layout';
import { ChatPage } from './pages/ChatPage';
import { CommandPalette } from './components/CommandPalette';
import { SetupScreen } from './components/SetupScreen';
import { Toaster } from './components/ui/sonner';
import { estCompact } from './lib/compact';
import { useAppStore, isLightTerminalSkin } from './lib/store';
import { ContexteVueHost } from './features/mesh/ContexteVueHost';
import { ModeGestesProvider } from './features/gestes/ModeGestesContexte';
import { VoyantGestes } from './features/gestes/VoyantGestes';
import { fetchModels, fetchServerInfo, fetchSavings, isTauri } from './lib/api';
import { ConfirmProvider } from './components/ConfirmDialog';
import { MeshHost } from './components/MeshHost';
import { TalkToDiapasonHost } from './components/TalkToDiapasonHost';
import { track, hashId } from './lib/analytics';
import { demarrerSyncConversations } from './lib/convSync';
import { startHabitReminderScheduler } from './features/succes/habitReminders';
import { normaliserZoom, raccourciZoom, zoomSuivant } from './lib/zoom';
import {
  annoncerLeGlissement,
  demanderLOuvertureDuSauteur,
  demanderLeFocusDuCompositeur,
} from './lib/panneau';
import { discussionVoisine, type SensVoisine } from './lib/discussions';

/**
 * ⌘⇧[ ou ⌘⇧] ? Le sens, ou null. Les crochets portent aussi leur `code` :
 * sur une disposition française, `[` n'existe qu'avec ⌥ et `key` ne dit
 * plus rien de fiable, alors que `BracketLeft` désigne la même touche que
 * ⌘⇧[ dans Safari et Arc (même règle que lib/saisie.ts).
 */
function sensDuRaccourci(e: KeyboardEvent): SensVoisine | null {
  if (!(e.metaKey || e.ctrlKey) || !e.shiftKey || e.altKey) return null;
  if (e.code === 'BracketLeft' || e.key === '[' || e.key === '{') return 'precedente';
  if (e.code === 'BracketRight' || e.key === ']' || e.key === '}') return 'suivante';
  return null;
}

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
const SuccesFinancesPage = lazy(() =>
  import('./pages/SuccesFinancesPage').then((module) => ({ default: module.SuccesFinancesPage })),
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
  const selectedModel = useAppStore((s) => s.selectedModel);
  const setServerInfo = useAppStore((s) => s.setServerInfo);
  const setSavings = useAppStore((s) => s.setSavings);
  const settings = useAppStore((s) => s.settings);
  const updateSettings = useAppStore((s) => s.updateSettings);
  const commandPaletteOpen = useAppStore((s) => s.commandPaletteOpen);
  const setCommandPaletteOpen = useAppStore((s) => s.setCommandPaletteOpen);
  const nouvelleDiscussion = useAppStore((s) => s.nouvelleDiscussion);
  const navigate = useNavigate();
  const { pathname } = useLocation();

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
    // Pousser le thème à la réglette native : ses WKWebView ne partagent pas
    // ce localStorage, elle ne peut pas le lire seule.
    if (isTauri()) {
      import('@tauri-apps/api/core')
        .then(({ invoke }) =>
          invoke('reglette_set_theme', {
            theme: settings.theme,
            skin: settings.terminalSkin ?? 'phosphor',
          }),
        )
        .catch(() => {});
    }
  }, [settings.theme, settings.terminalSkin]);

  useEffect(() => {
    const root = document.documentElement;
    if (settings.fontSize === 'small' || settings.fontSize === 'large') {
      root.dataset.fontSize = settings.fontSize;
    } else {
      delete root.dataset.fontSize;
    }
  }, [settings.fontSize]);

  // Synchronisation des conversations avec le serveur local — dans TOUS les
  // contextes, PAS de garde isTauri (contrairement à l'import overlay
  // dessous) : 16 sept. 2026, la fenêtre principale (tauri://localhost), le
  // mini-panneau (http://127.0.0.1:8000) et le navigateur ont chacun leur
  // localStorage ; seul le serveur les fait converger. Le moteur porte son
  // propre verrou « une fois », donc le double montage StrictMode est sûr.
  useEffect(() => {
    demarrerSyncConversations();
  }, []);

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
      })
      .catch(() => setModels([]))
      .finally(() => setModelsLoading(false));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch server info
  useEffect(() => {
    fetchServerInfo().then(setServerInfo).catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Poll local savings for the on-device dashboard. Nothing is uploaded.
  useEffect(() => {
    const refresh = () =>
      fetchSavings()
        .then(setSavings)
        .catch(() => {});
    refresh();
    const interval = setInterval(refresh, 30000);
    return () => clearInterval(interval);
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

  // Le zoom de l'interface — appliqué au webview, donc à TOUT, pixels
  // compris (voir lib/zoom.ts). Hors de l'app de bureau, le navigateur a le
  // sien ; on ne fait rien.
  useEffect(() => {
    if (!isTauri()) return;
    const zoom = normaliserZoom(settings.zoom);
    import('@tauri-apps/api/webview')
      .then(({ getCurrentWebview }) => getCurrentWebview().setZoom(zoom))
      .catch(() => {});
  }, [settings.zoom]);

  // Global keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Le zoom passe AVANT la garde de saisie : c'est en écrivant qu'on a
      // besoin de mieux voir, et aucun éditeur n'utilise ⌘ +, ⌘ −, ⌘ 0.
      const sens = raccourciZoom(e);
      if (sens && isTauri()) {
        e.preventDefault();
        updateSettings({ zoom: zoomSuivant(normaliserZoom(useAppStore.getState().settings.zoom), sens) });
        return;
      }
      // Ne jamais confisquer un raccourci à quelqu'un qui écrit. Cmd+I est
      // l'italique de toute zone de texte : sans cette garde, il ouvrait le
      // panneau système et l'italique natif ne marchait nulle part dans une
      // note. Cmd+K avait le même défaut.
      //
      // 17 sept. 2026 : la garde absolue tuait ⌘K depuis le compositeur —
      // presque toujours, dans le mini-panneau. Le SEUL champ qui porte
      // `data-raccourcis-globaux` (le textarea d'InputArea) laisse passer
      // une liste fermée (⌘K ⌘N ⌘J ⌘⇧[ ⌘⇧]) ; l'éditeur de notes ne la
      // porte pas et garde ses raccourcis.
      if (estDansUneZoneDeSaisie(e.target) && !laissePasserLeRaccourci(e.target, e)) return;
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setCommandPaletteOpen(!commandPaletteOpen);
      }
      if ((e.metaKey || e.ctrlKey) && e.key === 'i') {
        e.preventDefault();
        toggleSystemPanel();
      }
      // ⌘N — 17 sept. 2026 : « Nouvelle discussion » n'était qu'un bouton de
      // la barre latérale, absente du mini-panneau. Passe depuis le
      // compositeur (liste fermée de lib/saisie.ts) ; le menu natif Tauri ne
      // réserve que ⌘R (lib.rs, `accelerator`). Même règle que le bouton : une
      // vierge existante est réutilisée. Hors de la Discussion, on y va ; la
      // demande de focus est GARDÉE par lib/panneau.ts et relue par le
      // compositeur à son montage — différée d'un tour, elle arrivait encore
      // 50 ms avant lui (contre-revue du 17 sept. 2026). Ignoré pendant un
      // flux, comme ⌘⇧[ ] : sinon les jetons du fil quitté s'affichaient
      // sous le titre « Nouvelle discussion ».
      if ((e.metaKey || e.ctrlKey) && !e.shiftKey && !e.altKey && e.key === 'n') {
        e.preventDefault();
        if (useAppStore.getState().streamState.isStreaming) return;
        nouvelleDiscussion(useAppStore.getState().selectedModel);
        if (pathname !== '/') navigate('/');
        demanderLeFocusDuCompositeur();
      }
      // ⌘J — le sauteur de discussions, sous le titre du fil (ChatArea le
      // tient en state local). Même détour que ⌘N hors de la Discussion :
      // la page n'est pas montée quand la touche arrive, la demande attend
      // un tour. Un sauteur déjà ouvert garde le focus dans son champ, d'où
      // ⌘J ne passe pas ici : c'est lui qui se referme.
      if ((e.metaKey || e.ctrlKey) && !e.shiftKey && !e.altKey && e.key === 'j') {
        e.preventDefault();
        if (pathname === '/') {
          demanderLOuvertureDuSauteur();
        } else {
          navigate('/');
          window.setTimeout(demanderLOuvertureDuSauteur, 0);
        }
      }
      // ⌘⇧[ / ⌘⇧] — 17 sept. 2026 : alterner entre deux ou trois fils
      // récents (comparer une réponse, reprendre) exigeait d'ouvrir le
      // sauteur à chaque fois. Fil voisin dans l'ordre exact du sauteur ;
      // aux extrémités, rien. Ignoré pendant un flux : on ne quitte pas une
      // réponse en cours par accident. Le retour est le glissement du fil
      // et le titre de l'en-tête — pas de toast. Le clic passe par le
      // sauteur, la voix viendra (rang 10) : §82 sans chrome de plus.
      const sensVoisine = sensDuRaccourci(e);
      if (sensVoisine) {
        e.preventDefault();
        const etat = useAppStore.getState();
        if (etat.streamState.isStreaming) return;
        const voisine = discussionVoisine(etat.conversations, etat.activeId, sensVoisine, Date.now());
        if (!voisine || voisine.id === etat.activeId) return;
        if (pathname === '/') {
          annoncerLeGlissement(sensVoisine);
          etat.selectConversation(voisine.id);
          etat.loadMessages(voisine.id);
        } else {
          navigate('/');
          etat.selectConversation(voisine.id);
          etat.loadMessages(voisine.id);
          demanderLeFocusDuCompositeur();
        }
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [
    commandPaletteOpen,
    setCommandPaletteOpen,
    toggleSystemPanel,
    updateSettings,
    nouvelleDiscussion,
    navigate,
    pathname,
  ]);


  if (!setupDone) {
    return <SetupScreen onReady={handleSetupReady} />;
  }

  return (
    <ModeGestesProvider>
    <ConfirmProvider>
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
            <Route path="succes/finances" element={<SuccesFinancesPage />} />
            <Route path="succes/habits" element={<SuccesHabitsPage />} />
            <Route path="succes/notes" element={<SuccesNotesPage />} />
            <Route path="succes/templates" element={<Navigate to="/succes/tasks" replace />} />
            <Route path="succes/year-review" element={<SuccesYearReviewPage />} />
            <Route path="succes/sync" element={<SuccesSyncPage />} />
            <Route path="devices" element={<DevicesPage />} />
          </Route>
        </Routes>
      </Suspense>
      {/* En bas à droite, les toasts couvraient le compositeur et le bas de
          chaque module dans le mini-panneau (16 sept. 2026). Le sens de la
          pile (`data-y-position` sur chaque toast) est décidé ici par sonner :
          le CSS seul ne pouvait pas la retourner ; index.css cale ensuite les
          toasts sous la bande de glissement et borne leur largeur. */}
      <Toaster position={estCompact ? 'top-center' : 'bottom-right'} />
      <TalkToDiapasonHost />
      <MeshHost />
      <ContexteVueHost />
      <VoyantGestes />
      {commandPaletteOpen && <CommandPalette />}
    </ConfirmProvider>
    </ModeGestesProvider>
  );
}
