import { PAGES_ROUE } from '../roue/pagesRoue';

/** Une demande locale ne peut pas ouvrir une URL externe ni un chemin inventé. */
export function cheminLocal(path: string, expiresAtMs: number | undefined, now = Date.now()): string | null {
  if (!expiresAtMs || now >= expiresAtMs) return null;
  return PAGES_ROUE.some((page) => page.chemin === path) ? path : null;
}
