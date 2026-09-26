import { useLayoutEffect, useRef } from 'react';
import { inscrireSurfaceVitree } from './verreTexture';
import { suivreReflet } from './cristal';
import { estMobile } from '../../lib/natif';

export function useSurfaceVitree<T extends HTMLElement = HTMLDivElement>(reflet = false, visible = true) {
  const ref = useRef<T>(null);
  useLayoutEffect(() => {
    // 12 septembre 2026 — TalkOrb reste monté quand son DOM est fermé.
    // Réinscrire à chaque ouverture, et retirer la découpe dès la fermeture.
    if (!visible || !ref.current) return;
    // 26/09/2026 (lot 3) : au téléphone, le verre est plat (telephonePlat.css)
    // et le quadrillage du terminal passe sans découpes. Inscrire la vitre
    // coûtait, à chaque événement de défilement, une mesure de TOUTES les
    // vitres de la page (25 aux Tâches) et une réécriture du masque sur <html>.
    if (estMobile) return;
    const retirerSurface = inscrireSurfaceVitree(ref.current);
    const retirerReflet = reflet ? suivreReflet(ref.current) : undefined;
    return () => {
      retirerReflet?.();
      retirerSurface();
    };
  }, [reflet, visible]);
  return ref;
}
