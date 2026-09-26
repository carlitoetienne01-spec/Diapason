// Le contraste WCAG entre deux couleurs pleines — pour tenir la roue lisible
// dans les sept apparences (26/09/2026, lot 3). En clair, l'encre blanche sur
// l'accent #0891b2 ne faisait que 3,68:1 : un nom de 16 px sur la capsule
// allumée passait sous les 4,5:1 qu'exige un texte courant.

/** `#rrggbb` ou `#rgb` → [r, g, b] de 0 à 255. */
export function lireHex(hex: string): [number, number, number] {
  const brut = hex.trim().replace(/^#/, '');
  const plein = brut.length === 3 ? brut.split('').map((c) => c + c).join('') : brut.slice(0, 6);
  const n = Number.parseInt(plein, 16);
  if (!/^[0-9a-fA-F]{6}$/.test(plein) || Number.isNaN(n)) throw new Error(`couleur illisible : ${hex}`);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

/** La luminance relative (WCAG 2.x). */
export function luminance([r, g, b]: [number, number, number]): number {
  const canal = (c: number) => {
    const v = c / 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * canal(r) + 0.7152 * canal(g) + 0.0722 * canal(b);
}

/** Le rapport de contraste, de 1 à 21, dans n'importe quel ordre. */
export function rapportDeContraste(a: string, b: string): number {
  const [clair, sombre] = [luminance(lireHex(a)), luminance(lireHex(b))].sort((x, y) => y - x);
  return (clair + 0.05) / (sombre + 0.05);
}
