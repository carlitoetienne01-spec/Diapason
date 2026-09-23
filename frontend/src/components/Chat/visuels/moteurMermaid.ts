import { nettoyerSvg, preparerMermaid, type PaletteVisuel } from './svgSur';

let file: Promise<unknown> = Promise.resolve();
let numero = 0;
export function dessinerMermaid(source: string, palette: PaletteVisuel) {
  const description = preparerMermaid(source);
  // Mermaid a une configuration globale : deux cartes de thèmes différents
  // ne doivent pas se voler leurs couleurs au milieu d'un rendu.
  const travail = file.catch(() => undefined).then(async () => {
    const { default: mermaid } = await import('mermaid');
    const echelles = Object.fromEntries(Array.from({ length: 12 }, (_, i) => [
      [`cScale${i}`, palette.accent], [`cScaleLabel${i}`, palette.fond],
    ]).flat());
    const couleurs = [palette.accent, palette.secondaire, '#6085ba', '#bd874b', '#9982ae', '#5b9a87', '#b96c7b', '#9b963e', '#687ba3', '#af7367', '#599cac', '#978078'];
    const secteurs = Object.fromEntries(couleurs.map((couleur, i) => [`pie${i + 1}`, couleur]));
    mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', theme: 'base',
      maxTextSize: 12_000, maxEdges: 200, suppressErrorRendering: true,
      fontFamily: palette.police, htmlLabels: false, flowchart: { htmlLabels: false },
      themeVariables: { ...echelles, ...secteurs, git0: palette.accent, gitBranchLabel0: palette.fond, pieSectionTextColor: palette.fond,
        pieStrokeColor: palette.fond, pieOuterStrokeColor: palette.bord,
        secondaryBorderColor: palette.accent, tertiaryBorderColor: palette.accent,
        fontFamily: palette.police, primaryColor: palette.fond, primaryTextColor: palette.texte,
        primaryBorderColor: palette.accent, lineColor: palette.accent, textColor: palette.texte,
        secondaryColor: palette.fond, tertiaryColor: palette.fond, background: palette.fond },
    });
    const id = `diapason-visuel-${++numero}`;
    // Le conteneur explicite, retiré même en échec, empêche Mermaid de
    // laisser un SVG d'erreur dans le corps du chat.
    const hote = document.createElement('div');
    hote.style.cssText = 'position:fixed;left:-20000px;top:0;width:1000px;visibility:hidden';
    document.body.appendChild(hote);
    try {
      const rendu = await mermaid.render(id, description, hote);
      return nettoyerSvg(rendu.svg, palette, true);
    } finally { hote.remove(); }
  });
  file = travail;
  return travail;
}
