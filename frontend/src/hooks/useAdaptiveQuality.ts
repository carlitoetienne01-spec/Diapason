import { useCallback, useRef, useState } from 'react';

import type { AIQuality } from '../components/AIEntity/types';

/** First guess from what the device advertises. The render loop measures the
 * real frame time afterwards and corrects this, so a wrong guess costs a
 * second of adaptation rather than a permanently bad experience. */
export function guessQuality(): AIQuality {
  if (typeof window === 'undefined') return 'medium';

  const coarse = window.matchMedia?.('(pointer: coarse)').matches ?? false;
  const cores = navigator.hardwareConcurrency ?? 4;
  const memory = (navigator as unknown as { deviceMemory?: number }).deviceMemory ?? 4;

  if (coarse) return cores >= 6 && memory >= 4 ? 'medium' : 'low';
  if (cores >= 10 && memory >= 8) return 'ultra';
  if (cores >= 6) return 'high';
  return 'medium';
}

/**
 * Holds the active quality tier and rate-limits changes.
 *
 * Without the cooldown a machine sitting near the threshold would step up and
 * down every second or two, and a lattice rebuild that often is both visible
 * and pointless.
 */
export function useAdaptiveQuality(forced?: AIQuality) {
  const [quality, setQuality] = useState<AIQuality>(() => forced ?? guessQuality());
  const lastChange = useRef(0);

  const request = useCallback(
    (next: AIQuality) => {
      if (forced) return;
      const now = performance.now();
      if (now - lastChange.current < 4000) return;
      lastChange.current = now;
      setQuality((current) => (current === next ? current : next));
    },
    [forced],
  );

  return { quality: forced ?? quality, request };
}
