import { useCallback, useEffect, useRef, useState } from 'react';
import { isTauri } from '../lib/api';

/**
 * Streaming dictation backed by Apple's on-device recogniser (see
 * `src-tauri/src/live_speech.rs`).
 *
 * The recogniser does not emit deltas. Each non-final payload is the whole of
 * the current segment, revised as more audio arrives — a word can change after
 * it was first heard, because later context disambiguates it. So a partial
 * always *replaces* the live tail, while a final payload retires that segment
 * into `committed` and starts a new one.
 */

export interface LiveDictation {
  /** False on web builds, on non-macOS, or when no recogniser exists. */
  supported: boolean;
  listening: boolean;
  /** Everything heard this run: settled segments plus the live tail. */
  transcript: string;
  error: string | null;
  start: () => Promise<boolean>;
  /** Stops and resolves with the transcript, including any late final words. */
  stop: () => Promise<string>;
  reset: () => void;
}

/**
 * Apple wants a BCP-47 identifier. The UI language alone is too coarse — a
 * Québécois user running the French UI should be dictating fr-CA, not fr-FR —
 * so prefer the system's own region when its language already agrees.
 */
function recognitionLocale(uiLocale: string): string {
  const fallback: Record<string, string> = { fr: 'fr-FR', en: 'en-US' };
  const system = typeof navigator !== 'undefined' ? navigator.language : '';
  if (system && system.toLowerCase().startsWith(uiLocale.toLowerCase())) {
    return system;
  }
  return fallback[uiLocale] ?? 'en-US';
}

/** How long to wait after stopping for the tail of speech to be transcribed. */
const FINAL_GRACE_MS = 700;

export function useLiveDictation(uiLocale: string): LiveDictation {
  const [supported, setSupported] = useState(false);
  const [listening, setListening] = useState(false);
  const [transcript, setTranscript] = useState('');
  const [error, setError] = useState<string | null>(null);

  const committedRef = useRef('');
  const partialRef = useRef('');
  /** Mirrors `transcript` so `stop` can resolve without a render round-trip. */
  const transcriptRef = useRef('');

  const compose = useCallback(() => {
    const joined = [committedRef.current, partialRef.current]
      .filter(Boolean)
      .join(' ');
    transcriptRef.current = joined;
    setTranscript(joined);
  }, []);

  useEffect(() => {
    if (!isTauri()) return;
    let cancelled = false;
    (async () => {
      try {
        const { invoke } = await import('@tauri-apps/api/core');
        const ok = await invoke<boolean>('live_dictation_available');
        if (!cancelled) setSupported(Boolean(ok));
      } catch {
        // Older build without the command; batch dictation still works.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!isTauri()) return;
    let cancelled = false;
    let unlistenText: (() => void) | undefined;
    let unlistenError: (() => void) | undefined;

    (async () => {
      try {
        const { listen } = await import('@tauri-apps/api/event');
        if (cancelled) return;

        unlistenText = await listen<{ text: string; isFinal: boolean }>(
          'live-dictation',
          (event) => {
            const { text, isFinal } = event.payload;
            if (isFinal) {
              committedRef.current = [committedRef.current, text]
                .filter(Boolean)
                .join(' ');
              partialRef.current = '';
            } else {
              partialRef.current = text;
            }
            compose();
          },
        );

        unlistenError = await listen<{ message: string }>(
          'live-dictation-error',
          (event) => {
            setError(event.payload.message);
            setListening(false);
          },
        );
      } catch {
        // Web build.
      }
    })();

    return () => {
      cancelled = true;
      unlistenText?.();
      unlistenError?.();
    };
  }, [compose]);

  const reset = useCallback(() => {
    committedRef.current = '';
    partialRef.current = '';
    transcriptRef.current = '';
    setTranscript('');
    setError(null);
  }, []);

  const start = useCallback(async () => {
    if (!isTauri()) return false;
    reset();
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      await invoke('start_live_dictation', {
        locale: recognitionLocale(uiLocale),
      });
      setListening(true);
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setListening(false);
      return false;
    }
  }, [reset, uiLocale]);

  const stop = useCallback(async () => {
    setListening(false);
    if (!isTauri()) return transcriptRef.current;
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      await invoke('stop_live_dictation');
    } catch {
      // Already stopped.
    }
    // Ending the audio stream flushes one last result; without this pause the
    // final few words would be dropped from the returned text.
    await new Promise((resolve) => setTimeout(resolve, FINAL_GRACE_MS));
    return transcriptRef.current;
  }, []);

  // A recogniser left running past unmount keeps the microphone open and the
  // orange indicator lit.
  useEffect(() => {
    return () => {
      if (!isTauri()) return;
      void import('@tauri-apps/api/core')
        .then(({ invoke }) => invoke('stop_live_dictation'))
        .catch(() => {});
    };
  }, []);

  return { supported, listening, transcript, error, start, stop, reset };
}
