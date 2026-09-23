import { readFileSync } from 'fs';
import path from 'path';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { VitePWA } from 'vite-plugin-pwa';

// Single source of truth for the version shown in the UI. It was hard-coded
// as "v2.8" in GetStartedPage while package.json and tauri.conf.json both said
// 1.0.1 — a number no build could ever correct, because nothing linked them.
const pkgVersion = JSON.parse(
  readFileSync(path.resolve(__dirname, 'package.json'), 'utf-8'),
).version as string;

const isTauriBuild =
  process.env.npm_lifecycle_event === 'build:tauri' ||
  Boolean(process.env.TAURI_ENV_PLATFORM);

// L'empreinte du build, pour le cache client des pages Succès
// (features/succes/cacheSucces.ts) : nouvelle à chaque `npm run build` et à
// chaque démarrage du serveur Vite. La version seule ne suffisait pas —
// « 1.0.4 » pour 44 builds d'affilée, et un cache écrit par l'un était relu
// tel quel par tous les autres (revue du cache, 18 sept. 2026).
const buildStamp = `${pkgVersion}-${Date.now().toString(36)}`;

export default defineConfig({
  define: {
    __APP_VERSION__: JSON.stringify(pkgVersion),
    __BUILD_STAMP__: JSON.stringify(buildStamp),
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  plugins: [
    react(),
    tailwindcss(),
    // Desktop embeds assets directly — the Workbox SW step is unused there and
    // has been aborting the Vite close hook (terser) on this machine.
    !isTauriBuild &&
      VitePWA({
        registerType: 'autoUpdate',
        manifest: {
          name: 'Diapason',
          short_name: 'Diapason',
          description: 'On-device AI assistant',
          theme_color: '#161618',
          background_color: '#161618',
          display: 'standalone',
          icons: [
            { src: 'pwa-192x192.png', sizes: '192x192', type: 'image/png' },
            { src: 'pwa-512x512.png', sizes: '512x512', type: 'image/png' },
          ],
        },
        workbox: {
          globPatterns: ['**/*.{js,css,html,ico,png,svg}', 'fonts/visuels/*.ttf'],
          navigateFallbackDenylist: [/^\/v1\//, /^\/health/, /^\/dashboard/, /^\/api\//],
        },
      }),
  ].filter(Boolean),
  build: {
    outDir: '../src/diapason/server/static',
    emptyOutDir: true,
    minify: 'esbuild',
    rollupOptions: {
      output: {
        manualChunks: {
          react: ['react', 'react-dom'],
          markdown: ['react-markdown', 'rehype-highlight', 'remark-gfm'],
          charts: ['recharts'],
          router: ['react-router'],
          // Three is only ever needed once the voice panel opens; keeping it
          // out of the entry chunk means the app still starts on one request.
          three: ['three'],
        },
      },
    },
  },
  // Vitest tournait sans bloc `test`, donc en environnement `node`, donc SANS
  // `DOMParser`. `sanitizeNoteHtml` partait alors dans son `catch` et rendait
  // du texte nu : `<p><b>gras</b></p>` ressortait « gras ». Ses onze tests
  // passaient en deux millisecondes sans jamais exécuter la liste blanche —
  // y compris celui qui garantit que les gouttières de pagination ne sont
  // jamais enregistrées dans une note. Un filet qui ne touchait pas le sol.
  test: {
    environment: 'jsdom',
  },
  server: {
    port: 5173,
    proxy: {
      // ws: true is required for the /v1/agents/events WebSocket. Without it
      // Vite proxies the HTTP request but not the upgrade, so the socket never
      // opens — no error, no close event, just silence — and every live agent
      // view sits empty in dev while working in a production build.
      '/v1': {
        target: process.env.VITE_API_URL || 'http://localhost:8000',
        changeOrigin: true,
        ws: true,
      },
      '/health': process.env.VITE_API_URL || 'http://localhost:8000',
      '/api': process.env.VITE_API_URL || 'http://localhost:8000',
    },
  },
});
