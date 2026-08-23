"""The local voice turn machine: end-of-turn, barge-in, sentence streaming."""

from __future__ import annotations

import asyncio
import base64
import math
import struct

import pytest

from diapason.speech.realtime.base import SessionEvent
from diapason.speech.realtime.local_voice import (
    _SENTENCE_END,
    END_OF_TURN_S,
    INPUT_RATE,
    LocalVoiceSession,
    _turn_needs_tools,
    local_voice_readiness,
)


def pcm(seconds: float, amplitude: float = 0.05) -> bytes:
    """Mono PCM16: a soft tone (speech-like RMS) or silence at amplitude 0."""
    n = int(seconds * INPUT_RATE)
    return b"".join(
        struct.pack(
            "<h", int(amplitude * 32767 * math.sin(2 * math.pi * 220 * i / INPUT_RATE))
        )
        for i in range(n)
    )


class Harness:
    """A session with scripted stages and captured events."""

    def __init__(self, answer: str = "Bonjour. Comment ça va ?") -> None:
        self.transcribed: list[bytes] = []
        self.llm_calls: list[list[dict]] = []
        self.spoken: list[str] = []
        self.answer = answer

        def stt(audio: bytes) -> str:
            self.transcribed.append(audio)
            return "bonjour diapason"

        def llm(messages):
            self.llm_calls.append(messages)
            queue: asyncio.Queue = asyncio.Queue()
            # Stream the answer in small token-ish pieces, like Ollama does.
            for i in range(0, len(self.answer), 4):
                queue.put_nowait(self.answer[i : i + 4])
            queue.put_nowait(None)
            return queue

        def tts(text: str) -> bytes:
            self.spoken.append(text)
            return b"\x01\x02" * 240

        self.session = LocalVoiceSession(stt=stt, llm=llm, tts=tts)

    async def events_until(self, kind: str, limit: int = 30) -> list:
        seen = []
        for _ in range(limit):
            event = await asyncio.wait_for(self.session._queue.get(), timeout=2)
            if event is None:
                break
            seen.append(event)
            if event.kind == kind:
                break
        return seen


async def _drain_ready(harness: Harness) -> None:
    event = await asyncio.wait_for(harness.session._queue.get(), timeout=2)
    assert event.kind == "ready"


def test_readiness_rejects_a_missing_local_voice_extra(monkeypatch):
    monkeypatch.setattr(
        "diapason.speech.realtime.local_voice.importlib.util.find_spec",
        lambda name: None if name == "kokoro" else object(),
    )

    assert local_voice_readiness() == (False, "missing-dependencies")


@pytest.mark.asyncio
async def test_connect_emits_ready_only_after_successful_warmup(monkeypatch):
    session = LocalVoiceSession(stt=lambda _: "", llm=lambda _: None, tts=lambda _: b"")
    monkeypatch.setattr(
        "diapason.speech.realtime.local_voice.ollama_reachable", lambda: True
    )
    warmed = False

    async def warm() -> bool:
        nonlocal warmed
        await asyncio.sleep(0)
        warmed = True
        return True

    monkeypatch.setattr(session, "_warm", warm)
    await session.connect()

    event = await asyncio.wait_for(session._queue.get(), timeout=1)
    assert warmed is True
    assert event.kind == "ready"


@pytest.mark.asyncio
async def test_connect_does_not_emit_ready_after_failed_warmup(monkeypatch):
    session = LocalVoiceSession(stt=lambda _: "", llm=lambda _: None, tts=lambda _: b"")
    monkeypatch.setattr(
        "diapason.speech.realtime.local_voice.ollama_reachable", lambda: True
    )

    async def warm() -> bool:
        await session._queue.put(SessionEvent(kind="error", detail="missing Kokoro"))
        return False

    monkeypatch.setattr(session, "_warm", warm)
    await session.connect()

    event = await asyncio.wait_for(session._queue.get(), timeout=1)
    assert event.kind == "error"
    assert session._queue.empty()


class TestTurnDetection:
    @pytest.mark.asyncio
    async def test_speech_then_silence_triggers_a_full_turn(self):
        harness = Harness()
        session = harness.session
        await session.send_audio(pcm(0.6))
        await session.send_audio(pcm(END_OF_TURN_S + 0.1, amplitude=0.0))
        assert session._respond_task is not None
        await session._respond_task

        kinds = [e.kind async for e in _collect(session)]
        assert "transcript" in kinds and "audio" in kinds
        assert harness.transcribed, "STT must receive the utterance"
        assert harness.llm_calls, "the LLM must be asked"
        assert harness.spoken, "the answer must be synthesised"

    @pytest.mark.asyncio
    async def test_a_short_blip_is_not_a_turn(self):
        harness = Harness()
        session = harness.session
        # 100 ms of sound — a cough, not a sentence.
        await session.send_audio(pcm(0.1))
        await session.send_audio(pcm(END_OF_TURN_S + 0.1, amplitude=0.0))
        assert session._respond_task is None
        assert not harness.transcribed

    @pytest.mark.asyncio
    async def test_leading_silence_is_not_buffered(self):
        harness = Harness()
        session = harness.session
        await session.send_audio(pcm(2.0, amplitude=0.0))
        await session.send_audio(pcm(0.6))
        await session.send_audio(pcm(END_OF_TURN_S + 0.1, amplitude=0.0))
        await session._respond_task
        # The utterance should be ~1.3 s, not ~3.3 s: silence before speech
        # would only lengthen what Whisper has to chew through.
        assert len(harness.transcribed[0]) / 2 / INPUT_RATE < 2.0

    @pytest.mark.asyncio
    async def test_a_pause_shorter_than_end_of_turn_does_not_split(self):
        harness = Harness()
        session = harness.session
        await session.send_audio(pcm(0.5))
        await session.send_audio(pcm(0.3, amplitude=0.0))  # breath, not end
        await session.send_audio(pcm(0.5))
        assert session._respond_task is None, "the turn must still be open"


class TestRealtimeIntentLatency:
    """The schema costs prefill; withholding it costs a promised capability.

    This class used to assert that anything without a trigger word — « comment
    vas-tu aujourd'hui » among them — skipped the schema. That optimization
    was real, and so was its price: the allowlist had to name every phrasing
    of every one of the twenty tools the system prompt advertises, and the
    ones it missed were answered from imagination, in the same confident
    voice. The rule is now inverted, so a phrasing nobody anticipated gets
    the tools instead of getting invented.
    """

    @pytest.mark.parametrize(
        "utterance",
        [
            "Comment vas-tu aujourd’hui ?",  # was exempt, now carries them
            "Que contient mon calendrier ?",
            "Quelles sont mes tâches aujourd’hui ?",
            "Combien j’ai dépensé ce mois-ci ?",
            "Note que je dois appeler le dentiste",
            "Où j’en suis avec mes habitudes ?",
            "arrête le partage",  # a command, never filler
        ],
    )
    def test_anything_that_could_be_a_request_carries_the_schema(self, utterance):
        assert _turn_needs_tools([{"role": "user", "content": utterance}])

    @pytest.mark.parametrize(
        "utterance",
        [
            "oui",
            "Merci beaucoup",
            "d’accord",  # apostrophe typographique — ce que rend la STT
            "d'accord",  # apostrophe ASCII — ce que rendent d’autres moteurs
            "Salut !",
            "hmm",
            "parfait",
            "à plus",
        ],
    )
    def test_recognisable_filler_still_skips_it(self, utterance):
        assert not _turn_needs_tools([{"role": "user", "content": utterance}])

    def test_an_empty_turn_skips_it(self):
        assert not _turn_needs_tools([{"role": "user", "content": "   "}])

    @pytest.mark.asyncio
    async def test_explicit_open_notes_bypasses_the_llm(self, monkeypatch):
        harness = Harness()
        harness.session._stt = lambda _audio: "Ouvres-moi l'application note"
        monkeypatch.setattr(
            "diapason.desktop.voice_commands.execute_voice_action",
            lambda action: {
                "handled": True,
                "kind": action.kind,
                "target": action.target,
                "success": True,
                "detail": "Opened app Notes",
            },
        )

        await harness.session.send_audio(pcm(0.6))
        await harness.session.send_audio(pcm(END_OF_TURN_S + 0.1, amplitude=0.0))
        await harness.session._respond_task

        assert harness.llm_calls == []
        assert harness.spoken == ["J’ouvre Notes."]
        events = [event async for event in _collect(harness.session)]
        tool_events = [event for event in events if event.kind == "tool"]
        assert tool_events and tool_events[0].tool_ok is True

    @pytest.mark.asyncio
    async def test_bare_hallucinated_app_name_never_becomes_a_fast_action(
        self, monkeypatch
    ):
        harness = Harness(answer="Je t’écoute.")
        harness.session._stt = lambda _audio: "Google Chrome"
        execute = monkeypatch.setattr(
            "diapason.desktop.voice_commands.execute_voice_action",
            lambda _action: pytest.fail("a bare app name must not execute"),
        )

        await harness.session.send_audio(pcm(0.6))
        await harness.session.send_audio(pcm(END_OF_TURN_S + 0.1, amplitude=0.0))
        await harness.session._respond_task

        assert execute is None
        assert harness.llm_calls, "non-explicit text may converse, but must not act"


class TestBargeIn:
    @pytest.mark.asyncio
    async def test_speaking_over_the_answer_cancels_it(self):
        harness = Harness()
        session = harness.session

        async def slow_tts_never_finishes(*_a, **_k):
            await asyncio.sleep(30)

        # A respond task that would run forever without cancellation.
        session._respond_task = asyncio.get_running_loop().create_task(
            slow_tts_never_finishes()
        )
        await session.send_audio(pcm(0.1))
        await asyncio.sleep(0)
        assert session._respond_task.cancelled() or session._respond_task.done()
        kinds = [e.kind async for e in _collect(session)]
        assert "interrupted" in kinds

    @pytest.mark.asyncio
    async def test_explicit_interrupt_cancels_and_reports(self):
        harness = Harness()
        session = harness.session

        session._respond_task = asyncio.get_running_loop().create_task(
            asyncio.sleep(30)
        )
        await session.interrupt()
        await asyncio.sleep(0)
        assert session._respond_task.cancelled() or session._respond_task.done()
        kinds = [e.kind async for e in _collect(session)]
        assert "interrupted" in kinds


class TestSentenceStreaming:
    @pytest.mark.asyncio
    async def test_sentences_are_spoken_as_they_complete(self):
        harness = Harness(answer="Première phrase. Deuxième phrase. Et la fin")
        session = harness.session
        await session.send_text("dis trois choses")
        await session._respond_task
        # Three chunks: two closed sentences plus the unterminated tail —
        # waiting for the whole answer would turn "time to first sentence"
        # back into "time to full answer".
        assert len(harness.spoken) == 3
        assert harness.spoken[0].startswith("Première")

    @pytest.mark.asyncio
    async def test_the_full_answer_lands_in_history_and_transcript(self):
        harness = Harness(answer="Oui. Bien sûr.")
        session = harness.session
        await session.send_text("tu es là ?")
        await session._respond_task
        events = [e async for e in _collect(session)]
        finals = [e for e in events if e.kind == "transcript" and e.role == "assistant"]
        assert finals and "Bien sûr" in finals[-1].text
        assert session._history[-1]["role"] == "assistant"

    @pytest.mark.asyncio
    async def test_audio_events_carry_base64_pcm_at_24k(self):
        harness = Harness(answer="Test.")
        session = harness.session
        await session.send_text("va")
        await session._respond_task
        events = [e async for e in _collect(session)]
        audio = [e for e in events if e.kind == "audio"]
        assert audio
        assert audio[0].sample_rate == 24000
        assert base64.b64decode(audio[0].audio_b64) == b"\x01\x02" * 240

    @pytest.mark.asyncio
    async def test_llm_error_token_becomes_an_error_event(self):
        def broken_llm(messages):
            queue: asyncio.Queue = asyncio.Queue()
            queue.put_nowait("\x00ERROR\x00ollama est tombé")
            queue.put_nowait(None)
            return queue

        session = LocalVoiceSession(
            stt=lambda _a: "peu importe", llm=broken_llm, tts=lambda _t: b""
        )
        await session.send_text("bonjour")
        await session._respond_task
        events = [e async for e in _collect(session)]
        errors = [e for e in events if e.kind == "error"]
        assert errors and "ollama" in errors[0].detail


class TestSentenceRegex:
    def test_splits_on_ordinary_punctuation(self):
        assert _SENTENCE_END.search("Bonjour. La suite") is not None
        assert _SENTENCE_END.search("Vraiment ? Oui") is not None

    def test_does_not_split_mid_sentence(self):
        assert _SENTENCE_END.search("Bonjour tout le monde") is None

    def test_newline_is_a_boundary(self):
        assert _SENTENCE_END.search("liste :\ndeux") is not None


class TestHistory:
    @pytest.mark.asyncio
    async def test_history_is_capped(self):
        harness = Harness(answer="Ok.")
        session = harness.session
        for i in range(20):
            await session.send_text(f"message {i}")
            await session._respond_task
        assert len(session._history) <= 16


async def _collect(session) -> "asyncio.AsyncIterator":
    while not session._queue.empty():
        event = session._queue.get_nowait()
        if event is not None:
            yield event


class ToolHarness:
    """A session whose LLM asks for a tool once, then answers with text."""

    def __init__(
        self,
        *,
        rounds_of_tools: int = 1,
        enable_tools: bool = True,
        max_tool_steps: int = 12,
    ) -> None:
        self.executed: list[tuple[str, dict]] = []
        self.llm_rounds: list[list[dict]] = []
        self.spoken: list[str] = []
        rounds = {"left": rounds_of_tools}

        def llm(messages):
            self.llm_rounds.append(messages)
            queue: asyncio.Queue = asyncio.Queue()
            if rounds["left"] > 0:
                rounds["left"] -= 1
                queue.put_nowait(
                    (
                        "tools",
                        [
                            {
                                "function": {
                                    "name": "open_uri",
                                    "arguments": {"uri": "https://example.com"},
                                }
                            }
                        ],
                    )
                )
            else:
                queue.put_nowait("C'est fait.")
            queue.put_nowait(None)
            return queue

        def executor(name: str, args: dict) -> dict:
            self.executed.append((name, args))
            return {"ok": True, "content": "ouvert"}

        def tts(text: str) -> bytes:
            self.spoken.append(text)
            return b"\x01" * 64

        self.session = LocalVoiceSession(
            stt=lambda _a: "ouvre example point com",
            llm=llm,
            tts=tts,
            tool_executor=executor,
            enable_tools=enable_tools,
            max_tool_steps=max_tool_steps,
        )


class TestVoiceTools:
    @pytest.mark.asyncio
    async def test_a_tool_call_runs_then_the_answer_is_spoken(self):
        harness = ToolHarness()
        await harness.session.send_text("ouvre example")
        await harness.session._respond_task

        assert harness.executed == [("open_uri", {"uri": "https://example.com"})]
        # Round two must carry the tool result so the model can build on it.
        assert len(harness.llm_rounds) == 2
        roles = [m["role"] for m in harness.llm_rounds[1]]
        assert "tool" in roles
        assert harness.spoken == ["C'est fait."]

    @pytest.mark.asyncio
    async def test_the_panel_hears_about_the_tool(self):
        harness = ToolHarness()
        await harness.session.send_text("va")
        await harness.session._respond_task
        events = [e async for e in _collect(harness.session)]
        tools = [e for e in events if e.kind == "tool"]
        assert tools and tools[0].tool_name == "open_uri" and tools[0].tool_ok

    @pytest.mark.asyncio
    async def test_an_endless_tool_asker_is_bounded_by_the_budget(self):
        harness = ToolHarness(rounds_of_tools=99, max_tool_steps=3)
        await harness.session.send_text("boucle")
        await harness.session._respond_task
        # Three executions, then budget refusals, and the loop terminates —
        # a model that asks for tools forever must not be able to loop us
        # forever.
        assert len(harness.executed) == 3

    @pytest.mark.asyncio
    async def test_tools_disabled_ignores_the_calls(self):
        harness = ToolHarness(enable_tools=False)
        await harness.session.send_text("ouvre example")
        await harness.session._respond_task
        assert harness.executed == []
        assert len(harness.llm_rounds) == 1

    @pytest.mark.asyncio
    async def test_string_arguments_are_parsed(self):
        executed = []

        def llm(messages):
            queue: asyncio.Queue = asyncio.Queue()
            if not executed:
                queue.put_nowait(
                    (
                        "tools",
                        [
                            {
                                "function": {
                                    "name": "focus_app",
                                    "arguments": '{"name": "Safari"}',
                                }
                            }
                        ],
                    )
                )
            else:
                queue.put_nowait("Voilà.")
            queue.put_nowait(None)
            return queue

        session = LocalVoiceSession(
            stt=lambda _a: "",
            llm=llm,
            tts=lambda _t: b"",
            tool_executor=lambda n, a: (executed.append((n, a)), {"ok": True})[1],
        )
        await session.send_text("mets Safari devant")
        await session._respond_task
        # Gemini and Ollama send arguments as a dict; OpenAI as a JSON string.
        # Both must land as the same dict.
        assert executed == [("focus_app", {"name": "Safari"})]


class TestSpeakable:
    def test_emojis_never_reach_the_vocoder(self):
        from diapason.speech.realtime.local_voice import speakable

        assert speakable("Bonjour ! 😊🎉") == "Bonjour !"
        assert speakable("C'est fait ✅") == "C'est fait"
        assert speakable("🇫🇷 On y va") == "On y va"

    def test_markdown_is_silenced(self):
        from diapason.speech.realtime.local_voice import speakable

        assert speakable("**Important** : `code` et *italique*") == (
            "Important : code et italique"
        )
        assert speakable("- premier point") == "premier point"

    def test_ordinary_french_is_untouched(self):
        from diapason.speech.realtime.local_voice import speakable

        text = "L'été, à 15 h 30, ça coûte 3,50 € — d'accord ?"
        assert speakable(text) == text

    @pytest.mark.asyncio
    async def test_an_all_emoji_chunk_is_skipped_not_crashed(self):
        harness = Harness(answer="👍👍👍. Vraiment super.")
        await harness.session.send_text("merci")
        await harness.session._respond_task
        # The emoji-only sentence must neither reach the vocoder nor leave
        # a hole in the transcript.
        assert harness.spoken == ["Vraiment super."]

    @pytest.mark.asyncio
    async def test_the_transcript_matches_what_was_actually_said(self):
        harness = Harness(answer="Bonne idée 🎉 ! Allons-y.")
        await harness.session.send_text("on y va ?")
        await harness.session._respond_task
        events = [e async for e in _collect(harness.session)]
        finals = [e for e in events if e.kind == "transcript" and e.role == "assistant"]
        assert "🎉" not in finals[-1].text


class TestFirstChunkLatency:
    @pytest.mark.asyncio
    async def test_the_first_comma_is_a_boundary(self):
        harness = Harness(
            answer="Oui bien sûr Carlito, je peux le faire tout de suite."
        )
        await harness.session.send_text("tu peux ?")
        await harness.session._respond_task
        # "Oui bien sûr Carlito," must be audible before the sentence ends —
        # that half-second is the one the user experiences as "it heard me".
        assert harness.spoken[0] == "Oui bien sûr Carlito,"

    @pytest.mark.asyncio
    async def test_later_commas_do_not_fragment_the_speech(self):
        harness = Harness(
            answer="D'accord, je commence. Ensuite, on verra, si tu veux."
        )
        await harness.session.send_text("va")
        await harness.session._respond_task
        # "D'accord, " is under the minimum-length guard, so no early cut
        # happens at all here: two whole sentences, none of the later commas
        # honoured. Cutting at every comma would turn the voice into a
        # telegram — the guard exists precisely for this case, and this test
        # originally expected the wrong thing.
        assert harness.spoken == [
            "D'accord, je commence.",
            "Ensuite, on verra, si tu veux.",
        ]


class TestSpeculativeSTT:
    @pytest.mark.asyncio
    async def test_transcription_starts_during_the_silence_window(self):
        harness = Harness()
        session = harness.session
        await session.send_audio(pcm(0.6))
        # 0.3 s of silence: past the speculation threshold, before end of turn.
        await session.send_audio(pcm(0.3, amplitude=0.0))
        assert session._speculative is not None
        assert session._respond_task is None, "the turn must not be over yet"

    @pytest.mark.asyncio
    async def test_the_speculative_result_is_used_once(self):
        harness = Harness()
        session = harness.session
        await session.send_audio(pcm(0.6))
        await session.send_audio(pcm(0.8, amplitude=0.0))
        await session._respond_task
        # One transcription total: the speculative one, not a second full run.
        assert len(harness.transcribed) == 1

    @pytest.mark.asyncio
    async def test_resumed_speech_discards_the_speculation(self):
        harness = Harness()
        session = harness.session
        await session.send_audio(pcm(0.6))
        await session.send_audio(pcm(0.3, amplitude=0.0))
        assert session._speculative is not None
        await session.send_audio(pcm(0.4))  # reprise : la phrase continue
        assert session._speculative is None, "stale speculation must die"


class TestPlaybackInterruption:
    """The reported bug: « je demande d'arrêter de parler, il n'arrête pas ».

    Synthesis outruns playback, so the respond task is usually finished while
    the user is still HEARING the answer — there was nothing left to cancel,
    and the barge-in silently did nothing. The fix interrupts the playback
    clock, not just the task.
    """

    @pytest.mark.asyncio
    async def test_speech_over_finished_task_still_interrupts(self):
        import time

        harness = Harness()
        session = harness.session
        # The respond task is DONE, but 5 s of audio are still playing
        # client-side.
        session._speaking_until = time.monotonic() + 5.0
        await session.send_audio(pcm(0.1, amplitude=0.08))  # voix franche
        kinds = [e.kind async for e in _collect(session)]
        assert "interrupted" in kinds
        assert session._speaking_until == 0.0

    @pytest.mark.asyncio
    async def test_speaker_echo_does_not_self_interrupt(self):
        import time

        harness = Harness()
        session = harness.session
        session._speaking_until = time.monotonic() + 5.0
        # Between the speech and barge thresholds: what the microphone hears
        # of the speakers, not a voice over the top.
        await session.send_audio(pcm(0.3, amplitude=0.015))
        kinds = [e.kind async for e in _collect(session)]
        assert "interrupted" not in kinds
        assert len(session._buffer) == 0, "echo must not be transcribed later"

    @pytest.mark.asyncio
    async def test_speaking_clock_advances_with_synthesised_audio(self):
        import time

        harness = Harness(answer="Une phrase assez longue pour durer.")
        session = harness.session
        before = time.monotonic()
        await session.send_text("parle")
        await session._respond_task
        assert session._speaking_until > before

    @pytest.mark.asyncio
    async def test_normal_threshold_returns_after_playback(self):
        harness = Harness()
        session = harness.session
        session._speaking_until = 0.0  # plus rien ne joue
        await session.send_audio(pcm(0.4, amplitude=0.015))  # voix douce
        assert session._in_speech, "soft speech must count again"


class TestStopPhrases:
    def test_the_phrases_that_mean_silence(self):
        from diapason.speech.realtime.local_voice import is_stop_phrase

        for phrase in (
            "Arrête",
            "arrête de parler",
            "Diapason, arrête !",
            "stop",
            "Tais-toi",
            "chut",
            "ça suffit",
            "c'est bon merci",
            "arrête-toi s'il te plaît",
        ):
            assert is_stop_phrase(phrase), phrase

    def test_ordinary_sentences_are_not_stops(self):
        from diapason.speech.realtime.local_voice import is_stop_phrase

        for phrase in (
            "arrête-moi si je me trompe, mais continue",
            "peux-tu arrêter le minuteur ?",
            "le stop du bus est loin",
            "c'est bon pour la santé ?",
        ):
            assert not is_stop_phrase(phrase), phrase

    @pytest.mark.asyncio
    async def test_a_stop_phrase_gets_silence_not_an_answer(self):
        harness = Harness()
        harness.session._stt = lambda _a: "arrête de parler"
        session = harness.session
        await session.send_audio(pcm(0.6))
        await session.send_audio(pcm(END_OF_TURN_S + 0.1, amplitude=0.0))
        await session._respond_task
        # The user transcript appears; no LLM round, nothing spoken.
        assert harness.llm_calls == []
        assert harness.spoken == []
        events = [e async for e in _collect(session)]
        users = [e for e in events if e.kind == "transcript" and e.role == "user"]
        assert users and users[0].text == "arrête de parler"


class TestPromptComposition:
    def test_memory_instructions_compose_with_voice_rules(self):
        session = LocalVoiceSession(
            instructions="Tu connais Carlito et ses projets.",
            language="français",
            stt=lambda _a: "",
            llm=lambda _m: None,
            tts=lambda _t: b"",
        )
        prompt = session._system_prompt()
        # Both halves, or the default-on memory path silently drops the
        # anti-emoji rule and the language pin — which is how emojis came
        # back in real sessions despite the prompt saying never.
        assert "Carlito" in prompt
        assert "READ ALOUD" in prompt
        assert "français" in prompt

    def test_without_instructions_the_oral_template_still_carries_rules(self):
        session = LocalVoiceSession(
            stt=lambda _a: "", llm=lambda _m: None, tts=lambda _t: b""
        )
        assert "READ ALOUD" in session._system_prompt()


class TestToolsRefusalFallback:
    @pytest.mark.asyncio
    async def test_a_model_without_tools_degrades_instead_of_breaking(
        self, monkeypatch
    ):
        """gemma3-style refusal: Ollama 400s the whole request when a model
        does not support the tools field. A voice that cannot act is
        degraded; one that errors on EVERY turn is broken — the retry strips
        the tools and streams normally."""
        import io
        import json as _json
        import urllib.error

        from diapason.speech.realtime import local_voice

        bodies: list[dict] = []

        class FakeResponse:
            def __init__(self, lines):
                self._lines = lines

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def __iter__(self):
                return iter(self._lines)

        def fake_urlopen(request, timeout=0):
            body = _json.loads(request.data)
            bodies.append(body)
            if "tools" in body:
                raise urllib.error.HTTPError(
                    "http://x",
                    400,
                    "Bad Request",
                    {},
                    io.BytesIO(b'{"error":"gemma3 does not support tools"}'),
                )
            return FakeResponse(
                [
                    _json.dumps({"message": {"content": "Bonjour."}}).encode(),
                    _json.dumps({"done": True}).encode(),
                ]
            )

        monkeypatch.setattr(local_voice.urllib.request, "urlopen", fake_urlopen)
        llm = local_voice._default_llm("gemma3:12b", "système", [{"type": "function"}])
        queue = llm([{"role": "user", "content": "ouvre Notes"}])
        items = []
        while True:
            item = await asyncio.wait_for(queue.get(), timeout=5)
            if item is None:
                break
            items.append(item)

        assert items == ["Bonjour."], "the retry must stream normally"
        assert "tools" in bodies[0] and "tools" not in bodies[1]

    @pytest.mark.asyncio
    async def test_other_http_errors_still_surface(self, monkeypatch):
        import io
        import urllib.error

        from diapason.speech.realtime import local_voice

        def fake_urlopen(request, timeout=0):
            raise urllib.error.HTTPError(
                "http://x", 500, "boom", {}, io.BytesIO(b'{"error":"down"}')
            )

        monkeypatch.setattr(local_voice.urllib.request, "urlopen", fake_urlopen)
        llm = local_voice._default_llm("m", "s", None)
        queue = llm([])
        first = await asyncio.wait_for(queue.get(), timeout=5)
        assert isinstance(first, str) and first.startswith("\x00ERROR\x00")


class TestFrenchClock:
    def test_spells_the_date_in_french(self):
        import datetime

        from diapason.speech.realtime.local_voice import french_now

        moment = datetime.datetime(2026, 8, 12, 14, 5)
        assert french_now(moment) == "mercredi 12 août 2026, 14 h 05"

    def test_minutes_are_zero_padded(self):
        import datetime

        from diapason.speech.realtime.local_voice import french_now

        moment = datetime.datetime(2026, 1, 1, 9, 7)
        assert french_now(moment).endswith("9 h 07")


class TestCrossTurnToolMemory:
    """« joue-la » next turn needs a trace; the budget must not starve turns."""

    @pytest.mark.asyncio
    async def test_budget_resets_each_turn(self):
        # Per-session, never reset, the cap starved every turn after the
        # first: twelve tool calls into a session, all later « joue X »
        # failed with "budget exceeded" until reconnect.
        harness = ToolHarness(rounds_of_tools=99, max_tool_steps=3)
        await harness.session.send_text("boucle")
        await harness.session._respond_task
        await harness.session.send_text("encore")
        await harness.session._respond_task
        assert len(harness.executed) == 6

    @pytest.mark.asyncio
    async def test_tool_actions_leave_a_compact_trace_in_history(self):
        harness = ToolHarness()
        await harness.session.send_text("ouvre example")
        await harness.session._respond_task
        notes = [m for m in harness.session._history if m["role"] == "system"]
        assert len(notes) == 1
        note = notes[0]["content"]
        assert "open_uri" in note
        assert "https://example.com" in note
        assert "ok" in note

    @pytest.mark.asyncio
    async def test_the_next_turn_sees_the_trace(self):
        harness = ToolHarness()
        await harness.session.send_text("ouvre example")
        await harness.session._respond_task
        await harness.session.send_text("joue-la")
        await harness.session._respond_task
        # Turn 2's prompt must carry turn 1's actions — that is the whole
        # point: the raw tool payloads stay per-turn, the trace crosses.
        turn2_messages = harness.llm_rounds[-1]
        assert any(
            m["role"] == "system" and "open_uri" in m.get("content", "")
            for m in turn2_messages
        )

    @pytest.mark.asyncio
    async def test_no_tools_no_trace(self):
        harness = ToolHarness(rounds_of_tools=0)
        await harness.session.send_text("bonjour")
        await harness.session._respond_task
        assert not [m for m in harness.session._history if m["role"] == "system"]


class TestToolNote:
    def test_note_compacts_call_and_result(self):
        import json as _json

        from diapason.speech.realtime.local_voice import _tool_note

        call = {
            "function": {
                "name": "open_anything",
                "arguments": {"target": "joue papaoutai sur youtube"},
            }
        }
        reply = {
            "role": "tool",
            "content": _json.dumps(
                {
                    "ok": True,
                    "content": (
                        "Playing top YouTube result for 'papaoutai': "
                        "https://www.youtube.com/watch?v=abc12345678"
                    ),
                }
            ),
        }
        note = _tool_note(call, reply)
        assert "open_anything" in note
        assert "joue papaoutai sur youtube" in note
        assert "-> ok" in note
        assert "watch?v=abc12345678" in note

    def test_note_survives_garbage(self):
        from diapason.speech.realtime.local_voice import _tool_note

        note = _tool_note({}, {"content": "not json"})
        assert "?" in note  # unknown name and unknown outcome, but no crash

    def test_note_survives_a_non_dict_json_payload(self):
        # json.loads('"..."') is a str: .get on it is an AttributeError,
        # which — uncaught — aborted the whole spoken turn.
        from diapason.speech.realtime.local_voice import _tool_note

        call = {"function": {"name": "open_uri", "arguments": {}}}
        note = _tool_note(call, {"content": '"just a string"'})
        assert "open_uri" in note  # no crash is the test


class TestPreRoll:
    """Word onsets live BELOW the speech threshold; the ring saves them.

    Without it, « App Store » reached Whisper as « …Store » — the gate only
    started buffering once RMS crossed SPEECH_RMS, a syllable too late.
    """

    @pytest.mark.asyncio
    async def test_quiet_onset_is_prepended_to_the_utterance(self):
        harness = Harness()
        session = harness.session
        await session.connect()
        quiet = pcm(0.3, 0.002)  # sous le seuil : l'attaque du mot
        speech = pcm(0.5, 0.05)
        await session.send_audio(quiet)
        await session.send_audio(speech)
        await session.send_audio(pcm(END_OF_TURN_S + 0.2, 0.0))
        await session._respond_task
        assert len(harness.transcribed) == 1
        got = len(harness.transcribed[0])
        # L'énoncé doit contenir la parole ET (une partie de) l'attaque
        # silencieuse — pas seulement ce qui dépasse le seuil.
        assert got > len(speech)
        assert got >= len(speech) + min(len(quiet), int(0.4 * INPUT_RATE) * 2)

    @pytest.mark.asyncio
    async def test_the_ring_is_bounded(self):
        harness = Harness()
        session = harness.session
        await session.connect()
        # Trois secondes de silence ne doivent pas gonfler l'énoncé : seule
        # la fenêtre de pré-roll survit.
        await session.send_audio(pcm(3.0, 0.002))
        assert len(session._preroll) <= int(0.4 * INPUT_RATE) * 2
        await session.send_audio(pcm(0.5, 0.05))
        await session.send_audio(pcm(END_OF_TURN_S + 0.2, 0.0))
        await session._respond_task
        got = len(harness.transcribed[0])
        cap = (
            len(pcm(0.5, 0.05))
            + int(0.4 * INPUT_RATE) * 2
            + len(pcm(END_OF_TURN_S + 0.2, 0.0))
        )
        assert got <= cap

    @pytest.mark.asyncio
    async def test_barge_in_onset_survives_playback(self):
        harness = Harness()
        session = harness.session
        await session.connect()
        import time as _time

        session._speaking_until = _time.monotonic() + 30
        # Pendant la lecture : une amorce sous le seuil de barge-in (perdue
        # avant ce correctif), puis la voix qui monte au-dessus.
        soft_start = pcm(0.2, 0.012)  # > SPEECH_RMS mais < BARGE_RMS
        await session.send_audio(soft_start)
        await session.send_audio(pcm(0.5, 0.09))  # barge-in franc
        await session.send_audio(pcm(END_OF_TURN_S + 0.2, 0.0))
        await session._respond_task
        got = len(harness.transcribed[0])
        assert got >= len(pcm(0.5, 0.09)) + min(
            len(soft_start), int(0.4 * INPUT_RATE) * 2
        )


class TestVoiceTranscriptPolish:
    def test_dictionary_corrections_reach_voice_transcripts(self, monkeypatch):
        import diapason.speech.dictation_dictionary as dd
        from diapason.speech.realtime.local_voice import polish_transcript

        seen = {}

        def fake_apply(text, entries=None, *, path=None, bump_usage=True):
            seen["bump"] = bump_usage
            return text.replace("app store", "App Store")

        monkeypatch.setattr(dd, "apply_dictionary", fake_apply)
        assert polish_transcript("ouvre l'app store") == "ouvre l'App Store"
        # La voix ne doit pas fausser les statistiques du dictionnaire.
        assert seen["bump"] is False

    def test_a_broken_dictionary_never_blocks_the_voice(self, monkeypatch):
        import diapason.speech.dictation_dictionary as dd
        from diapason.speech.realtime.local_voice import polish_transcript

        def boom(*a, **k):
            raise RuntimeError("dictionnaire corrompu")

        monkeypatch.setattr(dd, "apply_dictionary", boom)
        assert polish_transcript("bonjour") == "bonjour"


class TestPromesseSansActe:
    """« D'accord, je cherche du R&B sur YouTube pour toi » — dit, rien fait
    (23 août 2026). Un tour qui promet sans appeler d'outil est repris une
    fois, avec sommation, et l'acte suit la parole."""

    @staticmethod
    def _harnais(reponses):
        """Un LLM scripté : chaque élément est soit un texte, soit une liste
        d'appels d'outils."""
        etat = {"i": 0}
        journal = {"executed": [], "rounds": []}

        def llm(messages):
            journal["rounds"].append(list(messages))
            queue: asyncio.Queue = asyncio.Queue()
            scenario = reponses[min(etat["i"], len(reponses) - 1)]
            etat["i"] += 1
            if isinstance(scenario, list):
                queue.put_nowait(("tools", scenario))
                queue.put_nowait("Voilà, ça joue.")
            else:
                queue.put_nowait(scenario)
            queue.put_nowait(None)
            return queue

        def executor(name, args):
            journal["executed"].append((name, args))
            return {"ok": True, "content": "ouvert"}

        session = LocalVoiceSession(
            stt=lambda _a: "je veux du R&B",
            llm=llm,
            tts=lambda _t: b"\x01" * 64,
            tool_executor=executor,
            enable_tools=True,
        )
        return session, journal

    @pytest.mark.asyncio
    async def test_la_promesse_est_sommee_puis_l_acte_suit(self):
        session, journal = self._harnais(
            [
                "D'accord, je cherche de la musique R&B sur YouTube pour toi.",
                [{"function": {"name": "open_anything",
                               "arguments": {"target": "joue du R&B sur youtube"}}}],
            ]
        )
        await session._respond_to_text("je veux du R&B")
        assert journal["executed"], "la sommation doit produire l'acte"
        assert journal["executed"][0][0] == "open_anything"
        # la sommation est bien passée au second appel
        sommation = journal["rounds"][1][-1]
        assert sommation["role"] == "system"
        assert "sans appeler d'outil" in sommation["content"]

    @pytest.mark.asyncio
    async def test_une_reponse_ordinaire_ne_declenche_rien(self):
        session, journal = self._harnais(["Le R&B est né dans les années 40."])
        await session._respond_to_text("c'est quoi le R&B ?")
        assert journal["executed"] == []
        assert len(journal["rounds"]) == 1

    @pytest.mark.asyncio
    async def test_une_seule_sommation_jamais_deux(self):
        session, journal = self._harnais(
            [
                "Je cherche ça pour toi.",
                "Je vais chercher, un instant.",
            ]
        )
        await session._respond_to_text("je veux du R&B")
        # deux promesses de suite : une seule relance, pas de boucle
        assert len(journal["rounds"]) == 2
        assert journal["executed"] == []


class TestClicheDuBureau:
    """Le cliché du bureau entre dans le tour — en FIN de contexte, jamais
    dans le préambule où il brûlerait le cache de préfixe."""

    def test_le_cliche_arrive_juste_avant_le_tour_utilisateur(self, monkeypatch):
        from diapason.desktop.etat_bureau import EtatBureau
        import diapason.desktop.etat_bureau as eb

        monkeypatch.setattr(
            eb, "_cache", EtatBureau("Safari", ("Safari", "Notes"), 0.0)
        )
        session = Harness().session
        messages = session._turn_messages("ouvre Notes")
        assert messages[-1] == {"role": "user", "content": "ouvre Notes"}
        assert messages[-2]["role"] == "system"
        assert "au premier plan, Safari" in messages[-2]["content"]

    def test_sans_cliche_le_tour_reste_nu(self, monkeypatch):
        import diapason.desktop.etat_bureau as eb

        monkeypatch.setattr(eb, "_cache", None)
        session = Harness().session
        messages = session._turn_messages("bonjour")
        assert messages[-1]["role"] == "user"
        assert all("État du bureau" not in (m.get("content") or "") for m in messages)
