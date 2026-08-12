"""The local voice turn machine: end-of-turn, barge-in, sentence streaming."""

from __future__ import annotations

import asyncio
import base64
import math
import struct

import pytest

from diapason.speech.realtime.local_voice import (
    _SENTENCE_END,
    END_OF_TURN_S,
    INPUT_RATE,
    LocalVoiceSession,
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
