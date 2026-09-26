// Le thème que la coquille du téléphone doit épouser (phase 3, étape 6).
//
// 26/09/2026 : la coquille Flutter peint elle-même la barre d'état d'Android
// et ses écrans natifs (« Mac injoignable », démarrage à froid). Sans savoir
// l'apparence choisie dans la WebView, elle aurait écrit des icônes claires
// sur le panneau pâle d'Ardéchine — illisibles — et affiché un flash blanc au
// lancement en Phosphore. Le bundle lui envoie donc, à chaque changement,
// le thème, sa peau, les deux couleurs de fond et d'encre réellement
// calculées, et `clair` : vrai quand le fond est pâle.

import { isLightTerminalSkin, type TerminalSkin, type ThemeMode } from './store';

export type ThemeNatif = {
  theme: ThemeMode;
  skin: TerminalSkin;
  fond: string;
  encre: string;
  clair: boolean;
};

/** Les couleurs de base de `index.css`, si la feuille n'a encore rien calculé. */
const REPLI = {
  clair: { fond: '#f9f9f9', encre: '#09090b' },
  sombre: { fond: '#0a0a0b', encre: '#ededef' },
} as const;

/** Vrai quand l'apparence peint un fond pâle — la barre d'état veut alors une encre sombre. */
export function themeEstClair(theme: ThemeMode, skin: TerminalSkin, systemeSombre: boolean): boolean {
  if (theme === 'light') return true;
  if (theme === 'dark') return false;
  if (theme === 'terminal') return isLightTerminalSkin(skin);
  return !systemeSombre;
}

export function chargeThemeNatif(entree: {
  theme: ThemeMode;
  skin: TerminalSkin;
  systemeSombre: boolean;
  fond?: string;
  encre?: string;
}): ThemeNatif {
  const clair = themeEstClair(entree.theme, entree.skin, entree.systemeSombre);
  const repli = clair ? REPLI.clair : REPLI.sombre;
  return {
    theme: entree.theme,
    skin: entree.skin,
    fond: entree.fond?.trim() || repli.fond,
    encre: entree.encre?.trim() || repli.encre,
    clair,
  };
}

/** Lire les jetons après que les classes de <html> ont été posées. */
export function lireChargeThemeNatif(theme: ThemeMode, skin: TerminalSkin): ThemeNatif {
  const style = getComputedStyle(document.documentElement);
  let systemeSombre = false;
  try {
    systemeSombre = window.matchMedia('(prefers-color-scheme: dark)').matches;
  } catch {
    systemeSombre = false;
  }
  return chargeThemeNatif({
    theme,
    skin,
    systemeSombre,
    fond: style.getPropertyValue('--color-bg'),
    encre: style.getPropertyValue('--color-text'),
  });
}
