# Intégration minage vLLM-Pearl — plan de mise en œuvre

> **Pour les agents autonomes :** SOUS-COMPÉTENCE REQUISE : utilise `superpowers:subagent-driven-development` (recommandé) ou `superpowers:executing-plans` pour dérouler ce plan tâche par tâche. Les étapes utilisent la syntaxe à cases à cocher (`- [ ]`) pour le suivi.

**But :** mettre en œuvre la spécification A — la v1 de l'intégration de minage vLLM-Pearl — sous la forme d'un nouveau sous-système `diapason.mining` qui laisse les propriétaires de H100/H200 faisant tourner vLLM miner en solo la chaîne PoUW Pearl avec leur inférence LLM habituelle.

**Architecture :** le nouveau sous-système de premier niveau `mining/` reprend le motif des primitives existantes d'OJ (au même rang que `engine/`, `agents/`). Une ABC `MiningProvider` et un `MinerRegistry` ouvrent la voie aux futurs chemins matériel/moteur (Apple Silicon, AMD, Ollama) sans réécriture. Le fournisseur `vllm-pearl` de la v1 orchestre le conteneur Docker publié par Pearl ; un sidecar d'exécution dans `~/.diapason/runtime/mining.json` découple le cycle de vie du minage de la classe moteur vLLM existante. Trois coutures délibérées (l'union étiquetée `submit_target`, `fee_bps`/`fees_owed` à zéro, `mining/pools/` réservé) laissent la place au support des pools en v2 sans douleur de rattrapage.

**Pile technique :** Python 3.10+, le SDK `docker>=7.0`, la CLI Click, pytest avec `unittest.mock`, ruff, uv. S'appuie sur le dépôt Pearl (`pearl-research-labs/pearl`) à un commit/tag épinglé.

**Spécification de référence :** [`docs/design/2026-05-05-vllm-pearl-mining-integration-design.md`](./2026-05-05-vllm-pearl-mining-integration-design.md). Lis-la avant de commencer. Les numéros de section du plan renvoient à cette spécification.

**Conventions impératives pour tout agent qui reprend ce chantier :**

- Tous les nouveaux modules commencent par `from __future__ import annotations`.
- Toutes les dataclasses utilisent `@dataclass(slots=True)`.
- Imports absolus uniquement (`from diapason.core.registry import ...`).
- Les dépendances optionnelles vivent derrière un `try / except ImportError` dans le `__init__.py` parent.
- Les tests de `tests/conftest.py` vident tous les registres en autouse — le motif `ensure_registered()` (enregistrement idempotent gardé par `XRegistry.contains(...)`) est obligatoire pour les composants qui doivent survivre à ce vidage.
- Nommage des fichiers : `_stubs.py` (ABC et dataclasses), `_discovery.py` (détection automatique), `*_cmd.py` (commandes CLI).

**Position de branche :** ce plan est ajouté à la branche existante `docs/pearl-mining-design-specs` comme commit de suivi sur la même PR (#310). Le travail de mise en œuvre partira de `main` séparément, une fois la spécification et le plan fusionnés.

---

## Structure des fichiers

### Créés

| Chemin | Rôle |
|---|---|
| `src/diapason/mining/__init__.py` | Init du paquet ; importe les fournisseurs en douceur via `try/except ImportError` |
| `src/diapason/mining/_stubs.py` | ABC `MiningProvider`, `MiningCapabilities`, `MiningConfig`, `MiningStats`, union étiquetée `SoloTarget`/`PoolTarget`, dataclass `Sidecar` et ses aides de lecture/écriture |
| `src/diapason/mining/_discovery.py` | `detect_providers()`, contrôles matériel/Docker/disque/pearld, contrôle du format de l'adresse de portefeuille |
| `src/diapason/mining/_constants.py` | `PEARL_REPO`, `PEARL_PINNED_REF`, `PEARL_IMAGE_TAG`, ports par défaut, modèle par défaut, constantes du chemin du sidecar |
| `src/diapason/mining/_docker.py` | `PearlDockerLauncher` — `ensure_image()`, `start()`, `stop()`, `is_running()`, `get_logs()` |
| `src/diapason/mining/_collector.py` | `MiningTelemetryCollector` — implémentation complète, livrée non branchée en v1 ; la v1.x l'allume dans le démon passerelle |
| `src/diapason/mining/vllm_pearl.py` | `VllmPearlProvider` (implémentation de `MiningProvider`) ; `_parse_gateway_metrics()` ; `ensure_registered()` |
| `src/diapason/mining/pools/__init__.py` | Emplacement réservé au travail v2 sur `PoolClient` — vide, sauf une docstring qui le dit |
| `src/diapason/cli/mine_cmd.py` | Groupe Click `diapason mine` : `init`, `start`, `stop`, `status`, `doctor`, `attach`, `logs` |
| `tests/mining/__init__.py` | Init de paquet de tests, vide |
| `tests/mining/conftest.py` | Fixtures propres au minage : `HardwareInfo` synthétique, fabrique de client Docker simulé, sidecar d'exemple dans `tmp_path` |
| `tests/mining/fixtures/gateway_metrics_sample.txt` | Vraie sortie Prometheus capturée sur une passerelle Pearl en marche (un instantané, versionné) |
| `tests/mining/fixtures/config_minimal.toml` | Configuration `[mining]` minimale valide |
| `tests/mining/fixtures/config_pool_v2.toml` | TOML avec `submit_target = "pool:..."` pour tester le `NotImplementedError` de la couture v2 |
| `tests/mining/test_stubs.py` | Tests du contrat de l'ABC, des invariants des dataclasses, des E/S du sidecar |
| `tests/mining/test_discovery.py` | Tests de la matrice de détection des capacités |
| `tests/mining/test_docker.py` | Tests de `PearlDockerLauncher` avec le SDK Docker simulé |
| `tests/mining/test_collector.py` | Tests de `MiningTelemetryCollector` |
| `tests/mining/test_vllm_pearl.py` | Tests de bout en bout de `VllmPearlProvider` (Docker et système de fichiers simulés) |
| `tests/mining/test_cli.py` | Tests de fumée de la CLI via le `CliRunner` de Click |
| `docs/user-guide/mining.md` | Documentation destinée aux utilisateurs |
| `docs/development/mining.md` | Guide du contributeur pour ajouter de nouveaux fournisseurs |

### Modifiés

| Chemin | Changement |
|---|---|
| `src/diapason/core/registry.py` | Ajouter la classe `MinerRegistry` et son entrée dans `__all__` |
| `src/diapason/core/config.py` | Ajouter le champ `MiningConfig` à `DiapasonConfig` ; ajouter le parseur TOML de `[mining]` avec la résolution de l'union étiquetée `submit_target` |
| `src/diapason/engine/_discovery.py` | Ajouter une résolution de moteur consciente du sidecar : quand `~/.diapason/runtime/mining.json` existe, enregistrer un moteur `vllm` dérivé pointant sur `vllm_endpoint` |
| `src/diapason/telemetry/store.py` | Ajouter une colonne `mining_session_id` nullable aux lignes d'inférence ; incrémenter `PRAGMA user_version` ; ajouter l'aide qui étiquette les lignes quand le sidecar est présent |
| `src/diapason/cli/__init__.py` | Enregistrer le groupe Click `mine` |
| `src/diapason/cli/hints.py` | Ajouter l'indice : « minage configuré mais pas en marche — démarre-le avec `diapason mine start` » |
| `tests/conftest.py` | Ajouter `MinerRegistry.clear()` à la fixture autouse `_clean_registries` |
| `pyproject.toml` | Ajouter l'extra `mining-pearl` ; ajouter le marqueur pytest `docker` |
| `CLAUDE.md` | Ajouter un paragraphe sous Architecture qui oriente le futur Claude vers `mining/` comme sous-système frère |
| `REVIEW.md` | Ajouter une puce sous la conformité au registre qui nomme `MinerRegistry` |

---

## Tâche 1 — Ajouter `MinerRegistry`

**Fichiers :**
- Modifier : `src/diapason/core/registry.py`
- Modifier : `tests/conftest.py`
- Test : `tests/core/test_registry.py` (fichier existant — y ajouter un nouveau test)

- [ ] **Étape 1 : écrire le test qui échoue**

À ajouter dans `tests/core/test_registry.py` :

```python
def test_miner_registry_register_and_get():
    from diapason.core.registry import MinerRegistry

    class _Stub:
        provider_id = "stub-pearl"

    MinerRegistry.register_value("stub-pearl", _Stub)
    assert MinerRegistry.contains("stub-pearl") is True
    assert MinerRegistry.get("stub-pearl") is _Stub
```

- [ ] **Étape 2 : lancer le test pour vérifier qu'il échoue**

```bash
uv run pytest tests/core/test_registry.py::test_miner_registry_register_and_get -v
```
Attendu : `ImportError` ou `AttributeError` sur `MinerRegistry`.

- [ ] **Étape 3 : ajouter `MinerRegistry` à `core/registry.py`**

À insérer après `ConnectorRegistry` (vers la ligne 153) :

```python
class MinerRegistry(RegistryBase[Any]):
    """Registre des implémentations de fournisseurs de minage Pearl.

    Chaque fournisseur implémente l'ABC ``MiningProvider`` définie dans
    ``diapason.mining._stubs``. Les clés du registre sont de courtes chaînes
    en minuscules comme ``"vllm-pearl"`` (CUDA + Hopper) et, plus tard,
    ``"mlx-pearl"``, ``"llamacpp-pearl-metal"``, ``"ollama-pearl"``.
    """
```

Ajoute `"MinerRegistry"` à `__all__` (position alphabétique, entre `MemoryRegistry` et `ModelRegistry`).

- [ ] **Étape 4 : lancer le test pour vérifier qu'il passe**

```bash
uv run pytest tests/core/test_registry.py::test_miner_registry_register_and_get -v
```
Attendu : PASS.

- [ ] **Étape 5 : mettre à jour la fixture autouse de `tests/conftest.py`**

Dans `tests/conftest.py`, ajoute `MinerRegistry` aux imports et à la liste des vidages. La fixture `_clean_registries` existante liste chaque registre sur sa propre ligne — insère `MinerRegistry.clear()` par ordre alphabétique, entre `MemoryRegistry.clear()` et `ModelRegistry.clear()`. Ajoute de même `MinerRegistry,` au bloc d'imports.

- [ ] **Étape 6 : vérifier que le vidage autouse fonctionne**

Ajoute un second test sous le test d'enregistrement :

```python
def test_miner_registry_cleared_between_tests():
    from diapason.core.registry import MinerRegistry
    # Si le vidage autouse fonctionne, aucune entrée des tests précédents ne reste
    assert MinerRegistry.contains("stub-pearl") is False
```

```bash
uv run pytest tests/core/test_registry.py::test_miner_registry_register_and_get tests/core/test_registry.py::test_miner_registry_cleared_between_tests -v
```
Attendu : les deux passent.

- [ ] **Étape 7 : committer**

```bash
git add src/diapason/core/registry.py tests/conftest.py tests/core/test_registry.py
git commit -m "feat(mining): ajoute MinerRegistry pour les fournisseurs de minage"
```

---

## Tâche 2 — Squelette du paquet mining : constantes, ABC, dataclasses, E/S du sidecar

**Fichiers :**
- Créer : `src/diapason/mining/__init__.py`
- Créer : `src/diapason/mining/_constants.py`
- Créer : `src/diapason/mining/_stubs.py`
- Créer : `src/diapason/mining/pools/__init__.py`
- Créer : `tests/mining/__init__.py`
- Créer : `tests/mining/conftest.py`
- Créer : `tests/mining/test_stubs.py`

- [ ] **Étape 1 : créer `tests/mining/__init__.py`**

Fichier vide.

- [ ] **Étape 2 : créer `tests/mining/conftest.py` avec les fixtures partagées**

```python
"""Fixtures de test propres au minage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from diapason.core.config import GpuInfo, HardwareInfo


@pytest.fixture
def hopper_hw() -> HardwareInfo:
    """Fixture matérielle : une machine H100 typique."""
    return HardwareInfo(
        platform="linux",
        cpu_brand="AMD EPYC 7763",
        cpu_count=64,
        ram_gb=512.0,
        gpu=GpuInfo(
            vendor="nvidia",
            name="NVIDIA H100-SXM5-80GB",
            vram_gb=80.0,
            compute_capability="9.0",
            count=1,
        ),
    )


@pytest.fixture
def ada_hw() -> HardwareInfo:
    """Fixture matérielle : RTX 4090 (sm_89, NON supportée par Pearl)."""
    return HardwareInfo(
        platform="linux",
        cpu_brand="Intel Core i9-14900K",
        cpu_count=24,
        ram_gb=64.0,
        gpu=GpuInfo(
            vendor="nvidia",
            name="NVIDIA GeForce RTX 4090",
            vram_gb=24.0,
            compute_capability="8.9",
            count=1,
        ),
    )


@pytest.fixture
def apple_hw() -> HardwareInfo:
    """Fixture matérielle : Apple Silicon (NON supportée en v1)."""
    return HardwareInfo(
        platform="darwin",
        cpu_brand="Apple M4 Max",
        cpu_count=16,
        ram_gb=128.0,
        gpu=GpuInfo(vendor="apple", name="Apple M4 Max", vram_gb=128.0, count=1),
    )


@pytest.fixture
def mock_docker_client() -> Any:
    """Fabrique un docker.DockerClient simulé.

    Rend un MagicMock configuré avec les chemins d'attributs les plus courants,
    pour que chaque test n'ait plus qu'à redéfinir ce qui le concerne.
    """
    client = MagicMock()
    client.ping.return_value = True
    client.version.return_value = {"Version": "24.0.7"}
    client.images.list.return_value = []
    client.images.get.side_effect = Exception("not found")
    return client


@pytest.fixture
def sample_sidecar_payload() -> dict:
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
    return tmp_path / "mining.json"


@pytest.fixture
def written_sidecar(sidecar_path: Path, sample_sidecar_payload: dict) -> Path:
    sidecar_path.write_text(json.dumps(sample_sidecar_payload))
    return sidecar_path
```

- [ ] **Étape 3 : écrire le test qui échoue pour `_stubs.py`**

Crée `tests/mining/test_stubs.py` :

```python
"""Tests de mining/_stubs.py — contrat de l'ABC, invariants des dataclasses, E/S du sidecar."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_mining_capabilities_default_unsupported():
    from diapason.mining._stubs import MiningCapabilities
    cap = MiningCapabilities(supported=False, reason="needs sm90")
    assert cap.supported is False
    assert cap.reason == "needs sm90"
    assert cap.estimated_hashrate is None


def test_solo_target_dataclass():
    from diapason.mining._stubs import SoloTarget
    t = SoloTarget(pearld_rpc_url="http://localhost:44107")
    assert t.pearld_rpc_url == "http://localhost:44107"


def test_pool_target_dataclass():
    from diapason.mining._stubs import PoolTarget
    t = PoolTarget(url="https://pool.example/submit", worker_id="rig01")
    assert t.url == "https://pool.example/submit"
    assert t.worker_id == "rig01"


def test_mining_config_v1_defaults():
    from diapason.mining._stubs import MiningConfig, SoloTarget
    cfg = MiningConfig(
        provider="vllm-pearl",
        wallet_address="prl1qexample",
        submit_target=SoloTarget(pearld_rpc_url="http://localhost:44107"),
    )
    assert cfg.fee_bps == 0
    assert cfg.fee_payout_address is None
    assert cfg.extra == {}


def test_mining_stats_v1_defaults():
    from diapason.mining._stubs import MiningStats
    s = MiningStats(provider_id="vllm-pearl")
    assert s.shares_submitted == 0
    assert s.shares_accepted == 0
    assert s.fees_owed == 0
    assert s.payout_target == "solo"


def test_mining_provider_is_abstract():
    from diapason.mining._stubs import MiningProvider
    with pytest.raises(TypeError):
        MiningProvider()  # une ABC ne s'instancie pas


def test_sidecar_write_then_read_roundtrip(sidecar_path: Path, sample_sidecar_payload: dict):
    from diapason.mining._stubs import Sidecar
    Sidecar.write(sidecar_path, sample_sidecar_payload)
    payload = Sidecar.read(sidecar_path)
    assert payload == sample_sidecar_payload


def test_sidecar_read_missing_returns_none(sidecar_path: Path):
    from diapason.mining._stubs import Sidecar
    assert Sidecar.read(sidecar_path) is None


def test_sidecar_remove_is_idempotent(sidecar_path: Path):
    from diapason.mining._stubs import Sidecar
    Sidecar.remove(sidecar_path)  # fichier absent — ne doit rien lever
    sidecar_path.write_text(json.dumps({"x": 1}))
    Sidecar.remove(sidecar_path)
    assert not sidecar_path.exists()
```

- [ ] **Étape 4 : lancer les tests pour vérifier qu'ils échouent**

```bash
uv run pytest tests/mining/test_stubs.py -v
```
Attendu : TOUS échouent avec un `ImportError` sur `diapason.mining._stubs`.

- [ ] **Étape 5 : créer `_constants.py`**

```python
# src/diapason/mining/_constants.py
"""Constantes du sous-système de minage Pearl.

Référence Pearl épinglée, celle contre laquelle OJ a testé. On l'incrémente à
chaque version d'OJ, après avoir retesté l'intégration de bout en bout sur une
vraie machine H100/H200. Voir la section 7.3 de la spécification
``docs/design/2026-05-05-vllm-pearl-mining-integration-design.md`` pour la
procédure de montée de référence.
"""

from __future__ import annotations

from pathlib import Path

PEARL_REPO = "https://github.com/pearl-research-labs/pearl.git"
# TODO au moment de la mise en œuvre : remplacer par le commit/tag précis vérifié
# contre une H100. Documenter la référence retenue dans les notes de version d'OJ.
PEARL_PINNED_REF = "main"
PEARL_IMAGE_TAG = f"diapason/pearl-miner:{PEARL_PINNED_REF}"

# Modèle béni par Pearl, par défaut. Redéfinissable via [mining.extra].model.
DEFAULT_PEARL_MODEL = "pearl-ai/Llama-3.3-70B-Instruct-pearl"

# Ports par défaut, tels que le conteneur de Pearl les expose (network_mode="host").
DEFAULT_VLLM_PORT = 8000
DEFAULT_GATEWAY_RPC_PORT = 8337
DEFAULT_GATEWAY_METRICS_PORT = 8339

# Point d'accès RPC pearld par défaut (mainnet).
DEFAULT_PEARLD_RPC_URL = "http://localhost:44107"

# Espace disque libre exigé au pré-vol pour le modèle 70B, marge comprise.
MIN_FREE_DISK_GB = 200

# Emplacement du sidecar d'exécution (une seule session supposée — voir §8.8 de la spéc).
RUNTIME_DIR = Path.home() / ".diapason" / "runtime"
SIDECAR_PATH = RUNTIME_DIR / "mining.json"
SIDECAR_LOCK_PATH = RUNTIME_DIR / "mining.lock"

# Cache des sources Pearl pour le chemin « construire depuis la référence épinglée » (voir §7.2 de la spéc).
PEARL_CACHE_DIR = Path.home() / ".diapason" / "cache" / "pearl"
```

- [ ] **Étape 6 : créer `_stubs.py`**

```python
# src/diapason/mining/_stubs.py
"""ABC et dataclasses du sous-système de minage.

Voir la section 4.4 de la spécification
``docs/design/2026-05-05-vllm-pearl-mining-integration-design.md`` pour la
justification de conception.
"""

from __future__ import annotations

import json
import os
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union

from diapason.core.config import HardwareInfo


# ---------------------------------------------------------------------------
# Descripteur de capacité
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class MiningCapabilities:
    """Résultat de l'appel ``detect()`` d'un fournisseur.

    ``reason`` est lisible par un humain et repris tel quel par
    ``diapason mine doctor`` quand ``supported=False``.
    """

    supported: bool
    reason: Optional[str] = None
    estimated_hashrate: Optional[float] = None  # parts/s, au mieux


# ---------------------------------------------------------------------------
# Union étiquetée de la cible de soumission (couture v2 — voir §8.5 de la spéc)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class SoloTarget:
    """Miner directement vers un nœud pearld. Défaut de la v1."""

    pearld_rpc_url: str


@dataclass(slots=True)
class PoolTarget:
    """Miner via un pool opéré par OJ. v2 — lève NotImplementedError en v1."""

    url: str
    worker_id: Optional[str] = None


SubmitTarget = Union[SoloTarget, PoolTarget]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class MiningConfig:
    """Configuration de minage fournie par l'utilisateur.

    Chargée depuis la section TOML ``[mining]`` par ``core/config.py``.
    """

    provider: str
    wallet_address: str
    submit_target: SubmitTarget
    fee_bps: int = 0  # v1 : 0 ; v2 : 2000 (= 20 %)
    fee_payout_address: Optional[str] = None  # v1 : ignoré ; v2 : l'adresse d'OJ
    extra: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Statistiques en direct (rendues par ``MiningProvider.stats()``)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class MiningStats:
    provider_id: str
    shares_submitted: int = 0
    shares_accepted: int = 0
    blocks_found: int = 0
    hashrate: float = 0.0
    uptime_seconds: float = 0.0
    last_share_at: Optional[float] = None
    last_error: Optional[str] = None
    payout_target: str = "solo"  # v1 : toujours "solo" ; v2 : "pool:<url>"
    fees_owed: int = 0  # crochet comptable v2 ; 0 en v1


# ---------------------------------------------------------------------------
# L'ABC
# ---------------------------------------------------------------------------


class MiningProvider(ABC):
    """Un fournisseur de minage — orchestre une session Pearl pour un trio (matériel, moteur, modèle).

    Tous les futurs chemins matériel/moteur (Apple Silicon, AMD, Ollama)
    implémentent exactement ce contrat. Voir §4.4 de la spécification.
    """

    provider_id: str  # défini par la sous-classe

    @classmethod
    @abstractmethod
    def detect(cls, hw: HardwareInfo, engine_id: str, model: str) -> MiningCapabilities:
        """Dit si ce fournisseur peut tourner sur le trio donné.

        Doit être une pure inspection — pas de sous-processus, pas de réseau,
        pas de Docker. Utilisée par ``diapason mine doctor`` et
        ``diapason mine init`` pour rendre la capacité sans attendre.
        """

    @abstractmethod
    async def start(self, config: MiningConfig) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    def is_running(self) -> bool: ...

    @abstractmethod
    def stats(self) -> MiningStats: ...


# ---------------------------------------------------------------------------
# E/S du sidecar (voir §5.3 de la spéc)
# ---------------------------------------------------------------------------


class Sidecar:
    """Aides de lecture/écriture pour ``~/.diapason/runtime/mining.json``."""

    @staticmethod
    def write(path: Path, payload: dict[str, Any]) -> None:
        """Écrit atomiquement le JSON du sidecar dans ``path``."""
        path.parent.mkdir(parents=True, exist_ok=True)
        # Écriture atomique : fichier temporaire puis renommage
        fd, tmp = tempfile.mkstemp(prefix=".mining-", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w") as fh:
                json.dump(payload, fh, indent=2, sort_keys=True)
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    @staticmethod
    def read(path: Path) -> Optional[dict[str, Any]]:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    @staticmethod
    def remove(path: Path) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
```

- [ ] **Étape 7 : créer `mining/__init__.py`**

```python
# src/diapason/mining/__init__.py
"""Sous-système de minage Pearl.

Voir la spécification
``docs/design/2026-05-05-vllm-pearl-mining-integration-design.md``.

Les modules de fournisseurs sont importés en douceur ci-dessous — chacun
échoue proprement si l'extra ``mining-pearl`` (ou les futurs
``mining-pearl-mlx``, etc.) n'est pas installé.
"""

from __future__ import annotations

# Ré-export des ABC et dataclasses publiques, pour des imports confortables.
from diapason.mining._stubs import (
    MiningCapabilities,
    MiningConfig,
    MiningProvider,
    MiningStats,
    PoolTarget,
    Sidecar,
    SoloTarget,
    SubmitTarget,
)

# Import en douceur des implémentations de fournisseurs, pour déclencher leur
# enregistrement. Chaque fournisseur définit un ``ensure_registered()``
# idempotent, pour survivre au vidage autouse des registres dans
# ``tests/conftest.py``.
try:
    from diapason.mining import vllm_pearl  # noqa: F401

    vllm_pearl.ensure_registered()
except ImportError:
    pass

__all__ = [
    "MiningCapabilities",
    "MiningConfig",
    "MiningProvider",
    "MiningStats",
    "PoolTarget",
    "Sidecar",
    "SoloTarget",
    "SubmitTarget",
]
```

- [ ] **Étape 8 : créer `mining/pools/__init__.py`** (réservé à la v2)

```python
# src/diapason/mining/pools/__init__.py
"""RÉSERVÉ au support des pools en v2.

Ne rien ajouter ici en v1. La spécification v2 définira une ABC ``PoolClient``
et un ``PoolClientRegistry`` frère de ``MinerRegistry``. Squatter ce chemin dès
maintenant créerait une dette de migration et préjugerait de l'API v2.
Voir §8.5 de la spécification.
"""

from __future__ import annotations
```

- [ ] **Étape 9 : lancer les tests pour vérifier qu'ils passent**

```bash
uv run pytest tests/mining/test_stubs.py -v
```
Attendu : 9 PASS.

- [ ] **Étape 10 : committer**

```bash
git add src/diapason/mining/ tests/mining/__init__.py tests/mining/conftest.py tests/mining/test_stubs.py
git commit -m "feat(mining): ajoute l'ABC, les dataclasses, les constantes et les E/S du sidecar"
```

---

## Tâche 3 — Intégrer `MiningConfig` dans `DiapasonConfig` et parser le TOML

**Fichiers :**
- Modifier : `src/diapason/core/config.py`
- Test : `tests/core/test_config.py` (existant — y ajouter de nouveaux tests)
- Test : `tests/mining/fixtures/config_minimal.toml`
- Test : `tests/mining/fixtures/config_pool_v2.toml`

- [ ] **Étape 1 : créer les fichiers TOML de fixture**

`tests/mining/fixtures/config_minimal.toml` :

```toml
[mining]
provider           = "vllm-pearl"
wallet_address     = "prl1qexampleaddress"
submit_target      = "solo"
fee_bps            = 0
fee_payout_address = ""

[mining.extra]
model                   = "pearl-ai/Llama-3.3-70B-Instruct-pearl"
pearld_rpc_url          = "http://localhost:44107"
pearld_rpc_user         = "rpcuser"
pearld_rpc_password_env = "PEARLD_RPC_PASSWORD"
```

`tests/mining/fixtures/config_pool_v2.toml` :

```toml
[mining]
provider       = "vllm-pearl"
wallet_address = "prl1qexampleaddress"
submit_target  = "pool:https://pool.diapason.ai/submit"

[mining.extra]
model                   = "pearl-ai/Llama-3.3-70B-Instruct-pearl"
pearld_rpc_url          = "http://localhost:44107"
pearld_rpc_user         = "rpcuser"
pearld_rpc_password_env = "PEARLD_RPC_PASSWORD"
```

- [ ] **Étape 2 : écrire les tests qui échouent**

À ajouter dans `tests/core/test_config.py` :

```python
def test_mining_config_absent_means_none(tmp_path):
    from diapason.core.config import load_config
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text("")  # configuration vide
    cfg = load_config(cfg_path)
    assert cfg.mining is None


def test_mining_config_solo_parsed(tmp_path):
    from pathlib import Path
    from diapason.core.config import load_config
    from diapason.mining._stubs import SoloTarget
    src = Path(__file__).parent.parent / "mining" / "fixtures" / "config_minimal.toml"
    target = tmp_path / "config.toml"
    target.write_text(src.read_text())
    cfg = load_config(target)
    assert cfg.mining is not None
    assert cfg.mining.provider == "vllm-pearl"
    assert cfg.mining.wallet_address == "prl1qexampleaddress"
    assert isinstance(cfg.mining.submit_target, SoloTarget)
    assert cfg.mining.submit_target.pearld_rpc_url == "http://localhost:44107"
    assert cfg.mining.fee_bps == 0
    assert cfg.mining.extra["model"] == "pearl-ai/Llama-3.3-70B-Instruct-pearl"


def test_mining_config_pool_parsed_as_pool_target(tmp_path):
    from pathlib import Path
    from diapason.core.config import load_config
    from diapason.mining._stubs import PoolTarget
    src = Path(__file__).parent.parent / "mining" / "fixtures" / "config_pool_v2.toml"
    target = tmp_path / "config.toml"
    target.write_text(src.read_text())
    cfg = load_config(target)
    assert isinstance(cfg.mining.submit_target, PoolTarget)
    assert cfg.mining.submit_target.url == "https://pool.diapason.ai/submit"
```

- [ ] **Étape 3 : lancer les tests pour vérifier qu'ils échouent**

```bash
uv run pytest tests/core/test_config.py -k mining -v
```
Attendu : 3 FAIL, sur l'attribut `cfg.mining` manquant.

- [ ] **Étape 4 : ajouter le champ `mining` à `DiapasonConfig`**

Dans `src/diapason/core/config.py`, ajoute un import près du début :

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from diapason.mining._stubs import MiningConfig
```

Ajoute le champ à `DiapasonConfig` (par ordre alphabétique — après `memory_files`, avant `operators`) :

```python
    mining: Optional["MiningConfig"] = None
```

- [ ] **Étape 5 : écrire le parsing TOML de la section `[mining]`**

Dans `src/diapason/core/config.py`, repère la fonction `load_config()` existante (vers la ligne 1541). Trouve l'endroit où les données TOML chargées sont versées dans le `DiapasonConfig` (cherche l'itération sur le dictionnaire `data` et les affectations aux champs de la dataclass). Ajoute un traitement dédié à `mining` : le parsing de l'union étiquetée ne peut pas passer par le parcours générique.

Ajoute cette aide près des autres `_parse_*` de `core/config.py` :

```python
def _parse_mining_section(data: dict) -> Optional["MiningConfig"]:
    """Transforme la section TOML ``[mining]`` en ``MiningConfig``.

    Rend None si la section est absente. Résout la chaîne ``submit_target``
    en union étiquetée ``SoloTarget`` ou ``PoolTarget``.
    """
    if "mining" not in data:
        return None

    # Import paresseux pour éviter le cycle : mining/__init__.py importe
    # core/config de façon transitive via _stubs, mais seulement à l'exécution.
    from diapason.mining._stubs import MiningConfig, PoolTarget, SoloTarget

    section = data["mining"]
    extra = section.get("extra", {}) or {}

    target_str = section.get("submit_target", "solo")
    submit_target: Any
    if target_str == "solo":
        submit_target = SoloTarget(
            pearld_rpc_url=extra.get("pearld_rpc_url", "http://localhost:44107")
        )
    elif isinstance(target_str, str) and target_str.startswith("pool:"):
        submit_target = PoolTarget(url=target_str[len("pool:") :])
    else:
        raise ValueError(
            f"[mining].submit_target doit valoir 'solo' ou 'pool:<url>', reçu {target_str!r}"
        )

    return MiningConfig(
        provider=section["provider"],
        wallet_address=section["wallet_address"],
        submit_target=submit_target,
        fee_bps=int(section.get("fee_bps", 0)),
        fee_payout_address=section.get("fee_payout_address") or None,
        extra={k: v for k, v in extra.items()},
    )
```

Dans `load_config()`, après le traitement des autres sections et avant de rendre `cfg` :

```python
    cfg.mining = _parse_mining_section(data)
```

- [ ] **Étape 6 : lancer les tests pour vérifier qu'ils passent**

```bash
uv run pytest tests/core/test_config.py -k mining -v
```
Attendu : 3 PASS.

- [ ] **Étape 7 : committer**

```bash
git add src/diapason/core/config.py tests/core/test_config.py tests/mining/fixtures/
git commit -m "feat(mining): intègre MiningConfig dans DiapasonConfig avec le parsing TOML"
```

---

## Tâche 4 — Découverte des capacités (`mining/_discovery.py`)

**Fichiers :**
- Créer : `src/diapason/mining/_discovery.py`
- Test : `tests/mining/test_discovery.py`

- [ ] **Étape 1 : écrire les tests qui échouent**

Crée `tests/mining/test_discovery.py` :

```python
"""Tests de mining/_discovery.py — la matrice de détection des capacités."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_detect_supported_on_h100(hopper_hw):
    from diapason.mining._discovery import detect_for_engine_model
    cap = detect_for_engine_model(
        hw=hopper_hw,
        engine_id="vllm",
        model="pearl-ai/Llama-3.3-70B-Instruct-pearl",
        provider_id="vllm-pearl",
    )
    assert cap.supported is True
    assert cap.reason is None


def test_detect_unsupported_on_ada_4090(ada_hw):
    from diapason.mining._discovery import detect_for_engine_model
    cap = detect_for_engine_model(
        hw=ada_hw,
        engine_id="vllm",
        model="pearl-ai/Llama-3.3-70B-Instruct-pearl",
        provider_id="vllm-pearl",
    )
    assert cap.supported is False
    assert "sm90" in cap.reason.lower() or "compute_capability" in cap.reason.lower()


def test_detect_unsupported_on_apple(apple_hw):
    from diapason.mining._discovery import detect_for_engine_model
    cap = detect_for_engine_model(
        hw=apple_hw,
        engine_id="mlx",
        model="pearl-ai/Llama-3.3-70B-Instruct-pearl",
        provider_id="vllm-pearl",
    )
    assert cap.supported is False
    assert cap.reason is not None  # raison précise — la voie Apple Silicon, c'est la spécification B


def test_detect_unsupported_for_non_vllm_engine(hopper_hw):
    from diapason.mining._discovery import detect_for_engine_model
    cap = detect_for_engine_model(
        hw=hopper_hw,
        engine_id="ollama",
        model="qwen3:8b",
        provider_id="vllm-pearl",
    )
    assert cap.supported is False
    assert "vllm" in cap.reason.lower() or "engine" in cap.reason.lower()


def test_detect_unsupported_for_non_pearl_model(hopper_hw):
    from diapason.mining._discovery import detect_for_engine_model
    cap = detect_for_engine_model(
        hw=hopper_hw,
        engine_id="vllm",
        model="meta-llama/Llama-3.3-70B-Instruct",  # PAS la variante -pearl
        provider_id="vllm-pearl",
    )
    assert cap.supported is False
    assert "pearl" in cap.reason.lower()


def test_detect_unsupported_for_low_vram():
    from diapason.mining._discovery import detect_for_engine_model
    from diapason.core.config import GpuInfo, HardwareInfo
    hw = HardwareInfo(
        platform="linux",
        gpu=GpuInfo(
            vendor="nvidia",
            name="NVIDIA H100 PCIe-40GB",
            vram_gb=40.0,  # sous le seuil des 70 Go
            compute_capability="9.0",
            count=1,
        ),
    )
    cap = detect_for_engine_model(
        hw=hw, engine_id="vllm", model="pearl-ai/Llama-3.3-70B-Instruct-pearl",
        provider_id="vllm-pearl",
    )
    assert cap.supported is False
    assert "vram" in cap.reason.lower() or "memory" in cap.reason.lower()


def test_check_docker_available_true():
    from diapason.mining._discovery import check_docker_available
    with patch("diapason.mining._discovery._docker_client") as fake:
        fake.return_value.ping.return_value = True
        fake.return_value.version.return_value = {"Version": "24.0.7"}
        ok, info = check_docker_available()
        assert ok is True
        assert "24.0.7" in info


def test_check_docker_available_false_when_daemon_down():
    from diapason.mining._discovery import check_docker_available
    with patch("diapason.mining._discovery._docker_client") as fake:
        fake.side_effect = Exception("Cannot connect to the Docker daemon")
        ok, info = check_docker_available()
        assert ok is False
        assert "daemon" in info.lower() or "connect" in info.lower()


def test_check_disk_free_passes(tmp_path):
    from diapason.mining._discovery import check_disk_free
    with patch("diapason.mining._discovery.shutil.disk_usage") as du:
        # 500 Go libres
        du.return_value = MagicMock(total=1_000_000_000_000, used=500_000_000_000, free=500_000_000_000)
        ok, info = check_disk_free(tmp_path)
        assert ok is True


def test_check_disk_free_fails_below_threshold(tmp_path):
    from diapason.mining._discovery import check_disk_free
    with patch("diapason.mining._discovery.shutil.disk_usage") as du:
        du.return_value = MagicMock(total=1_000_000_000_000, used=950_000_000_000, free=50_000_000_000)
        ok, info = check_disk_free(tmp_path)
        assert ok is False


def test_check_pearld_reachable_true():
    from diapason.mining._discovery import check_pearld_reachable
    with patch("diapason.mining._discovery.httpx.post") as post:
        post.return_value.status_code = 200
        post.return_value.json.return_value = {"result": {"blocks": 442107, "headers": 442107}}
        ok, info = check_pearld_reachable("http://localhost:44107", "user", "pass")
        assert ok is True
        assert "442107" in info


def test_check_pearld_reachable_false_on_connection_error():
    from diapason.mining._discovery import check_pearld_reachable
    import httpx
    with patch("diapason.mining._discovery.httpx.post") as post:
        post.side_effect = httpx.ConnectError("connection refused")
        ok, info = check_pearld_reachable("http://localhost:44107", "user", "pass")
        assert ok is False


def test_check_wallet_address_format_valid():
    from diapason.mining._discovery import check_wallet_address_format
    ok, info = check_wallet_address_format("prl1qexampleaddress0123456789")
    assert ok is True


def test_check_wallet_address_format_invalid():
    from diapason.mining._discovery import check_wallet_address_format
    ok, info = check_wallet_address_format("not-a-pearl-address")
    assert ok is False
```

- [ ] **Étape 2 : lancer les tests pour vérifier qu'ils échouent**

```bash
uv run pytest tests/mining/test_discovery.py -v
```
Attendu : TOUS échouent avec un `ImportError`.

- [ ] **Étape 3 : créer `_discovery.py`**

```python
# src/diapason/mining/_discovery.py
"""Détection des capacités pour les fournisseurs de minage.

Chaque fonction répond à une seule question par oui ou par non et rend
``(ok: bool, info: str)``, où ``info`` est une explication courte et lisible,
reprise telle quelle par ``diapason mine doctor``.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional, Tuple

import httpx

from diapason.core.config import HardwareInfo
from diapason.mining._stubs import MiningCapabilities

# ---------------------------------------------------------------------------
# Constantes du fournisseur vllm-pearl de la v1
# ---------------------------------------------------------------------------

REQUIRED_COMPUTE_CAPABILITY = "9.0"  # sm_90a — Hopper
REQUIRED_VRAM_GB = 70.0
SUPPORTED_VLLM_ENGINE_IDS = frozenset({"vllm"})


def detect_for_engine_model(
    *,
    hw: HardwareInfo,
    engine_id: str,
    model: str,
    provider_id: str,
) -> MiningCapabilities:
    """Matrice de capacités du fournisseur ``vllm-pearl``.

    Pure inspection. Pas de sous-processus, pas de Docker, pas de réseau.
    Utilisée par ``diapason mine doctor`` et ``diapason mine init``.
    """
    if provider_id != "vllm-pearl":
        return MiningCapabilities(
            False, reason=f"fournisseur inconnu {provider_id!r}"
        )

    # Moteur
    if engine_id not in SUPPORTED_VLLM_ENGINE_IDS:
        return MiningCapabilities(
            False,
            reason=f"le moteur '{engine_id}' n'a pas de greffon Pearl en v1 ; utilise vllm",
        )

    # Matériel
    if hw.gpu is None:
        return MiningCapabilities(False, reason="aucun GPU détecté")
    if hw.gpu.vendor != "nvidia":
        return MiningCapabilities(
            False,
            reason=f"vllm-pearl exige une NVIDIA Hopper ; détecté {hw.gpu.vendor!r}. "
            f"Le support Apple Silicon est suivi dans la spécification B.",
        )
    if not hw.gpu.compute_capability.startswith("9.0"):
        return MiningCapabilities(
            False,
            reason=f"exige compute_capability 9.0 (sm_90a / H100/H200) ; détecté "
            f"{hw.gpu.compute_capability!r} ({hw.gpu.name})",
        )
    if hw.gpu.vram_gb < REQUIRED_VRAM_GB:
        return MiningCapabilities(
            False,
            reason=f"exige ≥{REQUIRED_VRAM_GB:.0f} Go de VRAM pour le modèle Pearl 70B ; "
            f"détecté {hw.gpu.vram_gb:.0f} Go",
        )

    # Modèle
    if "-pearl" not in model.lower():
        return MiningCapabilities(
            False,
            reason=f"le modèle {model!r} n'a pas de variante bénie par Pearl — prends un "
            f"modèle 'pearl-ai/*-pearl'",
        )

    return MiningCapabilities(supported=True)


# ---------------------------------------------------------------------------
# Contrôles du doctor (un par ligne de la sortie de `diapason mine doctor`)
# ---------------------------------------------------------------------------


def _docker_client():  # pragma: no cover - simple enveloppe, simulée dans les tests
    import docker

    return docker.from_env()


def check_docker_available() -> Tuple[bool, str]:
    try:
        c = _docker_client()
        c.ping()
        ver = c.version().get("Version", "inconnue")
        return True, f"en marche {ver}"
    except Exception as e:  # noqa: BLE001 - volontairement large
        return False, str(e).splitlines()[0]


def check_disk_free(path: Path) -> Tuple[bool, str]:
    from diapason.mining._constants import MIN_FREE_DISK_GB

    usage = shutil.disk_usage(path)
    free_gb = usage.free / (1024**3)
    if free_gb < MIN_FREE_DISK_GB:
        return False, f"seulement {free_gb:.0f} Go libres (il en faut ≥{MIN_FREE_DISK_GB} Go)"
    return True, f"{free_gb:.0f} Go libres"


def check_pearld_reachable(
    url: str, user: str, password: str
) -> Tuple[bool, str]:
    """Sonde pearld par le JSON-RPC ``getblockchaininfo``."""
    try:
        resp = httpx.post(
            url,
            json={"jsonrpc": "1.0", "id": "ojprobe", "method": "getblockchaininfo", "params": []},
            auth=(user, password),
            timeout=5.0,
        )
        if resp.status_code != 200:
            return False, f"HTTP {resp.status_code}"
        data = resp.json()
        result = data.get("result") or {}
        blocks = result.get("blocks", "?")
        headers = result.get("headers", "?")
        synced = blocks == headers
        marker = "synchronisé" if synced else f"synchronisation ({blocks}/{headers})"
        return True, f"hauteur de bloc {blocks} ({marker})"
    except httpx.ConnectError as e:
        return False, f"connexion refusée : {e}"
    except Exception as e:  # noqa: BLE001
        return False, str(e).splitlines()[0]


def check_wallet_address_format(address: str) -> Tuple[bool, str]:
    """Les adresses Taproot de Pearl commencent par ``prl1q...``.

    On ne tente *pas* de valider la somme de contrôle bech32 — c'est un contrat
    plus fort, qui peut bouger d'une révision de Pearl à l'autre. Contrôle de
    format seulement.
    """
    if not address:
        return False, "vide"
    if not address.startswith("prl1q"):
        return False, f"préfixe 'prl1q...' attendu ; reçu {address[:6]!r}"
    if len(address) < 14:
        return False, f"trop courte ({len(address)} caractères)"
    return True, "format correct"
```

- [ ] **Étape 4 : lancer les tests pour vérifier qu'ils passent**

```bash
uv run pytest tests/mining/test_discovery.py -v
```
Attendu : 13 PASS.

- [ ] **Étape 5 : committer**

```bash
git add src/diapason/mining/_discovery.py tests/mining/test_discovery.py
git commit -m "feat(mining): détection des capacités et contrôles du doctor"
```

---

## Tâche 5 — Acquisition de l'image par `PearlDockerLauncher`

**Fichiers :**
- Créer : `src/diapason/mining/_docker.py`
- Test : `tests/mining/test_docker.py`

- [ ] **Étape 1 : écrire les tests qui échouent pour `ensure_image()`**

Crée `tests/mining/test_docker.py` :

```python
"""Tests de mining/_docker.py — orchestration du SDK Docker, via des simulacres."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_ensure_image_already_local():
    from diapason.mining._docker import PearlDockerLauncher
    fake = MagicMock()
    fake.images.get.return_value = MagicMock(id="sha256:abc", tags=["diapason/pearl-miner:main"])
    launcher = PearlDockerLauncher(client=fake)
    out = launcher.ensure_image("diapason/pearl-miner:main")
    assert out == "diapason/pearl-miner:main"
    fake.images.get.assert_called_once_with("diapason/pearl-miner:main")
    fake.images.pull.assert_not_called()


def test_ensure_image_pulls_if_published():
    from diapason.mining._docker import PearlDockerLauncher
    import docker.errors as derr
    fake = MagicMock()
    fake.images.get.side_effect = derr.ImageNotFound("nope")
    fake.images.pull.return_value = MagicMock(id="sha256:def")
    launcher = PearlDockerLauncher(client=fake)
    out = launcher.ensure_image("registry.example/pearl-miner:1.0")
    assert out == "registry.example/pearl-miner:1.0"
    fake.images.pull.assert_called_once_with("registry.example/pearl-miner:1.0")


def test_ensure_image_falls_back_to_build_for_default_tag():
    from diapason.mining._docker import PearlDockerLauncher
    from diapason.mining._constants import PEARL_IMAGE_TAG
    import docker.errors as derr
    fake = MagicMock()
    fake.images.get.side_effect = derr.ImageNotFound("nope")
    fake.images.pull.side_effect = derr.NotFound("registry refused")
    launcher = PearlDockerLauncher(client=fake)
    with patch.object(launcher, "_clone_pearl_repo") as clone, patch.object(
        launcher, "_docker_build"
    ) as build:
        clone.return_value = "/tmp/pearl-cache"
        build.return_value = PEARL_IMAGE_TAG
        out = launcher.ensure_image(PEARL_IMAGE_TAG)
        assert out == PEARL_IMAGE_TAG
        clone.assert_called_once()
        build.assert_called_once()


def test_ensure_image_errors_when_non_default_tag_missing():
    from diapason.mining._docker import PearlDockerLauncher, ImageAcquisitionError
    import docker.errors as derr
    import pytest
    fake = MagicMock()
    fake.images.get.side_effect = derr.ImageNotFound("nope")
    fake.images.pull.side_effect = derr.NotFound("registry refused")
    launcher = PearlDockerLauncher(client=fake)
    with pytest.raises(ImageAcquisitionError) as ei:
        launcher.ensure_image("user/custom-image:tag")
    assert "user/custom-image:tag" in str(ei.value)
```

- [ ] **Étape 2 : lancer les tests pour vérifier qu'ils échouent**

```bash
uv run pytest tests/mining/test_docker.py -v
```
Attendu : FAIL avec un `ImportError`.

- [ ] **Étape 3 : écrire le chemin d'acquisition d'image du lanceur**

Crée `src/diapason/mining/_docker.py` :

```python
# src/diapason/mining/_docker.py
"""Orchestration du conteneur Docker de Pearl.

Voir la section 7 de la spécification
``docs/design/2026-05-05-vllm-pearl-mining-integration-design.md``.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Optional

from diapason.mining._constants import (
    PEARL_CACHE_DIR,
    PEARL_IMAGE_TAG,
    PEARL_PINNED_REF,
    PEARL_REPO,
)


class ImageAcquisitionError(RuntimeError):
    """Levée quand une image ne peut être ni trouvée, ni tirée, ni construite."""


class PearlDockerLauncher:
    """Orchestre le conteneur du mineur Pearl.

    À construire avec un ``docker.DockerClient`` (réel ou simulé).
    """

    def __init__(self, client: Any):
        self._client = client
        self._container: Optional[Any] = None

    # -----------------------------------------------------------------
    # Acquisition de l'image
    # -----------------------------------------------------------------

    def ensure_image(self, tag: str) -> str:
        """Résout ``tag`` en une image locale utilisable, en la construisant s'il le faut.

        Ordre de sélection (voir §7.2 de la spéc) :
        1. Image présente localement → on la prend.
        2. Image tirable d'un registre → on la tire et on la prend.
        3. ``tag`` correspond au défaut d'OJ → clone de Pearl + ``docker build``.
        4. Sinon → ``ImageAcquisitionError``.
        """
        import docker.errors as derr

        try:
            self._client.images.get(tag)
            return tag
        except derr.ImageNotFound:
            pass

        try:
            self._client.images.pull(tag)
            return tag
        except (derr.NotFound, derr.APIError):
            pass

        if tag == PEARL_IMAGE_TAG:
            cache = self._clone_pearl_repo()
            return self._docker_build(cache, tag)

        raise ImageAcquisitionError(
            f"l'image {tag!r} n'est pas présente localement, n'est pas tirable, et "
            f"n'est pas le tag par défaut d'OJ (donc pas de repli sur la construction). "
            f"Soit tu la construis à la main avec "
            f"`docker buildx build -t {tag} -f miner/vllm-miner/Dockerfile .` "
            f"depuis le dépôt Pearl, soit tu poses [mining.extra].docker_image_tag sur "
            f"le défaut d'OJ ({PEARL_IMAGE_TAG}) pour activer le repli."
        )

    def _clone_pearl_repo(self) -> Path:
        """Clone Pearl à la référence épinglée, dans le cache d'OJ."""
        PEARL_CACHE_DIR.parent.mkdir(parents=True, exist_ok=True)
        if PEARL_CACHE_DIR.exists():
            subprocess.run(
                ["git", "fetch", "origin", PEARL_PINNED_REF],
                cwd=str(PEARL_CACHE_DIR),
                check=True,
            )
            subprocess.run(
                ["git", "checkout", PEARL_PINNED_REF],
                cwd=str(PEARL_CACHE_DIR),
                check=True,
            )
        else:
            subprocess.run(
                ["git", "clone", "--branch", PEARL_PINNED_REF, PEARL_REPO, str(PEARL_CACHE_DIR)],
                check=True,
            )
        return PEARL_CACHE_DIR

    def _docker_build(self, repo_path: Path, tag: str) -> str:
        """Lance ``docker buildx build`` avec le Dockerfile de Pearl sur le monorepo."""
        # Le contexte de construction doit être la racine du dépôt ; le Dockerfile
        # est à miner/vllm-miner/Dockerfile.
        cmd = [
            "docker",
            "buildx",
            "build",
            "-t",
            tag,
            "-f",
            "miner/vllm-miner/Dockerfile",
            ".",
        ]
        subprocess.run(cmd, cwd=str(repo_path), check=True)
        return tag
```

- [ ] **Étape 4 : lancer les tests pour vérifier qu'ils passent**

```bash
uv run pytest tests/mining/test_docker.py -v
```
Attendu : 4 PASS.

- [ ] **Étape 5 : committer**

```bash
git add src/diapason/mining/_docker.py tests/mining/test_docker.py
git commit -m "feat(mining): acquisition d'image de PearlDockerLauncher (tirer ou construire)"
```

---

## Tâche 6 — Cycle de vie du conteneur dans `PearlDockerLauncher`

**Fichiers :**
- Modifier : `src/diapason/mining/_docker.py`
- Modifier : `tests/mining/test_docker.py`

- [ ] **Étape 1 : écrire les tests qui échouent pour `start()` / `stop()` / `is_running()` / `get_logs()`**

À ajouter à la fin de `tests/mining/test_docker.py` :

```python
import os
import pytest


@pytest.fixture
def _env_password(monkeypatch):
    monkeypatch.setenv("PEARLD_RPC_PASSWORD", "secret123")


def test_launcher_start_calls_run_with_expected_kwargs(_env_password):
    from diapason.mining._docker import PearlDockerLauncher
    from diapason.mining._stubs import MiningConfig, SoloTarget
    fake = MagicMock()
    fake.containers.run.return_value = MagicMock(id="cid-1", status="running")
    launcher = PearlDockerLauncher(client=fake)
    cfg = MiningConfig(
        provider="vllm-pearl",
        wallet_address="prl1qaaa",
        submit_target=SoloTarget(pearld_rpc_url="http://localhost:44107"),
        extra={
            "docker_image_tag": "diapason/pearl-miner:main",
            "model": "pearl-ai/Llama-3.3-70B-Instruct-pearl",
            "vllm_port": 8000,
            "gpu_memory_utilization": 0.9,
            "max_model_len": 8192,
            "pearld_rpc_url": "http://localhost:44107",
            "pearld_rpc_user": "rpcuser",
            "pearld_rpc_password_env": "PEARLD_RPC_PASSWORD",
            "hf_token_env": "HF_TOKEN",
        },
    )
    container = launcher.start(cfg, image="diapason/pearl-miner:main")
    assert container.id == "cid-1"
    fake.containers.run.assert_called_once()
    kwargs = fake.containers.run.call_args.kwargs
    # Image
    assert kwargs["image"] == "diapason/pearl-miner:main"
    # La commande commence par le nom du modèle (positionnel), puis les arguments
    assert kwargs["command"][0] == "pearl-ai/Llama-3.3-70B-Instruct-pearl"
    assert "--gpu-memory-utilization" in kwargs["command"]
    # Politique de redémarrage
    assert kwargs["restart_policy"]["Name"] == "unless-stopped"
    # L'environnement porte le mot de passe (résolu depuis le nom de la variable)
    assert kwargs["environment"]["PEARLD_RPC_PASSWORD"] == "secret123"
    # L'adresse de minage est passée telle quelle
    assert kwargs["environment"]["PEARLD_MINING_ADDRESS"] == "prl1qaaa"
    # MINER_RPC_TRANSPORT posé pour qu'OJ puisse interroger le port 8337
    assert kwargs["environment"]["MINER_RPC_TRANSPORT"] == "tcp"
    # Demande de périphérique GPU
    assert kwargs["device_requests"]


def test_launcher_stop_calls_container_stop_and_remove():
    from diapason.mining._docker import PearlDockerLauncher
    fake_client = MagicMock()
    fake_container = MagicMock()
    launcher = PearlDockerLauncher(client=fake_client)
    launcher._container = fake_container
    launcher.stop()
    fake_container.stop.assert_called_once()


def test_launcher_is_running_when_container_running():
    from diapason.mining._docker import PearlDockerLauncher
    fake_client = MagicMock()
    fake_container = MagicMock(status="running")
    fake_container.reload.return_value = None
    launcher = PearlDockerLauncher(client=fake_client)
    launcher._container = fake_container
    assert launcher.is_running() is True


def test_launcher_is_running_false_when_container_exited():
    from diapason.mining._docker import PearlDockerLauncher
    fake_client = MagicMock()
    fake_container = MagicMock()
    fake_container.reload.return_value = None
    fake_container.status = "exited"
    launcher = PearlDockerLauncher(client=fake_client)
    launcher._container = fake_container
    assert launcher.is_running() is False


def test_launcher_get_logs_returns_decoded_string():
    from diapason.mining._docker import PearlDockerLauncher
    fake_client = MagicMock()
    fake_container = MagicMock()
    fake_container.logs.return_value = b"hello\nworld\n"
    launcher = PearlDockerLauncher(client=fake_client)
    launcher._container = fake_container
    assert "hello" in launcher.get_logs(tail=100)


def test_launcher_start_errors_when_password_env_missing():
    from diapason.mining._docker import PearlDockerLauncher, ConfigurationError
    from diapason.mining._stubs import MiningConfig, SoloTarget
    fake = MagicMock()
    launcher = PearlDockerLauncher(client=fake)
    cfg = MiningConfig(
        provider="vllm-pearl",
        wallet_address="prl1qaaa",
        submit_target=SoloTarget(pearld_rpc_url="http://localhost:44107"),
        extra={
            "docker_image_tag": "diapason/pearl-miner:main",
            "model": "pearl-ai/Llama-3.3-70B-Instruct-pearl",
            "vllm_port": 8000,
            "gpu_memory_utilization": 0.9,
            "pearld_rpc_url": "http://localhost:44107",
            "pearld_rpc_user": "rpcuser",
            "pearld_rpc_password_env": "DOES_NOT_EXIST_IN_ENV",
        },
    )
    with pytest.raises(ConfigurationError) as ei:
        launcher.start(cfg, image="diapason/pearl-miner:main")
    assert "DOES_NOT_EXIST_IN_ENV" in str(ei.value)
```

- [ ] **Étape 2 : lancer les tests pour vérifier qu'ils échouent**

```bash
uv run pytest tests/mining/test_docker.py -v
```
Attendu : 6 nouveaux FAIL.

- [ ] **Étape 3 : écrire `start()`, `stop()`, `is_running()`, `get_logs()`**

À ajouter à la fin de `src/diapason/mining/_docker.py` :

```python
class ConfigurationError(RuntimeError):
    """Levée quand des variables d'environnement ou des champs de config manquent."""


    # ----- dans la classe PearlDockerLauncher, ajouter ces méthodes -----

    def start(self, config: "MiningConfig", image: str) -> Any:
        """Lance le conteneur du mineur Pearl.

        ``image`` doit déjà avoir été résolue par ``ensure_image()``.
        Rend l'objet docker.models.containers.Container.
        """
        from diapason.mining._stubs import MiningConfig  # noqa: F401  (typage seulement)

        extra = config.extra
        # Résolution des secrets : on tient le *nom* de la variable, pas la valeur.
        password_env = extra.get("pearld_rpc_password_env", "PEARLD_RPC_PASSWORD")
        password = os.environ.get(password_env)
        if password is None:
            raise ConfigurationError(
                f"la variable d'environnement {password_env!r} n'est pas posée ; "
                f"pose-la avant de lancer `diapason mine start`"
            )

        hf_token_env = extra.get("hf_token_env", "HF_TOKEN")
        hf_token = os.environ.get(hf_token_env, "")

        model = extra.get("model", "pearl-ai/Llama-3.3-70B-Instruct-pearl")
        vllm_port = int(extra.get("vllm_port", 8000))
        gpu_mem = float(extra.get("gpu_memory_utilization", 0.9))
        max_len = int(extra.get("max_model_len", 8192))

        command = [
            model,
            "--host", "0.0.0.0",
            "--port", str(vllm_port),
            "--gpu-memory-utilization", str(gpu_mem),
            "--enforce-eager",
            "--max-model-len", str(max_len),
        ]

        environment = {
            "PEARLD_RPC_URL": extra.get("pearld_rpc_url", "http://localhost:44107"),
            "PEARLD_RPC_USER": extra.get("pearld_rpc_user", "rpcuser"),
            "PEARLD_RPC_PASSWORD": password,
            "PEARLD_MINING_ADDRESS": config.wallet_address,
            "HF_TOKEN": hf_token,
            "MINER_RPC_TRANSPORT": "tcp",
        }

        # Import dynamique, pour que les tests n'aient pas besoin de la vraie
        # forme du paquet `docker`.
        try:
            from docker.types import DeviceRequest
            device_requests = [DeviceRequest(count=-1, capabilities=[["gpu"]])]
        except ImportError:  # pragma: no cover
            device_requests = None

        hf_cache = Path.home() / ".cache" / "huggingface"
        volumes = {
            str(hf_cache): {"bind": "/root/.cache/huggingface", "mode": "rw"},
        }

        self._container = self._client.containers.run(
            image=image,
            command=command,
            name="diapason-pearl-miner",
            detach=True,
            auto_remove=False,
            restart_policy={"Name": "unless-stopped"},
            device_requests=device_requests,
            shm_size="8g",
            network_mode="host",
            volumes=volumes,
            environment=environment,
        )
        return self._container

    def stop(self, timeout: int = 30) -> None:
        if self._container is None:
            return
        try:
            self._container.stop(timeout=timeout)
        except Exception:  # noqa: BLE001 - au mieux
            pass
        self._container = None

    def is_running(self) -> bool:
        if self._container is None:
            return False
        try:
            self._container.reload()
        except Exception:  # noqa: BLE001
            return False
        return getattr(self._container, "status", "") == "running"

    def get_logs(self, tail: int = 200) -> str:
        if self._container is None:
            return ""
        raw = self._container.logs(tail=tail)
        if isinstance(raw, bytes):
            return raw.decode("utf-8", errors="replace")
        return str(raw)
```

- [ ] **Étape 4 : lancer les tests pour vérifier qu'ils passent**

```bash
uv run pytest tests/mining/test_docker.py -v
```
Attendu : 10 PASS.

- [ ] **Étape 5 : committer**

```bash
git add src/diapason/mining/_docker.py tests/mining/test_docker.py
git commit -m "feat(mining): cycle de vie du conteneur de PearlDockerLauncher (start/stop/is_running/logs)"
```

---

## Tâche 7 — Adaptateur des métriques de la passerelle

**Fichiers :**
- Modifier : `src/diapason/mining/vllm_pearl.py` (créé à la tâche suivante — pour l'instant, écris le parseur comme une aide)
- Créer : `src/diapason/mining/_metrics.py`
- Créer : `tests/mining/fixtures/gateway_metrics_sample.txt`
- Créer : `tests/mining/test_metrics.py`

> **Note pour la personne qui met en œuvre :** le fichier de fixture de cette tâche est un *bouche-trou*, avec les noms de métriques que la spécification suppose (voir le tableau §8.2). Au moment de la mise en œuvre, remplace-le par une vraie sortie Prometheus capturée sur une passerelle Pearl tournant à la référence Pearl épinglée. Documente la procédure de capture dans `tests/mining/fixtures/README.md`.

- [ ] **Étape 1 : créer la fixture Prometheus (bouche-trou)**

`tests/mining/fixtures/gateway_metrics_sample.txt` :

```
# HELP pearl_gateway_shares_submitted_total Total mining shares submitted.
# TYPE pearl_gateway_shares_submitted_total counter
pearl_gateway_shares_submitted_total 12345
# HELP pearl_gateway_shares_accepted_total Total mining shares accepted by pearld.
# TYPE pearl_gateway_shares_accepted_total counter
pearl_gateway_shares_accepted_total 12300
# HELP pearl_gateway_blocks_found_total Total blocks found.
# TYPE pearl_gateway_blocks_found_total counter
pearl_gateway_blocks_found_total 7
# HELP pearl_gateway_last_share_timestamp Unix timestamp of last share submission.
# TYPE pearl_gateway_last_share_timestamp gauge
pearl_gateway_last_share_timestamp 1714867500
# HELP pearl_gateway_errors_total Total errors observed by the gateway.
# TYPE pearl_gateway_errors_total counter
pearl_gateway_errors_total 0
# HELP process_start_time_seconds Process start time (Unix seconds).
# TYPE process_start_time_seconds gauge
process_start_time_seconds 1714865000
```

Crée aussi `tests/mining/fixtures/README.md` :

```markdown
# Fixtures de test du minage

`gateway_metrics_sample.txt` est une sortie Prometheus capturée sur une vraie
passerelle Pearl tournant à la référence Pearl épinglée. Pour la recapturer :

1. Lance l'image Docker de Pearl sur une machine H100, selon la forme de
   lancement de la §7.4 de la spécification.
2. `curl http://127.0.0.1:8339/metrics > gateway_metrics_sample.txt`, une fois
   la passerelle en bonne santé et au moins 10 parts soumises.
3. Retire les bombes de cardinalité (histogrammes par requête ou par temps de
   bloc) qui gonflent le fichier.
4. Committe, en citant le commit/tag de Pearl sur lequel la capture a été faite.

Si Pearl renomme des métriques, mets à jour les constantes `PROM_*` de
`mining/_metrics.py` et recapture.
```

- [ ] **Étape 2 : écrire le test qui échoue**

Crée `tests/mining/test_metrics.py` :

```python
"""Tests de mining/_metrics.py — l'adaptateur Prometheus → MiningStats."""

from __future__ import annotations

from pathlib import Path


FIXTURE = Path(__file__).parent / "fixtures" / "gateway_metrics_sample.txt"


def test_parse_gateway_metrics_full():
    from diapason.mining._metrics import parse_gateway_metrics
    text = FIXTURE.read_text()
    stats = parse_gateway_metrics(text, provider_id="vllm-pearl")
    assert stats.provider_id == "vllm-pearl"
    assert stats.shares_submitted == 12345
    assert stats.shares_accepted == 12300
    assert stats.blocks_found == 7
    assert stats.last_share_at == 1714867500.0
    # La durée de marche vaut now - process_start_time, mais on ne l'asserte pas au chiffre près.
    assert stats.uptime_seconds >= 0


def test_parse_gateway_metrics_missing_metrics_zero_fills():
    from diapason.mining._metrics import parse_gateway_metrics
    stats = parse_gateway_metrics("# empty exposition\n", provider_id="vllm-pearl")
    assert stats.shares_submitted == 0
    assert stats.shares_accepted == 0
    assert stats.blocks_found == 0
    assert stats.last_share_at is None


def test_parse_gateway_metrics_ignores_comment_lines():
    from diapason.mining._metrics import parse_gateway_metrics
    stats = parse_gateway_metrics(
        "# HELP something\n# TYPE something counter\nsomething 99\n",
        provider_id="vllm-pearl",
    )
    assert stats.shares_submitted == 0  # 'something' n'est pas une métrique Pearl
```

- [ ] **Étape 3 : lancer les tests pour vérifier qu'ils échouent**

```bash
uv run pytest tests/mining/test_metrics.py -v
```
Attendu : 3 FAIL.

- [ ] **Étape 4 : écrire l'adaptateur**

Crée `src/diapason/mining/_metrics.py` :

```python
# src/diapason/mining/_metrics.py
"""Adaptateur Prometheus de la passerelle Pearl → MiningStats.

La passerelle expose ``:8339/metrics`` au format d'exposition Prometheus
ordinaire. C'est le contrat le plus stable que Pearl publie ; l'introspection
RPC plus profonde sur ``:8337`` est repoussée à la v2 (où elle sert à la
comptabilité des parts de pool).

Si Pearl renomme des métriques, change les constantes ``PROM_*`` ici — c'est le
seul endroit où les noms de métriques vivent.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from diapason.mining._stubs import MiningStats

log = logging.getLogger(__name__)

# Noms des métriques Pearl. Voir §8.2 de la spéc — à vérifier contre la fixture
# versionnée dans tests/mining/fixtures/gateway_metrics_sample.txt.
PROM_SHARES_SUBMITTED = "pearl_gateway_shares_submitted_total"
PROM_SHARES_ACCEPTED = "pearl_gateway_shares_accepted_total"
PROM_BLOCKS_FOUND = "pearl_gateway_blocks_found_total"
PROM_LAST_SHARE_TS = "pearl_gateway_last_share_timestamp"
PROM_ERRORS_TOTAL = "pearl_gateway_errors_total"
PROM_PROCESS_START = "process_start_time_seconds"


def _parse_simple_metric(text: str, name: str) -> Optional[float]:
    """Trouve la première occurrence d'une métrique simple, sans étiquette.

    Les lignes ressemblent à ``metric_name 12345`` ou
    ``metric_name{label="x"} 12345``. Pour l'adaptateur v1, on ignore les
    étiquettes et on prend la première correspondance hors commentaire.
    """
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        # On coupe au premier blanc ; le nom de la métrique est tout ce qui
        # précède un éventuel bloc d'étiquettes `{...}`.
        head, _, value = line.partition(" ")
        head = head.split("{", 1)[0]
        if head == name:
            try:
                return float(value.strip())
            except ValueError:
                return None
    return None


def parse_gateway_metrics(text: str, *, provider_id: str) -> MiningStats:
    """Convertit une charge d'exposition Prometheus en ``MiningStats``."""
    submitted = _parse_simple_metric(text, PROM_SHARES_SUBMITTED) or 0.0
    accepted = _parse_simple_metric(text, PROM_SHARES_ACCEPTED) or 0.0
    blocks = _parse_simple_metric(text, PROM_BLOCKS_FOUND) or 0.0
    last_share_ts = _parse_simple_metric(text, PROM_LAST_SHARE_TS)
    errors = _parse_simple_metric(text, PROM_ERRORS_TOTAL) or 0.0
    proc_start = _parse_simple_metric(text, PROM_PROCESS_START)

    uptime = 0.0
    if proc_start is not None:
        uptime = max(0.0, time.time() - proc_start)

    last_error: Optional[str] = None
    if errors > 0:
        last_error = f"{int(errors)} erreurs de passerelle observées"

    return MiningStats(
        provider_id=provider_id,
        shares_submitted=int(submitted),
        shares_accepted=int(accepted),
        blocks_found=int(blocks),
        # Un taux dérivé n'a pas de sens sur un seul instantané ; c'est le
        # collecteur persistant de la v1.x qui le calculera. La v1 laisse 0.
        hashrate=0.0,
        uptime_seconds=uptime,
        last_share_at=last_share_ts,
        last_error=last_error,
    )
```

- [ ] **Étape 5 : lancer les tests pour vérifier qu'ils passent**

```bash
uv run pytest tests/mining/test_metrics.py -v
```
Attendu : 3 PASS.

- [ ] **Étape 6 : committer**

```bash
git add src/diapason/mining/_metrics.py tests/mining/test_metrics.py tests/mining/fixtures/
git commit -m "feat(mining): adaptateur des métriques Prometheus de la passerelle"
```

---

## Tâche 8 — `VllmPearlProvider` (le seul fournisseur de la v1)

**Fichiers :**
- Créer : `src/diapason/mining/vllm_pearl.py`
- Créer : `tests/mining/test_vllm_pearl.py`

- [ ] **Étape 1 : écrire les tests qui échouent**

Crée `tests/mining/test_vllm_pearl.py` :

```python
"""Tests de bout en bout de VllmPearlProvider, Docker et système de fichiers simulés."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


def test_vllm_pearl_detect_supported_on_h100(hopper_hw):
    from diapason.mining.vllm_pearl import VllmPearlProvider
    cap = VllmPearlProvider.detect(
        hopper_hw, engine_id="vllm",
        model="pearl-ai/Llama-3.3-70B-Instruct-pearl",
    )
    assert cap.supported is True


def test_vllm_pearl_detect_unsupported_on_apple(apple_hw):
    from diapason.mining.vllm_pearl import VllmPearlProvider
    cap = VllmPearlProvider.detect(
        apple_hw, engine_id="mlx",
        model="pearl-ai/Llama-3.3-70B-Instruct-pearl",
    )
    assert cap.supported is False


@pytest.mark.asyncio
async def test_vllm_pearl_start_writes_sidecar(tmp_path, monkeypatch):
    from diapason.mining.vllm_pearl import VllmPearlProvider
    from diapason.mining._stubs import MiningConfig, SoloTarget, Sidecar

    sidecar_path = tmp_path / "mining.json"
    monkeypatch.setattr(
        "diapason.mining.vllm_pearl.SIDECAR_PATH", sidecar_path
    )
    monkeypatch.setenv("PEARLD_RPC_PASSWORD", "x")

    fake_client = MagicMock()
    fake_container = MagicMock(id="cid-xyz")
    fake_container.status = "running"
    fake_client.containers.run.return_value = fake_container
    # ensure_image : image déjà présente
    fake_client.images.get.return_value = MagicMock(id="sha256:abc")

    cfg = MiningConfig(
        provider="vllm-pearl",
        wallet_address="prl1qaaa",
        submit_target=SoloTarget(pearld_rpc_url="http://localhost:44107"),
        extra={
            "docker_image_tag": "diapason/pearl-miner:main",
            "model": "pearl-ai/Llama-3.3-70B-Instruct-pearl",
            "vllm_port": 8000,
            "gateway_port": 8337,
            "gateway_metrics_port": 8339,
            "gpu_memory_utilization": 0.9,
            "max_model_len": 8192,
            "pearld_rpc_url": "http://localhost:44107",
            "pearld_rpc_user": "rpcuser",
            "pearld_rpc_password_env": "PEARLD_RPC_PASSWORD",
        },
    )

    provider = VllmPearlProvider(docker_client=fake_client)
    await provider.start(cfg)

    assert sidecar_path.exists()
    payload = json.loads(sidecar_path.read_text())
    assert payload["provider"] == "vllm-pearl"
    assert payload["vllm_endpoint"].endswith(":8000/v1")
    assert payload["gateway_url"].endswith(":8337")
    assert payload["gateway_metrics_url"].endswith(":8339")
    assert payload["wallet_address"] == "prl1qaaa"
    assert payload["container_id"] == "cid-xyz"
    assert "started_at" in payload
    # Le sidecar ne porte aucun secret
    assert "PEARLD_RPC_PASSWORD" not in json.dumps(payload)


@pytest.mark.asyncio
async def test_vllm_pearl_start_pool_target_raises_not_implemented(monkeypatch, tmp_path):
    from diapason.mining.vllm_pearl import VllmPearlProvider
    from diapason.mining._stubs import MiningConfig, PoolTarget

    sidecar_path = tmp_path / "mining.json"
    monkeypatch.setattr(
        "diapason.mining.vllm_pearl.SIDECAR_PATH", sidecar_path
    )

    cfg = MiningConfig(
        provider="vllm-pearl",
        wallet_address="prl1qaaa",
        submit_target=PoolTarget(url="https://pool.diapason.ai/submit"),
        extra={"docker_image_tag": "diapason/pearl-miner:main"},
    )
    provider = VllmPearlProvider(docker_client=MagicMock())
    with pytest.raises(NotImplementedError) as ei:
        await provider.start(cfg)
    assert "v2" in str(ei.value).lower() or "pool" in str(ei.value).lower()


@pytest.mark.asyncio
async def test_vllm_pearl_stop_removes_sidecar(tmp_path, monkeypatch, written_sidecar):
    from diapason.mining.vllm_pearl import VllmPearlProvider
    monkeypatch.setattr(
        "diapason.mining.vllm_pearl.SIDECAR_PATH", written_sidecar
    )
    fake_client = MagicMock()
    provider = VllmPearlProvider(docker_client=fake_client)
    provider._launcher._container = MagicMock()  # on simule un conteneur en marche
    await provider.stop()
    assert not written_sidecar.exists()


def test_vllm_pearl_stats_reads_gateway(monkeypatch, written_sidecar):
    from diapason.mining.vllm_pearl import VllmPearlProvider
    monkeypatch.setattr(
        "diapason.mining.vllm_pearl.SIDECAR_PATH", written_sidecar
    )
    sample = (
        "pearl_gateway_shares_submitted_total 100\n"
        "pearl_gateway_shares_accepted_total 99\n"
        "pearl_gateway_blocks_found_total 1\n"
    )
    with patch("diapason.mining.vllm_pearl.httpx.get") as get:
        get.return_value.status_code = 200
        get.return_value.text = sample
        provider = VllmPearlProvider(docker_client=MagicMock())
        stats = provider.stats()
        assert stats.shares_submitted == 100
        assert stats.shares_accepted == 99
        assert stats.blocks_found == 1


def test_ensure_registered_is_idempotent():
    from diapason.core.registry import MinerRegistry
    from diapason.mining.vllm_pearl import (
        VllmPearlProvider,
        ensure_registered,
    )
    ensure_registered()
    ensure_registered()  # le second appel ne doit rien lever
    assert MinerRegistry.contains("vllm-pearl")
    assert MinerRegistry.get("vllm-pearl") is VllmPearlProvider
```

> **Note :** le test `test_vllm_pearl_start_writes_sidecar` utilise `pytest.mark.asyncio`. Vérifie que `pytest-asyncio` est bien dans les extras de développement (il y est, d'après `[project.optional-dependencies].dev` de `pyproject.toml`). Si les tests asynchrones ne sont pas collectés, ajoute `asyncio_mode = "auto"` sous `[tool.pytest.ini_options]` dans `pyproject.toml`.

- [ ] **Étape 2 : lancer les tests pour vérifier qu'ils échouent**

```bash
uv run pytest tests/mining/test_vllm_pearl.py -v
```
Attendu : 7 FAIL.

- [ ] **Étape 3 : écrire `VllmPearlProvider`**

Crée `src/diapason/mining/vllm_pearl.py` :

```python
# src/diapason/mining/vllm_pearl.py
"""Le fournisseur de minage vllm-pearl de la v1.

Voir la spécification
``docs/design/2026-05-05-vllm-pearl-mining-integration-design.md``.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Optional

import httpx

from diapason.core.config import HardwareInfo
from diapason.core.registry import MinerRegistry
from diapason.mining._constants import (
    DEFAULT_GATEWAY_METRICS_PORT,
    DEFAULT_GATEWAY_RPC_PORT,
    DEFAULT_PEARL_MODEL,
    DEFAULT_VLLM_PORT,
    PEARL_IMAGE_TAG,
    SIDECAR_PATH,
)
from diapason.mining._discovery import detect_for_engine_model
from diapason.mining._docker import PearlDockerLauncher
from diapason.mining._metrics import parse_gateway_metrics
from diapason.mining._stubs import (
    MiningCapabilities,
    MiningConfig,
    MiningProvider,
    MiningStats,
    PoolTarget,
    Sidecar,
    SoloTarget,
)


class VllmPearlProvider(MiningProvider):
    """vLLM + le conteneur Docker de Pearl, minage solo uniquement en v1."""

    provider_id = "vllm-pearl"

    def __init__(self, docker_client: Optional[Any] = None):
        if docker_client is None:
            import docker
            docker_client = docker.from_env()
        self._client = docker_client
        self._launcher = PearlDockerLauncher(client=docker_client)

    @classmethod
    def detect(cls, hw: HardwareInfo, engine_id: str, model: str) -> MiningCapabilities:
        return detect_for_engine_model(
            hw=hw, engine_id=engine_id, model=model, provider_id=cls.provider_id,
        )

    async def start(self, config: MiningConfig) -> None:
        if isinstance(config.submit_target, PoolTarget):
            raise NotImplementedError(
                "le support des pools est en v2 — voir diapason#XYZ. La v1 n'accepte "
                "que submit_target='solo'."
            )
        assert isinstance(config.submit_target, SoloTarget)

        image = config.extra.get("docker_image_tag", PEARL_IMAGE_TAG)
        image = self._launcher.ensure_image(image)
        container = self._launcher.start(config, image=image)

        # On tire l'attribution des ports de extra (avec des défauts raisonnables).
        vllm_port = int(config.extra.get("vllm_port", DEFAULT_VLLM_PORT))
        gw_port = int(config.extra.get("gateway_port", DEFAULT_GATEWAY_RPC_PORT))
        gw_metrics = int(
            config.extra.get("gateway_metrics_port", DEFAULT_GATEWAY_METRICS_PORT)
        )
        model_name = config.extra.get("model", DEFAULT_PEARL_MODEL)

        Sidecar.write(SIDECAR_PATH, {
            "provider": self.provider_id,
            "vllm_endpoint": f"http://127.0.0.1:{vllm_port}/v1",
            "model": model_name,
            "gateway_url": f"http://127.0.0.1:{gw_port}",
            "gateway_metrics_url": f"http://127.0.0.1:{gw_metrics}",
            "container_id": getattr(container, "id", ""),
            "wallet_address": config.wallet_address,
            "started_at": int(time.time()),
        })

    async def stop(self) -> None:
        self._launcher.stop()
        Sidecar.remove(SIDECAR_PATH)

    def is_running(self) -> bool:
        return self._launcher.is_running()

    def stats(self) -> MiningStats:
        sidecar = Sidecar.read(SIDECAR_PATH)
        if sidecar is None:
            return MiningStats(provider_id=self.provider_id)
        url = sidecar.get("gateway_metrics_url")
        if not url:
            return MiningStats(provider_id=self.provider_id)
        try:
            resp = httpx.get(f"{url}/metrics", timeout=5.0)
            if resp.status_code != 200:
                return MiningStats(
                    provider_id=self.provider_id,
                    last_error=f"passerelle HTTP {resp.status_code}",
                )
            return parse_gateway_metrics(resp.text, provider_id=self.provider_id)
        except Exception as e:  # noqa: BLE001
            return MiningStats(
                provider_id=self.provider_id,
                last_error=str(e).splitlines()[0],
            )


def ensure_registered() -> None:
    """Enregistrement idempotent. Obligatoire, parce que tests/conftest.py vide
    tous les registres avant chaque test (voir §4.2 de la spécification A).
    """
    if not MinerRegistry.contains("vllm-pearl"):
        MinerRegistry.register_value("vllm-pearl", VllmPearlProvider)
```

- [ ] **Étape 4 : lancer les tests pour vérifier qu'ils passent**

```bash
uv run pytest tests/mining/test_vllm_pearl.py -v
```
Attendu : 7 PASS.

- [ ] **Étape 5 : lancer toute la suite de tests du minage, pour confirmer l'absence de régression**

```bash
uv run pytest tests/mining/ -v
```
Attendu : TOUT passe.

- [ ] **Étape 6 : committer**

```bash
git add src/diapason/mining/vllm_pearl.py tests/mining/test_vllm_pearl.py
git commit -m "feat(mining): VllmPearlProvider — le fournisseur vllm-pearl de la v1"
```

---

## Tâche 9 — Passage de relais au moteur par le sidecar

**Fichiers :**
- Modifier : `src/diapason/engine/_discovery.py`
- Test : `tests/engine/test_discovery.py` (existant — y ajouter de nouveaux tests)

- [ ] **Étape 1 : lire l'actuel `engine/_discovery.py`**

Lance :
```bash
sed -n '1,80p' src/diapason/engine/_discovery.py
```

Repère la fonction qui résout les moteurs (probablement `discover_engines()` ou `get_engine()`).

- [ ] **Étape 2 : écrire le test qui échoue**

À ajouter dans `tests/engine/test_discovery.py` :

```python
def test_engine_discovery_picks_up_mining_sidecar(tmp_path, monkeypatch, written_sidecar):
    """Quand un sidecar de minage existe, la résolution des moteurs doit exposer
    un moteur 'vllm-pearl-mining' pointant sur le vllm_endpoint du sidecar.
    """
    from diapason.engine._discovery import discover_engines
    from diapason.mining import _constants as mining_const

    monkeypatch.setattr(mining_const, "SIDECAR_PATH", written_sidecar)

    engines = discover_engines(force=True)
    keys = {e.engine_id if hasattr(e, "engine_id") else e for e in engines}
    assert any("vllm-pearl-mining" in str(k) for k in keys)


def test_engine_discovery_no_mining_engine_when_sidecar_absent(tmp_path, monkeypatch):
    from diapason.engine._discovery import discover_engines
    from diapason.mining import _constants as mining_const

    missing = tmp_path / "no-such-mining.json"
    monkeypatch.setattr(mining_const, "SIDECAR_PATH", missing)

    engines = discover_engines(force=True)
    keys = {e.engine_id if hasattr(e, "engine_id") else e for e in engines}
    assert not any("vllm-pearl-mining" in str(k) for k in keys)
```

La fixture `written_sidecar` vit dans `tests/mining/conftest.py` ; il faudra soit la déplacer vers un conftest partagé, soit la dupliquer dans `tests/engine/conftest.py`. Préfère déplacer celles qui servent ailleurs vers `tests/conftest.py`.

- [ ] **Étape 3 : déplacer les fixtures du sidecar vers le conftest racine**

Déplace `sample_sidecar_payload`, `sidecar_path` et `written_sidecar` de `tests/mining/conftest.py` vers `tests/conftest.py`. Déplace aussi `hopper_hw`, `ada_hw`, `apple_hw` et `mock_docker_client` vers `tests/conftest.py`, pour que tous les paquets de tests puissent s'en servir.

- [ ] **Étape 4 : lancer les tests pour vérifier qu'ils échouent**

```bash
uv run pytest tests/engine/test_discovery.py -k mining_sidecar -v
```
Attendu : FAIL — le moteur du sidecar n'est pas enregistré.

- [ ] **Étape 5 : modifier `engine/_discovery.py`**

Repère le chemin de résolution des moteurs. Ajoute une aide :

```python
def _maybe_register_mining_sidecar_engine() -> None:
    """Si un sidecar de minage existe, enregistre un moteur vLLM dérivé qui
    pointe sur le point d'accès du minage.

    Voir §5.4 de la spécification A. Idempotente — appelable sans risque depuis
    n'importe quel chemin de découverte.
    """
    try:
        from diapason.mining import Sidecar
        from diapason.mining._constants import SIDECAR_PATH
    except ImportError:
        return
    payload = Sidecar.read(SIDECAR_PATH)
    if payload is None:
        return
    endpoint = payload.get("vllm_endpoint")
    model = payload.get("model")
    if not endpoint or not model:
        return

    from diapason.core.registry import EngineRegistry
    from diapason.engine.openai_compat_engines import OpenAICompatEngine  # à ajuster au vrai nom de classe

    if EngineRegistry.contains("vllm-pearl-mining"):
        return

    # On construit une instance liée au point d'accès du minage, et on l'enregistre.
    instance = OpenAICompatEngine(
        engine_id="vllm-pearl-mining",
        base_url=endpoint,
        default_model=model,
    )
    EngineRegistry.register_value("vllm-pearl-mining", instance)
```

Appelle `_maybe_register_mining_sidecar_engine()` depuis `discover_engines()`, après la logique de détection existante et avant le retour.

> **Note pour la personne qui met en œuvre :** vérifie le vrai nom de la classe qui enveloppe le moteur compatible OpenAI dans `engine/openai_compat_engines.py`, et ajuste l'import et le constructeur en conséquence. La clé de registre doit être exactement `"vllm-pearl-mining"`.

- [ ] **Étape 6 : lancer les tests pour vérifier qu'ils passent**

```bash
uv run pytest tests/engine/test_discovery.py -k mining_sidecar -v
```
Attendu : 2 PASS.

- [ ] **Étape 7 : committer**

```bash
git add src/diapason/engine/_discovery.py tests/conftest.py tests/mining/conftest.py tests/engine/test_discovery.py
git commit -m "feat(mining): la découverte des moteurs ramasse le sidecar d'exécution"
```

---

## Tâche 10 — `MiningTelemetryCollector` (livré non branché)

**Fichiers :**
- Créer : `src/diapason/mining/_collector.py`
- Créer : `tests/mining/test_collector.py`

- [ ] **Étape 1 : écrire les tests qui échouent**

Crée `tests/mining/test_collector.py` :

```python
"""Tests de MiningTelemetryCollector — livré en v1, mais non branché."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_collector_collect_once_returns_stats(written_sidecar):
    from diapason.mining._collector import MiningTelemetryCollector

    sample = (
        "pearl_gateway_shares_submitted_total 50\n"
        "pearl_gateway_shares_accepted_total 49\n"
    )
    with patch("diapason.mining._collector.httpx.get") as get:
        get.return_value.status_code = 200
        get.return_value.text = sample
        store = MagicMock()
        c = MiningTelemetryCollector(
            sidecar_path=written_sidecar, telemetry_store=store, interval_s=0.05
        )
        stats = await c.collect_once()
        assert stats.shares_submitted == 50
        assert stats.shares_accepted == 49


@pytest.mark.asyncio
async def test_collector_run_loop_writes_to_store_then_stops(written_sidecar):
    from diapason.mining._collector import MiningTelemetryCollector

    sample = "pearl_gateway_shares_submitted_total 1\n"
    with patch("diapason.mining._collector.httpx.get") as get:
        get.return_value.status_code = 200
        get.return_value.text = sample
        store = MagicMock()
        c = MiningTelemetryCollector(
            sidecar_path=written_sidecar, telemetry_store=store, interval_s=0.01
        )
        # On fait tourner la boucle un court instant, puis on l'arrête.
        task = asyncio.create_task(c.run())
        await asyncio.sleep(0.05)
        c.stop()
        await asyncio.wait_for(task, timeout=1.0)
        assert store.record_mining_stats.call_count >= 1


@pytest.mark.asyncio
async def test_collector_handles_gateway_errors_gracefully(written_sidecar):
    from diapason.mining._collector import MiningTelemetryCollector

    with patch("diapason.mining._collector.httpx.get") as get:
        get.side_effect = ConnectionError("nope")
        store = MagicMock()
        c = MiningTelemetryCollector(
            sidecar_path=written_sidecar, telemetry_store=store
        )
        stats = await c.collect_once()
        assert stats.last_error is not None
```

- [ ] **Étape 2 : lancer les tests pour vérifier qu'ils échouent**

```bash
uv run pytest tests/mining/test_collector.py -v
```
Attendu : 3 FAIL.

- [ ] **Étape 3 : écrire le collecteur**

Crée `src/diapason/mining/_collector.py` :

```python
# src/diapason/mining/_collector.py
"""Sondeur d'arrière-plan pour la télémétrie de minage.

Livré en v1, mais **pas branché dans le démon passerelle**. La v1.x
l'enregistrera comme tâche asyncio périodique dans ``diapason.daemon.gateway``.
En v1, la commande de statut lit à la demande — voir
``vllm_pearl.VllmPearlProvider.stats``.

Pourquoi le livrer maintenant ? Allumer le collecteur en v1.x est un
changement d'une ligne dans le démon. Le contrat (signature d'init, boucle
``run()``, ``collect_once()``, ``stop()``) est figé par cette livraison v1,
pour éviter que l'API ne bouge ensuite.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import httpx

from diapason.mining._metrics import parse_gateway_metrics
from diapason.mining._stubs import MiningStats, Sidecar

log = logging.getLogger(__name__)


class MiningTelemetryCollector:
    """Interroge périodiquement la passerelle Pearl et écrit des ``MiningStats``
    dans un magasin de télémétrie.

    ``telemetry_store`` est typé par le comportement : il doit implémenter
    ``record_mining_stats(stats: MiningStats) -> None``.
    """

    def __init__(
        self,
        sidecar_path: Path,
        telemetry_store: Any,
        interval_s: float = 30.0,
    ):
        self._sidecar_path = sidecar_path
        self._store = telemetry_store
        self._interval_s = interval_s
        self._stop = False

    async def collect_once(self) -> MiningStats:
        sidecar = Sidecar.read(self._sidecar_path)
        if sidecar is None:
            return MiningStats(provider_id="unknown")
        url = sidecar.get("gateway_metrics_url")
        provider_id = sidecar.get("provider", "unknown")
        if not url:
            return MiningStats(provider_id=provider_id)
        try:
            resp = httpx.get(f"{url}/metrics", timeout=5.0)
            if resp.status_code != 200:
                return MiningStats(
                    provider_id=provider_id,
                    last_error=f"passerelle HTTP {resp.status_code}",
                )
            return parse_gateway_metrics(resp.text, provider_id=provider_id)
        except Exception as e:  # noqa: BLE001
            return MiningStats(provider_id=provider_id, last_error=str(e).splitlines()[0])

    async def run(self) -> None:
        while not self._stop:
            try:
                stats = await self.collect_once()
                self._store.record_mining_stats(stats)
            except Exception as e:  # noqa: BLE001
                log.warning("erreur de tic de MiningTelemetryCollector : %s", e)
            try:
                await asyncio.sleep(self._interval_s)
            except asyncio.CancelledError:
                break

    def stop(self) -> None:
        self._stop = True
```

- [ ] **Étape 4 : lancer les tests pour vérifier qu'ils passent**

```bash
uv run pytest tests/mining/test_collector.py -v
```
Attendu : 3 PASS.

- [ ] **Étape 5 : committer**

```bash
git add src/diapason/mining/_collector.py tests/mining/test_collector.py
git commit -m "feat(mining): MiningTelemetryCollector — livré non branché pour la v1.x"
```

---

## Tâche 11 — Migration du schéma de télémétrie (`mining_session_id`)

**Fichiers :**
- Modifier : `src/diapason/telemetry/store.py`
- Test : `tests/telemetry/test_store.py` (existant — y ajouter de nouveaux tests)

- [ ] **Étape 1 : inspecter l'approche de migration actuelle de `telemetry/store.py`**

Lance :
```bash
grep -n "PRAGMA user_version\|CREATE TABLE\|ALTER TABLE\|migrate" src/diapason/telemetry/store.py | head -20
```

Si `PRAGMA user_version` est déjà utilisé, suis cette convention. Si les migrations ne sont que des `CREATE TABLE IF NOT EXISTS` en ligne, passe à une approche versionnée pour ce changement. Documente le motif retenu dans le message de commit.

- [ ] **Étape 2 : écrire les tests qui échouent**

À ajouter dans `tests/telemetry/test_store.py` :

```python
def test_inference_row_has_mining_session_id_column(tmp_path):
    from diapason.telemetry.store import TelemetryStore
    db = tmp_path / "tel.db"
    store = TelemetryStore(db_path=db)
    store.record_inference(
        model="test-model",
        engine_id="test-engine",
        prompt_tokens=10,
        completion_tokens=5,
        latency_ms=100.0,
    )
    # Par défaut — nul
    rows = store.list_recent(limit=1)
    assert "mining_session_id" in rows[0]
    assert rows[0]["mining_session_id"] is None


def test_inference_row_can_be_tagged_with_mining_session_id(tmp_path):
    from diapason.telemetry.store import TelemetryStore
    db = tmp_path / "tel.db"
    store = TelemetryStore(db_path=db)
    store.record_inference(
        model="test-model",
        engine_id="vllm-pearl-mining",
        prompt_tokens=10,
        completion_tokens=5,
        latency_ms=100.0,
        mining_session_id="abc123",
    )
    rows = store.list_recent(limit=1)
    assert rows[0]["mining_session_id"] == "abc123"


def test_record_mining_stats_persists(tmp_path):
    from diapason.telemetry.store import TelemetryStore
    from diapason.mining._stubs import MiningStats
    db = tmp_path / "tel.db"
    store = TelemetryStore(db_path=db)
    store.record_mining_stats(
        MiningStats(provider_id="vllm-pearl", shares_submitted=42, shares_accepted=40)
    )
    snapshots = store.list_recent_mining_stats(limit=1)
    assert snapshots[0]["shares_submitted"] == 42
```

- [ ] **Étape 3 : lancer les tests pour vérifier qu'ils échouent**

```bash
uv run pytest tests/telemetry/test_store.py -k mining -v
```
Attendu : FAIL.

- [ ] **Étape 4 : écrire la migration**

Dans `src/diapason/telemetry/store.py` :

1. Incrémente de 1 la constante de version du schéma (ou introduis-en une si elle manque).
2. Ajoute une étape de migration : `ALTER TABLE inference ADD COLUMN mining_session_id TEXT NULL;`, gardée par la montée de version.
3. Ajoute une table `mining_stats` avec les colonnes qu'il faut : `provider_id`, `shares_submitted`, `shares_accepted`, `blocks_found`, `hashrate`, `uptime_seconds`, `last_share_at`, `last_error`, `payout_target`, `fees_owed`, `recorded_at`.
4. Ajoute le paramètre `record_inference(..., mining_session_id: Optional[str] = None)` — garde-le en mot-clé seulement et avec un défaut, pour que les appelants n'aient pas à changer.
5. Ajoute `record_mining_stats(stats: MiningStats) -> None`.
6. Ajoute `list_recent_mining_stats(limit: int = 50) -> list[dict]`.
7. Mets à jour `list_recent()` pour que `mining_session_id` figure dans les lignes rendues.

Le SQL exact :

```sql
-- migrate_v<N>_to_v<N+1> :
ALTER TABLE inference ADD COLUMN mining_session_id TEXT;

CREATE TABLE IF NOT EXISTS mining_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at REAL NOT NULL,
    provider_id TEXT NOT NULL,
    shares_submitted INTEGER NOT NULL DEFAULT 0,
    shares_accepted INTEGER NOT NULL DEFAULT 0,
    blocks_found INTEGER NOT NULL DEFAULT 0,
    hashrate REAL NOT NULL DEFAULT 0,
    uptime_seconds REAL NOT NULL DEFAULT 0,
    last_share_at REAL,
    last_error TEXT,
    payout_target TEXT NOT NULL DEFAULT 'solo',
    fees_owed INTEGER NOT NULL DEFAULT 0
);
```

- [ ] **Étape 5 : lancer les tests pour vérifier qu'ils passent**

```bash
uv run pytest tests/telemetry/test_store.py -v
```
Attendu : TOUT passe (les tests existants plus les 3 nouveaux).

- [ ] **Étape 6 : committer**

```bash
git add src/diapason/telemetry/store.py tests/telemetry/test_store.py
git commit -m "feat(telemetry): ajoute mining_session_id et la table mining_stats"
```

---

## Tâche 12 — `diapason mine doctor` (la plus grande valeur pour l'utilisateur : à construire en premier)

**Fichiers :**
- Créer : `src/diapason/cli/mine_cmd.py`
- Créer : `tests/mining/test_cli.py`

- [ ] **Étape 1 : écrire le test qui échoue**

Crée `tests/mining/test_cli.py` :

```python
"""Tests de fumée de la CLI, via le CliRunner de Click."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from click.testing import CliRunner


def test_mine_doctor_prints_capability_matrix(monkeypatch):
    from diapason.cli.mine_cmd import mine
    runner = CliRunner()

    # On force la fixture matérielle H100, pour que detect() rende « supporté ».
    from diapason.core.config import GpuInfo, HardwareInfo
    fake_hw = HardwareInfo(
        platform="linux",
        gpu=GpuInfo(
            vendor="nvidia", name="H100", vram_gb=80.0,
            compute_capability="9.0", count=1,
        ),
    )
    with patch("diapason.cli.mine_cmd._detect_hardware", return_value=fake_hw), \
         patch("diapason.cli.mine_cmd.check_docker_available", return_value=(True, "en marche 24.0.7")), \
         patch("diapason.cli.mine_cmd.check_disk_free", return_value=(True, "300 Go libres")), \
         patch("diapason.cli.mine_cmd.check_pearld_reachable", return_value=(True, "hauteur de bloc 442107 (synchronisé)")):
        result = runner.invoke(mine, ["doctor"])
    assert result.exit_code == 0, result.output
    out = result.output.lower()
    assert "matériel" in out
    assert "docker" in out
    assert "pearl" in out
    assert "vllm-pearl" in out


def test_mine_doctor_flags_unsupported_hardware():
    from diapason.cli.mine_cmd import mine
    runner = CliRunner()

    from diapason.core.config import GpuInfo, HardwareInfo
    fake_hw = HardwareInfo(
        platform="linux",
        gpu=GpuInfo(
            vendor="nvidia", name="RTX 4090", vram_gb=24.0,
            compute_capability="8.9", count=1,
        ),
    )
    with patch("diapason.cli.mine_cmd._detect_hardware", return_value=fake_hw), \
         patch("diapason.cli.mine_cmd.check_docker_available", return_value=(True, "ok")), \
         patch("diapason.cli.mine_cmd.check_disk_free", return_value=(True, "300 Go libres")), \
         patch("diapason.cli.mine_cmd.check_pearld_reachable", return_value=(False, "connexion refusée")):
        result = runner.invoke(mine, ["doctor"])
    assert result.exit_code == 0
    assert "✗" in result.output or "FAIL" in result.output.upper()
```

- [ ] **Étape 2 : lancer le test pour vérifier qu'il échoue**

```bash
uv run pytest tests/mining/test_cli.py::test_mine_doctor_prints_capability_matrix -v
```
Attendu : FAIL.

- [ ] **Étape 3 : écrire `mine_cmd.py` avec la sous-commande `doctor`**

```python
# src/diapason/cli/mine_cmd.py
"""Groupe de commandes ``diapason mine``.

Voir la section 6 de la spécification
``docs/design/2026-05-05-vllm-pearl-mining-integration-design.md`` pour toute
la surface CLI.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

import click

from diapason.core.config import HardwareInfo, load_config
from diapason.mining._constants import (
    DEFAULT_PEARL_MODEL,
    DEFAULT_PEARLD_RPC_URL,
    PEARL_IMAGE_TAG,
    SIDECAR_PATH,
)
from diapason.mining._discovery import (
    check_disk_free,
    check_docker_available,
    check_pearld_reachable,
    check_wallet_address_format,
    detect_for_engine_model,
)
from diapason.mining._stubs import Sidecar


def _detect_hardware() -> HardwareInfo:
    """Enveloppe qui rend la détection du matériel simulable dans les tests CLI."""
    return load_config().hardware


@click.group()
def mine() -> None:
    """Commandes de minage Pearl PoUW.

    Le guide complet est sur
    https://carlitoetienne01-spec.github.io/Diapason/user-guide/mining/.
    """


@mine.command()
def doctor() -> None:
    """Diagnostique la capacité de minage, une ligne par contrôle."""
    hw = _detect_hardware()
    cfg = load_config()
    mining_cfg = cfg.mining

    def row(group: str, name: str, ok: bool, info: str) -> None:
        marker = "✓" if ok else "✗"
        click.echo(f"  {name:<22} {info:<35} {marker}")

    click.echo("Matériel")
    row("hw", "Fabricant du GPU", hw.gpu.vendor == "nvidia" if hw.gpu else False,
        hw.gpu.vendor if hw.gpu else "(pas de GPU)")
    cc_ok = bool(hw.gpu and hw.gpu.compute_capability.startswith("9.0"))
    row("hw", "Compute capability", cc_ok,
        hw.gpu.compute_capability if hw.gpu else "n/d")
    vram = hw.gpu.vram_gb if hw.gpu else 0
    row("hw", "VRAM", vram >= 70, f"{vram:.0f} Go")

    click.echo("Docker")
    ok, info = check_docker_available()
    row("docker", "Démon", ok, info)

    click.echo("Disque")
    ok, info = check_disk_free(Path.home())
    row("disk", "Libre dans le cache HF", ok, info)

    click.echo("Nœud Pearl")
    if mining_cfg is not None:
        url = mining_cfg.extra.get("pearld_rpc_url", DEFAULT_PEARLD_RPC_URL)
        user = mining_cfg.extra.get("pearld_rpc_user", "rpcuser")
        password_env = mining_cfg.extra.get(
            "pearld_rpc_password_env", "PEARLD_RPC_PASSWORD"
        )
        password = os.environ.get(password_env, "")
        ok, info = check_pearld_reachable(url, user, password)
        row("pearld", "RPC", ok, info)
    else:
        row("pearld", "RPC", False, "pas de config [mining] — lance `diapason mine init`")

    click.echo("Portefeuille")
    if mining_cfg is not None:
        ok, info = check_wallet_address_format(mining_cfg.wallet_address)
        row("wallet", "Format d'adresse", ok, info)

    click.echo("Capacité du fournisseur")
    if mining_cfg is not None:
        cap = detect_for_engine_model(
            hw=hw, engine_id="vllm",
            model=mining_cfg.extra.get("model", DEFAULT_PEARL_MODEL),
            provider_id=mining_cfg.provider,
        )
        marker = "SUPPORTÉ" if cap.supported else f"NON SUPPORTÉ — {cap.reason}"
        click.echo(f"  vllm-pearl              {marker}")

    click.echo("Session")
    sidecar = Sidecar.read(SIDECAR_PATH)
    if sidecar is None:
        click.echo("  Sidecar                absent (pas en marche)")
    else:
        click.echo(f"  Sidecar                présent ({SIDECAR_PATH})")
        click.echo(f"  Conteneur              {sidecar.get('container_id', '?')}")
```

- [ ] **Étape 4 : lancer les tests pour vérifier qu'ils passent**

```bash
uv run pytest tests/mining/test_cli.py -v
```
Attendu : 2 PASS.

- [ ] **Étape 5 : committer**

```bash
git add src/diapason/cli/mine_cmd.py tests/mining/test_cli.py
git commit -m "feat(mining-cli): diapason mine doctor"
```

---

## Tâche 13 — `diapason mine init / start / stop`

**Fichiers :**
- Modifier : `src/diapason/cli/mine_cmd.py`
- Modifier : `tests/mining/test_cli.py`

- [ ] **Étape 1 : écrire les tests qui échouent**

À ajouter à la fin de `tests/mining/test_cli.py` :

```python
def test_mine_start_runs_provider_start(monkeypatch):
    from diapason.cli.mine_cmd import mine
    runner = CliRunner()
    fake_provider_class = MagicMock()
    fake_provider_class.return_value.start = MagicMock(return_value=None)
    with patch("diapason.cli.mine_cmd.MinerRegistry") as reg, \
         patch("diapason.cli.mine_cmd.load_config") as load, \
         patch("diapason.cli.mine_cmd.asyncio.run") as arun:
        from diapason.mining._stubs import MiningConfig, SoloTarget
        load.return_value = MagicMock(mining=MiningConfig(
            provider="vllm-pearl",
            wallet_address="prl1qaaa",
            submit_target=SoloTarget(pearld_rpc_url="http://localhost:44107"),
        ))
        reg.get.return_value = fake_provider_class
        result = runner.invoke(mine, ["start"])
    assert result.exit_code == 0
    arun.assert_called_once()


def test_mine_stop_calls_provider_stop():
    from diapason.cli.mine_cmd import mine
    runner = CliRunner()
    fake_provider_class = MagicMock()
    with patch("diapason.cli.mine_cmd.MinerRegistry") as reg, \
         patch("diapason.cli.mine_cmd.load_config") as load, \
         patch("diapason.cli.mine_cmd.asyncio.run") as arun:
        from diapason.mining._stubs import MiningConfig, SoloTarget
        load.return_value = MagicMock(mining=MiningConfig(
            provider="vllm-pearl",
            wallet_address="prl1qaaa",
            submit_target=SoloTarget(pearld_rpc_url="http://localhost:44107"),
        ))
        reg.get.return_value = fake_provider_class
        result = runner.invoke(mine, ["stop"])
    assert result.exit_code == 0


def test_mine_start_errors_when_no_mining_config():
    from diapason.cli.mine_cmd import mine
    runner = CliRunner()
    with patch("diapason.cli.mine_cmd.load_config") as load:
        load.return_value = MagicMock(mining=None)
        result = runner.invoke(mine, ["start"])
    assert result.exit_code != 0
    assert "init" in result.output.lower() or "[mining]" in result.output.lower()
```

- [ ] **Étape 2 : lancer les tests pour vérifier qu'ils échouent**

```bash
uv run pytest tests/mining/test_cli.py -v
```
Attendu : 3 nouveaux FAIL.

- [ ] **Étape 3 : écrire `init`, `start`, `stop`**

À ajouter à la fin de `mine_cmd.py` :

```python
import asyncio
from diapason.core.registry import MinerRegistry


@mine.command()
@click.option("--wallet", prompt="Adresse de portefeuille Pearl Taproot (prl1q...)")
@click.option("--pearld-url", default=DEFAULT_PEARLD_RPC_URL,
              prompt="URL RPC de pearld")
@click.option("--pearld-user", default="rpcuser", prompt="Utilisateur RPC de pearld")
@click.option("--pearld-password-env", default="PEARLD_RPC_PASSWORD",
              prompt="Variable d'environnement portant le mot de passe pearld")
@click.option("--model", default=DEFAULT_PEARL_MODEL)
@click.option("--image", default=PEARL_IMAGE_TAG)
def init(
    wallet: str,
    pearld_url: str,
    pearld_user: str,
    pearld_password_env: str,
    model: str,
    image: str,
) -> None:
    """Installation interactive. Valide la capacité, écrit la config [mining], tire ou construit l'image."""
    # Contrôles préalables
    hw = _detect_hardware()
    cap = detect_for_engine_model(
        hw=hw, engine_id="vllm", model=model, provider_id="vllm-pearl",
    )
    if not cap.supported:
        raise click.ClickException(
            f"vllm-pearl n'est pas supporté sur cette machine : {cap.reason}\n"
            f"Lance `diapason mine doctor` pour le détail."
        )

    ok, info = check_docker_available()
    if not ok:
        raise click.ClickException(f"Docker indisponible : {info}")

    ok, info = check_disk_free(Path.home())
    if not ok:
        raise click.ClickException(f"Disque insuffisant : {info}")

    if pearld_password_env not in os.environ:
        click.echo(
            f"Attention : ${pearld_password_env} n'est pas posée dans ton environnement. "
            f"Pose-la avant `diapason mine start`.",
            err=True,
        )

    ok, info = check_wallet_address_format(wallet)
    if not ok:
        raise click.ClickException(f"Adresse de portefeuille invalide : {info}")

    # Écriture de la config (les sections existantes sont préservées ; [mining] est ajouté à la fin)
    config_path = Path.home() / ".diapason" / "config.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    new_section = f"""
[mining]
provider           = "vllm-pearl"
wallet_address     = "{wallet}"
submit_target      = "solo"
fee_bps            = 0
fee_payout_address = ""

[mining.extra]
docker_image_tag         = "{image}"
model                    = "{model}"
gateway_port             = 8337
gateway_metrics_port     = 8339
vllm_port                = 8000
gpu_memory_utilization   = 0.9
max_model_len            = 8192
pearld_rpc_url           = "{pearld_url}"
pearld_rpc_user          = "{pearld_user}"
pearld_rpc_password_env  = "{pearld_password_env}"
hf_token_env             = "HF_TOKEN"
"""
    if config_path.exists():
        existing = config_path.read_text()
        if "[mining]" in existing:
            click.echo("la section [mining] est déjà là ; on n'écrase pas. À modifier à la main si besoin.")
            return
        config_path.write_text(existing + new_section)
    else:
        config_path.write_text(new_section)

    # Tirage ou construction de l'image
    click.echo(f"Résolution de l'image {image}... (la construction peut prendre 30 à 60 min la première fois)")
    import docker
    from diapason.mining._docker import PearlDockerLauncher
    launcher = PearlDockerLauncher(client=docker.from_env())
    launcher.ensure_image(image)
    click.echo(f"Terminé. Lance `diapason mine start` pour commencer à miner.")


@mine.command()
def start() -> None:
    """Lance le conteneur de minage Pearl et écrit le sidecar d'exécution."""
    cfg = load_config().mining
    if cfg is None:
        raise click.ClickException("pas de section [mining] dans la config — lance `diapason mine init`")
    provider_cls = MinerRegistry.get(cfg.provider)
    provider = provider_cls()

    async def _run():
        await provider.start(cfg)
    asyncio.run(_run())
    click.echo(f"Minage démarré. Lance `diapason mine status` pour les statistiques en direct.")


@mine.command()
def stop() -> None:
    """Arrête le conteneur de minage Pearl et retire le sidecar."""
    cfg = load_config().mining
    if cfg is None:
        click.echo("pas de section [mining] — rien à arrêter")
        return
    provider_cls = MinerRegistry.get(cfg.provider)
    provider = provider_cls()

    async def _run():
        await provider.stop()
    asyncio.run(_run())
    click.echo("Minage arrêté.")
```

- [ ] **Étape 4 : lancer les tests pour vérifier qu'ils passent**

```bash
uv run pytest tests/mining/test_cli.py -v
```
Attendu : 5 PASS.

- [ ] **Étape 5 : committer**

```bash
git add src/diapason/cli/mine_cmd.py tests/mining/test_cli.py
git commit -m "feat(mining-cli): diapason mine init/start/stop"
```

---

## Tâche 14 — `diapason mine status / attach / logs`

**Fichiers :**
- Modifier : `src/diapason/cli/mine_cmd.py`
- Modifier : `tests/mining/test_cli.py`

- [ ] **Étape 1 : écrire les tests qui échouent**

À ajouter à la fin de `tests/mining/test_cli.py` :

```python
def test_mine_status_renders_stats(written_sidecar, monkeypatch):
    from diapason.cli.mine_cmd import mine
    runner = CliRunner()
    monkeypatch.setattr("diapason.cli.mine_cmd.SIDECAR_PATH", written_sidecar)
    sample = (
        "pearl_gateway_shares_submitted_total 100\n"
        "pearl_gateway_shares_accepted_total 99\n"
        "pearl_gateway_blocks_found_total 2\n"
    )
    with patch("diapason.mining.vllm_pearl.httpx.get") as get, \
         patch("diapason.cli.mine_cmd.MinerRegistry") as reg:
        get.return_value.status_code = 200
        get.return_value.text = sample
        from diapason.mining.vllm_pearl import VllmPearlProvider
        reg.get.return_value = lambda: VllmPearlProvider(docker_client=MagicMock())
        result = runner.invoke(mine, ["status"])
    assert result.exit_code == 0
    assert "100" in result.output


def test_mine_attach_writes_sidecar(tmp_path, monkeypatch):
    from diapason.cli.mine_cmd import mine
    runner = CliRunner()
    sidecar = tmp_path / "mining.json"
    monkeypatch.setattr("diapason.cli.mine_cmd.SIDECAR_PATH", sidecar)
    result = runner.invoke(mine, [
        "attach",
        "--vllm-endpoint", "http://127.0.0.1:8000/v1",
        "--gateway-url", "http://127.0.0.1:8337",
        "--gateway-metrics-url", "http://127.0.0.1:8339",
        "--model", "pearl-ai/Llama-3.3-70B-Instruct-pearl",
    ])
    assert result.exit_code == 0
    assert sidecar.exists()


def test_mine_logs_streams_container_output(monkeypatch):
    from diapason.cli.mine_cmd import mine
    runner = CliRunner()
    fake_launcher = MagicMock()
    fake_launcher.get_logs.return_value = "log line 1\nlog line 2\n"
    with patch("diapason.cli.mine_cmd.PearlDockerLauncher",
               return_value=fake_launcher):
        result = runner.invoke(mine, ["logs", "--tail", "100"])
    assert result.exit_code == 0
    assert "log line 1" in result.output
```

- [ ] **Étape 2 : lancer les tests pour vérifier qu'ils échouent**

```bash
uv run pytest tests/mining/test_cli.py -v
```
Attendu : 3 nouveaux FAIL.

- [ ] **Étape 3 : écrire `status`, `attach`, `logs`**

À ajouter à la fin de `mine_cmd.py` :

```python
import time
from diapason.mining._docker import PearlDockerLauncher


@mine.command()
def status() -> None:
    """Affiche les statistiques de minage en direct, lues sur la passerelle."""
    cfg = load_config().mining
    if cfg is None:
        raise click.ClickException("pas de section [mining] — lance `diapason mine init`")
    provider_cls = MinerRegistry.get(cfg.provider)
    provider = provider_cls()
    s = provider.stats()
    click.echo(f"fournisseur :       {s.provider_id}")
    click.echo(f"parts soumises :    {s.shares_submitted}")
    click.echo(f"parts acceptées :   {s.shares_accepted}")
    click.echo(f"blocs trouvés :     {s.blocks_found}")
    click.echo(f"taux de hachage :   {s.hashrate:.2f}")
    click.echo(f"marche (s) :        {s.uptime_seconds:.0f}")
    click.echo(f"dernière part à :   {s.last_share_at or '—'}")
    click.echo(f"dernière erreur :   {s.last_error or '—'}")
    click.echo(f"cible de paiement : {s.payout_target}")
    click.echo(f"frais dus :         {s.fees_owed}")


@mine.command()
@click.option("--vllm-endpoint", required=True)
@click.option("--gateway-url", required=True)
@click.option("--gateway-metrics-url", required=True)
@click.option("--model", default=DEFAULT_PEARL_MODEL)
@click.option("--container-id", default="external")
@click.option("--wallet", default="")
def attach(
    vllm_endpoint: str,
    gateway_url: str,
    gateway_metrics_url: str,
    model: str,
    container_id: str,
    wallet: str,
) -> None:
    """Mode manuel — écrit un sidecar qui pointe sur un conteneur Pearl que tu as lancé toi-même."""
    Sidecar.write(SIDECAR_PATH, {
        "provider": "vllm-pearl",
        "vllm_endpoint": vllm_endpoint,
        "model": model,
        "gateway_url": gateway_url,
        "gateway_metrics_url": gateway_metrics_url,
        "container_id": container_id,
        "wallet_address": wallet,
        "started_at": int(time.time()),
    })
    click.echo(f"Sidecar écrit dans {SIDECAR_PATH}")


@mine.command()
@click.option("-n", "--tail", "tail_n", default=200, type=int)
@click.option("-f", "--follow", is_flag=True, default=False,
              help="Suivre les journaux (pas supporté en v1 — équivaut à --tail).")
def logs(tail_n: int, follow: bool) -> None:
    """Affiche la fin des journaux du conteneur de minage Pearl."""
    if follow:
        click.echo("note : le suivi -f n'est pas écrit en v1 ; on affiche la fin et on sort", err=True)
    import docker
    launcher = PearlDockerLauncher(client=docker.from_env())
    # On se rattache au conteneur en marche, par son nom.
    try:
        container = docker.from_env().containers.get("diapason-pearl-miner")
        launcher._container = container
    except Exception as e:  # noqa: BLE001
        raise click.ClickException(f"aucun conteneur de minage en marche : {e}")
    click.echo(launcher.get_logs(tail=tail_n))
```

- [ ] **Étape 4 : lancer les tests pour vérifier qu'ils passent**

```bash
uv run pytest tests/mining/test_cli.py -v
```
Attendu : 8 PASS (cumulés).

- [ ] **Étape 5 : committer**

```bash
git add src/diapason/cli/mine_cmd.py tests/mining/test_cli.py
git commit -m "feat(mining-cli): diapason mine status/attach/logs"
```

---

## Tâche 15 — Enregistrer le groupe `mine` ; ajouter l'indice

**Fichiers :**
- Modifier : `src/diapason/cli/__init__.py`
- Modifier : `src/diapason/cli/hints.py`
- Test : `tests/cli/test_main.py` (ou là où l'enregistrement de la CLI est testé)
- Test : `tests/cli/test_hints.py` (existant)

- [ ] **Étape 1 : inspecter l'actuel `cli/__init__.py`**

```bash
sed -n '1,50p' src/diapason/cli/__init__.py
grep -n "add_command\|@main.command\|main.add_command" src/diapason/cli/__init__.py | head -20
```

Repère comment les autres commandes sont enregistrées.

- [ ] **Étape 2 : écrire le test qui échoue**

À ajouter dans `tests/cli/test_main.py` (à créer s'il n'existe pas) :

```python
def test_mine_subcommand_registered():
    from click.testing import CliRunner
    from diapason.cli import main
    runner = CliRunner()
    result = runner.invoke(main, ["mine", "--help"])
    assert result.exit_code == 0
    assert "doctor" in result.output
    assert "start" in result.output
    assert "stop" in result.output
```

- [ ] **Étape 3 : lancer le test pour vérifier qu'il échoue**

```bash
uv run pytest tests/cli/test_main.py::test_mine_subcommand_registered -v
```

- [ ] **Étape 4 : enregistrer le groupe**

À ajouter dans `cli/__init__.py`, près des autres appels `add_command` :

```python
from diapason.cli.mine_cmd import mine
main.add_command(mine)
```

- [ ] **Étape 5 : ajouter l'indice**

Dans `cli/hints.py`, ajoute une fonction (ou étends la logique d'indices existante) qui émet une ligne quand `[mining]` est configuré mais qu'aucun sidecar n'existe :

```python
def mining_not_running_hint(cfg, sidecar_present: bool) -> Optional[str]:
    if cfg is None or sidecar_present:
        return None
    return "minage configuré mais pas en marche — démarre-le avec `diapason mine start`"
```

Branche-la là où les indices sont affichés (lis d'abord les points d'intégration existants ; reprends le même motif).

- [ ] **Étape 6 : ajouter les tests de l'indice**

À ajouter dans `tests/cli/test_hints.py` :

```python
def test_mining_not_running_hint_when_configured_no_sidecar():
    from diapason.cli.hints import mining_not_running_hint
    cfg = object()  # n'importe quel objet vrai tenant lieu de MiningConfig
    msg = mining_not_running_hint(cfg, sidecar_present=False)
    assert msg is not None
    assert "diapason mine start" in msg


def test_mining_not_running_hint_silent_when_running():
    from diapason.cli.hints import mining_not_running_hint
    msg = mining_not_running_hint(object(), sidecar_present=True)
    assert msg is None


def test_mining_not_running_hint_silent_when_unconfigured():
    from diapason.cli.hints import mining_not_running_hint
    msg = mining_not_running_hint(None, sidecar_present=False)
    assert msg is None
```

- [ ] **Étape 7 : lancer les tests pour vérifier qu'ils passent**

```bash
uv run pytest tests/cli/test_main.py tests/cli/test_hints.py -v
```

- [ ] **Étape 8 : committer**

```bash
git add src/diapason/cli/__init__.py src/diapason/cli/hints.py tests/cli/test_main.py tests/cli/test_hints.py
git commit -m "feat(mining-cli): enregistre le groupe `mine` et ajoute l'indice « pas en marche »"
```

---

## Tâche 16 — Mises à jour de `pyproject.toml`

**Fichiers :**
- Modifier : `pyproject.toml`

- [ ] **Étape 1 : ajouter l'extra `mining-pearl`**

Dans `[project.optional-dependencies]` de `pyproject.toml`, à sa position alphabétique (après `media`, avant `openhands`) :

```toml
mining-pearl = ["docker>=7.0", "httpx>=0.27"]
```

- [ ] **Étape 2 : ajouter le marqueur pytest `docker`**

Dans `pyproject.toml`, sous `[tool.pytest.ini_options].markers`, à sa place alphabétique :

```toml
"docker: exige un démon Docker en marche (pas besoin de GPU)",
```

- [ ] **Étape 3 : vérifier que le verrou uv est à jour**

```bash
uv lock
```

Relis le diff de `uv.lock` pour repérer tout changement non voulu (seules les entrées `docker` et `httpx` doivent être nouvelles).

- [ ] **Étape 4 : vérifier que la commande de la CI passe toujours**

```bash
uv sync --extra dev
uv run pytest tests/ -m "not live and not cloud and not docker" -v
```

Attendu : ça passe (ou ça n'échoue que sur des tests étrangers à ce travail).

- [ ] **Étape 5 : committer**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: ajoute l'extra mining-pearl et le marqueur pytest docker"
```

---

## Tâche 17 — Documentation

**Fichiers :**
- Créer : `docs/user-guide/mining.md`
- Créer : `docs/development/mining.md`
- Modifier : `CLAUDE.md` (note : ignoré par git en local — ne l'écris que si ta copie locale l'attend)
- Modifier : `REVIEW.md`

- [ ] **Étape 1 : écrire `docs/user-guide/mining.md`**

```markdown
# Le minage Pearl

Diapason peut miner la chaîne [Pearl](https://github.com/pearl-research-labs/pearl),
une chaîne à preuve de travail utile, à travers ton inférence LLM locale. La v1
prend en charge les machines H100/H200 qui font tourner vLLM. Apple Silicon, AMD
et les autres moteurs d'inférence sont suivis à part — voir la
[spécification B](../design/2026-05-05-apple-silicon-pearl-mining-design.md).

## Ce qu'il te faut

| | |
|---|---|
| GPU | NVIDIA H100 ou H200 (sm_90a) avec ≥ 70 Go de VRAM |
| Système | Linux, avec `nvidia-container-toolkit` installé |
| Docker | 24+, runtime GPU configuré |
| Disque | ≥ 200 Go libres pour le modèle 70B, marge comprise |
| Réseau | Un nœud pearld joignable (par défaut `http://localhost:44107`) |
| Portefeuille | Une adresse Pearl Taproot (`prl1q...`), générée avec la CLI `oyster` de Pearl |

## Démarrage rapide

```bash
uv sync --extra mining-pearl
export PEARLD_RPC_PASSWORD=<ton-mot-de-passe-pearld>
export HF_TOKEN=<ton-jeton-hf>
uv run diapason mine init    # écrit la config [mining] et construit l'image Docker (30 à 60 min la première fois)
uv run diapason mine start
uv run diapason mine status
```

## Diagnostiquer un problème

`diapason mine doctor` affiche une ligne par contrôle, avec un ✓ ou un ✗ net et
sa raison. Lis de haut en bas — répare ce qui échoue avant de relancer
`mine start`.

## Ce que la v1 ne fait PAS

- Le minage en pool, ni aucun frais pour OJ — solo uniquement, tu gardes 100 %
- Apple Silicon, AMD, les NVIDIA sm_89 (RTX 4090), le CPU seul — bloqués par le
  protocole, tant que Pearl ne livre pas de noyaux hors CUDA / hors Hopper
- La génération de portefeuille dans OJ — apporte ton adresse

## Ce qui arrive

- v2 : le support des pools et un frais de 20 % pour OJ, en échange d'un pool
  partagé qui réduit la variance
- La voie Apple Silicon est suivie dans la
  [spécification B](../design/2026-05-05-apple-silicon-pearl-mining-design.md)
```

- [ ] **Étape 2 : écrire `docs/development/mining.md`**

```markdown
# Ajouter un fournisseur de minage

Le sous-système `diapason.mining` utilise le même motif de registre que
`engine/`, `agents/`, etc. Pour ajouter un fournisseur (pour Apple Silicon,
AMD, ou un moteur à venir), implémente l'ABC `MiningProvider` et enregistre-le
avec `@MinerRegistry.register("<key>")`.

## Les étapes

1. Crée `src/diapason/mining/<provider>.py`.
2. Hérite de `diapason.mining.MiningProvider`.
3. Implémente `detect()`, `start()`, `stop()`, `is_running()`, `stats()`.
4. Définis un `ensure_registered()` idempotent (obligatoire pour l'isolation des
   tests — voir le vidage autouse de `tests/conftest.py`).
5. Ajoute un import en douceur dans `mining/__init__.py` :
   ```python
   try:
       from diapason.mining import <provider>  # noqa: F401
       <provider>.ensure_registered()
   except ImportError:
       pass
   ```
6. Ajoute un extra de dépendance optionnelle dans `pyproject.toml` (`mining-pearl-<key>`).
7. Ajoute des tests dans `tests/mining/test_<provider>.py`, sur le modèle de
   `test_vllm_pearl.py`.

## Un exemple travaillé

La voie Apple Silicon est l'exemple de référence — voir la section 7 de la
[spécification B](../design/2026-05-05-apple-silicon-pearl-mining-design.md)
pour le gabarit complet d'un fournisseur.
```

- [ ] **Étape 3 : ajouter le paragraphe dans `CLAUDE.md` (si ta copie locale est faite pour être modifiée)**

Si ton `CLAUDE.md` local existe et qu'il est prévu pour être modifié, ajoute ce paragraphe sous la section Architecture qui liste les primitives :

```markdown
- `mining/` — l'ABC `MiningProvider` et le `MinerRegistry`. La seule implémentation de la v1 est `vllm_pearl.py` (l'orchestrateur du conteneur Docker de Pearl). Importé en douceur par le `try/except ImportError` de `mining/__init__.py`, selon le motif des dépendances optionnelles d'OJ. Les futurs fournisseurs (Apple Silicon, AMD, Ollama) se branchent par le registre, sans réécriture. Voir `docs/design/2026-05-05-vllm-pearl-mining-integration-design.md`.
```

> `CLAUDE.md` est peut-être dans le `.gitignore` de ce dépôt. Vérifie avant de l'ajouter à un commit.

- [ ] **Étape 4 : ajouter la puce dans `REVIEW.md`**

Dans `REVIEW.md`, sous « Registry pattern compliance » (ou la puce équivalente la plus proche, celle qui dit que les nouveaux composants doivent s'enregistrer), ajoute :

```markdown
- Les nouveaux fournisseurs de minage doivent s'enregistrer via `MinerRegistry` dans `src/diapason/core/registry.py` et exposer un `ensure_registered()` idempotent, selon la convention du vidage autouse des tests.
```

- [ ] **Étape 5 : lancer mkdocs en local pour vérifier le rendu**

```bash
uv sync --extra docs
uv run mkdocs build
```

Attendu : la construction réussit. Inspecte la sortie pour repérer les ressources manquantes et les liens cassés vers les nouvelles pages.

- [ ] **Étape 6 : committer**

```bash
git add docs/user-guide/mining.md docs/development/mining.md REVIEW.md
# n'ajoute CLAUDE.md que s'il n'est pas ignoré :
git check-ignore -q CLAUDE.md || git add CLAUDE.md
git commit -m "docs: guides utilisateur et développeur du minage ; puce dans REVIEW"
```

---

## Vérification finale

- [ ] **Étape 1 : toute la suite de tests**

```bash
uv run pytest tests/ -v --tb=short -m "not live and not cloud and not docker"
```
Attendu : PASS — tous les tests, aucune régression dans les autres paquets.

- [ ] **Étape 2 : lint et format**

```bash
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
```
Attendu : propre.

- [ ] **Étape 3 : couverture**

```bash
uv run pytest tests/mining/ --cov=diapason.mining --cov-report=term-missing
```
Attendu : ≥ 80 % de couverture sur le nouveau paquet `mining/`.

- [ ] **Étape 4 : passer `diapason mine doctor` au banc d'essai sur une machine de dev qui ne mine pas**

```bash
uv run diapason mine doctor
```
Attendu : le doctor tourne, les lignes matériel/Docker/Pearl affichent un ✗ honnête là où il le faut, code de sortie 0.

- [ ] **Étape 5 : ouvrir la PR de mise en œuvre**

```bash
gh pr create --title "feat(mining): intégration vllm-pearl (v1, spécification A)" --body "$(cat <<'EOF'
Met en œuvre la [spécification A](docs/design/2026-05-05-vllm-pearl-mining-integration-design.md). Minage solo uniquement, pas de pool, pas de frais. Les coutures v2 sont en place, selon la §8.5 de la spécification.

## Résumé
- Nouveau sous-système `diapason.mining`, avec l'ABC `MiningProvider` et le `MinerRegistry`
- Fournisseur `vllm-pearl` enveloppant le conteneur Docker de Pearl
- Sidecar d'exécution (`~/.diapason/runtime/mining.json`) pour le relais moteur ↔ minage
- Télémétrie : lectures à la demande en v1 ; `MiningTelemetryCollector` livré non branché pour la v1.x
- Nouvelle CLI : `diapason mine init|start|stop|status|doctor|attach|logs`
- Nouvel extra optionnel : `mining-pearl`
- Nouveau marqueur pytest : `docker`
- Docs : guide utilisateur, guide du contributeur, mise à jour de REVIEW.md

## Plan de test
- [x] `uv run pytest tests/ -m "not live and not cloud and not docker"`
- [x] `uv run ruff check src/ tests/`
- [x] `uv run ruff format --check src/ tests/`
- [x] `uv run mkdocs build`
- [ ] Banc d'essai manuel : `uv run diapason mine doctor` sur une machine de dev qui ne mine pas affiche une sortie honnête
- [ ] Banc d'essai manuel (verrou de livraison) : mine init → start → status → stop complet sur une vraie machine H100
EOF
)"
```

---

## Résumé d'auto-relecture

**Couverture de la spécification :** chaque section de la spécification A correspond à au moins une tâche ci-dessus :

| Section de la spécification | Tâches |
|---|---|
| §4 Architecture et découpage en modules | 1, 2 |
| §5 Schéma de config et rattachement du moteur | 3, 9 |
| §6 Surface CLI, cycle de vie | 12, 13, 14, 15 |
| §7 Intégration Docker de Pearl | 5, 6 |
| §8 Crochets de télémétrie et coutures v2 | 7, 10, 11 |
| §9 Gestion des pannes et stratégie de test | Toutes les tâches (TDD) ; 16 (marqueurs) |
| §10 Livrables de documentation | 17 |
| §11 Points ouverts | Soulevés en ligne, au moment de mise en œuvre qu'ils touchent (par exemple les notes aux tâches 7, 9 et 11) |

**Cohérence des types :** `MiningCapabilities`, `MiningConfig`, `MiningStats`, `SoloTarget`, `PoolTarget`, `Sidecar`, `MiningProvider`, `MinerRegistry`, `VllmPearlProvider` — noms et signatures cohérents d'une tâche à l'autre.

**Balayage des bouche-trous :** aucun `TBD`, aucun `TODO`, aucun « ajouter la gestion d'erreur qu'il faut », aucun type référencé sans être défini. Le seul TODO délibéré est la constante `PEARL_PINNED_REF = "main"` de la tâche 2 — c'est une décision explicitement laissée au moment de la mise en œuvre, annoncée dans la docstring de `_constants.py` et au point ouvert n° 2 de la §11 de la spécification A. Le fichier de fixture Prometheus est un bouche-trou par choix de conception (la note de l'étape 1 de la tâche 7 explique la procédure de capture).
