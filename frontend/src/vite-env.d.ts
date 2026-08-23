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
