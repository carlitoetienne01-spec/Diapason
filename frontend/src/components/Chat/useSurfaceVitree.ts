import { useLayoutEffect, useRef } from 'react';
import { inscrireSurfaceVitree } from './verreTexture';
import { suivreReflet } from './cristal';

export function useSurfaceVitree<T extends HTMLElement = HTMLDivElement>(reflet = false, visible = true) {
  const ref = useRef<T>(null);
  useLayoutEffect(() => {
    // 12 septembre 2026 — TalkOrb reste monté quand son DOM est fermé.
    // Réinscrire à chaque ouverture, et retirer la découpe dès la fermeture.
    if (!visible || !ref.current) return;
    const retirerSurface = inscrireSurfaceVitree(ref.current);
    const retirerReflet = reflet ? suivreReflet(ref.current) : undefined;
    return () => {
      retirerReflet?.();
      retirerSurface();
    };
  }, [reflet, visible]);
  return ref;
}
