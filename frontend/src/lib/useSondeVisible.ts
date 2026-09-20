import { useCallback, useEffect, useRef } from 'react';
import { creerSondeVisible } from './sondeVisible';

/** 19/09/2026 : les voyants du chrome continuaient leurs sondes hors écran.
 * Les rappels et validations, utiles en arrière-plan, ne passent pas ici. */
export function useSondeVisible(
  lire: (signal: AbortSignal) => Promise<void>,
  intervalleMs: number,
  active = true,
) {
  const sonde = useRef<ReturnType<typeof creerSondeVisible> | null>(null);
  useEffect(() => {
    if (!active) return;
    const courante = creerSondeVisible(lire, () => !document.hidden, intervalleMs);
    sonde.current = courante;
    const actualiser = () => {
      if (document.hidden) courante.suspendre();
      else void courante.rafraichir();
    };
    document.addEventListener('visibilitychange', actualiser);
    window.addEventListener('focus', actualiser);
    window.addEventListener('diapason:panneau-repris', actualiser);
    void courante.rafraichir();
    return () => {
      courante.fermer();
      sonde.current = null;
      document.removeEventListener('visibilitychange', actualiser);
      window.removeEventListener('focus', actualiser);
      window.removeEventListener('diapason:panneau-repris', actualiser);
    };
  }, [lire, intervalleMs, active]);
  return useCallback(() => { void sonde.current?.rafraichir(); }, []);
}
