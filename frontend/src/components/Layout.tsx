import { useEffect, useRef, useState } from 'react';
import { Outlet, useNavigate } from 'react-router';
import { ApprovalBell } from './ApprovalBell';
import { Sidebar } from './Sidebar/Sidebar';
import { SystemPulse } from './SystemPulse';
import { useAppStore } from '../lib/store';
import { checkHealth } from '../lib/api';
import { estCompact } from '../lib/compact';
import { useTranslation } from '../i18n/useTranslation';

export function Layout() {
  const { t } = useTranslation();
  const sidebarOpen = useAppStore((s) => s.sidebarOpen);
  const [apiReachable, setApiReachable] = useState<boolean | null>(null);

  useEffect(() => {
    // En compact (mini-panneau), pas de sonde santé ni de bandeau : la surface
    // ne montre que le module.
    if (estCompact) return;
    const check = () => checkHealth().then(setApiReachable);
    check();
    const interval = setInterval(check, 30000);
    const onFocus = () => check();
    window.addEventListener('focus', onFocus);
    return () => {
      clearInterval(interval);
      window.removeEventListener('focus', onFocus);
    };
  }, []);

  const navigate = useNavigate();
  const topRightRef = useRef<HTMLDivElement>(null);

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

      <div className="flex flex-1 min-h-0 relative z-10">
        <Sidebar />
        {sidebarOpen && (
          <div
            className="fixed inset-0 z-20 bg-black/40 md:hidden"
            onClick={() => useAppStore.getState().setSidebarOpen(false)}
          />
        )}
        <main className="flex-1 flex flex-col min-w-0 h-full relative overflow-hidden" style={{ background: 'transparent' }}>
          <div className="flex-1 flex flex-col min-w-0 min-h-0 relative z-[2]">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
