import { isTauri } from './api';

/**
 * Un lien qu'on accepte d'ouvrir.
 *
 * `http` et `https`, rien d'autre. Une note peut contenir n'importe quel
 * texte, et `javascript:`, `data:` ou `file:` y passeraient pour des liens
 * comme les autres — le premier exécute du code dans la page, le troisième
 * ouvre le disque. La portée déclarée dans `capabilities/default.json` dit la
 * même chose au greffon ; celle-ci le dit AVANT l'appel, pour que le refus
 * soit lisible plutôt qu'une erreur de permission.
 */
export function estLienOuvrable(url: string): boolean {
  try {
    const u = new URL(String(url ?? ''));
    return u.protocol === 'http:' || u.protocol === 'https:';
  } catch {
    return false;
  }
}

/**
 * Ouvrir un lien dans le NAVIGATEUR du système.
 *
 * `<a target="_blank">` ne fait rien du tout dans la fenêtre de bureau :
 * WKWebView n'ouvre pas de seconde fenêtre, et le clic tombe dans le vide sans
 * le moindre message. Le lien paraissait cliquable — souligné, en couleur
 * d'accent — et ne l'était pas. C'est exactement la promesse en attente que le
 * cahier des charges interdit.
 *
 * Dans un navigateur ordinaire, `window.open` fait l'affaire ; dans la
 * fenêtre, il faut passer par le greffon.
 */
export async function ouvrirLienExterne(url: string): Promise<boolean> {
  if (!estLienOuvrable(url)) return false;
  if (!isTauri()) {
    window.open(url, '_blank', 'noopener,noreferrer');
    return true;
  }
  try {
    const { invoke } = await import('@tauri-apps/api/core');
    await invoke('plugin:opener|open_url', { url });
    return true;
  } catch {
    return false;
  }
}
