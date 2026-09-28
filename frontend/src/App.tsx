import { Suspense, useEffect, useLayoutEffect, useState, useCallback, useRef, type ReactElement, type ReactNode } from 'react';
import { estDansUneZoneDeSaisie, laissePasserLeRaccourci } from './lib/saisie';
import { Routes, Route, Navigate, useLocation, useNavigate } from 'react-router';
import { Layout } from './components/Layout';
import { ChatPage } from './pages/ChatPage';
import { CommandPalette } from './components/CommandPalette';
import { SetupScreen } from './components/SetupScreen';
import { Toaster } from './components/ui/sonner';
import { estCompact } from './lib/compact';
import { demanderAuTelephone, estMobile } from './lib/natif';
import { hotesDuMac } from './lib/hotesDuMac';
import { lireChargeThemeNatif } from './lib/themeNatif';
import { useAppStore, isLightTerminalSkin } from './lib/store';
import { ContexteVueHost } from './features/mesh/ContexteVueHost';
import { ModeGestesProvider } from './features/gestes/ModeGestesContexte';
import { VoyantGestes } from './features/gestes/VoyantGestes';
import { fetchModels, fetchServerInfo, fetchSavings, isTauri } from './lib/api';
import { ConfirmProvider } from './components/ConfirmDialog';
import { MeshHost } from './components/MeshHost';
import { NavigationDuTelephone } from './components/NavigationDuTelephone';
import { PartageDuTelephone } from './components/PartageDuTelephone';
import { pagesAffichees } from './lib/pagesAffichees';
import { pageParesseuse } from './lib/pageParesseuse';
import { optionsDuNavigateur, piloterPrechargement } from './lib/prechargerPages';
import { releveNavigation } from './lib/mesuresNavigation';
import { TalkToDiapasonHost } from './components/TalkToDiapasonHost';
import { track, hashId } from './lib/analytics';
import { demarrerSyncConversations } from './lib/convSync';
import { startHabitReminderScheduler } from './features/vie/habitReminders';
import { cibleHeritee, PAGES_VIE, type PageVie } from './features/vie/routesVie';
import { normaliserZoom, raccourciZoom, zoomSuivant } from './lib/zoom';
import {
  annoncerLeGlissement,
  demanderLOuvertureDuSauteur,
  demanderLeFocusDuCompositeur,
} from './lib/panneau';
import { discussionVoisine, type SensVoisine } from './lib/discussions';
import { EcranCompte } from './features/compte/EcranCompte';
import { lireStatutCompte } from './features/compte/api';
import { doitAfficherAccueil } from './lib/compte';

/**
 * Ce que l'écran d'activation du compte peut retarder l'app, au plus. Même
 * budget que la présélection du modèle (SetupScreen) : c'est une question
 * posée une fois, jamais une porte — un serveur local lent ou ancien (sans
 * `/v1/account`) laisse passer l'app au lieu de la retenir.
 */
const ACCUEIL_COMPTE_BUDGET_MS = 2500;

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

// 26/09/2026, chantier de la fluidité (lot 2) : chaque page sait se
// précharger (lib/pageParesseuse.tsx) — voir `PAGES_A_PRECHARGER`.
const DashboardPage = pageParesseuse(() => import('./pages/DashboardPage').then((m) => m.DashboardPage));
const SettingsPage = pageParesseuse(() => import('./pages/SettingsPage').then((m) => m.SettingsPage));
const GetStartedPage = pageParesseuse(() => import('./pages/GetStartedPage').then((m) => m.GetStartedPage));
const AgentsPage = pageParesseuse(() => import('./pages/AgentsPage').then((m) => m.AgentsPage));
const DataSourcesPage = pageParesseuse(() => import('./pages/DataSourcesPage').then((m) => m.DataSourcesPage));
const LogsPage = pageParesseuse(() => import('./pages/LogsPage').then((m) => m.LogsPage));
const ViePlannerPage = pageParesseuse(() => import('./pages/ViePlannerPage').then((m) => m.ViePlannerPage));
const VieDashboardPage = pageParesseuse(() => import('./pages/VieDashboardPage').then((m) => m.VieDashboardPage));
const VieTasksPage = pageParesseuse(() => import('./pages/VieTasksPage').then((m) => m.VieTasksPage));
const VieProjectsPage = pageParesseuse(() => import('./pages/VieProjectsPage').then((m) => m.VieProjectsPage));
const VieHabitsPage = pageParesseuse(() => import('./pages/VieHabitsPage').then((m) => m.VieHabitsPage));
const VieFinancesPage = pageParesseuse(() => import('./pages/VieFinancesPage').then((m) => m.VieFinancesPage));
const VieNotesPage = pageParesseuse(() => import('./pages/VieNotesPage').then((m) => m.VieNotesPage));
const VieYearReviewPage = pageParesseuse(() => import('./pages/VieYearReviewPage').then((m) => m.VieYearReviewPage));
const VieSyncPage = pageParesseuse(() => import('./pages/VieSyncPage').then((m) => m.VieSyncPage));
const DevicesPage = pageParesseuse(() => import('./pages/DevicesPage').then((m) => m.DevicesPage));

/**
 * Au téléphone, les pages préchargées pendant les creux, dans l'ordre :
 * les onglets (Tâches, Planificateur, Notes), puis ce que « Plus » ouvre.
 * Au banc du 26/09/2026 (4G simulée, processeur ×4), la première visite
 * des Tâches attendait 400 ms ses 12 morceaux avant de demander ses
 * données. Toutes les pages y sont : aucune n'emporte Plotly, Mermaid ni
 * Three, qui restent chargés à l'usage par les visuels du chat et la voix.
 */
const PAGES_A_PRECHARGER: readonly (() => Promise<unknown>)[] = [
  VieTasksPage, ViePlannerPage, VieNotesPage,
  VieProjectsPage, VieFinancesPage, VieHabitsPage, VieYearReviewPage, VieDashboardPage,
  SettingsPage, DevicesPage, DashboardPage, VieSyncPage, AgentsPage, LogsPage,
  DataSourcesPage, GetStartedPage,
].map((page) => page.precharger);

/**
 * Une page par entrée de `PAGES_VIE` : le `Record` refuse une page oubliée
 * comme une page en trop, et c'est cette même liste que la réglette et
 * `__diapNoms` (lib.rs) sont tenus de suivre (features/vie/routesVie.test.ts).
 */
const PAGES_VIE_ELEMENTS: Record<PageVie, ReactElement> = {
  planner: <ViePlannerPage />,
  dashboard: <VieDashboardPage />,
  tasks: <VieTasksPage />,
  projects: <VieProjectsPage />,
  finances: <VieFinancesPage />,
  habits: <VieHabitsPage />,
  notes: <VieNotesPage />,
  'year-review': <VieYearReviewPage />,
  sync: <VieSyncPage />,
};

/**
 * Signale la page une fois MONTÉE — l'effet ne part qu'après que React l'a
 * posée dans le document, jamais pour une page restée derrière son
 * `Suspense`. C'est ce qu'attend `naviguer` avant d'acquitter au téléphone
 * (lib/pagesAffichees.ts, 26/09/2026).
 */
function PageAffichee({ chemin, children }: { chemin: string; children: ReactElement }) {
  useEffect(() => pagesAffichees.signalerMontee(chemin), [chemin]);
  return children;
}

/**
 * Le relevé de fluidité du téléphone (lib/mesuresNavigation.ts,
 * 26/09/2026) : le DÉBUT est noté au premier rendu de la nouvelle adresse,
 * la MONTÉE quand React a posé la page dans le document — l'effet ne part
 * qu'une fois son morceau arrivé et son `Suspense` levé. Posé autour de
 * `Layout`, qui reste tel quel. Hors du téléphone, rien n'est relevé.
 */
function MesureDeRoute({ children }: { children: ReactNode }) {
  const { key, pathname } = useLocation();
  // La clé seule ne suffit pas : une entrée d'historique posée hors du
  // routeur (un `pushState` sans état) garde la clé « default » de
  // l'ouverture, et chaque page suivante passait pour la même navigation.
  const cle = `${key}\u0000${pathname}`;
  if (estMobile) releveNavigation.debut(cle, pathname, performance.now());
  // Un effet de MISE EN PAGE, pas un effet passif : ceux-là partent après
  // ceux de la page, et le banc les a vus attendre derrière 100 à 200 ms de
  // travail des pages déjà peintes (relevé à 136 ms quand le contenu était
  // à l'écran à 21 ms, 26/09/2026).
  useLayoutEffect(() => {
    if (estMobile) releveNavigation.montee(cle);
  }, [cle]);
  return children;
}

/** `/succes/*` → `/vie/*`, requête et ancre comprises (voir `cibleHeritee`). */
function RedirectionHeritee() {
  return <Navigate to={cibleHeritee(useLocation())} replace />;
}


const HOTES = hotesDuMac(estMobile, estCompact);
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
  // D13 (compte-chiffre.md §3.11 P1) : l'écran du compte s'affiche UNE fois,
  // dans la fenêtre de bureau, après l'installation et le modèle — donc
  // après SetupScreen. Le drapeau vit dans compte/accueil.json côté serveur,
  // jamais dans le localStorage : la fenêtre et le mini-panneau n'ont pas la
  // même origine (CLAUDE.md §3).
  const [accueilCompte, setAccueilCompte] = useState<'verification' | 'afficher' | 'passer'>(
    () => (isTauri() && !estCompact ? 'verification' : 'passer'),
  );
  useEffect(() => {
    if (!setupDone || accueilCompte !== 'verification') return;
    const controle = new AbortController();
    // Le budget épuisé fait passer l'app ; un démontage (double montage de
    // StrictMode compris) ne décide RIEN — sinon le premier montage, annulé,
    // concluait « passer » avant que le second ait lu le statut.
    let demonte = false;
    const minuteur = setTimeout(() => controle.abort(), ACCUEIL_COMPTE_BUDGET_MS);
    lireStatutCompte(controle.signal)
      .then((statut) => {
        if (!demonte) setAccueilCompte(doitAfficherAccueil(statut, true) ? 'afficher' : 'passer');
      })
      .catch(() => {
        if (!demonte) setAccueilCompte('passer');
      })
      .finally(() => clearTimeout(minuteur));
    return () => {
      demonte = true;
      clearTimeout(minuteur);
      controle.abort();
    };
  }, [setupDone, accueilCompte]);
  const fermerAccueilCompte = useCallback(() => setAccueilCompte('passer'), []);

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
    // Et à la coquille du téléphone, qui peint la barre d'état et ses écrans
    // natifs (26/09/2026). Sans réponse, rien ne casse : la coquille garde
    // son dernier thème connu.
    if (estMobile) {
      const skin = settings.terminalSkin ?? 'phosphor';
      const envoyer = () =>
        void demanderAuTelephone('theme', lireChargeThemeNatif(settings.theme, skin)).catch(() => {});
      envoyer();
      // En « système », l'apparence suit Android : la barre doit suivre aussi.
      if (settings.theme === 'system') {
        try {
          const requete = window.matchMedia('(prefers-color-scheme: dark)');
          requete.addEventListener('change', envoyer);
          return () => requete.removeEventListener('change', envoyer);
        } catch {
          // Pas de matchMedia : le thème envoyé ci-dessus reste le dernier.
        }
      }
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

  // Au téléphone, les pages se préchargent pendant les creux, une fois
  // l'ouverture passée, et se taisent pendant chaque navigation
  // (lib/prechargerPages.ts, 26/09/2026). Le Mac lit ses morceaux sur le
  // disque : rien à y gagner, rien n'y change.
  const piloteRef = useRef<ReturnType<typeof piloterPrechargement> | null>(null);
  useEffect(() => {
    if (!estMobile) return;
    const pilote = piloterPrechargement(PAGES_A_PRECHARGER, optionsDuNavigateur());
    piloteRef.current = pilote;
    if (document.readyState === 'complete') pilote.demarrer();
    else window.addEventListener('load', pilote.demarrer, { once: true });
    return () => {
      window.removeEventListener('load', pilote.demarrer);
      pilote.arreter();
      piloteRef.current = null;
    };
  }, []);
  // Chaque changement de page (pas le premier rendu) met le préchargement
  // en pause : la page demandée a le lien pour elle seule.
  const cheminPrecedent = useRef(pathname);
  useEffect(() => {
    if (cheminPrecedent.current === pathname) return;
    cheminPrecedent.current = pathname;
    piloteRef.current?.navigation();
  }, [pathname]);

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
  // Au téléphone, pas écran éteint ou app en arrière-plan : chaque relève
  // réveille la radio 4G pour un compteur que personne ne regarde
  // (26/09/2026, chantier de la fluidité).
  useEffect(() => {
    const refresh = () => {
      if (estMobile && document.visibilityState === 'hidden') return;
      fetchSavings()
        .then(setSavings)
        .catch(() => {});
    };
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

  // Habit OS reminders (desktop only; in-process timers + Tauri notify).
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

  if (accueilCompte === 'verification') {
    return <div className="fixed inset-0" style={{ background: 'var(--color-bg)' }} aria-busy="true" />;
  }

  if (accueilCompte === 'afficher') {
    return (
      <ConfirmProvider>
        <EcranCompte contexte="accueil" onFermer={fermerAccueilCompte} />
      </ConfirmProvider>
    );
  }

  return (
    <ModeGestesProvider>
    <ConfirmProvider>
      <Suspense fallback={<div role="status" className="p-6" data-chargement="">Chargement…</div>}>
        <TalkToDiapasonHost>
        <Routes>
          <Route element={<MesureDeRoute><Layout /></MesureDeRoute>}>
            <Route index element={<ChatPage />} />
            <Route path="dashboard" element={<DashboardPage />} />
            <Route path="settings" element={<SettingsPage />} />
            <Route path="get-started" element={<GetStartedPage />} />
            <Route path="data-sources" element={<DataSourcesPage />} />
            <Route path="agents" element={<AgentsPage />} />
            <Route path="logs" element={<LogsPage />} />
            {PAGES_VIE.map((page) => (
              <Route
                key={page}
                path={`vie/${page}`}
                element={
                  <PageAffichee chemin={`/vie/${page}`}>{PAGES_VIE_ELEMENTS[page]}</PageAffichee>
                }
              />
            ))}
            <Route path="vie/templates" element={<Navigate to="/vie/tasks" replace />} />
            <Route path="succes" element={<RedirectionHeritee />} />
            <Route path="succes/*" element={<RedirectionHeritee />} />
            <Route path="devices" element={<DevicesPage />} />
          </Route>
        </Routes>
        </TalkToDiapasonHost>
      </Suspense>
      {/* En bas à droite, les toasts couvraient le compositeur et le bas de
          chaque module dans le mini-panneau (16 sept. 2026). Le sens de la
          pile (`data-y-position` sur chaque toast) est décidé ici par sonner :
          le CSS seul ne pouvait pas la retourner ; index.css cale ensuite les
          toasts sous la bande de glissement et borne leur largeur. */}
      {/* Au téléphone, en bas au centre et AU-DESSUS du bouton « Aller à… »
          (76 px = la bande de la roue, 68, et 8 d'air ; 26/09/2026) : en bas
          à droite, un toast couvrait le bouton pendant quatre secondes. */}
      <Toaster
        position={estCompact ? 'top-center' : estMobile ? 'bottom-center' : 'bottom-right'}
        {...(estMobile ? { offset: { bottom: 76 }, mobileOffset: { bottom: 76 } } : {})}
      />
      {/* Seule la fenêtre du Mac vide la boîte du maillage et publie sa vue
          (lib/hotesDuMac.ts, 26/09/2026). */}
      {HOTES.boiteDuMaillage && <MeshHost />}
      {/* Au téléphone, c'est la coquille qui reçoit les commandes du maillage
          et demande l'écran ici (verbe « naviguer », 26/09/2026). */}
      {estMobile && <NavigationDuTelephone />}
      {/* Et un « Partager vers Diapason » fait depuis une autre app (verbe
          « partager », phase 5). */}
      {estMobile && <PartageDuTelephone />}
      {HOTES.contexteDeLaVue && <ContexteVueHost />}
      <VoyantGestes />
      {commandPaletteOpen && <CommandPalette />}
    </ConfirmProvider>
    </ModeGestesProvider>
  );
}
