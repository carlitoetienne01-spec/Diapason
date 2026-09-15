// Le mode compact — quand l'app est chargée dans le mini-panneau de la
// réglette (l'onglet de bord d'écran). Le mini-panneau ouvre le VRAI module
// dans une WKWebView native ; son WKUserScript pose, au tout début du document
// (avant que ce bundle ne s'exécute), l'attribut `data-diapason-compact="1"`
// sur <html> et `window.__DIAPASON_COMPACT__`. En compact, le chrome (barre
// latérale, en-tête, bandeau santé) disparaît : le panneau ne montre que le
// module. Le drapeau ne change pas d'une session à l'autre — on le lit UNE
// fois, sans course ni scintillement.

function lireCompact(): boolean {
  if (typeof document === 'undefined') return false;
  const parAttribut =
    document.documentElement.getAttribute('data-diapason-compact') === '1';
  const parGlobale =
    (window as unknown as { __DIAPASON_COMPACT__?: boolean }).__DIAPASON_COMPACT__ === true;
  let parRequete = false;
  try {
    parRequete = new URLSearchParams(window.location.search).has('compact');
  } catch {
    parRequete = false;
  }
  return parAttribut || parGlobale || parRequete;
}

export const estCompact = lireCompact();

// Quel que soit le chemin d'entrée (WKUserScript, globale, ?compact en
// navigateur), le drapeau finit sur <html> : LE sélecteur CSS unique — le
// variant Tailwind `compact:` et la réserve `--surplomb-panneau` (index.css)
// s'appuient dessus. Sans cette normalisation, le banc `?compact=1` n'avait
// pas l'attribut et le CSS compact ne s'y appliquait pas.
if (estCompact && typeof document !== 'undefined') {
  document.documentElement.setAttribute('data-diapason-compact', '1');
}
