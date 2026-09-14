import { useState, useRef, useCallback, useEffect } from 'react';
import { Send, Square, Paperclip, Brain } from 'lucide-react';
import { toast } from 'sonner';
import { useAppStore, generateId } from '../../lib/store';
import { streamChat, streamResearch } from '../../lib/sse';
import { fetchSavings, getBase, isTauri, finalizeDictation } from '../../lib/api';
import { recordDictationStat } from '../../lib/dictationStats';
import { listConnectors, getSyncStatus } from '../../lib/connectors-api';
import { MicButton } from './MicButton';
import { useSpeech } from '../../hooks/useSpeech';
import { useLiveDictation } from '../../hooks/useLiveDictation';
import { useTranslation } from '../../i18n/useTranslation';
import { ContextRing, ModeChip, ModelChip } from './ComposerBar';
import { isCloudModel } from '../../lib/cloud-models';
import './ComposerGlass.css';
import { useSurfaceVitree } from './useSurfaceVitree';
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
  const streamState = useAppStore((s) => s.streamState);
  const messages = useAppStore((s) => s.messages);
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
    if (prevModelRef.current !== selectedModel && streamState.isStreaming) {
      abortRef.current?.abort();
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
      resetStream();
      abortRef.current = null;
    }
    prevModelRef.current = selectedModel;
  }, [selectedModel, streamState.isStreaming, resetStream]);

  // Live dictation runs entirely in the app on Apple's on-device recogniser,
  // so it works whether or not the Python speech backend is configured. When
  // it is available the microphone becomes a toggle that writes into the
  // composer as you speak; otherwise the older hold-to-talk path stands.
  const live = useLiveDictation(locale);
  const liveMode = live.supported && speechEnabled;

  const micDisabled =
    !speechEnabled ||
    (!liveMode && !speechAvailable) ||
    streamState.isStreaming;
  const micReason: 'not-enabled' | 'no-backend' | 'streaming' | undefined =
    !speechEnabled ? 'not-enabled'
    : !liveMode && !speechAvailable ? 'no-backend'
    : streamState.isStreaming ? 'streaming'
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

  const stopStreaming = useCallback(() => {
    abortRef.current?.abort();
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    resetStream();
  }, [resetStream]);

  // `override` exists for dictation: the last words are transcribed after the
  // microphone closes, so the auto-send path has fresher text than `input`.
  const sendMessage = useCallback(async (override?: string) => {
    const content = (override ?? input).trim();
    if (!content || streamState.isStreaming) return;
    if (!selectedModel) {
      toast.error(t('chat.input.pickModel'));
      return;
    }

    setInput('');

    let convId = activeId;
    if (!convId) {
      convId = createConversation(selectedModel);
    }

    const userMsg: ChatMessage = {
      id: generateId(),
      role: 'user',
      content,
      timestamp: Date.now(),
    };
    addMessage(convId, userMsg);

    // Build API messages before adding assistant placeholder
    const currentMessages = useAppStore.getState().messages;
    const apiMessages = currentMessages.map((m) => ({
      role: m.role,
      content: m.content,
    }));

    const assistantMsg: ChatMessage = {
      id: generateId(),
      role: 'assistant',
      content: '',
      timestamp: Date.now(),
      isResearch: deepResearch || undefined,
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
    let usage: TokenUsage | undefined;
    let complexity: { score: number; tier: string; suggested_max_tokens: number } | undefined;
    let lightningMeta: { action?: string; total_ms?: number; verified?: boolean } | undefined;
    const toolCalls: ToolCallInfo[] = [];
    const researchTraces: ResearchSearchTrace[] = [];
    const researchSourcesByRef = new Map<number, ResearchSource>();
    const flushSources = () =>
      Array.from(researchSourcesByRef.values()).sort((a, b) => a.ref - b.ref);
    let lastFlush = 0;
    let ttftMs: number | undefined;

    setStreamState({
      isStreaming: true,
      phase: deepResearch ? t('chat.stream.researching') : t('chat.stream.generating'),
      elapsedMs: 0,
      activeToolCalls: [],
      content: '',
    });
    useAppStore.getState().addLogEntry({
      timestamp: Date.now(),
      level: 'info',
      category: 'chat',
      message: deepResearch
        ? `Research: "${content.slice(0, 80)}${content.length > 80 ? '...' : ''}"`
        : `Request: "${content.slice(0, 80)}${content.length > 80 ? '...' : ''}" → ${selectedModel}`,
    });

    try {
      if (deepResearch) {
        for await (const ev of streamResearch(
          content,
          selectedModel,
          controller.signal,
        )) {
          if (ev.type === 'search_call') {
            const trace: ResearchSearchTrace = {
              id: generateId(),
              query: ev.arguments?.query ?? '',
              person: ev.arguments?.person,
              timeRange: ev.arguments?.time_range,
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
          } else if (ev.type === 'synthesis') {
            if (!ttftMs) ttftMs = Date.now() - startTime;
            accumulatedContent += ev.text;
            setStreamState({ content: accumulatedContent, phase: '' });
            const now = Date.now();
            if (now - lastFlush >= 80) {
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
              lastFlush = now;
            }
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
        },
        controller.signal,
      )) {
        const eventName = sseEvent.event;

        if (eventName === 'agent_turn_start') {
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
            if (delta?.content) {
              if (!ttftMs) ttftMs = Date.now() - startTime;
              accumulatedContent += delta.content;
              setStreamState({ content: accumulatedContent, phase: '' });

              const now = Date.now();
              if (now - lastFlush >= 80) {
                updateLastAssistant(
                  convId,
                  accumulatedContent,
                  toolCalls.length > 0 ? [...toolCalls] : undefined,
                );
                lastFlush = now;
              }
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
        model_id: selectedModel,
        total_ms: totalMs,
        ttft_ms: ttftMs,
        tokens_per_sec: usage?.completion_tokens
          ? usage.completion_tokens / (totalMs / 1000)
          : undefined,
        complexity_score: complexity?.score,
        complexity_tier: complexity?.tier,
        suggested_max_tokens: complexity?.suggested_max_tokens,
      };
      // Check if the response has digest audio available
      let audioMeta: { url: string } | undefined;
      try {
        const digestRes = await fetch(`${getBase()}/api/digest`);
        if (digestRes.ok) {
          const digest = await digestRes.json();
          if (digest.audio_available) {
            audioMeta = { url: `${getBase()}/api/digest/audio` };
          }
        }
      } catch {
        // Not a digest response or server unavailable — skip
      }

      updateLastAssistant(
        convId,
        accumulatedContent,
        toolCalls.length > 0 ? toolCalls : undefined,
        usage,
        telemetry,
        audioMeta,
        researchTraces.length > 0 ? researchTraces : undefined,
        researchSourcesByRef.size > 0 ? flushSources() : undefined,
      );
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
      resetStream();
      useAppStore.getState().addLogEntry({
        timestamp: Date.now(), level: 'info', category: 'chat',
        message: `Response: ${accumulatedContent.length} chars`,
      });
      abortRef.current = null;

      // Research path updates session counters optimistically from the
      // `done` event's usage payload — re-fetching here would overwrite
      // it with a potentially stale snapshot if the server's research
      // telemetry hasn't been merged into /v1/savings yet.
      if (!deepResearch) {
        fetchSavings()
          .then((data) => useAppStore.getState().setSavings(data))
          .catch(() => {});
      }
    }
  }, [
    input,
    activeId,
    selectedModel,
    streamState.isStreaming,
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
          disabled={streamState.isStreaming || modelLoading}
        />
        {streamState.isStreaming ? (
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
            <ModeChip disabled={streamState.isStreaming} />
            <button
              type="button"
              onClick={() => setDeepResearch(!deepResearch)}
              disabled={streamState.isStreaming}
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
            <ModelChip disabled={streamState.isStreaming} />
          </div>
        </div>
      </div>
      <div className="flex items-center justify-center mt-2 text-[11px]" style={{ color: 'var(--color-text-tertiary)' }}>
        <span>
          <kbd className="font-mono">Enter</kbd> {t('chat.input.toSend')} &middot;{' '}
          <kbd className="font-mono">Shift+Enter</kbd> {t('chat.input.forNewLine')}
        </span>
      </div>
    </div>
  );
}
