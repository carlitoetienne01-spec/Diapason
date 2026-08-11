import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchVoiceLiveHealth, voiceLiveWsUrl } from '../lib/voiceLive';

export type VoiceLiveState =
  | 'idle'
  | 'connecting'
  | 'listening'
  | 'speaking'
  | 'error';

export type VoiceLiveProvider = 'gemini' | 'openai';

export interface TranscriptLine {
  role: 'user' | 'assistant';
  text: string;
  final: boolean;
}

export interface ToolEventLine {
  name: string;
  ok: boolean;
  detail: string;
}

function floatTo16BitPCM(float32: Float32Array): ArrayBuffer {
  const buffer = new ArrayBuffer(float32.length * 2);
  const view = new DataView(buffer);
  for (let i = 0; i < float32.length; i++) {
    const s = Math.max(-1, Math.min(1, float32[i]));
    view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return buffer;
}

function arrayBufferToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

function base64ToInt16(b64: string): Int16Array {
  const binary = atob(b64);
  const len = binary.length;
  const bytes = new Uint8Array(len);
  for (let i = 0; i < len; i++) bytes[i] = binary.charCodeAt(i);
  return new Int16Array(bytes.buffer);
}

export function useVoiceLive() {
  const [state, setState] = useState<VoiceLiveState>('idle');
  const [error, setError] = useState<string | null>(null);
  const [available, setAvailable] = useState(false);
  const [provider, setProvider] = useState<VoiceLiveProvider>('gemini');
  const [transcripts, setTranscripts] = useState<TranscriptLine[]>([]);
  const [toolEvents, setToolEvents] = useState<ToolEventLine[]>([]);
  const [statusLabel, setStatusLabel] = useState('Idle');

  const wsRef = useRef<WebSocket | null>(null);
  const captureCtxRef = useRef<AudioContext | null>(null);
  const playbackCtxRef = useRef<AudioContext | null>(null);
  // The assistant's own voice, exposed so the UI can visualise it.
  const outputNodeRef = useRef<GainNode | null>(null);
  const [outputNode, setOutputNode] = useState<GainNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const nextPlayTimeRef = useRef(0);
  const speakingRef = useRef(false);

  useEffect(() => {
    fetchVoiceLiveHealth()
      .then((h) => {
        setAvailable(h.available);
        if (h.default_provider === 'openai' || h.default_provider === 'gemini') {
          setProvider(h.default_provider);
        }
      })
      .catch(() => setAvailable(false));
  }, []);

  const stopPlayback = useCallback(() => {
    speakingRef.current = false;
    nextPlayTimeRef.current = 0;
    outputNodeRef.current = null;
    setOutputNode(null);
    const ctx = playbackCtxRef.current;
    if (ctx) {
      playbackCtxRef.current = null;
      void ctx.close();
    }
  }, []);

  const enqueuePcm = useCallback((b64: string, sampleRate: number) => {
    const samples = base64ToInt16(b64);
    if (!samples.length) return;

    let ctx = playbackCtxRef.current;
    if (!ctx || ctx.state === 'closed') {
      ctx = new AudioContext({ sampleRate });
      playbackCtxRef.current = ctx;
      nextPlayTimeRef.current = ctx.currentTime;
      // Everything is played through one node so the visualiser has a single
      // place to listen. Tapping each buffer source instead would miss the
      // gaps between them, and the field would stutter between syllables.
      const output = ctx.createGain();
      output.connect(ctx.destination);
      outputNodeRef.current = output;
      setOutputNode(output);
    }

    const float = new Float32Array(samples.length);
    for (let i = 0; i < samples.length; i++) {
      float[i] = samples[i] / 0x8000;
    }
    const buffer = ctx.createBuffer(1, float.length, sampleRate);
    buffer.copyToChannel(float, 0);
    const src = ctx.createBufferSource();
    src.buffer = buffer;
    src.connect(outputNodeRef.current ?? ctx.destination);
    const startAt = Math.max(ctx.currentTime, nextPlayTimeRef.current);
    src.start(startAt);
    nextPlayTimeRef.current = startAt + buffer.duration;
    speakingRef.current = true;
    setState('speaking');
    setStatusLabel('Speaking');
  }, []);

  const cleanupCapture = useCallback(() => {
    processorRef.current?.disconnect();
    processorRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    if (captureCtxRef.current) {
      void captureCtxRef.current.close();
      captureCtxRef.current = null;
    }
  }, []);

  const stop = useCallback(() => {
    try {
      wsRef.current?.send(JSON.stringify({ type: 'stop' }));
    } catch {}
    wsRef.current?.close();
    wsRef.current = null;
    cleanupCapture();
    stopPlayback();
    setState('idle');
    setStatusLabel('Idle');
  }, [cleanupCapture, stopPlayback]);

  const interrupt = useCallback(() => {
    stopPlayback();
    try {
      wsRef.current?.send(JSON.stringify({ type: 'interrupt' }));
    } catch {}
    setState('listening');
    setStatusLabel('Listening · speak');
  }, [stopPlayback]);

  const start = useCallback(
    async (opts?: { provider?: VoiceLiveProvider; voice?: string }) => {
      setError(null);
      setTranscripts([]);
      setToolEvents([]);
      setState('connecting');
      setStatusLabel('Connecting…');

      const chosen = opts?.provider || provider;

      // Fail with the real reason before opening a socket. Without this, a
      // missing API key surfaces as a bare "WebSocket error" — the server
      // accepts the connection and immediately drops it, which tells the
      // user nothing about what to fix.
      try {
        const health = await fetchVoiceLiveHealth();
        const configured = (health as any)?.providers?.[chosen]?.configured;
        if (configured === false) {
          setState('idle');
          setStatusLabel('Idle');
          setError(chosen === 'gemini' ? 'missing-key-gemini' : 'missing-key-openai');
          return;
        }
      } catch {
        // Health unreachable: let the socket attempt report connectivity.
      }

      const ws = new WebSocket(voiceLiveWsUrl({ provider: chosen }));
      wsRef.current = ws;

      ws.onopen = async () => {
        ws.send(
          JSON.stringify({
            type: 'start',
            provider: chosen,
            voice: opts?.voice || '',
            include_memory: true,
          }),
        );

        try {
          const stream = await navigator.mediaDevices.getUserMedia({
            audio: {
              echoCancellation: true,
              noiseSuppression: true,
              channelCount: 1,
            },
          });
          streamRef.current = stream;
          const ctx = new AudioContext({ sampleRate: 16000 });
          captureCtxRef.current = ctx;
          const source = ctx.createMediaStreamSource(stream);
          const processor = ctx.createScriptProcessor(4096, 1, 1);
          processorRef.current = processor;
          processor.onaudioprocess = (ev) => {
            if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
            const input = ev.inputBuffer.getChannelData(0);
            const pcm = floatTo16BitPCM(input);
            wsRef.current.send(
              JSON.stringify({
                type: 'audio',
                data: arrayBufferToBase64(pcm),
                sample_rate: 16000,
              }),
            );
          };
          // Keep the processor graph alive without audible mic monitor.
          const mute = ctx.createGain();
          mute.gain.value = 0;
          source.connect(processor);
          processor.connect(mute);
          mute.connect(ctx.destination);
        } catch (err) {
          setError('Microphone access denied');
          setState('error');
          ws.close();
        }
      };

      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data as string);
          switch (msg.type) {
            case 'ready':
              setState('listening');
              setStatusLabel('Listening · speak');
              break;
            case 'audio':
              enqueuePcm(msg.data, msg.sample_rate || 24000);
              break;
            case 'transcript':
              setTranscripts((prev) => {
                const role = msg.role === 'user' ? 'user' : 'assistant';
                const last = prev[prev.length - 1];
                if (last && last.role === role && !last.final) {
                  const next = [...prev];
                  next[next.length - 1] = {
                    role,
                    text: msg.final ? msg.text : last.text + msg.text,
                    final: !!msg.final,
                  };
                  return next;
                }
                return [
                  ...prev,
                  { role, text: msg.text || '', final: !!msg.final },
                ];
              });
              break;
            case 'interrupted':
              stopPlayback();
              setState('listening');
              setStatusLabel('Listening · speak');
              break;
            case 'tool':
              setToolEvents((prev) => [
                ...prev.slice(-11),
                {
                  name: msg.name || 'tool',
                  ok: !!msg.ok,
                  detail: msg.detail || '',
                },
              ]);
              setStatusLabel(`Tool · ${msg.name || '…'}`);
              break;
            case 'error':
              setError(msg.detail || 'Voice session error');
              setState('error');
              setStatusLabel('Error');
              break;
            case 'closed':
              stop();
              break;
            default:
              break;
          }
        } catch {}
      };

      ws.onerror = () => {
        setError('WebSocket error');
        setState('error');
      };

      ws.onclose = () => {
        cleanupCapture();
        stopPlayback();
        if (wsRef.current === ws) wsRef.current = null;
        setState((s) => (s === 'error' ? s : 'idle'));
        setStatusLabel('Idle');
      };
    },
    [cleanupCapture, enqueuePcm, provider, stop, stopPlayback],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (state === 'idle' || state === 'connecting' || state === 'error') return;
      if (e.code === 'Space' && !e.repeat && !(e.target instanceof HTMLInputElement) && !(e.target instanceof HTMLTextAreaElement)) {
        e.preventDefault();
        interrupt();
      }
      if (e.code === 'Escape') {
        e.preventDefault();
        stop();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [interrupt, state, stop]);

  useEffect(() => () => stop(), [stop]);

  return {
    state,
    error,
    available,
    provider,
    setProvider,
    transcripts,
    toolEvents,
    statusLabel,
    outputNode,
    start,
    stop,
    interrupt,
    isActive: state === 'connecting' || state === 'listening' || state === 'speaking',
  };
}
