import { useLayoutEffect, useState, type Dispatch, type SetStateAction } from 'react';
import { estMobile } from './natif';

// 28/09/2026 : chaque cran de la roue démonte la page quittée. Les saisies
// restent en mémoire de CETTE WebView, sans stockage disque ni page cachée
// montée. Annuler/enregistrer remet déjà ces états à zéro chez l'appelant.
const brouillons = new Map<string, unknown>();
export function useBrouillonMobile<T>(cle: string, initial: T | (() => T)): [T, Dispatch<SetStateAction<T>>] {
  const [valeur, poser] = useState<T>(() => estMobile && brouillons.has(cle)
    ? brouillons.get(cle) as T
    : typeof initial === 'function' ? (initial as () => T)() : initial);
  useLayoutEffect(() => {
    if (estMobile) brouillons.set(cle, valeur);
  }, [cle, valeur]);
  return [valeur, poser];
}
