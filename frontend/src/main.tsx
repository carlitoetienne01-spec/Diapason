import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { TranslationProvider } from './i18n/useTranslation';
import { BrowserRouter } from 'react-router';
import { ErrorBoundary } from './components/ErrorBoundary';
import App from './App';
import { initApiBase } from './lib/api';
import { initAnalytics } from './lib/analytics';
import '@fontsource/press-start-2p';
import '@fontsource/vt323';
import './index.css';

function applyTheme() {
  try {
    const raw = localStorage.getItem('diapason-settings');
    const settings = raw ? JSON.parse(raw) : {};
    const theme = settings.theme || 'system';
    if (theme === 'dark') {
      document.documentElement.classList.add('dark');
      document.documentElement.classList.remove('light');
    } else if (theme === 'light') {
      document.documentElement.classList.add('light');
      document.documentElement.classList.remove('dark');
    } else if (theme === 'terminal') {
      // Ardéchine is a reflective screen: dark ink on a pale panel, so it rides
      // with `.light`. Kept in sync with `isLightTerminalSkin` in the store —
      // duplicated rather than imported because this runs before any module
      // graph is loaded, to avoid a flash of the wrong palette.
      const skin = settings.terminalSkin || 'phosphor';
      const light = skin === 'ardechine';
      document.documentElement.classList.add(light ? 'light' : 'dark', 'terminal');
      document.documentElement.classList.remove(light ? 'dark' : 'light');
      document.documentElement.dataset.terminalSkin = skin;
    }
    // Applied before first paint so the UI never flashes at the wrong scale.
    const fontSize = settings.fontSize;
    if (fontSize === 'small' || fontSize === 'large') {
      document.documentElement.dataset.fontSize = fontSize;
    }
  } catch { /* use system default */ }
}

applyTheme();

// Fetch the API base URL from the Tauri backend before rendering.
// This keeps the API port and generated local credential in the Rust backend.
// In non-Tauri environments this is a no-op.
initApiBase().finally(() => {
  // Kick off analytics init in the background — it's never awaited so
  // a slow/failed identity fetch never delays UI render.
  void initAnalytics();

  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      {/* The provider wraps the boundary, not the other way round: the
          boundary's own "something went wrong" screen is the one moment the
          user most needs to be spoken to in their language. */}
      <TranslationProvider>
        <ErrorBoundary>
          <BrowserRouter>
            <App />
          </BrowserRouter>
        </ErrorBoundary>
      </TranslationProvider>
    </StrictMode>,
  );
});
