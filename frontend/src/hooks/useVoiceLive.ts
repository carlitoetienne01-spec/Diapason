import { useCallback, useEffect, useRef, useState } from 'react';
import {
  canStartVoiceSession,
  fetchVoiceLiveHealth,
  VoiceLiveHealthError,
  voiceLiveDiagnosticUrl,
  voiceLiveProtocols,
  voiceLiveWsUrl,
  type VoiceLiveHealth,
} from '../lib/voiceLive';
import { refreshLocalApiKey } from '../lib/api';
import { LectureVocale } from '../lib/lectureVocale';
import { creerCaptureVocale, type CaptureVocale } from '../lib/captureVocale';
// Le même lecteur et le même badge qu'au chat : deux calculs du même niveau
// finiraient par diverger, et c'est celui qu'on oublierait qui mentirait.
import {
  lireVerification,
  type Verification,
} from '../components/Chat/notesDeVerification';

export type VoiceLiveState =
  | 'idle'
  | 'connecting'
  | 'listening'
  | 'speaking'
  | 'error';

export type VoiceLiveProvider = 'gemini' | 'openai' | 'local';

export interface TranscriptLine {
  role: 'user' | 'assistant';
  text: string;
  final: boolean;
  /** Rang d'arrivée, partagé avec les outils : le fil se lit dans l'ordre vécu. */
  at: number;
}

export interface ToolEventLine {
  at: number;
  name: string;
  ok: boolean;
  detail: string;
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

export function useVoiceLive() {
  const [state, setState] = useState<VoiceLiveState>('idle');
  const [error, setError] = useState<string | null>(null);
  const [health, setHealth] = useState<VoiceLiveHealth | null>(null);
  const [checkingService, setCheckingService] = useState(true);
  const [serviceError, setServiceError] = useState<string | null>(null);
  // Local is the product's promise (« rien ne quitte ce Mac ») — it is the
  // default everywhere; cloud providers are the opt-in, never the reverse.
  const [provider, setProvider] = useState<VoiceLiveProvider>('local');
  const [transcripts, setTranscripts] = useState<TranscriptLine[]>([]);
  const [toolEvents, setToolEvents] = useState<ToolEventLine[]>([]);
  // Le niveau de vérification du dernier tour d'actualité (22/09/2026). Le
  // panneau n'avait rien : l'épilogue parlé ne se prononce QUE lorsqu'il a
  // quelque chose à avouer, donc son silence disait aussi bien « vérifié en
  // ligne » que « personne n'a rien vérifié ».
  const [verification, setVerification] = useState<Verification | undefined>(undefined);
  // Paroles et outils arrivent par deux canaux : sans rang commun, le fil
  // affiché ne peut pas respecter l'ordre réellement vécu.
  const seqRef = useRef(0);
  const [statusLabel, setStatusLabel] = useState('Idle');

  const wsRef = useRef<WebSocket | null>(null);
  const generationRef = useRef(0);
  const demarrageRef = useRef(false);
  const captureCtxRef = useRef<AudioContext | null>(null);
  const [outputNode, setOutputNode] = useState<GainNode | null>(null);
  // The microphone, teed for the orb's visual analyser — silent, never
  // routed to the speakers.
  const [micNode, setMicNode] = useState<AudioNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const processorRef = useRef<CaptureVocale | null>(null);
  const serviceErrorRef = useRef<string | null>(null);
  const lectureRef = useRef<LectureVocale | null>(null);
  if (!lectureRef.current) {
    lectureRef.current = new LectureVocale((sortie, parle) => {
      setOutputNode(sortie);
      if (!wsRef.current) return;
      setState((precedent) => precedent === 'error' ? precedent : parle ? 'speaking' : 'listening');
      setStatusLabel(parle ? 'Speaking' : 'Listening · speak');
    });
  }

  const checkService = useCallback(async (showLoading = false) => {
    if (showLoading) setCheckingService(true);
    try {
      const current = await fetchVoiceLiveHealth();
      setHealth(current);
      serviceErrorRef.current = null;
      setServiceError(null);
      return current;
    } catch (err) {
      const code = err instanceof VoiceLiveHealthError && err.status === 401
        ? 'voice-auth-unavailable'
        : 'voice-service-unavailable';
      console.error('[voice-live] health check failed', err);
      setHealth(null);
      serviceErrorRef.current = code;
      setServiceError(code);
      return null;
    } finally {
      setCheckingService(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    void checkService(true).then((current) => {
      if (cancelled || !current) return;
      if (
        current.default_provider === 'openai'
        || current.default_provider === 'gemini'
        || current.default_provider === 'local'
      ) {
        setProvider(current.default_provider);
      }
    });
    const timer = window.setInterval(() => void checkService(false), 5000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [checkService]);

  const stopPlayback = useCallback(() => {
    lectureRef.current?.arreter();
  }, []);

  const enqueuePcm = useCallback((b64: string, sampleRate: number) => {
    lectureRef.current?.ajouter(b64, sampleRate);
  }, []);

  const cleanupCapture = useCallback(() => {
    processorRef.current?.arreter();
    processorRef.current = null;
    // Seul l'arrêt de CAPTURE retire le micro de la forme. Interrompre
    // Diapason ne doit pas rendre invisible la voix qui le remplace.
    setMicNode(null);
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    if (captureCtxRef.current) {
      void captureCtxRef.current.close();
      captureCtxRef.current = null;
    }
  }, []);

  const stop = useCallback(() => {
    generationRef.current++;
    demarrageRef.current = false;
    const ws = wsRef.current;
    wsRef.current = null;
    try {
      ws?.send(JSON.stringify({ type: 'stop' }));
    } catch {}
    ws?.close();
    cleanupCapture();
    stopPlayback();
    setState('idle');
    setStatusLabel('Idle');
  }, [cleanupCapture, stopPlayback]);

  const interrupt = useCallback(() => {
    if (!wsRef.current) return;
    stopPlayback();
    try {
      wsRef.current?.send(JSON.stringify({ type: 'interrupt' }));
    } catch {}
    setState('listening');
    setStatusLabel('Listening · speak');
  }, [stopPlayback]);

  const start = useCallback(
    async (opts?: { provider?: VoiceLiveProvider; voice?: string }) => {
      if (wsRef.current || demarrageRef.current) return;
      const generation = ++generationRef.current;
      demarrageRef.current = true;
      setError(null);
      setTranscripts([]);
      setToolEvents([]);
      setVerification(undefined);

      const chosen = opts?.provider || provider;

      // Revalidate immediately before the handshake. Besides preventing a
      // startup race, apiFetch refreshes the desktop key after a 401 so the
      // synchronous URL builder below sees the current credential.
      const current = await checkService(true);
      if (generation !== generationRef.current) return;
      if (!canStartVoiceSession(current, chosen)) {
        demarrageRef.current = false;
        setState('idle');
        setStatusLabel('Idle');
        setError(
          current
            ? chosen === 'gemini'
              ? 'missing-key-gemini'
              : chosen === 'openai'
                ? 'missing-key-openai'
                : 'local-not-ready'
            : serviceErrorRef.current || 'voice-service-unavailable',
        );
        return;
      }

      setState('connecting');
      setStatusLabel('Connecting…');
      let ws: WebSocket;
      let socketUrl: string;
      try {
        await refreshLocalApiKey();
        if (generation !== generationRef.current) return;
        socketUrl = voiceLiveWsUrl({ provider: chosen });
        ws = new WebSocket(socketUrl, voiceLiveProtocols());
      } catch (err) {
        if (generation !== generationRef.current) return;
        demarrageRef.current = false;
        console.error('[voice-live] initialization failed', err);
        setError('voice-connection-failed');
        setState('error');
        setStatusLabel('Error');
        return;
      }
      console.info('[voice-live] opening WebSocket', { provider: chosen, url: voiceLiveDiagnosticUrl(socketUrl) });
      let socketFailed = false;
      wsRef.current = ws;
      demarrageRef.current = false;
      const actuelle = () => wsRef.current === ws && generationRef.current === generation;

      ws.onopen = async () => {
        if (!actuelle()) return;
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
          // Une permission micro peut rester ouverte après « Terminer ».
          // Son résultat tardif ne doit jamais rallumer une session fermée.
          if (!actuelle()) {
            stream.getTracks().forEach((piste) => piste.stop());
            return;
          }
          streamRef.current = stream;
          const ctx = new AudioContext({ sampleRate: 16000 });
          captureCtxRef.current = ctx;
          const source = ctx.createMediaStreamSource(stream);
          const micTap = ctx.createGain();
          micTap.gain.value = 1;
          source.connect(micTap);
          setMicNode(micTap);
          const processor = await creerCaptureVocale(ctx, source, (pcm) => {
            if (!actuelle() || ws.readyState !== WebSocket.OPEN) return;
            ws.send(
              JSON.stringify({
                type: 'audio',
                data: arrayBufferToBase64(pcm),
                sample_rate: ctx.sampleRate,
              }),
            );
          });
          if (!actuelle()) { processor.arreter(); return; }
          processorRef.current = processor;
          if (ctx.state === 'suspended') await ctx.resume();
        } catch (err) {
          if (!actuelle()) return;
          console.error('[voice-live] microphone initialization failed', err);
          socketFailed = true;
          cleanupCapture();
          stopPlayback();
          setError('microphone-denied');
          setState('error');
          setStatusLabel('Error');
          ws.close();
        }
      };

      ws.onmessage = (ev) => {
        if (!actuelle() || socketFailed) return;
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
                    at: last.at,
                    role,
                    // `replace` distingue les deux protocoles. Gemini et
                    // OpenAI envoient des deltas, qu'on concatène. La
                    // transcription locale relit tout le tampon et peut
                    // réviser ce qu'elle avait compris, donc elle remplace :
                    // c'est ce qui fait qu'un mot se corrige tout seul à
                    // l'écran au lieu de se dupliquer.
                    text:
                      msg.final || msg.replace
                        ? msg.text
                        : last.text + msg.text,
                    final: !!msg.final,
                  };
                  return next;
                }
                seqRef.current += 1;
                return [
                  ...prev,
                  {
                    role,
                    text: msg.text || '',
                    final: !!msg.final,
                    at: seqRef.current,
                  },
                ];
              });
              break;
            case 'interrupted':
              stopPlayback();
              setState('listening');
              setStatusLabel('Listening · speak');
              break;
            case 'tool':
              seqRef.current += 1;
              setToolEvents((prev) => [
                ...prev.slice(-11),
                {
                  at: seqRef.current,
                  name: msg.name || 'tool',
                  ok: !!msg.ok,
                  detail: msg.detail || '',
                },
              ]);
              setStatusLabel(`Tool · ${msg.name || '…'}`);
              break;
            case 'verification':
              // Un tour sans niveau lisible EFFACE le précédent : garder la
              // pastille du tour d'avant sous la réponse d'à côté serait la
              // pire des lectures.
              setVerification(lireVerification(msg));
              break;
            case 'error':
              console.error('[voice-live] server session error', {
                provider: chosen,
                detail: msg.detail || 'unknown error',
              });
              socketFailed = true;
              cleanupCapture();
              stopPlayback();
              setError(
                chosen === 'local' && /ollama/i.test(String(msg.detail || ''))
                  ? 'local-not-ready'
                  : 'voice-session-failed',
              );
              setState('error');
              setStatusLabel('Error');
              break;
            case 'closed':
              stop();
              break;
            default:
              break;
          }
        } catch (err) {
          console.warn('[voice-live] ignored malformed server message', err);
        }
      };

      ws.onerror = (event) => {
        if (!actuelle()) return;
        socketFailed = true;
        cleanupCapture();
        stopPlayback();
        console.error('[voice-live] WebSocket connection failed', {
          provider: chosen,
          url: voiceLiveDiagnosticUrl(socketUrl),
          readyState: ws.readyState,
          event,
        });
        setError('voice-connection-failed');
        setState('error');
        setStatusLabel('Error');
      };

      ws.onclose = (event) => {
        if (!actuelle()) return;
        console.info('[voice-live] WebSocket closed', {
          provider: chosen,
          code: event.code,
          reason: event.reason || '(none)',
          clean: event.wasClean,
        });
        wsRef.current = null;
        cleanupCapture();
        stopPlayback();
        if (socketFailed) {
          setState('error');
          setStatusLabel('Error');
        } else {
          setState('idle');
          setStatusLabel('Idle');
        }
      };
    },
    [checkService, cleanupCapture, enqueuePcm, provider, stop, stopPlayback],
  );

  const chooseProvider = useCallback((next: VoiceLiveProvider) => {
    setProvider(next);
    setError(null);
    void checkService(true);
  }, [checkService]);

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

  const readinessError = !checkingService
    && health
    && !canStartVoiceSession(health, provider)
      ? provider === 'gemini'
        ? 'missing-key-gemini'
        : provider === 'openai'
          ? 'missing-key-openai'
          : health.providers?.local?.reason === 'missing-dependencies'
            || health.providers?.local?.reason === 'missing-phonemizer'
            ? 'local-components-missing'
            : 'local-not-ready'
      : null;

  return {
    state,
    error: error || serviceError || readinessError,
    available: !!health?.available,
    serviceReady: canStartVoiceSession(health, provider),
    checkingService,
    provider,
    setProvider: chooseProvider,
    transcripts,
    toolEvents,
    verification,
    statusLabel,
    outputNode,
    micNode,
    refreshAvailability: () => checkService(true),
    start,
    stop,
    interrupt,
    isActive: state === 'connecting' || state === 'listening' || state === 'speaking',
  };
}
