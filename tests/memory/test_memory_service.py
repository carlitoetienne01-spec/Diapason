"""Tests for the background memory service (diapason.memory.service)."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

from diapason.core.config import StorageConfig
from diapason.core.events import EventBus
from diapason.memory.service import (
    MemoryService,
    build_memory_service,
    publish_completed_exchange,
)
from diapason.memory.store import LocalFactStore


def _wait_until(predicate, timeout=2.0, interval=0.01):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


class FakeExtractor:
    """Extractor stub with controllable output, blocking and failures."""

    def __init__(self, facts=None, *, raises=None, gate=None):
        self._facts = facts or []
        self._raises = raises
        self._gate = gate  # optional threading.Event to block on
        self.calls = []

    def extract(self, user_text, assistant_text=""):
        self.calls.append((user_text, assistant_text))
        if self._gate is not None:
            self._gate.wait(timeout=2.0)
        if self._raises is not None:
            raise self._raises
        return list(self._facts)


def _service(tmp_path, extractor, **kwargs):
    store = LocalFactStore(tmp_path / "facts.jsonl")
    return MemoryService(store, extractor, **kwargs)


def test_start_stop_lifecycle(tmp_path):
    svc = _service(tmp_path, FakeExtractor())
    assert svc.is_running is False
    svc.start()
    assert svc.is_running is True
    svc.start()  # idempotent
    assert svc.is_running is True
    svc.stop()
    assert svc.is_running is False
    svc.stop()  # idempotent


def test_submit_extracts_and_stores(tmp_path):
    extractor = FakeExtractor(["User likes hiking"])
    svc = _service(tmp_path, extractor)
    svc.start()
    try:
        assert svc.submit("I love hiking", "Nice!") is True
        assert _wait_until(lambda: svc.fact_count() == 1)
        assert [f.text for f in svc.list_facts()] == ["User likes hiking"]
    finally:
        svc.stop()


def test_completed_exchange_event_extracts_and_stores(tmp_path):
    bus = EventBus(record_history=True)
    extractor = FakeExtractor(["User likes jazz"])
    store = LocalFactStore(tmp_path / "facts.jsonl")
    svc = MemoryService(store, extractor, event_bus=bus)
    svc.start()
    try:
        assert publish_completed_exchange(
            bus,
            "I like jazz",
            "Noted.",
            source="test",
        )
        assert _wait_until(lambda: svc.fact_count() == 1)
        assert extractor.calls == [("I like jazz", "Noted.")]
    finally:
        svc.stop()


def test_completed_exchange_event_unsubscribes_on_stop(tmp_path):
    bus = EventBus(record_history=True)
    extractor = FakeExtractor(["User likes jazz"])
    store = LocalFactStore(tmp_path / "facts.jsonl")
    svc = MemoryService(store, extractor, event_bus=bus)
    svc.start()
    svc.stop()

    publish_completed_exchange(bus, "I like jazz", "Noted.", source="test")

    assert extractor.calls == []


def test_submit_when_not_running_is_dropped(tmp_path):
    extractor = FakeExtractor(["x"])
    svc = _service(tmp_path, extractor)
    assert svc.submit("hi", "there") is False
    assert extractor.calls == []


def test_submit_empty_user_text_dropped(tmp_path):
    extractor = FakeExtractor(["x"])
    svc = _service(tmp_path, extractor)
    svc.start()
    try:
        assert svc.submit("   ", "y") is False
    finally:
        svc.stop()


def test_worker_survives_extractor_broken_pipe(tmp_path):
    """A BrokenPipeError in one job must not kill the worker."""
    extractor = FakeExtractor(raises=BrokenPipeError("client gone"))
    svc = _service(tmp_path, extractor)
    svc.start()
    try:
        svc.submit("first", "a")
        assert _wait_until(lambda: len(extractor.calls) == 1)
        # Service is still alive and accepting work.
        assert svc.is_running is True
        assert svc.submit("second", "b") is True
        assert _wait_until(lambda: len(extractor.calls) == 2)
    finally:
        svc.stop()


def test_worker_survives_generic_exception(tmp_path):
    extractor = FakeExtractor(raises=RuntimeError("boom"))
    svc = _service(tmp_path, extractor)
    svc.start()
    try:
        svc.submit("x", "y")
        assert _wait_until(lambda: len(extractor.calls) == 1)
        assert svc.is_running is True
    finally:
        svc.stop()


def test_submit_returns_false_when_queue_full(tmp_path):
    """Backpressure: a full queue drops work instead of blocking the caller."""
    gate = threading.Event()
    extractor = FakeExtractor(["fact"], gate=gate)
    svc = _service(tmp_path, extractor, max_queue=1)
    svc.start()
    try:
        # First submit is pulled by the worker and blocks on the gate.
        assert svc.submit("job1", "a") is True
        assert _wait_until(lambda: len(extractor.calls) == 1)
        # Fill the (size-1) queue, then the next submit must be dropped.
        assert svc.submit("job2", "b") is True
        dropped = svc.submit("job3", "c")
        assert dropped is False
    finally:
        gate.set()
        svc.stop()


def test_build_memory_service_disabled_returns_none(tmp_path):
    cfg = SimpleNamespace(memory=StorageConfig(enabled=False))
    assert build_memory_service(cfg, object(), "model") is None


def test_build_memory_service_no_engine_returns_none(tmp_path):
    cfg = SimpleNamespace(memory=StorageConfig(enabled=True))
    assert build_memory_service(cfg, None, "model") is None


def test_build_memory_service_no_model_returns_none(tmp_path):
    cfg = SimpleNamespace(memory=StorageConfig(enabled=True, extraction_model=""))
    assert build_memory_service(cfg, object(), "") is None


def test_build_memory_service_enabled(tmp_path):
    cfg = SimpleNamespace(
        memory=StorageConfig(
            enabled=True,
            extraction_model="qwen3:14b",
            facts_path=str(tmp_path / "facts.jsonl"),
            max_facts=10,
        )
    )
    svc = build_memory_service(cfg, object(), "fallback-model")
    assert isinstance(svc, MemoryService)
    assert svc._extractor._use_active_model is False


def test_build_memory_service_falls_back_to_default_model(tmp_path):
    cfg = SimpleNamespace(
        memory=StorageConfig(
            enabled=True,
            extraction_model="",
            facts_path=str(tmp_path / "facts.jsonl"),
        )
    )
    svc = build_memory_service(cfg, object(), "active-model")
    assert isinstance(svc, MemoryService)
    assert svc._extractor._use_active_model is True


class TestMemoirePrioritaire:
    """§5 : différer ne signifie ni perdre les échanges ni lancer deux ouvriers."""

    def test_un_doublon_en_attente_ne_consomme_pas_une_seconde_place(self, tmp_path):
        gate = threading.Event()
        extractor = FakeExtractor(["fact"], gate=gate)
        svc = _service(tmp_path, extractor, max_queue=1)
        svc.start()
        try:
            assert svc.submit("premier", "a")
            assert _wait_until(lambda: len(extractor.calls) == 1)
            assert svc.submit("premier", "a"), (
                "l'échange en cours est déjà pris en charge"
            )
            assert svc.submit("second", "b")
            assert svc.submit("second", "b"), "le doublon ne remplit pas la file"
            assert not svc.submit("second", "autre réponse"), (
                "une réponse différente reste distincte"
            )
            gate.set()
            assert _wait_until(lambda: svc._queue.unfinished_tasks == 0)
            assert extractor.calls == [("premier", "a"), ("second", "b")]
            assert svc.submit("premier", "a"), (
                "la déduplication ne dure pas éternellement"
            )
            assert _wait_until(lambda: len(extractor.calls) == 3)
        finally:
            gate.set()
            svc.stop()

    def test_un_redemarrage_ne_duplique_pas_une_extraction_encore_en_cours(
        self, tmp_path
    ):
        gate = threading.Event()
        extractor = FakeExtractor(["fact"], gate=gate)
        svc = _service(tmp_path, extractor)
        svc.start()
        try:
            svc.submit("premier", "a")
            assert _wait_until(lambda: len(extractor.calls) == 1)
            thread = svc._thread
            svc.stop(timeout=0.001)
            svc.start()
            assert svc._thread is thread, "l'ancien ouvrier possède encore son appel"
            assert not svc.is_running
            gate.set()
            thread.join(1)
            svc.start()
            assert svc.is_running
            assert svc.submit("second", "b")
            assert _wait_until(lambda: len(extractor.calls) == 2)
        finally:
            gate.set()
            svc.stop()

    def test_une_memoire_differee_secrit_apres_la_question(self, tmp_path):
        from diapason.engine.scheduling import InferenceScheduler, interactive_turn
        from diapason.memory.extractor import FactExtractor

        scheduler = InferenceScheduler(quiet_seconds=0)
        appels = []

        class Moteur:
            def generate(self, messages, *, model, **kwargs):
                with scheduler.slot(model):
                    appels.append(model)
                    return {"content": '["Préfère le thé"]'}

        svc = _service(tmp_path, FactExtractor(Moteur(), "m"))
        svc.start()
        try:
            with interactive_turn():
                assert svc.submit("J'aime le thé", "Noté")
                assert _wait_until(lambda: len(scheduler._pending) == 1)
                assert not appels, "la mémoire ne prend pas le moteur pendant le tour"
                assert svc.fact_count() == 0
            assert _wait_until(lambda: svc.fact_count() == 1)
            assert [f.text for f in svc.list_facts()] == ["Préfère le thé"]
        finally:
            svc.stop()

    def test_arreter_la_memoire_differee_ne_declenche_aucun_appel(self, tmp_path):
        from diapason.engine.scheduling import InferenceScheduler, interactive_turn
        from diapason.memory.extractor import FactExtractor

        scheduler = InferenceScheduler(quiet_seconds=0)
        appels = []

        class Moteur:
            def generate(self, messages, *, model, **kwargs):
                with scheduler.slot(model):
                    appels.append(model)
                    return {"content": "[]"}

        svc = _service(tmp_path, FactExtractor(Moteur(), "m"))
        svc.start()
        with interactive_turn():
            svc.submit("Test", "Réponse")
            assert _wait_until(lambda: len(scheduler._pending) == 1)
            svc.stop(timeout=1)
            assert svc._thread is None, "le fil sort même pendant une discussion"
        assert not appels, "un arrêt n'envoie pas une vieille extraction à Ollama"
        assert not scheduler._pending
