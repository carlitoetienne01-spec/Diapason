import { useCallback, useEffect, useRef, useState } from 'react';
import {
  canStartVoiceSession,
  coupureCliente,
  fetchVoiceLiveHealth,
  motifDeFermeture,
  VoiceLiveHealthError,
  voiceLiveDiagnosticUrl,
  voiceLiveProtocols,
  voiceLiveWsUrl,
  type VoiceLiveHealth,
} from '../lib/voiceLive';
import { refreshLocalApiKey } from '../lib/api';
import { serviParLeTailnet } from '../lib/tailnet';
import { LectureVocale } from '../lib/lectureVocale';
import { creerCaptureVocale, type CaptureVocale } from '../lib/captureVocale';
import { cleEtatVocal } from '../lib/etatVocal';
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
  interrupted?: boolean;
  timestamp?: number;
}

export interface ToolEventLine {
  at: number;
  name: string;
  ok: boolean;
  detail: string;
  // 22/09/2026 : une recherche à zéro résultat arrivait ici en ok=true,
  // detail='' — indiscernable d'une recherche fructueuse. Mêmes clés qu'au
  // chat, même fonction d'affichage (`resumeDeRecherche`).
  engine?: string;
  numResults?: number;
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
  const [voixSession, setVoixSession] = useState('');
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
  const [conversationSeule, setConversationSeule] = useState(false);
  const [microEnPause, setMicroEnPause] = useState(false);
  const [finVocale, setFinVocale] = useState(false);
  const [enFermeture, setEnFermeture] = useState(false);
  const fermetureRef = useRef<{ recue: boolean; finir: () => void; garde: number } | null>(null);
  const pauseRef = useRef(false);
  const lectureEnCoursRef = useRef(false);
  const repriseMicroRef = useRef(0);
  const etapeRef = useRef('Listening · speak');

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
      lectureEnCoursRef.current = parle;
      if (!parle) repriseMicroRef.current = performance.now() + 300;
      setOutputNode(sortie);
      if (fermetureRef.current) {
        if (!parle && fermetureRef.current.recue) fermetureRef.current.finir();
        else {
          setState(parle ? 'speaking' : 'listening');
          setStatusLabel('ending');
        }
        return;
      }
      if (!wsRef.current) return;
      setState((precedent) => precedent === 'error' ? precedent : parle ? 'speaking' : 'listening');
      setStatusLabel(parle ? 'Speaking' : etapeRef.current);
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
    // Au téléphone, pas de relève toutes les 5 s (constat 15 de la phase 2) :
    // la santé se lit à l'ouverture de l'orbe et avant chaque « Parler »,
    // ce qui suffit à ne jamais démarrer une séance que le Mac refuserait.
    const timer = window.setInterval(() => {
      if (!serviParLeTailnet()) void checkService(false);
    }, 5000);
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
    if (fermetureRef.current) window.clearTimeout(fermetureRef.current.garde);
    fermetureRef.current = null;
    setEnFermeture(false);
    pauseRef.current = false;
    setMicroEnPause(false);
    setConversationSeule(false);
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
    if (fermetureRef.current) { fermetureRef.current.finir(); return; }
    if (!wsRef.current) return;
    etapeRef.current = 'Listening · speak';
    stopPlayback();
    setTranscripts(prev => prev.map(l => l.role === 'assistant' && !l.final ? { ...l, final: true, interrupted: true } : l));
    try {
      wsRef.current?.send(JSON.stringify({ type: 'interrupt' }));
    } catch {}
    setState('listening');
    setStatusLabel('Listening · speak');
  }, [stopPlayback]);

  const start = useCallback(
    async (opts?: { provider?: VoiceLiveProvider; voice?: string; conversationOnly?: boolean;
      model?: string; history?: Array<{ role: 'user' | 'assistant'; content: string }> }) => {
      if (wsRef.current || demarrageRef.current) return;
      const generation = ++generationRef.current;
      demarrageRef.current = true;
      setFinVocale(false);
      pauseRef.current = false;
      setMicroEnPause(false);
      setState('connecting');
      setStatusLabel('Connecting…');
      setError(null);
      setTranscripts([]);
      setToolEvents([]);
      setVerification(undefined);
      const conversationOnly = opts?.conversationOnly === true;
      etapeRef.current = 'Listening · speak';
      setConversationSeule(conversationOnly);
      let modeConfirme = !conversationOnly;

      const chosen = conversationOnly ? 'local' : opts?.provider || provider;

      // Revalidate immediately before the handshake. Besides preventing a
      // startup race, apiFetch refreshes the desktop key after a 401 so the
      // synchronous URL builder below sees the current credential.
      const current = await checkService(true);
      if (generation !== generationRef.current) return;
      const voixChoisie = opts?.voice || (chosen === 'local' ? current?.defaultVoice : '') || '';
      setVoixSession(voixChoisie);
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
      let serveurPret = false;
      let capturePrete = false;
      let ecouteAnnoncee = false;
      const annoncerEcoute = () => {
        // 27/09/2026 : READY du serveur pouvait précéder la permission
        // micro ou le chargement du worklet. « Je t'écoute » faisait alors
        // parler l'utilisateur avant le premier échantillon capturable.
        if (!actuelle() || fermetureRef.current || socketFailed || !serveurPret || !capturePrete || ecouteAnnoncee) return;
        ecouteAnnoncee = true;
        setState('listening');
        setStatusLabel('Listening · speak');
      };

      // La garde du client (26/09/2026, contre-épreuve) : la coupure du Mac
      // n'atteint pas un téléphone hors réseau. Toutes les 5 s, on regarde
      // si le Mac parle encore et si l'envoi avance ; sinon, le micro se
      // ferme ici, et on dit pourquoi.
      const debutMs = Date.now();
      let derniereTrameMs = debutMs;
      let battementVu = false;
      const garde = window.setInterval(() => {
        if (!actuelle()) {
          window.clearInterval(garde);
          return;
        }
        const coupure = coupureCliente({
          maintenantMs: Date.now(),
          debutMs,
          derniereTrameMs,
          battementVu,
          tamponOctets: ws.bufferedAmount,
        });
        if (!coupure) return;
        window.clearInterval(garde);
        console.warn('[voice-live] closed by the client guard', { reason: coupure });
        stop();
        setError(coupure);
      }, 5000);

      ws.onopen = async () => {
        if (!actuelle()) return;
        ws.send(
          JSON.stringify({
            type: 'start',
            provider: chosen,
            voice: voixChoisie,
            ...(opts?.model ? { model: opts.model } : {}),
            ...(opts?.history ? { history: opts.history } : {}),
            include_memory: !conversationOnly,
            ...(conversationOnly ? { conversationOnly: true, enable_tools: false } : {}),
          }),
        );

        try {
          const stream = await navigator.mediaDevices.getUserMedia({
            audio: {
              echoCancellation: !conversationOnly,
              noiseSuppression: !conversationOnly,
              channelCount: 1,
            },
          });
          // Une permission micro peut rester ouverte après « Terminer ».
          // Son résultat tardif ne doit jamais rallumer une session fermée.
          if (!actuelle() || fermetureRef.current) {
            stream.getTracks().forEach((piste) => piste.stop());
            return;
          }
          streamRef.current = stream;
          for (const track of stream.getTracks()) track.enabled = !pauseRef.current;
          const ctx = new AudioContext({ sampleRate: 16000 });
          captureCtxRef.current = ctx;
          const source = ctx.createMediaStreamSource(stream);
          const micTap = ctx.createGain();
          micTap.gain.value = 1;
          source.connect(micTap);
          setMicNode(micTap);
          const processor = await creerCaptureVocale(ctx, source, (pcm) => {
            if (!actuelle() || socketFailed || ws.readyState !== WebSocket.OPEN || !pcm.byteLength) return;
            capturePrete = true;
            annoncerEcoute();
            // Aucun son vers un ancien serveur qui ignorerait ce mode.
            // Sans anti-écho, la propre lecture de Diapason est écartée.
            if (fermetureRef.current || !serveurPret || !modeConfirme || pauseRef.current || (conversationOnly && (
              lectureEnCoursRef.current || performance.now() < repriseMicroRef.current
            ))) return;
            ws.send(
              JSON.stringify({
                type: 'audio',
                data: arrayBufferToBase64(pcm),
                sample_rate: ctx.sampleRate,
              }),
            );
          });
          if (!actuelle() || fermetureRef.current) { processor.arreter(); return; }
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
        derniereTrameMs = Date.now();
        try {
          const msg = JSON.parse(ev.data as string);
          // 27/09/2026 : après le départ, seul le dernier message et son
          // audio peuvent encore arriver. Ni un READY tardif ni une
          // interruption ne doivent réannoncer un micro déjà fermé.
          if (fermetureRef.current && (
            fermetureRef.current.recue || !['audio', 'transcript', 'closed', 'error'].includes(msg.type)
          )) return;
          switch (msg.type) {
            case 'closing': {
              if (msg.reason !== 'farewell') break;
              cleanupCapture();
              stopPlayback();
              setEnFermeture(true);
              setState('listening');
              setStatusLabel('ending');
              const finir = () => {
                if (!actuelle()) return;
                setFinVocale(true);
                stop();
              };
              // 8 s de synthèse maximum côté serveur + une courte formule
              // et la marge de transport. Un lecteur suspendu ne bloque
              // jamais la fermeture ; le micro est déjà physiquement arrêté.
              fermetureRef.current = { recue: false, finir,
                garde: window.setTimeout(finir, 12000) };
              break;
            }
            case 'alive':
              battementVu = true;
              break;
            case 'ready':
              if (conversationOnly && msg.conversationOnly !== true) {
                socketFailed = true;
                stop();
                setError('voice-conversation-unavailable');
                return;
              }
              modeConfirme = true;
              serveurPret = true;
              annoncerEcoute();
              break;
            case 'status':
              if (cleEtatVocal(msg.stage)) {
                etapeRef.current = msg.stage;
                setStatusLabel(msg.stage);
              }
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
                    ...last,
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
                    timestamp: Date.now(),
                  },
                ];
              });
              break;
            case 'interrupted':
              setTranscripts(prev => prev.map(l => l.role === 'assistant' && !l.final ? { ...l, final: true, interrupted: true } : l));
              etapeRef.current = 'Listening · speak';
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
                  ...(typeof msg.engine === 'string' && msg.engine ? { engine: msg.engine } : {}),
                  // `0` passe ; `Number.isInteger` écarte NaN et Infinity,
                  // qui s'afficheraient tels quels.
                  ...(Number.isInteger(msg.numResults) ? { numResults: msg.numResults as number } : {}),
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
              if (fermetureRef.current) stop();
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
            case 'closed': {
              if (msg.reason === 'farewell' && fermetureRef.current) {
                fermetureRef.current.recue = true;
                if (!lectureEnCoursRef.current) fermetureRef.current.finir();
                break;
              }
              // Le motif AVANT stop() : stop() coupe le micro (le voyant
              // d'Android s'éteint), le motif dit pourquoi.
              const motif = motifDeFermeture(msg);
              stop();
              if (motif) setError(motif);
              break;
            }
            default:
              break;
          }
        } catch (err) {
          console.warn('[voice-live] ignored malformed server message', err);
        }
      };

      ws.onerror = (event) => {
        if (!actuelle()) return;
        if (fermetureRef.current) stop();
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
        if (fermetureRef.current?.recue) {
          // Le serveur libère sa séance pendant que le dernier PCM se lit.
          // onended termine le client ; X peut toujours couper avant.
          return;
        }
        if (fermetureRef.current) { fermetureRef.current.finir(); return; }
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

  const mettreMicroEnPause = useCallback((pause: boolean) => {
    if (fermetureRef.current) return;
    if (pause === pauseRef.current) return;
    pauseRef.current = pause;
    setMicroEnPause(pause);
    for (const track of streamRef.current?.getTracks() ?? []) track.enabled = !pause;
    // Une seconde de silence clôt la parole déjà captée avant la pause ;
    // sans elle, le serveur attendrait la fin de ce mot au prochain réveil.
    if (pause && wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'audio',
        data: arrayBufferToBase64(new ArrayBuffer(32000)), sample_rate: 16000 }));
    }
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented) return;
      if (state === 'idle' || state === 'connecting' || state === 'error') return;
      if (e.code === 'Space' && !e.repeat && !(e.target as HTMLElement | null)?.closest('input, textarea, button, select, [contenteditable="true"]')) {
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
            || health.providers?.local?.reason === 'missing-expressive-voice'
            ? 'local-components-missing'
            : 'local-not-ready'
      : null;

  return {
    state,
    error: error || serviceError || readinessError,
    available: !!health?.available,
    serviceReady: canStartVoiceSession(health, provider),
    checkingService,
    voix: (state === 'connecting' || state === 'listening' || state === 'speaking') && voixSession
      ? voixSession : health?.defaultVoice ?? 'qwen3-b',
    voixDisponibles: health?.voices ?? [],
    provider,
    setProvider: chooseProvider,
    transcripts,
    toolEvents,
    verification,
    statusLabel,
    conversationSeule,
    outputNode,
    micNode,
    refreshAvailability: () => checkService(true),
    start,
    stop,
    interrupt,
    microEnPause,
    enFermeture,
    finVocale,
    mettreMicroEnPause,
    isActive: state === 'connecting' || state === 'listening' || state === 'speaking',
  };
}
