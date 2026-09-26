/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

// Injected by vite.config.ts from package.json — the single source of
// truth for the version shown in the UI.
declare const __APP_VERSION__: string;

// Injected by vite.config.ts: the package version followed by the build
// instant, new on every build and every Vite start. The vie client cache (cacheVie.ts)
// stamps its entries with it and discards what another build wrote.
declare const __BUILD_STAMP__: string;

// Injected by vite.config.ts: true when the build ships a service worker
// (the PWA plugin), false for the Tauri build. main.tsx registers it.
declare const __PWA_ACTIF__: boolean;
