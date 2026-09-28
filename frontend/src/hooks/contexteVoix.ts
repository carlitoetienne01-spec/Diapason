import { createContext, useContext } from 'react';
import type { useVoiceLive } from './useVoiceLive';

export const ContexteVoix = createContext<ReturnType<typeof useVoiceLive> | null>(null);
export function useVoixPartagee() {
  const voix = useContext(ContexteVoix);
  if (!voix) throw new Error('La voix doit être placée sous son hôte unique.');
  return voix;
}
