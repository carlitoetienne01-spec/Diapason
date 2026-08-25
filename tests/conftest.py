"""Shared fixtures — clear all registries and the event bus between tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from diapason.core.config import GpuInfo, HardwareInfo
from diapason.core.events import EventBus, reset_event_bus
from diapason.core.registry import (
    AgentRegistry,
    BenchmarkRegistry,
    ChannelRegistry,
    CompressionRegistry,
    ConnectorRegistry,
    EngineRegistry,
    FactStoreRegistry,
    MemoryRegistry,
    MinerRegistry,
    ModelRegistry,
    RouterPolicyRegistry,
    SkillRegistry,
    SpeechRegistry,
    ToolRegistry,
    TTSRegistry,
)


@pytest.fixture(autouse=True)
def _no_update_check(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> None:
    """Never let the CLI's PyPI update-check nag run during tests.

    ``check_for_updates`` writes its banner to stderr, which ``CliRunner``
    merges into ``result.output`` — polluting JSON/CSV output of any test
    that invokes a CLI command. It already self-disables when ``CI`` is
    set, but that only helps in CI; locally (e.g. a dev with a stale
    version-check cache and network access) it fires for real.
    """
    if request.path.name != "test_version_check.py":
        monkeypatch.setenv("DIAPASON_NO_UPDATE_CHECK", "1")


@pytest.fixture(autouse=True)
def _allow_mocked_outbound_paths(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    """Let unit-test doubles exercise outbound code paths without real egress.

    Production defaults remain local-only. Tests that verify that contract
    explicitly override this patch with their own local-mode verdict.
    """
    local_only_contract_tests = {
        "tests/channels/test_channel_contract.py",
        "tests/core/test_local_mode.py",
        "tests/engine/test_discovery_local_only.py",
        "tests/privacy/test_local_only_chokepoints.py",
        "tests/speech/test_discovery.py",
        "tests/speech/test_llm_polish_local_mode.py",
        "tests/speech/test_model_integrity.py",
        "tests/tools/test_screen_vision_tools.py",
    }
    relative_path = request.path.relative_to(Path(__file__).parent.parent).as_posix()
    if relative_path in local_only_contract_tests:
        return

    from diapason.core import local_mode

    monkeypatch.setattr(local_mode, "local_only", lambda config=None: False)


@pytest.fixture(autouse=True)
def _clean_registries() -> None:
    """Ensure each test starts with empty registries and a fresh event bus."""
    ModelRegistry.clear()
    EngineRegistry.clear()
    MemoryRegistry.clear()
    FactStoreRegistry.clear()
    MinerRegistry.clear()
    AgentRegistry.clear()
    ToolRegistry.clear()
    RouterPolicyRegistry.clear()
    BenchmarkRegistry.clear()
    ChannelRegistry.clear()
    SpeechRegistry.clear()
    CompressionRegistry.clear()
    ConnectorRegistry.clear()
    TTSRegistry.clear()
    SkillRegistry.clear()
    reset_event_bus()


# ---------------------------------------------------------------------------
# Hardware fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def nvidia_gpu() -> GpuInfo:
    """NVIDIA A100 GPU fixture."""
    return GpuInfo(vendor="nvidia", name="NVIDIA A100-SXM4-80GB", vram_gb=80.0, count=1)


@pytest.fixture
def nvidia_consumer_gpu() -> GpuInfo:
    """NVIDIA consumer GPU fixture."""
    return GpuInfo(
        vendor="nvidia",
        name="NVIDIA GeForce RTX 4090",
        vram_gb=24.0,
        count=1,
    )


@pytest.fixture
def nvidia_multi_gpu() -> GpuInfo:
    """NVIDIA multi-GPU fixture."""
    return GpuInfo(vendor="nvidia", name="NVIDIA H100", vram_gb=80.0, count=4)


@pytest.fixture
def amd_gpu() -> GpuInfo:
    """AMD MI300X GPU fixture."""
    return GpuInfo(vendor="amd", name="AMD Instinct MI300X", vram_gb=192.0, count=1)


@pytest.fixture
def apple_gpu() -> GpuInfo:
    """Apple Silicon GPU fixture."""
    return GpuInfo(vendor="apple", name="Apple M4 Max", vram_gb=128.0, count=1)


@pytest.fixture
def hardware_nvidia(nvidia_gpu: GpuInfo) -> HardwareInfo:
    """Full NVIDIA hardware profile."""
    return HardwareInfo(
        platform="linux",
        cpu_brand="AMD EPYC 7763",
        cpu_count=64,
        ram_gb=512.0,
        gpu=nvidia_gpu,
    )


@pytest.fixture
def hardware_nvidia_consumer(nvidia_consumer_gpu: GpuInfo) -> HardwareInfo:
    """Consumer NVIDIA hardware profile."""
    return HardwareInfo(
        platform="linux",
        cpu_brand="Intel Core i9-14900K",
        cpu_count=24,
        ram_gb=64.0,
        gpu=nvidia_consumer_gpu,
    )


@pytest.fixture
def hardware_amd(amd_gpu: GpuInfo) -> HardwareInfo:
    """Full AMD hardware profile."""
    return HardwareInfo(
        platform="linux",
        cpu_brand="AMD EPYC 9654",
        cpu_count=96,
        ram_gb=768.0,
        gpu=amd_gpu,
    )


@pytest.fixture
def hardware_apple(apple_gpu: GpuInfo) -> HardwareInfo:
    """Apple Silicon hardware profile."""
    return HardwareInfo(
        platform="darwin",
        cpu_brand="Apple M4 Max",
        cpu_count=16,
        ram_gb=128.0,
        gpu=apple_gpu,
    )


@pytest.fixture
def hardware_cpu_only() -> HardwareInfo:
    """CPU-only hardware profile (no GPU)."""
    return HardwareInfo(
        platform="linux",
        cpu_brand="Intel Xeon E5-2686 v4",
        cpu_count=8,
        ram_gb=32.0,
        gpu=None,
    )


# ---------------------------------------------------------------------------
# Engine availability fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def has_ollama() -> bool:
    """Check if Ollama is running locally."""
    try:
        import httpx

        resp = httpx.get("http://localhost:11434/api/tags", timeout=2.0)
        return resp.status_code == 200
    except Exception:
        return False


@pytest.fixture
def has_vllm() -> bool:
    """Check if vLLM is running locally."""
    try:
        import httpx

        resp = httpx.get("http://localhost:8000/v1/models", timeout=2.0)
        return resp.status_code == 200
    except Exception:
        return False


@pytest.fixture
def has_llamacpp() -> bool:
    """Check if llama.cpp server is running locally."""
    try:
        import httpx

        resp = httpx.get("http://localhost:8080/v1/models", timeout=2.0)
        return resp.status_code == 200
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Cloud API key fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def has_openai_key() -> bool:
    """Check if OPENAI_API_KEY is set."""
    return bool(os.environ.get("OPENAI_API_KEY"))


@pytest.fixture
def has_anthropic_key() -> bool:
    """Check if ANTHROPIC_API_KEY is set."""
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


@pytest.fixture
def has_gemini_key() -> bool:
    """Check if GEMINI_API_KEY or GOOGLE_API_KEY is set."""
    return bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))


# ---------------------------------------------------------------------------
# Mock engine factory
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_engine():
    """Factory for mock InferenceEngine instances."""

    def _factory(
        engine_id: str = "mock",
        model_response: str = "Hello!",
        tool_calls: list | None = None,
        models: list[str] | None = None,
    ) -> MagicMock:
        engine = MagicMock()
        engine.engine_id = engine_id
        engine.health.return_value = True
        engine.list_models.return_value = models or ["test-model"]

        result = {
            "content": model_response,
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            "model": "test-model",
            "finish_reason": "stop",
        }
        if tool_calls:
            result["tool_calls"] = tool_calls
            result["finish_reason"] = "tool_calls"
        engine.generate.return_value = result
        return engine

    return _factory


@pytest.fixture
def event_bus() -> EventBus:
    """Fresh EventBus with history recording enabled."""
    return EventBus(record_history=True)


# ---------------------------------------------------------------------------
# Mining sidecar fixtures (shared across tests/mining/ and tests/engine/)
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_sidecar_payload() -> dict:
    """A valid vllm-pearl sidecar payload with all expected fields."""
    return {
        "provider": "vllm-pearl",
        "vllm_endpoint": "http://127.0.0.1:8000/v1",
        "model": "pearl-ai/Llama-3.3-70B-Instruct-pearl",
        "gateway_url": "http://127.0.0.1:8337",
        "gateway_metrics_url": "http://127.0.0.1:8339",
        "container_id": "abc123def456",
        "wallet_address": "prl1qexampleaddress",
        "started_at": 1714867200,
    }


@pytest.fixture
def sidecar_path(tmp_path: Path) -> Path:
    """Path to a (not-yet-written) mining sidecar JSON file."""
    return tmp_path / "mining.json"


@pytest.fixture
def written_sidecar(sidecar_path: Path, sample_sidecar_payload: dict) -> Path:
    """A written mining sidecar JSON file; returns the path."""
    sidecar_path.write_text(json.dumps(sample_sidecar_payload))
    return sidecar_path

@pytest.fixture(autouse=True)
def _isoler_le_profil_vocal(monkeypatch, tmp_path):
    """Aucun test ne touche l'empreinte vocale RÉELLE du propriétaire.

    Découvert le 23 août 2026, à la première exécution : les bancs vocaux ont
    enrôlé leur audio synthétique dans ~/.diapason/voice_profile.npz — cinq
    échantillons de bruit, verrou armé. Armé ainsi, l'assistant aurait été
    SOURD à la vraie voix de l'utilisateur. Chaque test reçoit donc un
    vérificateur neutre (jamais armé, enrôlement muet) ; les tests du module
    speaker_id construisent explicitement leur propre instance sur tmp_path.
    """
    from diapason.speech import speaker_id

    class _VerificateurNeutre:
        arme = False
        echantillons = 0

        def enroll(self, *a, **k):
            return False

        def verify(self, *a, **k):
            return 1.0, True

        def reset(self):
            pass

    monkeypatch.setattr(speaker_id, "_partage", None)
    monkeypatch.setattr(speaker_id, "get_verifier", lambda: _VerificateurNeutre())



@pytest.fixture(autouse=True)
def _isoler_le_bureau(monkeypatch):
    """Aucun test ne lit le VRAI bureau (osascript System Events).

    Le rafraîchissement d'état parti en tâche de fond pendant les tests de
    parole remplissait le cache module avec les vraies applications de la
    machine — et ce cliché fuyait dans les tours d'autres tests (constaté
    le 23 août 2026). Un test qui veut un état l'injecte explicitement en
    patchant ``etat_bureau._cache`` ou les fonctions elles-mêmes.
    """
    from diapason.desktop import etat_bureau

    monkeypatch.setattr(etat_bureau, "_cache", None)
    monkeypatch.setattr(etat_bureau, "etat_du_bureau", lambda **_k: None)
    monkeypatch.setattr(etat_bureau, "premier_plan", lambda *_a, **_k: "")
    # onglet_actif est publique et lance osascript : sans ce patch, la suite
    # interrogerait le VRAI navigateur (24 août 2026, même fuite que le cliché).
    monkeypatch.setattr(etat_bureau, "onglet_actif", lambda *_a, **_k: "")

    # Le CONTEXTE D'APPLICATION suit la même règle, et pour la même raison
    # (25 août 2026) : c'est un cliché volatile en variable de module,
    # injecté en fin de contexte de chaque tour vocal. Un test qui le pose
    # — ceux du presse-papiers spatial, par exemple — le laissait visible
    # aux tests de parole, qui comptaient alors un message système de trop.
    # Une variable de module partagée sans garde finit toujours par fuir.
    from diapason.desktop import contexte_app

    monkeypatch.setattr(contexte_app, "_cache", None)

    # Et le presse-papiers spatial, pour la même raison : un objet « tenu »
    # qui survit à son test ferait déposer quelque chose au suivant.
    from diapason.desktop import presse_papiers_spatial

    monkeypatch.setattr(presse_papiers_spatial, "_tenu", None)
    yield
