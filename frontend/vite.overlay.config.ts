import path from 'path';
import { defineConfig } from 'vite';

/**
 * Builds the dictation overlay as ONE self-contained script.
 *
 * Library mode rather than an HTML entry: the result must be inlined into a
 * single file that ships inside the Python package, because the dictation
 * service is a separate process that cannot depend on the frontend having
 * been built, nor on a chunk sitting next to it on disk.
 */
export default defineConfig({
  build: {
    lib: {
      entry: path.resolve(__dirname, 'src/overlay-entity.ts'),
      formats: ['iife'],
      name: 'DiapasonOverlay',
      fileName: () => 'overlay.js',
    },
    outDir: '.overlay-build',
    emptyOutDir: true,
    minify: 'esbuild',
  },
});
