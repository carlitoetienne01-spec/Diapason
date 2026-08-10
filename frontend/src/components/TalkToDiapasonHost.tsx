import { useCallback, useEffect, useRef, useState } from 'react';
import { TalkOrb } from './Chat/TalkOrb';
import { useVoiceLive } from '../hooks/useVoiceLive';
import { fetchScreenShareStatus, isTauri, pollTriggers } from '../lib/api';

/** Global Talk-to-Diapason host (Alt+Space / wake-word / button). */
export function TalkToDiapasonHost() {
  const [open, setOpen] = useState(false);
  const [screenSharing, setScreenSharing] = useState(false);
  const voice = useVoiceLive();
  const triggerOffset = useRef(0);

  const openTalk = useCallback(() => {
    setOpen(true);
    if (!voice.isActive) void voice.start();
  }, [voice]);

  const closeTalk = useCallback(() => {
    voice.stop();
    setOpen(false);
  }, [voice]);

  const toggleTalk = useCallback(() => {
    if (open) closeTalk();
    else openTalk();
  }, [closeTalk, open, openTalk]);

  // Tauri global hotkey Alt+Space → talk-toggle
  useEffect(() => {
    if (!isTauri()) return;
    let unlisten: (() => void) | undefined;
    let cancelled = false;
    (async () => {
      try {
        const { listen } = await import('@tauri-apps/api/event');
        if (cancelled) return;
        unlisten = await listen('talk-toggle', () => toggleTalk());
      } catch {
        // plugin missing
      }
    })();
    return () => {
      cancelled = true;
      unlisten?.();
    };
  }, [toggleTalk]);

  // Web / in-app: Alt+Space (avoid when typing)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!e.altKey || e.metaKey || e.ctrlKey || e.code !== 'Space') return;
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) {
        return;
      }
      e.preventDefault();
      toggleTalk();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [toggleTalk]);

  // Chat header / other UI can open via custom event
  useEffect(() => {
    const onOpen = () => openTalk();
    const onToggle = () => toggleTalk();
    window.addEventListener('openjarvis-talk-open', onOpen);
    window.addEventListener('openjarvis-talk-toggle', onToggle);
    return () => {
      window.removeEventListener('openjarvis-talk-open', onOpen);
      window.removeEventListener('openjarvis-talk-toggle', onToggle);
    };
  }, [openTalk, toggleTalk]);

  // Wake-word / clap CLI → local_trigger talk_open
  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    const tick = async () => {
      try {
        const data = await pollTriggers(triggerOffset.current);
        if (cancelled) return;
        triggerOffset.current = data.offset;
        for (const ev of data.events) {
          if (ev.event === 'talk_open') {
            openTalk();
            break;
          }
        }
      } catch {
        // server may be down
      }
      if (!cancelled) {
        timer = window.setTimeout(tick, 1000);
      }
    };
    timer = window.setTimeout(tick, 800);
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [openTalk]);

  // Screen-share badge while Talk is open
  useEffect(() => {
    if (!open) {
      setScreenSharing(false);
      return;
    }
    let cancelled = false;
    let timer: number | undefined;
    const tick = async () => {
      try {
        const st = await fetchScreenShareStatus();
        if (!cancelled) setScreenSharing(!!st.active);
      } catch {
        if (!cancelled) setScreenSharing(false);
      }
      if (!cancelled) timer = window.setTimeout(tick, 2000);
    };
    void tick();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [open]);

  return (
    <TalkOrb
      open={open}
      state={voice.state}
      statusLabel={voice.statusLabel}
      error={voice.error}
      provider={voice.provider}
      transcripts={voice.transcripts}
      toolEvents={voice.toolEvents}
      screenSharing={screenSharing}
      onProviderChange={voice.setProvider}
      onStart={() => void voice.start()}
      onStop={voice.stop}
      onInterrupt={voice.interrupt}
      onClose={closeTalk}
    />
  );
}

export function openTalkToDiapason(): void {
  window.dispatchEvent(new CustomEvent('openjarvis-talk-open'));
}
