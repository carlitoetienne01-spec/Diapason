// Inlines the built overlay bundle into a single HTML file inside the Python
// package. One file means the dictation service can load it with a plain
// file URL and nothing else has to exist on disk.
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const js = readFileSync(resolve(here, '../.overlay-build/overlay.js'), 'utf-8');
const out = resolve(here, '../../src/diapason/desktop/overlay_page.html');

// A literal </script> inside the bundle would close the tag early. Minified
// three does not contain one today, but the failure would be silent and total.
const safe = js.replace(/<\/script/gi, '<\\/script');

mkdirSync(dirname(out), { recursive: true });
writeFileSync(
  out,
  `<!doctype html>
<html lang="fr">
<head>
<meta charset="UTF-8" />
<title>Diapason — dictation overlay</title>
<style>
html,body{margin:0;height:100%;background:transparent;overflow:hidden}
body{-webkit-user-select:none;user-select:none}
</style>
</head>
<body>
<script>${safe}</script>
</body>
</html>
`,
  'utf-8',
);
console.log(`overlay_page.html ecrit (${(js.length / 1024).toFixed(0)} Ko de JS inline)`);
