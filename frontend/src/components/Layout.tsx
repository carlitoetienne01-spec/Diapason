import { useCallback, useEffect, useRef, useState } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router';
import { ApprovalBell } from './ApprovalBell';
import { Sidebar } from './Sidebar/Sidebar';
import { panneauVisible } from './Sidebar/navigation';
import { SystemPulse } from './SystemPulse';
import { useAppStore } from '../lib/store';
import { checkHealth } from '../lib/api';
import { estCompact } from '../lib/compact';
import { estMobile } from '../lib/natif';
import { RoueNavigation } from '../features/roue/RoueNavigation';
import { signalerPanneauOuvert } from '../lib/panneau';
import { titreDiscussion } from '../lib/discussions';
import { useTranslation } from '../i18n/useTranslation';
import { useSondeVisible } from '../lib/useSondeVisible';
import { BandeauCompte } from '../features/compte/BandeauCompte';

export function Layout() {
  const { t } = useTranslation();
  const sidebarOpen = useAppStore((s) => s.sidebarOpen);
  const [apiReachable, setApiReachable] = useState<boolean | null>(null);
  const verifierSante = useCallback(async (signal: AbortSignal) => {
    const disponible = await checkHealth(signal);
    if (!signal.aborted) setApiReachable(disponible);
  }, []);
  useSondeVisible(verifierSante, 30000, !estCompact);

  useEffect(() => {
    // En compact (mini-panneau), pas de sonde santé ni de bandeau : la surface
    // ne montre que le module.
    if (estCompact) {
      // 17 sept. 2026 : Rust signale « panneau ouvert » à chaque
      // présentation, mais la première tombe sur un document encore vide
      // (le bundle n'a pas chargé). Le seul lecteur du mode compact rejoue
      // donc le signal une fois monté — après les effets des pages, qui
      // écoutent déjà — pour que le compositeur ait le curseur dès le
      // premier chargement.
      signalerPanneauOuvert();
      return;
    }
  }, []);

  const navigate = useNavigate();
  const topRightRef = useRef<HTMLDivElement>(null);

  // 17 sept. 2026, chantier « discussions dans le mini-panneau » : réduit en
  // pastille, le panneau disait « Discussion » quel que soit le fil. Le script
  // natif (lib.rs, __diapReduit) lit maintenant `document.title` quand le
  // chemin est « / » ; le bundle y pose le titre du fil actif. Ici et pas
  // dans ChatArea : Layout est le seul lecteur du mode compact (convention),
  // et la fenêtre principale garde son titre — Tauri n'y suit pas le document.
  // Le sélecteur rend une chaîne : Layout ne se re-rend que quand le titre
  // change, pas à chaque message ajouté.
  const { pathname } = useLocation();
  const titreFil = useAppStore((s) => titreDiscussion(s.conversations, s.activeId, t));
  useEffect(() => {
    if (!estCompact) return;
    document.title = pathname === '/' ? titreFil : 'Diapason';
  }, [pathname, titreFil]);

  // The cluster floats over every page, so its width is published as a token
  // rather than duplicated as a magic number wherever content has to clear it.
  useEffect(() => {
    const node = topRightRef.current;
    if (!node) return;
    const publish = () =>
      document.documentElement.style.setProperty('--top-right-cluster', `${node.offsetWidth}px`);
    publish();
    const observer = new ResizeObserver(publish);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  // Surface compacte du mini-panneau : uniquement le verre + le module, sans
  // barre latérale, sans en-tête « Diapason », sans bandeau. Le routage et le
  // thème restent intacts (les classes de thème vivent sur <html>, posées par
  // main.tsx). §82 : rien ne devient geste-only, toutes les routes restent
  // atteignables par URL.
  if (estCompact) {
    return (
      <div className="flex flex-col h-full w-full overflow-hidden relative">
        <div className="hud-backdrop" aria-hidden="true" />
        <main
          className="flex-1 flex flex-col min-w-0 h-full relative overflow-hidden z-[2]"
          // La barre de glissement injectée par le panneau natif recouvre les
          // ~24 px du haut : on les réserve, sinon l'en-tête passe dessous.
          style={{ background: 'transparent', paddingTop: 'var(--surplomb-panneau, 0px)' }}
        >
          {/* D14 (compte-chiffre.md §3.11) : le mini-panneau montre l'état du
              compte et permet de le déverrouiller — seul bandeau admis ici,
              et seulement quand il a quelque chose à dire. */}
          <BandeauCompte compact />
          <Outlet />
        </main>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full w-full overflow-hidden relative" style={{ paddingTop: '3px' }}>
      <div className="hud-backdrop" aria-hidden="true" />
      <SystemPulse apiReachable={apiReachable} />

      <div ref={topRightRef} className="fixed top-2 right-3 z-40 flex items-center gap-1.5">
        <ApprovalBell />
      </div>

      {/* Health check banner */}
      {apiReachable === false && (
        <div
          className="flex items-center gap-3 px-4 py-2 text-sm shrink-0"
          style={{
            background: 'color-mix(in srgb, var(--color-error) 8%, transparent)',
            borderBottom: '1px solid color-mix(in srgb, var(--color-error) 15%, transparent)',
            color: 'var(--color-text)',
          }}
        >
          <span
            className="w-1.5 h-1.5 rounded-full shrink-0"
            style={{ background: 'var(--color-error)' }}
          />
          <span>{t('common.backendUnreachable')}</span>
          <button
            onClick={() => navigate('/settings')}
            className="text-sm underline cursor-pointer ml-auto shrink-0"
            style={{ color: 'var(--color-accent)' }}
          >
            {t('common.changeUrl')}
          </button>
        </div>
      )}

      <BandeauCompte />

      <div className="flex flex-1 min-h-0 relative z-10">
        {/* Au téléphone, la roue remplace la barre (26/09/2026, lot 3) : le
            tiroir de 260 px et son voile n'y sont plus montés du tout. */}
        {!estMobile && <Sidebar />}
        {!estMobile && panneauVisible(sidebarOpen, pathname) && (
          <div
            className="fixed inset-0 z-20 bg-black/40 md:hidden"
            onClick={() => useAppStore.getState().setSidebarOpen(false)}
          />
        )}
        <main className="flex-1 flex flex-col min-w-0 h-full relative overflow-hidden" style={{ background: 'transparent' }}>
          {/* La Discussion réserve la place du bouton de la barre dans son
              propre en-tête ; les autres pages reçoivent une bande au-dessus
              d'elles (index.css, `--bande-barre-fermee`). */}
          <div
            data-colonne-page=""
            className="flex-1 flex flex-col min-w-0 min-h-0 relative z-[2]"
            style={{
              paddingTop: pathname === '/' ? 0 : 'var(--bande-barre-fermee, 0px)',
              // Au téléphone, la bande du bouton « Aller à… » n'est réservée
              // AUTOUR de la page que sur la Discussion, pour le compositeur.
              // Ailleurs, elle vit DANS le défileur de la page (index.css) :
              // le contenu passe sous le bouton en défilant et ne s'arrête
              // au-dessus qu'en fin de liste. 26/09/2026, contre-épreuve :
              // réservée autour, c'était 68 px morts en bas de chaque page,
              // où aucun glissé ne faisait défiler (scrollTop 0 depuis
              // (200, 760) sur 12 pages).
              paddingBottom: estMobile && pathname === '/' ? 'var(--reserve-roue, 0px)' : undefined,
            }}
          >
            <Outlet />
          </div>
        </main>
      </div>
      {estMobile && <RoueNavigation />}
    </div>
  );
}
