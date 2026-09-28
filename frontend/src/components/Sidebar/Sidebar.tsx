import { useEffect, useLayoutEffect, useRef, useState } from 'react';
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
  Trophy,
  MonitorSmartphone,
  RefreshCw,
  ChevronLeft,
  ChevronRight,
  MessagesSquare,
  HardDrive,
} from 'lucide-react';
import { ConversationList } from './ConversationList';
import { GlassNav } from './GlassNav';
import { PanneauEspaces } from './PanneauEspaces';
import { PanneauContextuel } from './PanneauContextuel';
import { rubriqueDuChemin, correspondALaRecherche, panneauDisponible, panneauVisible, type Rubrique } from './navigation';
import { useHistoriqueNavigation } from './useHistoriqueNavigation';
import './Navigation.css';
import { TalkButton } from '../TalkButton';
import { BandeauMiseAJour } from '../Desktop/BandeauMiseAJour';
import { useAppStore, type ThemeMode, type TerminalSkin } from '../../lib/store';
import { useTranslation } from '../../i18n/useTranslation';
import { demanderLeFocusDuCompositeur } from '../../lib/panneau';
import {
  appliquerNavigation,
  barreSuperposee,
  estCheminDesReglages,
  inscrireRetourBarre,
} from '../../lib/barre';
import { pontNatif } from '../../lib/natif';

/** Ce que la fenêtre sait de sa largeur, en CSS — jamais `innerWidth`. */
function lireSuperposee(): boolean {
  return barreSuperposee(
    typeof window !== 'undefined' && window.matchMedia ? window.matchMedia.bind(window) : undefined,
  );
}

export function Sidebar() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const [searchQuery, setSearchQuery] = useState('');
  // ChatGPT-style: a magnifier in the header, the input appears on demand.
  const [searchOpen, setSearchOpen] = useState(false);
  const onSettingsRoute = estCheminDesReglages(location.pathname);

  const rubrique = rubriqueDuChemin(location.pathname);
  const historique = useHistoriqueNavigation();
  const rechercheRef = useRef<HTMLInputElement>(null);
  const boutonRechercheRef = useRef<HTMLButtonElement>(null);
  const sidebarOpen = useAppStore((s) => s.sidebarOpen);
  const panneauOuvert = panneauVisible(sidebarOpen, location.pathname);
  const aUnPanneau = panneauDisponible(location.pathname);
  const setSidebarOpen = useAppStore((s) => s.setSidebarOpen);
  const toggleSidebar = useAppStore((s) => s.toggleSidebar);
  const nouvelleDiscussion = useAppStore((s) => s.nouvelleDiscussion);
  const selectedModel = useAppStore((s) => s.selectedModel);

  const settings = useAppStore((s) => s.settings);
  const updateSettings = useAppStore((s) => s.updateSettings);

  // Les fenêtres modales se centrent dans ce qui reste à droite de la barre
  // (`.voile-modal`, index.css) : elles doivent savoir si elle est ouverte.
  // Avant la peinture : le dégagement du bouton flottant
  // (`--degagement-barre-fermee`) en dépend, et un effet ordinaire laissait
  // l'en-tête de la Discussion sauter de 60 px au premier affichage.
  useLayoutEffect(() => {
    document.documentElement.dataset.navigationRail = '1';
    if (panneauOuvert) document.documentElement.dataset.barre = 'ouverte';
    else delete document.documentElement.dataset.barre;
    return () => { delete document.documentElement.dataset.navigationRail; delete document.documentElement.dataset.barre; };
  }, [panneauOuvert]);

  // 28/09/2026 : un changement de rubrique rouvrait le panneau malgré
  // le choix de Carlito. Seule la sélection d'un élément dans la même
  // rubrique replie encore le tiroir étroit ; changer d'onglet garde le choix.
  const derniereNavigation = useRef({ cle: location.key, chemin: location.pathname });
  useEffect(() => {
    const precedente = derniereNavigation.current;
    if (precedente.cle === location.key) return;
    derniereNavigation.current = { cle: location.key, chemin: location.pathname };
    setSearchQuery('');
    setSearchOpen(false);
    if (precedente.chemin === location.pathname) appliquerNavigation(useAppStore.getState(), {
      superposee: lireSuperposee(),
      avant: precedente.chemin,
      apres: location.pathname,
    });
  }, [location.key, location.pathname]);

  // Le bouton retour d'Android ferme d'abord le tiroir (verbe `retour` de la
  // coquille) ; sans quoi il quittait la page sous le voile, tiroir resté
  // ouvert. Hors du téléphone, `pontNatif` est nul et rien ne s'inscrit.
  useEffect(() => inscrireRetourBarre(pontNatif, useAppStore.getState, lireSuperposee), []);

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

  const handleNewChat = () => {
    // The button always lands on a fresh chat. Reusing an existing empty
    // conversation (instead of silently doing nothing, the old behavior)
    // keeps the list free of stacked blanks while never ignoring a click.
    // 17 sept. 2026 : la règle de la vierge vivait ici, en ligne — le ＋ du
    // mini-panneau et ⌘N ne pouvaient pas la partager. Elle est dans le
    // store (nouvelleDiscussion → lib/discussions.trouverDiscussionVierge).
    nouvelleDiscussion(selectedModel);
    navigate('/');
    // Depuis un autre module, la Discussion n'est pas encore montée : la
    // demande est gardée par lib/panneau.ts et relue par le compositeur à son
    // montage (contre-revue du 17 sept. 2026 — le focus restait sur ce bouton).
    demanderLeFocusDuCompositeur();
  };

  // The page the drawer interrupted, so closing it can hand the view back.
  const routeBeforeSettings = useRef<string | null>(null);

  const openSettings = () => {
    setSearchOpen(false);
    setSearchQuery('');
    // Land on Général so the drawer never opens onto a blank pane.
    if (!onSettingsRoute) {
      routeBeforeSettings.current = location.pathname;
    }
    if (location.pathname !== '/settings') navigate('/settings');
  };

  const closeSettings = () => {
    const back = routeBeforeSettings.current;
    routeBeforeSettings.current = null;
    // Leaving the drawer has to move the content too: the sidebar was showing
    // the app again while the pane still displayed Réglages. Deep links have no
    // page to return to, so they fall back to the chat.
    if (onSettingsRoute) {
      navigate(back && !estCheminDesReglages(back) ? back : '/');
    }
  };

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
        { path: '/vie/sync', icon: RefreshCw, label: t('nav.vieSync') },
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

  const principaux = [
    { id: 'discussion', path: '/', icon: MessagesSquare, label: t('nav.chat') },
    { id: 'projets', path: '/vie/projects', icon: BriefcaseBusiness, label: t('nav.vieProjects') },
    { id: 'notes', path: '/vie/notes', icon: NotebookPen, label: t('nav.vieNotes') },
    { id: 'taches', path: '/vie/tasks', icon: ListTodo, label: t('nav.vieTasks') },
    { id: 'agenda', path: '/vie/planner', icon: CalendarRange, label: t('nav.viePlanner') },
    { id: 'tableau', path: '/vie/dashboard', icon: LayoutDashboard, label: t('nav.vieDashboard') },
    { id: 'finances', path: '/vie/finances', icon: Wallet, label: t('nav.vieFinances') },
    { id: 'habitudes', path: '/vie/habits', icon: Repeat2, label: t('nav.vieHabits') },
    { id: 'bilan', path: '/vie/year-review', icon: Trophy, label: t('nav.vieYearReview') },
  ] as const;
  const titres: Record<Rubrique, string> = {
    discussion: 'Diapason', projets: t('nav.vieProjects'),
    notes: t('nav.vieNotes'), taches: t('nav.vieTasks'), agenda: t('nav.viePlanner'),
    tableau: t('nav.vieDashboard'), finances: t('nav.vieFinances'),
    habitudes: t('nav.vieHabits'), bilan: t('nav.vieYearReview'), reglages: t('nav.settings'),
  };
  const choisirRubrique = (chemin: string) => {
    setSearchOpen(false);
    setSearchQuery('');
    if (chemin !== location.pathname) navigate(chemin);
  };
  const fermerRecherche = () => {
    setSearchOpen(false);
    setSearchQuery('');
    boutonRechercheRef.current?.focus();
  };
  const basculerRecherche = () => {
    if (searchOpen) fermerRecherche();
    else { setSearchOpen(true); requestAnimationFrame(() => rechercheRef.current?.focus()); }
  };
  const choixDePage = (chemin: string) => {
    navigate(chemin);
    if (lireSuperposee()) setSidebarOpen(false);
  };

  return (
    <aside className="navigation-diapason" data-ouvert={panneauOuvert} aria-label="Navigation Diapason">
      <nav className="navigation-rail" aria-label="Rubriques principales">
        <button className="navigation-rail-bouton navigation-bascule" onClick={toggleSidebar} disabled={!aUnPanneau}
          title={!aUnPanneau ? 'Aucun panneau complémentaire pour cette rubrique' : panneauOuvert ? t('sidebar.collapse') : t('sidebar.expand')}
          aria-label={!aUnPanneau ? 'Aucun panneau complémentaire pour cette rubrique' : panneauOuvert ? t('sidebar.collapse') : t('sidebar.expand')}
          aria-expanded={panneauOuvert} aria-controls="navigation-panneau">
          {panneauOuvert ? <PanelLeftClose size={20} /> : <PanelLeft size={20} />}
        </button>
        <div className="navigation-rail-rubriques">
          {principaux.map(({ id, path, icon: Icon, label }) => (
            <button key={id} className="navigation-rail-bouton" aria-label={label} title={label}
              aria-pressed={rubrique === id} onClick={() => choisirRubrique(path)}>
              <Icon size={21} />
            </button>
          ))}
        </div>
        <div className="navigation-rail-pied">
          <button className="navigation-rail-bouton" onClick={() => {
            openSettings();
          }} aria-label={t('nav.settings')} title={t('nav.settings')} aria-pressed={rubrique === 'reglages'}>
            <Settings size={21} />
          </button>
          <button className="navigation-rail-bouton" onClick={() => updateSettings(nextStop.skin
            ? { theme: nextStop.theme, terminalSkin: nextStop.skin } : { theme: nextStop.theme })}
            aria-label={t('sidebar.themeTooltip', { current: themeName({ theme: settings.theme, skin: activeSkin }), next: themeName(nextStop) })}
            title={t('sidebar.themeTooltip', { current: themeName({ theme: settings.theme, skin: activeSkin }), next: themeName(nextStop) })}>
            <ThemeIcon size={19} />
          </button>
        </div>
      </nav>
      {panneauOuvert && <section id="navigation-panneau" className="navigation-panneau" aria-label={titres[rubrique]}>
        <div className="navigation-historique">
          <button className="navigation-icone" onClick={() => historique.aller(-1)} disabled={!historique.precedent} aria-label="Précédent" title="Précédent"><ChevronLeft size={18} /></button>
          <button className="navigation-icone" onClick={() => historique.aller(1)} disabled={!historique.suivant} aria-label="Suivant" title="Suivant"><ChevronRight size={18} /></button>
          <span>Diapason</span>
        </div>
        <div className="navigation-entete">
          <div className="navigation-titre">{titres[rubrique]}</div>
          <button ref={boutonRechercheRef} className="navigation-icone" onClick={basculerRecherche}
            aria-label="Rechercher dans cette rubrique" title="Rechercher dans cette rubrique"
            aria-expanded={searchOpen} aria-controls="navigation-recherche"><Search size={18} /></button>
        </div>
        {searchOpen && <div className="navigation-recherche" id="navigation-recherche">
          <Search size={15} aria-hidden="true" />
          <input ref={rechercheRef} type="search" value={searchQuery} placeholder="Rechercher…" aria-label="Rechercher dans cette rubrique"
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); fermerRecherche(); } }} />
        </div>}
        {rubrique === 'discussion' && <button className="navigation-nouvelle" onClick={handleNewChat}>
          <Plus size={18} />{t('sidebar.newChat')}
        </button>}
        <div className="navigation-contenu">
          {rubrique === 'discussion' && <>
            <ConversationList searchQuery={searchQuery} />
          </>}
          {(rubrique === 'projets' || rubrique === 'notes') && <>
            <button className="navigation-ligne navigation-tout" onClick={() => choixDePage(rubrique === 'projets' ? '/vie/projects' : '/vie/notes')}>
              {rubrique === 'projets' ? <BriefcaseBusiness size={17} /> : <NotebookPen size={17} />}
              <span>{rubrique === 'projets' ? 'Tous les projets' : 'Toutes les notes'}</span>
            </button>
            <PanneauEspaces key={rubrique} mode={rubrique} recherche={searchQuery} />
          </>}
          {rubrique === 'reglages' && <div id="settings-nav">
            <button onClick={closeSettings} className="navigation-ligne"><ChevronLeft size={16} /><span>{t('sidebar.settingsBack')}</span></button>
            {settingsGroups.map((group) => {
              const items = group.items.filter((item) => correspondALaRecherche(item.label, searchQuery));
              return items.length ? <div key={group.label}><div className="navigation-section-entete">{group.label}</div><GlassNav items={items} groupLabel={group.label} /></div> : null;
            })}
          </div>}
          {['agenda', 'taches', 'finances'].includes(rubrique) && <PanneauContextuel chemin={location.pathname} recherche={searchQuery} />}
        </div>
        <BandeauMiseAJour />
        <footer className="navigation-pied">
          <div><HardDrive size={13} /><span>Ton espace Diapason</span></div>
          <TalkButton />
        </footer>
      </section>}
    </aside>
  );
}
