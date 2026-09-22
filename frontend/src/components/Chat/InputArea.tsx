import { useState, useRef, useCallback, useEffect } from 'react';
import { Send, Square, Paperclip, Brain } from 'lucide-react';
import { toast } from 'sonner';
import { useAppStore, generateId, completerAudioMessage, viderSauvegardeConversations } from '../../lib/store';
import { creerCadenceFlux } from '../../lib/cadenceFlux';
import { EVENEMENT_REPONSES_CHAT, lireQuestions, preparerEnvoiQuestions, texteQuestions, type EnvoiReponses } from '../../lib/questionsChat';
import { streamChat, streamResearch } from '../../lib/sse';
import { historiqueDeRecherche, remplacerLesSources } from './historiqueDeRecherche';
import { fetchSavings, getBase, isTauri, finalizeDictation, apiFetch } from '../../lib/api';
import { recordDictationStat } from '../../lib/dictationStats';
import { listConnectors, getSyncStatus } from '../../lib/connectors-api';
import { MicButton } from './MicButton';
import { useSpeech } from '../../hooks/useSpeech';
import { useLiveDictation } from '../../hooks/useLiveDictation';
import { useTranslation } from '../../i18n/useTranslation';
import { ContextRing, ModeChip, ModelChip } from './ComposerBar';
import { isCloudModel } from '../../lib/cloud-models';
import { modeleDeLaReponse, type RoutageServeur } from './modeleDeLaReponse';
import { EVENEMENT_VERIFIER_EN_LIGNE, lireVerification, type DemandeDeVerification } from './notesDeVerification';
import './ComposerGlass.css';
import { useSurfaceVitree } from './useSurfaceVitree';
import {
  EVENEMENT_DEPOSER_TEXTE,
  EVENEMENT_FOCUS_COMPOSITEUR,
  consommerLaDemandeDeFocus,
  publierLeBrouillon,
  signalerEntreeAVide,
} from '../../lib/panneau';
import type {
  ChatMessage,
  MessageTelemetry,
  ResearchSearchTrace,
  ResearchSource,
  TokenUsage,
  ToolCallInfo,
} from '../../types';

/** Silence after dictation that counts as "I'm done talking". */
const DICTATION_AUTO_SEND_MS = 6500;

// While Deep Research is toggled on, poll connected sources for sync
// progress so we can surface "Searching over N items — sync in progress"
// next to the toggle. Polling is gated on `enabled` so toggling DR off
// stops the network chatter immediately.
function useResearchCorpusSync(enabled: boolean): {
  syncing: boolean;
  itemsSynced: number;
} {
  const [state, setState] = useState({ syncing: false, itemsSynced: 0 });

  useEffect(() => {
    if (!enabled) {
      setState({ syncing: false, itemsSynced: 0 });
      return;
    }
    let cancelled = false;

    const poll = async () => {
      try {
        const list = await listConnectors();
        const connected = list.filter((c) => c.connected);
        if (connected.length === 0) {
          if (!cancelled) setState({ syncing: false, itemsSynced: 0 });
          return;
        }
        const results = await Promise.all(
          connected.map(async (c) => {
            try {
              return await getSyncStatus(c.connector_id);
            } catch {
              return null;
            }
          }),
        );
        let syncing = false;
        let itemsSynced = 0;
        for (const r of results) {
          if (!r) continue;
          if (r.state === 'syncing') syncing = true;
          itemsSynced += r.items_synced ?? 0;
        }
        if (!cancelled) setState({ syncing, itemsSynced });
      } catch {
        // Network blip — leave previous state intact.
      }
    };

    poll();
    const interval = setInterval(poll, 5000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [enabled]);

  return state;
}

export function InputArea() {
  const surfaceVitree = useSurfaceVitree(true);
  const { t, locale } = useTranslation();
  const [input, setInput] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const activeId = useAppStore((s) => s.activeId);
  const selectedModel = useAppStore((s) => s.selectedModel);
  const isStreaming = useAppStore((s) => s.streamState.isStreaming);
  const speechEnabled = useAppStore((s) => s.settings.speechEnabled);
  const maxTokens = useAppStore((s) => s.settings.maxTokens);
  const temperature = useAppStore((s) => s.settings.temperature);
  const createConversation = useAppStore((s) => s.createConversation);
  const addMessage = useAppStore((s) => s.addMessage);
  const updateLastAssistant = useAppStore((s) => s.updateLastAssistant);
  const setStreamState = useAppStore((s) => s.setStreamState);
  const resetStream = useAppStore((s) => s.resetStream);
  const modelLoading = useAppStore((s) => s.modelLoading);
  const deepResearch = useAppStore((s) => s.deepResearch);
  const setDeepResearch = useAppStore((s) => s.setDeepResearch);
  const corpusSync = useResearchCorpusSync(deepResearch);

  const {
    state: speechState,
    error: speechError,
    available: speechAvailable,
    startRecording,
    stopRecording,
  } = useSpeech();

  // Abort in-flight stream when the user switches models mid-generation.
  // This prevents errors from trying to continue a stream with a stale model.
  const prevModelRef = useRef(selectedModel);
  useEffect(() => {
    if (prevModelRef.current !== selectedModel && isStreaming) {
      abortRef.current?.abort();
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    }
    prevModelRef.current = selectedModel;
  }, [selectedModel, isStreaming]);

  // Live dictation runs entirely in the app on Apple's on-device recogniser,
  // so it works whether or not the Python speech backend is configured. When
  // it is available the microphone becomes a toggle that writes into the
  // composer as you speak; otherwise the older hold-to-talk path stands.
  const live = useLiveDictation(locale);
  const liveMode = live.supported && speechEnabled;

  const micDisabled =
    !speechEnabled ||
    (!liveMode && !speechAvailable) ||
    isStreaming;
  const micReason: 'not-enabled' | 'no-backend' | 'streaming' | undefined =
    !speechEnabled ? 'not-enabled'
    : !liveMode && !speechAvailable ? 'no-backend'
    : isStreaming ? 'streaming'
    : undefined;

  useEffect(() => {
    if (live.error) {
      toast.error(live.error, { duration: 8000 });
    }
  }, [live.error]);

  useEffect(() => {
    if (speechError) {
      toast.error(speechError, { duration: 8000 });
    }
  }, [speechError]);

  // Destructured so the effects below depend on stable identities: `live`
  // itself is a fresh object every render and would restart the idle timer
  // forever.
  const {
    listening: liveListening,
    transcript: liveTranscript,
    start: liveStart,
    stop: liveStop,
  } = live;

  /** Whatever was already typed when dictation began; speech appends to it. */
  const dictationBaseRef = useRef('');
  /** The last value we wrote ourselves, to tell our edits from the user's. */
  const appliedRef = useRef<string | null>(null);

  const composeDictated = useCallback((spoken: string) => {
    const base = dictationBaseRef.current;
    if (!base) return spoken;
    return spoken ? base + ' ' + spoken : base;
  }, []);

  useEffect(() => {
    if (!liveListening) return;
    const next = composeDictated(liveTranscript);
    appliedRef.current = next;
    setInput(next);
  }, [liveListening, liveTranscript, composeDictated]);

  /** Ends dictation and folds in the words that land after the microphone closes. */
  const finishDictation = useCallback(async () => {
    const spoken = await liveStop();
    const next = composeDictated(spoken);
    appliedRef.current = next;
    setInput(next);
    if (spoken) recordDictationStat(spoken.length);
    return next;
  }, [liveStop, composeDictated]);

  const handleMicClick = useCallback(async () => {
    if (liveMode) {
      if (liveListening) {
        await finishDictation();
      } else {
        dictationBaseRef.current = input.trim();
        await liveStart();
      }
      return;
    }

    if (speechState === 'recording') {
      try {
        const text = await stopRecording();
        if (text) {
          setInput((prev) => (prev ? prev + ' ' + text : text));
          recordDictationStat(text.length);
        }
      } catch {
        // Error is captured in useSpeech
      }
    } else {
      await startRecording();
    }
  }, [
    liveMode,
    liveListening,
    liveStart,
    finishDictation,
    input,
    speechState,
    startRecording,
    stopRecording,
  ]);

  const handleMicPointerDown = useCallback(async () => {
    if (speechState === 'recording' || speechState === 'transcribing') return;
    await startRecording();
  }, [speechState, startRecording]);

  const handleMicPointerUp = useCallback(async () => {
    try {
      const text = await stopRecording();
      if (!text) return;
      recordDictationStat(text.length);
      try {
        const finalized = await finalizeDictation(text, true);
        if (finalized.mode === 'wake' || finalized.meta?.suggest === 'talk_open') {
          window.dispatchEvent(new CustomEvent('diapason-talk-open'));
          return;
        }
        if (finalized.mode === 'command' && finalized.action?.handled) {
          if (finalized.action.success) {
            toast.success(
              finalized.action.detail ||
                t('chat.input.commandRan', { target: finalized.action.target ?? '' }),
            );
          } else {
            toast.error(finalized.action.detail || t('chat.input.commandFailed'));
          }
          return;
        }
        const polished = finalized.text || text;
        setInput((prev) => (prev ? prev + ' ' + polished : polished));
      } catch {
        setInput((prev) => (prev ? prev + ' ' + text : text));
      }
    } catch {
      // Not recording or transcription error — ignore
    }
  }, [stopRecording, t]);

  // In-window PTT listener, kept but currently INERT: the Cmd+Alt+Space
  // shortcut that emitted ptt-start/ptt-stop is no longer registered
  // (see src-tauri/src/lib.rs). Dictation is the background service,
  // which records outside the WebView and so works with this window
  // closed. The listener stays so restoring the shortcut is a one-line
  // change in Rust, with nothing to rewire here.
  const pttGlobalRef = useRef(false);
  useEffect(() => {
    if (!isTauri()) return;
    let unlistenStart: (() => void) | undefined;
    let unlistenStop: (() => void) | undefined;
    let cancelled = false;
    (async () => {
      try {
        const { listen } = await import('@tauri-apps/api/event');
        const { invoke } = await import('@tauri-apps/api/core');
        if (cancelled) return;
        unlistenStart = await listen('ptt-start', () => {
          pttGlobalRef.current = true;
          void handleMicPointerDown();
        });
        unlistenStop = await listen('ptt-stop', async () => {
          const fromGlobal = pttGlobalRef.current;
          pttGlobalRef.current = false;
          try {
            const text = await stopRecording();
            if (!text) return;
            recordDictationStat(text.length);

            let finalized: {
              mode: string;
              text: string;
              action?: { handled?: boolean; success?: boolean; detail?: string; target?: string } | null;
              meta?: { suggest?: string; wake_word?: boolean };
            } | null = null;
            try {
              finalized = await finalizeDictation(text, true);
            } catch {
              finalized = null;
            }

            if (finalized?.mode === 'wake' || finalized?.meta?.suggest === 'talk_open') {
              window.dispatchEvent(new CustomEvent('diapason-talk-open'));
              return;
            }

            if (finalized?.mode === 'command' && finalized.action?.handled) {
              if (finalized.action.success) {
                toast.success(
                  finalized.action.detail ||
                    t('chat.input.commandRan', { target: finalized.action.target ?? '' }),
                );
              } else {
                toast.error(finalized.action.detail || t('chat.input.commandFailed'));
              }
              return;
            }

            const polished = finalized?.text || text;
            if (fromGlobal) {
              try {
                await invoke('paste_to_frontmost', { text: polished });
                toast.success(t('chat.input.dictationPasted'));
              } catch (err) {
                setInput((prev) => (prev ? prev + ' ' + polished : polished));
                toast.error(
                  err instanceof Error ? err.message : t('chat.input.pasteFailed'),
                );
              }
            } else {
              setInput((prev) => (prev ? prev + ' ' + polished : polished));
            }
          } catch {
            // ignore
          }
        });
      } catch {
        // Web build or plugin missing
      }
    })();
    return () => {
      cancelled = true;
      unlistenStart?.();
      unlistenStop?.();
    };
  }, [handleMicPointerDown, stopRecording, t]);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 200) + 'px';
  }, [input]);

  // 17 sept. 2026, chantier « discussions dans le mini-panneau » : rien ne
  // rendait jamais le focus au compositeur. Un menu de puce fermé, la palette
  // refermée, le panneau qui vient de s'ouvrir : le curseur n'était nulle
  // part et il fallait cliquer avant d'écrire. Le compositeur écoute UNE
  // demande (`diapason:focus-compositeur`) et y répond seul — personne
  // d'autre n'a à connaître ce textarea.
  //
  // Un textarea `disabled` ignore `focus()` sans un mot : pendant le
  // chargement du modèle ou une réponse en cours, la demande est retenue et
  // honorée dès que le champ rouvre, sinon l'ouverture du panneau pendant un
  // stream laissait le curseur perdu pour de bon.
  //
  // Une demande émise AVANT ce montage est relue ici (contre-revue du
  // 17 sept. 2026) : « Nouvelle discussion » depuis Tâches naviguait vers
  // « / » et demandait le focus dans la foulée — personne n'écoutait, et
  // même différée d'un tour la demande arrivait 50 ms avant ce textarea.
  // Honorée ou relue, la demande est consommée : elle ne vaut qu'une fois.
  const compositeurBloque = isStreaming || modelLoading;
  const focusEnAttente = useRef(false);
  useEffect(() => {
    const focaliser = () => {
      consommerLaDemandeDeFocus();
      const el = textareaRef.current;
      if (!el) return;
      if (el.disabled) {
        focusEnAttente.current = true;
        return;
      }
      el.focus();
    };
    window.addEventListener(EVENEMENT_FOCUS_COMPOSITEUR, focaliser);
    if (consommerLaDemandeDeFocus()) focaliser();
    return () => window.removeEventListener(EVENEMENT_FOCUS_COMPOSITEUR, focaliser);
  }, []);

  // Le brouillon est publié (lib/panneau.ts) pour que l'atterrissage du
  // mini-panneau sache qu'on tient le fil — sans connaître ce textarea.
  // Démonté, le compositeur ne porte plus rien.
  useEffect(() => {
    publierLeBrouillon(input);
  }, [input]);
  useEffect(() => () => publierLeBrouillon(''), []);
  useEffect(() => {
    if (compositeurBloque || !focusEnAttente.current) return;
    focusEnAttente.current = false;
    textareaRef.current?.focus();
  }, [compositeurBloque]);

  // 17 sept. 2026 : le sauteur (⌘J) crée un fil depuis une requête sans
  // résultat — « Nouvelle discussion « permis » ↩ » — et le texte tapé doit
  // atterrir ICI, jamais partir tout seul (§100 : rien n'est envoyé qu'on
  // n'ait relu). À la suite d'un brouillon, avec une espace, comme la
  // dictée ; le curseur en fin de texte au tour suivant, après que React a
  // posé la valeur — `focus()` seul le laisserait en tête du champ.
  useEffect(() => {
    const deposer = (e: Event) => {
      const texte = (e as CustomEvent<string>).detail;
      if (typeof texte !== 'string' || !texte) return;
      setInput((prev) => (prev ? prev + ' ' + texte : texte));
      window.requestAnimationFrame(() => {
        const el = textareaRef.current;
        if (!el || el.disabled) return;
        el.focus();
        el.setSelectionRange(el.value.length, el.value.length);
      });
    };
    window.addEventListener(EVENEMENT_DEPOSER_TEXTE, deposer);
    return () => window.removeEventListener(EVENEMENT_DEPOSER_TEXTE, deposer);
  }, []);

  const stopStreaming = useCallback(() => {
    abortRef.current?.abort();
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    // La finalisation conserve le flux jusqu'à sa vraie sortie.
  }, []);

  // `override` exists for dictation: the last words are transcribed after the
  // microphone closes, so the auto-send path has fresher text than `input`.
  const sendMessage = useCallback(async (override?: string, envoi?: EnvoiReponses, options?: { verifyOnline?: boolean; garderBrouillon?: boolean }) => {
    // 21/09/2026 : « Vérifier en ligne » passe par le chat ordinaire, jamais
    // par la recherche profonde — c'est une question, pas un dossier.
    const recherche = deepResearch && !envoi && !options?.verifyOnline;
    const content = (override ?? input).trim();
    if (!content || useAppStore.getState().streamState.isStreaming) return;
    if (!selectedModel) {
      toast.error(t('chat.input.pickModel'));
      return;
    }

    if (envoi) {
      const actuel = useAppStore.getState();
      if (actuel.activeId !== envoi.conversationId || !preparerEnvoiQuestions(actuel.messages, envoi)) return;
    } else if (!options?.garderBrouillon) {
      // Revue du 21/09 : « Vérifier en ligne » effaçait le brouillon en cours ;
      // la dictée, elle, passe par ce vidage (elle pose son texte dans le champ).
      setInput('');
    }

    let convId = activeId;
    if (!convId) {
      convId = createConversation(selectedModel);
    }

    const userMsg: ChatMessage = {
      id: generateId(),
      role: 'user',
      content,
      timestamp: Date.now(),
      ...(envoi ? { questionReply: envoi.reply } : {}),
    };
    addMessage(convId, userMsg);

    // Build API messages before adding assistant placeholder
    const currentMessages = useAppStore.getState().messages;
    const apiMessages = currentMessages.map((m) => {
      const cadrage = m.role === 'assistant' ? lireQuestions(m.questions) : null;
      return { role: m.role, content: cadrage ? texteQuestions(cadrage) : m.content };
    });

    const assistantMsg: ChatMessage = {
      id: generateId(),
      role: 'assistant',
      content: '',
      timestamp: Date.now(),
      isResearch: recherche || undefined,
    };
    addMessage(convId, assistantMsg);

    // Start streaming
    const startTime = Date.now();
    const timer = setInterval(() => {
      setStreamState({ elapsedMs: Date.now() - startTime });
    }, 100);
    timerRef.current = timer;

    const controller = new AbortController();
    abortRef.current = controller;

    let accumulatedContent = '';
    let questions: ChatMessage['questions'];
    let usage: TokenUsage | undefined;
    let complexity: { score: number; tier: string; suggested_max_tokens: number } | undefined;
    let lightningMeta: { action?: string; total_ms?: number; verified?: boolean } | undefined;
    let modeleServeur: string | undefined;
    let routageServeur: RoutageServeur | undefined;
    let verification: ChatMessage['verification'];
    const toolCalls: ToolCallInfo[] = [];
    const researchTraces: ResearchSearchTrace[] = [];
    const researchSourcesByRef = new Map<number, ResearchSource>();
    const flushSources = () =>
      Array.from(researchSourcesByRef.values()).sort((a, b) => a.ref - b.ref);
    let ttftMs: number | undefined;
    const publication = creerCadenceFlux(() => {
      setStreamState({ content: accumulatedContent, phase: '' });
      updateLastAssistant(
        convId!, accumulatedContent,
        toolCalls.length ? toolCalls : undefined,
        undefined, undefined, undefined,
        researchTraces.length ? researchTraces : undefined,
        researchSourcesByRef.size ? flushSources() : undefined,
        questions,
      );
    });
    const sauvegarderEnSortant = () => {
      publication.vider();
      viderSauvegardeConversations();
    };
    const surVisibilite = () => { if (document.hidden) sauvegarderEnSortant(); };
    window.addEventListener('pagehide', sauvegarderEnSortant);
    window.addEventListener('beforeunload', sauvegarderEnSortant);
    document.addEventListener('visibilitychange', surVisibilite);

    setStreamState({
      isStreaming: true,
      conversationId: convId,
      phase: recherche ? t('chat.stream.researching') : t('chat.stream.generating'),
      elapsedMs: 0,
      activeToolCalls: [],
      content: '',
    });
    useAppStore.getState().addLogEntry({
      timestamp: Date.now(),
      level: 'info',
      category: 'chat',
      message: recherche
        ? `Research: "${content.slice(0, 80)}${content.length > 80 ? '...' : ''}"`
        : `Request: "${content.slice(0, 80)}${content.length > 80 ? '...' : ''}" → ${selectedModel}`,
    });

    try {
      if (recherche) {
        for await (const ev of streamResearch(
          content,
          selectedModel,
          controller.signal,
          historiqueDeRecherche(apiMessages),
        )) {
          if (ev.type !== 'synthesis' && ev.type !== 'system_metrics') publication.vider();
          if (ev.type === 'search_call') {
            const trace: ResearchSearchTrace = {
              id: generateId(),
              query: ev.arguments?.query ?? '',
              person: ev.arguments?.person,
              timeRange: ev.arguments?.time_range,
              tool: ev.arguments?.tool,
              status: 'pending',
            };
            researchTraces.push(trace);
            setStreamState({ phase: t('chat.stream.searching', { query: trace.query }) });
            updateLastAssistant(
              convId,
              accumulatedContent,
              undefined,
              undefined,
              undefined,
              undefined,
              [...researchTraces],
              flushSources(),
            );
            useAppStore.getState().addLogEntry({
              timestamp: Date.now(),
              level: 'info',
              category: 'tool',
              message: `Search: "${trace.query}"${trace.person ? ` (person: ${trace.person})` : ''}`,
            });
          } else if (ev.type === 'search_result') {
            const pending = [...researchTraces].reverse().find((t) => t.status === 'pending');
            if (pending) {
              pending.status = 'complete';
              pending.numHits = ev.num_hits;
              pending.topTitles = ev.top_titles;
              pending.error = ev.error;
            }
            if (ev.sources) {
              for (const src of ev.sources) {
                if (src && typeof src.ref === 'number' && !researchSourcesByRef.has(src.ref)) {
                  researchSourcesByRef.set(src.ref, src);
                }
              }
            }
            updateLastAssistant(
              convId,
              accumulatedContent,
              undefined,
              undefined,
              undefined,
              undefined,
              [...researchTraces],
              flushSources(),
            );
          } else if (ev.type === 'final_sources') {
            remplacerLesSources(researchSourcesByRef, ev.sources);
            updateLastAssistant(
              convId,
              accumulatedContent,
              undefined,
              undefined,
              undefined,
              undefined,
              [...researchTraces],
              flushSources(),
            );
          } else if (ev.type === 'synthesis') {
            if (!ttftMs) ttftMs = Date.now() - startTime;
            accumulatedContent += ev.text;
            publication.demander();
          } else if (ev.type === 'system_metrics') {
            // Live GPU sample — feed straight to the System panel so Power
            // (W) and Energy (kJ) tick up in real time as the agent runs.
            useAppStore.getState().setLiveEnergy({
              power_w: ev.power_w,
              energy_j: ev.energy_j,
              duration_s: ev.duration_s,
            });
          } else if (ev.type === 'error') {
            // Backend setup/worker failure (Ollama down, planner model
            // missing, KnowledgeStore locked, etc.). Without surfacing the
            // message, the user sees only the generic "No response was
            // generated" fallback and has no way to self-diagnose.
            const msg = ev.message || t('chat.research.noDetail');
            accumulatedContent = accumulatedContent
              ? `${accumulatedContent}\n\n${t('chat.research.stopped', { message: msg })}`
              : t('chat.research.failed', { message: msg });
            setStreamState({ content: accumulatedContent, phase: '' });
            useAppStore.getState().addLogEntry({
              timestamp: Date.now(),
              level: 'error',
              category: 'chat',
              message: `Deep Research error: ${msg}`,
            });
            toast.error(msg, { duration: 8000 });
          } else if (ev.type === 'done') {
            if (ev.sources && ev.sources.length) remplacerLesSources(researchSourcesByRef, ev.sources);
            if (ev.usage) {
              usage = {
                prompt_tokens: ev.usage.prompt_tokens ?? 0,
                completion_tokens: ev.usage.completion_tokens ?? 0,
                total_tokens:
                  ev.usage.total_tokens ??
                  (ev.usage.prompt_tokens ?? 0) +
                    (ev.usage.completion_tokens ?? 0),
              };
              // Optimistically roll this research turn into the session
              // counters so the Session panel updates the moment the
              // stream finishes, regardless of how /v1/savings aggregates
              // research telemetry server-side.
              useAppStore.getState().incrementSavings(usage);
            }
            // Hold the final live numbers visible for a beat so the panel
            // doesn't flash to 0 between the SSE close and the next
            // /v1/telemetry/energy poll picking up the persisted record.
            window.setTimeout(() => {
              useAppStore.getState().setLiveEnergy(null);
            }, 1500);
            break;
          }
        }
      } else {
      for await (const sseEvent of streamChat(
        {
          model: selectedModel,
          messages: apiMessages,
          stream: true,
          temperature,
          max_tokens: maxTokens,
          // Explicit trusted-client opt-in. OpenAI-compatible API callers
          // remain action-free unless they make the same deliberate choice.
          action_mode: 'auto',
          // Le tour qui reçoit les réponses réalise la demande ; il ne rouvre
          // pas un questionnaire identique sous l'effet du rappel d'interface.
          interactiveQuestions: !envoi,
          ...(options?.verifyOnline ? { verifyOnline: true } : {}),
        },
        controller.signal,
      )) {
        const eventName = sseEvent.event;

        if (eventName && eventName !== 'message') publication.vider();
        if (eventName === 'questions') {
          try {
            const validees = lireQuestions(JSON.parse(sseEvent.data));
            if (validees) {
              questions = validees;
              publication.demander();
            }
          } catch { /* Le texte de secours reste lisible si le formulaire est invalide. */ }
        } else if (eventName === 'agent_turn_start') {
          setStreamState({ phase: t('chat.stream.agentThinking') });
        } else if (eventName === 'inference_start') {
          setStreamState({ phase: t('chat.stream.generating') });
          useAppStore.getState().addLogEntry({
            timestamp: Date.now(), level: 'info', category: 'chat',
            message: `Generating with ${selectedModel}...`,
          });
        } else if (eventName === 'tool_call_start') {
          try {
            const data = JSON.parse(sseEvent.data);
            // Wake the approval bell now instead of waiting for its safety
            // poll. Harmless for tools that do not require confirmation.
            window.dispatchEvent(new CustomEvent('diapason-approval-possible'));
            const tc: ToolCallInfo = {
              id: generateId(),
              tool: data.tool,
              arguments: data.arguments || '',
              status: 'running',
              ...(data.auto === true ? { auto: true } : {}),
            };
            toolCalls.push(tc);
            setStreamState({
              phase: t('chat.stream.callingTool', { tool: data.tool }),
              activeToolCalls: [...toolCalls],
            });
            updateLastAssistant(convId, accumulatedContent, [...toolCalls]);
            useAppStore.getState().addLogEntry({
              timestamp: Date.now(), level: 'info', category: 'tool',
              message: `Calling ${data.tool}(${data.arguments || ''})`,
            });
          } catch {}
        } else if (eventName === 'verification') {
          // Ce que la réponse affirme sans source : un signal à part, jamais
          // dans le texte (il se copierait et le modèle le relirait).
          try {
            verification = lireVerification(JSON.parse(sseEvent.data));
          } catch {}
        } else if (eventName === 'sources') {
          // 20/09/2026 : une recherche rend des sources numérotées [N] ; les
          // pastilles cliquables et leur infobulle (titre · média · date)
          // existaient déjà pour Deep Research, il manquait l'événement.
          try {
            const lot = JSON.parse(sseEvent.data);
            for (const src of Array.isArray(lot) ? lot : []) {
              if (src && typeof src.ref === 'number' && !researchSourcesByRef.has(src.ref)) {
                researchSourcesByRef.set(src.ref, src);
              }
            }
          } catch {}
        } else if (eventName === 'tool_call_end') {
          try {
            const data = JSON.parse(sseEvent.data);
            const tc = toolCalls.find(
              (t) => t.tool === data.tool && t.status === 'running',
            );
            if (tc) {
              tc.status = data.success ? 'success' : 'error';
              tc.latency = data.latency;
              tc.result = data.result;
            }
            setStreamState({
              phase: t('chat.stream.generating'),
              activeToolCalls: [...toolCalls],
            });
            updateLastAssistant(convId, accumulatedContent, [...toolCalls]);
          } catch {}
        } else {
          try {
            const data = JSON.parse(sseEvent.data);
            const delta = data.choices?.[0]?.delta;
            if (data.usage) usage = data.usage;
            if (data.complexity) complexity = data.complexity;
            if (data.lightning) lightningMeta = data.lightning;
            if (typeof data.model === 'string' && data.model) modeleServeur = data.model;
            if (data.routing) routageServeur = data.routing;
            if (delta?.content) {
              if (!ttftMs) ttftMs = Date.now() - startTime;
              accumulatedContent += delta.content;
              publication.demander();
            }
            if (data.choices?.[0]?.finish_reason === 'stop') break;
          } catch {}
        }
      }
      }
    } catch (err: any) {
      if (err.name === 'AbortError') {
        // User cancelled or model switch — keep whatever was accumulated
        if (!accumulatedContent) accumulatedContent = t('chat.input.generationStopped');
      } else {
        const errMsg = err?.message || String(err);
        accumulatedContent =
          accumulatedContent || t('chat.input.error', { message: errMsg });
        useAppStore.getState().addLogEntry({
          timestamp: Date.now(), level: 'error', category: 'chat',
          message: `Stream error: ${errMsg}`,
        });
      }
      // If we tore out mid-research, make sure the live System panel
      // numbers don't get stuck on the last sample.
      useAppStore.getState().setLiveEnergy(null);
    } finally {
      if (!accumulatedContent) {
        accumulatedContent = t('chat.input.noResponse');
      }
      const totalMs = Date.now() - startTime;
      const engineLabel = lightningMeta
        ? 'lightning'
        : isCloudModel(selectedModel)
          ? 'cloud'
          : 'ollama';
      const telemetry: MessageTelemetry = {
        engine: engineLabel,
        ...modeleDeLaReponse(selectedModel, modeleServeur, routageServeur, Boolean(lightningMeta)),
        total_ms: totalMs,
        ttft_ms: ttftMs,
        tokens_per_sec: usage?.completion_tokens
          ? usage.completion_tokens / (totalMs / 1000)
          : undefined,
        complexity_score: complexity?.score,
        complexity_tier: complexity?.tier,
        suggested_max_tokens: complexity?.suggested_max_tokens,
      };
      publication.annuler();
      window.removeEventListener('pagehide', sauvegarderEnSortant);
      window.removeEventListener('beforeunload', sauvegarderEnSortant);
      document.removeEventListener('visibilitychange', surVisibilite);
      updateLastAssistant(
        convId,
        accumulatedContent,
        toolCalls.length > 0 ? toolCalls : undefined,
        usage,
        telemetry,
        undefined,
        researchTraces.length > 0 ? researchTraces : undefined,
        researchSourcesByRef.size > 0 ? flushSources() : undefined,
        questions,
        verification,
      );
      clearInterval(timer);
      if (timerRef.current === timer) timerRef.current = null;
      resetStream();
      useAppStore.getState().addLogEntry({
        timestamp: Date.now(), level: 'info', category: 'chat',
        message: `Response: ${accumulatedContent.length} chars`,
      });
      if (abortRef.current === controller) abortRef.current = null;

      // 19/09/2026 : cette lecture secondaire retenait le dernier fragment
      // et le bouton Envoyer. Elle ne possède plus le flux.
      const audioController = new AbortController();
      const delaiAudio = setTimeout(() => audioController.abort(), 3000);
      void apiFetch('/api/digest', { signal: audioController.signal })
        .then(async (res) => {
          if (!res.ok) return;
          const digest = await res.json();
          if (digest.audio_available && typeof digest.text === 'string'
            && digest.text.trim() === accumulatedContent.trim()) {
            completerAudioMessage(convId!, assistantMsg.id, { url: `${getBase()}/api/digest/audio` });
          }
        })
        .catch(() => {})
        .finally(() => clearTimeout(delaiAudio));

      // Research path updates session counters optimistically from the
      // `done` event's usage payload — re-fetching here would overwrite
      // it with a potentially stale snapshot if the server's research
      // telemetry hasn't been merged into /v1/savings yet.
      if (!recherche) {
        fetchSavings()
          .then((data) => useAppStore.getState().setSavings(data))
          .catch(() => {});
      }
    }
  }, [
    input,
    activeId,
    selectedModel,
    isStreaming,
    createConversation,
    addMessage,
    updateLastAssistant,
    setStreamState,
    resetStream,
    deepResearch,
    temperature,
    maxTokens,
    t,
  ]);

  useEffect(() => {
    const repondre = (event: Event) => {
      const envoi = (event as CustomEvent<EnvoiReponses>).detail;
      const actuel = useAppStore.getState();
      if (!envoi || actuel.streamState.isStreaming || actuel.activeId !== envoi.conversationId) return;
      const texte = preparerEnvoiQuestions(actuel.messages, envoi);
      if (texte) void sendMessage(texte, envoi);
    };
    window.addEventListener(EVENEMENT_REPONSES_CHAT, repondre);
    return () => window.removeEventListener(EVENEMENT_REPONSES_CHAT, repondre);
  }, [sendMessage]);

  // Le bouton « Vérifier en ligne » d'une bulle (21/09/2026) : un nouveau tour
  // « Vérifie ça en ligne. » que le serveur rattache à la question d'avant ;
  // la nouvelle réponse s'ajoute sous l'ancienne, elle ne la remplace pas.
  useEffect(() => {
    const verifier = (event: Event) => {
      const demande = (event as CustomEvent<DemandeDeVerification>).detail;
      const actuel = useAppStore.getState();
      if (!demande || actuel.streamState.isStreaming || actuel.activeId !== demande.conversationId) return;
      if (!actuel.messages.some((m) => m.id === demande.messageId)) return;
      void sendMessage(t('chat.verification.demande'), undefined, { verifyOnline: true, garderBrouillon: true });
    };
    window.addEventListener(EVENEMENT_VERIFIER_EN_LIGNE, verifier);
    return () => window.removeEventListener(EVENEMENT_VERIFIER_EN_LIGNE, verifier);
  }, [sendMessage, t]);

  // Falling silent ends the turn: once dictation has been quiet for this long,
  // the message goes on its own. Pressing Enter or the send button beats the
  // timer; typing cancels dictation altogether and with it the countdown.
  useEffect(() => {
    if (!liveListening || !liveTranscript.trim()) return;
    const timer = setTimeout(() => {
      void (async () => {
        const text = await finishDictation();
        if (text.trim()) await sendMessage(text);
      })();
    }, DICTATION_AUTO_SEND_MS);
    return () => clearTimeout(timer);
  }, [liveListening, liveTranscript, finishDictation, sendMessage]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (liveListening) {
        void (async () => {
          const text = await finishDictation();
          if (text.trim()) await sendMessage(text);
        })();
        return;
      }
      // 17 sept. 2026 : ↩ à vide n'envoyait rien (sendMessage l'écarte) et
      // ne disait rien. La page vide du mini-panneau propose « Reprendre
      // « <titre> » ↩ » : c'est elle qui décide si ce ↩ veut dire quelque
      // chose — ici on ne fait que le signaler.
      if (!input.trim()) {
        signalerEntreeAVide();
        return;
      }
      sendMessage();
    }
  };

  /** Typing hands control back to the keyboard and closes the microphone. */
  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const value = e.target.value;
    if (liveListening && value !== appliedRef.current) {
      void liveStop();
    }
    setInput(value);
  };

  return (
    <div className="px-4 pb-4 pt-2" style={{ maxWidth: 'var(--chat-max-width)', margin: '0 auto', width: '100%' }}>
      {deepResearch && corpusSync.syncing && corpusSync.itemsSynced > 0 && (
        <div
          className="mb-2 text-[11px] leading-snug"
          style={{ color: 'var(--color-text-tertiary)' }}
        >
            {t('chat.input.searchingOver')}{' '}
            <span key={corpusSync.itemsSynced} className="sync-bump" style={{ color: 'var(--color-text-secondary)' }}>
              {corpusSync.itemsSynced.toLocaleString()}
            </span>{' '}
          {t('chat.input.searchingOverSuffix', { count: corpusSync.itemsSynced })}
        </div>
      )}
      <div ref={surfaceVitree} className="composer-glass flex flex-col px-4 py-3">
        <div className="flex items-center gap-2">
        <textarea
          ref={textareaRef}
          value={input}
          onChange={handleInputChange}
          onKeyDown={handleKeyDown}
          placeholder={
            selectedModel ? t('chat.input.placeholder') : t('chat.input.placeholderNoModel')
          }
          rows={1}
          className="composer-glass-input flex-1 min-w-0 bg-transparent outline-none resize-none text-sm leading-relaxed"
          style={{ color: 'var(--color-text)', maxHeight: '200px' }}
          disabled={compositeurBloque}
          // Le seul champ d'où ⌘K, ⌘N, ⌘J, ⌘⇧[ et ⌘⇧] passent
          // (ATTRIBUT_RACCOURCIS_GLOBAUX, lib/saisie.ts) : l'éditeur de notes
          // ne le porte pas et garde ⌘I pour l'italique.
          data-raccourcis-globaux=""
        />
        {isStreaming ? (
          <button
            onClick={stopStreaming}
            className="composer-glass-stop p-2 shrink-0 cursor-pointer"
            style={{ background: 'var(--color-error)', color: 'var(--color-on-accent)' }}
            title={t('chat.input.stopGenerating')}
            aria-label={t('chat.input.stopGenerating')}
          >
            <Square size={16} />
          </button>
        ) : (
          <div className="composer-glass-actions flex items-center gap-2">
            <MicButton
              state={liveMode ? (liveListening ? 'recording' : 'idle') : speechState}
              onClick={handleMicClick}
              // Hold-to-talk only stands in for the batch path; live dictation
              // is a toggle, and passing these would suppress its click.
              onPointerDown={liveMode ? undefined : handleMicPointerDown}
              onPointerUp={liveMode ? undefined : handleMicPointerUp}
              disabled={micDisabled}
              reason={micReason}
              live={liveMode}
            />
            <button
              onClick={() => void sendMessage()}
              disabled={!input.trim() || modelLoading || !selectedModel}
              title={selectedModel ? t('chat.input.send') : t('chat.input.pickModel')}
              aria-label={selectedModel ? t('chat.input.send') : t('chat.input.pickModel')}
              className="composer-glass-send p-2 shrink-0 cursor-pointer disabled:cursor-default"
            >
              <Send size={16} />
            </button>
          </div>
        )}
        </div>

        {/* Toolbar — permission mode and deep research on the left; the
            context ring and active model on the right. Claude-Code grammar,
            Diapason wiring. */}
        <div className="composer-glass-toolbar">
          <div className="composer-glass-tools">
            <ModeChip disabled={isStreaming} />
            <button
              type="button"
              onClick={() => setDeepResearch(!deepResearch)}
              disabled={isStreaming}
              aria-pressed={deepResearch}
              aria-label={t('common.deepResearch')}
              className="composer-glass-chip composer-glass-research inline-flex items-center justify-center cursor-pointer disabled:cursor-default disabled:opacity-50"
              data-active={deepResearch}
              title={deepResearch ? t('chat.input.deepResearchOn') : t('chat.input.deepResearchOff')}
            >
              <Brain size={15} strokeWidth={1.75} />
            </button>
          </div>
          <div className="composer-glass-models">
            <ContextRing draftLength={input.length} />
            <ModelChip disabled={isStreaming} />
          </div>
        </div>
      </div>
      {/* Sous sm (le mini-panneau), cette rangée coûtait une ligne au pied
          d'un fil déjà court pour rappeler un raccourci que le placeholder
          suggère — audit du 16 sept. 2026 : secondaire, caché en étroit. */}
      <div className="hidden sm:flex items-center justify-center mt-2 text-[11px]" style={{ color: 'var(--color-text-tertiary)' }}>
        <span>
          <kbd className="font-mono">Enter</kbd> {t('chat.input.toSend')} &middot;{' '}
          <kbd className="font-mono">Shift+Enter</kbd> {t('chat.input.forNewLine')}
        </span>
      </div>
    </div>
  );
}
