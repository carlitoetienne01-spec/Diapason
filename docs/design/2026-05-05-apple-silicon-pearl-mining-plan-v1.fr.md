# Minage Pearl sur Apple Silicon v1 — plan de mise en œuvre

> **Pour les agents autonomes :** SOUS-COMPÉTENCE REQUISE : utilise `superpowers:subagent-driven-development` (recommandé) ou `superpowers:executing-plans` pour mettre ce plan en œuvre tâche par tâche. Les étapes utilisent la syntaxe à cases à cocher (`- [ ]`) pour le suivi.

**Objectif :** mettre en œuvre le fournisseur de minage `cpu-pearl` v1 — du minage CPU découplé pour Apple Silicon (et pour tout hôte sans CUDA où le mineur pur Rust de Pearl se construit), qui enveloppe le `pearl_mining.mine()` amont et lance le `pearl-gateway` de Pearl comme sous-processus.

**Architecture :** un nouveau fournisseur `CpuPearlProvider` dans `src/diapason/mining/cpu_pearl.py`, enregistré sous `"cpu-pearl"` via `MinerRegistry`. Le `start()` du fournisseur lance deux sous-processus : (1) le service Python `pearl-gateway` de Pearl (qui parle au `pearld` de l'utilisateur), et (2) une petite boucle de minage Python qui interroge la passerelle avec `getMiningInfo`, appelle `pearl_mining.mine()` et soumet via `submitPlainProof`. Réutilise l'ABC `MiningProvider` de la spec A, `MinerRegistry`, le fichier d'accompagnement (sidecar) `~/.diapason/runtime/mining.json`, l'adaptateur de télémétrie et la surface CLI (`diapason mine init|start|stop|status|doctor`) — tout cela inchangé.

**Pile technique :** Python 3.10+, `py-pearl-mining` (Rust+PyO3), `miner-base` (PyTorch), `pearl-gateway` (Python+JSON-RPC), `subprocess.Popen`, pytest avec `unittest.mock`, ruff. S'appuie sur le dépôt Pearl (`pearl-research-labs/pearl`) à un commit/tag figé, stocké dans `mining/_constants.py`.

**Prérequis ferme :** le plan de la spec A (`docs/design/2026-05-05-vllm-pearl-mining-integration-plan.md`) **doit être exécuté d'abord**. La v1 réutilise l'ABC `MiningProvider` de la spec A, son registre, la forme de son sidecar, son adaptateur de télémétrie, sa dataclass de configuration de minage et sa surface CLI. Si la spec A n'est pas fusionnée, arrête-toi ici et exécute-la d'abord ; ne redouble pas cette infrastructure dans ce plan.

---

## Structure des fichiers (nouveaux fichiers seulement — les fichiers de la spec A ne bougent pas)

```
src/diapason/mining/
    cpu_pearl.py             # CpuPearlProvider — implémente l'ABC MiningProvider pour le CPU
    _pearl_subprocess.py     # PearlSubprocessLauncher — gère les sous-processus passerelle + boucle de minage
    _install.py              # Aides : détecter les paquets amont, repli par construction depuis la référence figée
    _miner_loop_main.py      # Point d'entrée du sous-processus : interroger la passerelle, appeler pearl_mining.mine, soumettre

tests/mining/
    test_cpu_pearl.py        # Tests unitaires de CpuPearlProvider (détection de capacité, cycle de vie)
    test_pearl_subprocess.py # Tests unitaires du lanceur de sous-processus (Popen simulé)
    test_install.py          # Tests de la détection d'installation / de l'aide à la construction
    test_miner_loop.py       # Tests unitaires de la boucle de minage (socket de passerelle simulée)
    fixtures/
        gateway_mining_info.json    # Réponse RPC getMiningInfo capturée
        gateway_submit_ok.json      # Réponse OK de submitPlainProof capturée
        gateway_submit_rejected.json # Rejet de submitPlainProof capturé

docs/user-guide/
    mining-apple-silicon.md  # Guide destiné à l'utilisateur

# Fichiers modifiés
pyproject.toml               # Ajoute l'extra `mining-pearl-cpu`
src/diapason/mining/__init__.py  # Import souple de cpu_pearl
src/diapason/mining/_constants.py  # Ajoute PEARL_PINNED_REF et les constantes annexes
```

---

## Tâche 1 : amorçage — référence figée et constantes

**Fichiers :**
- Modifier : `src/diapason/mining/_constants.py:1-N` (créé dans la spec A)

Cette tâche ajoute le figement de la version de Pearl et les constantes propres au CPU auxquelles le reste du fournisseur se réfère. La spec A a déjà créé `_constants.py` avec `PEARL_PINNED_REF` et `PEARL_REPO` ; réutilise-les. On n'ajoute que les nouvelles valeurs propres à `cpu-pearl`.

- [ ] **Étape 1 : lire le `_constants.py` de la spec A pour en connaître la forme**

Lance : `cat src/diapason/mining/_constants.py`

Attendu : le fichier contient `PEARL_REPO`, `PEARL_PINNED_REF`, `PEARL_IMAGE_TAG`. S'ils manquent, **arrête-toi et exécute d'abord la spec A.**

- [ ] **Étape 2 : ajouter les constantes propres au CPU**

Ajoute à la fin de `src/diapason/mining/_constants.py` :

```python
# ── fournisseur cpu-pearl (v1, Apple Silicon et autres hôtes sans CUDA) ───────

# Formes de matrices par défaut pour la boucle de minage. Ce sont les valeurs
# qu'emploie le test_python_api.py amont de Pearl — connues pour produire une
# preuve valide par appel, à la difficulté de test. La vraie difficulté est
# fixée bloc par bloc par le réseau et nous n'y pouvons rien ; le seul bouton
# que nous exposons est la forme du matmul, qui détermine la taille de
# l'espace de recherche par appel à `mine()`.
CPU_PEARL_DEFAULT_M = 256
CPU_PEARL_DEFAULT_N = 128
CPU_PEARL_DEFAULT_K = 1024
CPU_PEARL_DEFAULT_RANK = 32

# Listes de motifs recopiées mot pour mot depuis les tests amont de Pearl.
CPU_PEARL_DEFAULT_ROWS_PATTERN = [0, 8, 64, 72]
CPU_PEARL_DEFAULT_COLS_PATTERN = [0, 1, 8, 9, 32, 33, 40, 41]

# Chemin du clone local qu'emploie le repli de _install.py. Créé seulement
# quand les wheels Pearl ne sont pas encore sur PyPI.
CPU_PEARL_LOCAL_CLONE_DIR = "~/.diapason/cache/pearl"

# Noms des paquets Python Pearl dont nous dépendons, dans l'ordre
# d'installation. Ce sont les paquets que nous installons depuis des chemins
# locaux (ou depuis PyPI une fois publiés).
PEARL_CPU_PACKAGES = (
    "py-pearl-mining",
    "miner-utils",
    "pearl-gateway",
    "miner-base",
)
```

- [ ] **Étape 3 : lancer le lint**

Lance : `uv run ruff check src/diapason/mining/_constants.py`
Attendu : aucune erreur.

- [ ] **Étape 4 : committer**

```bash
git add src/diapason/mining/_constants.py
git commit -m "feat(mining): constantes cpu-pearl (spec B v1, tâche 1)"
```

---

## Tâche 2 : ajouter l'extra optionnel `mining-pearl-cpu`

**Fichiers :**
- Modifier : `pyproject.toml`

- [ ] **Étape 1 : repérer l'extra `mining-pearl` existant**

Lance : `grep -n "mining-pearl" pyproject.toml`
Attendu : au moins une correspondance pour `mining-pearl = [...]`, venue de la spec A.

- [ ] **Étape 2 : ajouter l'extra `mining-pearl-cpu`**

Ajoute sous `[project.optional-dependencies]` :

```toml
mining-pearl-cpu = [
    # Le mineur pur Rust de Pearl, exposé à Python. Aujourd'hui : installation
    # depuis un chemin local ou une URL git. Quand Pearl publiera sur PyPI,
    # ceci deviendra une simple version épinglée (voir
    # CPU_PEARL_LOCAL_CLONE_DIR dans _constants.py).
    "py-pearl-mining ; sys_platform == 'darwin' or sys_platform == 'linux'",
    # Référence PyTorch de NoisyGEMM — sert seulement à valider la parité, pas
    # nécessaire à l'exécution, mais l'installation vérifie que torch se
    # construit correctement.
    "miner-base ; sys_platform == 'darwin' or sys_platform == 'linux'",
    # Serveur JSON-RPC qui parle à pearld et sert d'intermédiaire pour les
    # parts du mineur.
    "pearl-gateway ; sys_platform == 'darwin' or sys_platform == 'linux'",
]
```

Les marqueurs `sys_platform` écartent Windows pour l'instant ; la v1 ne prétend pas prendre Windows en charge, et nous ne voulons pas livrer par accident une installation cassée à quelqu'un sous Windows.

- [ ] **Étape 3 : lancer le lint et la vérification de résolution**

Lance :
```bash
uv run ruff check pyproject.toml || true
uv lock --check 2>&1 | tail -5
```

Attendu : ruff n'a rien à dire sur pyproject.toml. `uv lock --check` peut échouer parce que les vrais paquets ne sont pas encore installés — c'est normal. Note le mode d'échec pour la tâche 4.

- [ ] **Étape 4 : committer**

```bash
git add pyproject.toml
git commit -m "feat(mining): extra optionnel mining-pearl-cpu (spec B v1, tâche 2)"
```

---

## Tâche 3 : aide à la détection de l'installation (`_install.py`)

**Fichiers :**
- Créer : `src/diapason/mining/_install.py`
- Tester : `tests/mining/test_install.py`

`_install.py` répond à une seule question : les paquets Python Pearl sont-ils installés dans l'environnement courant ? Utilisé par `cpu_pearl.detect()` et par `mine doctor`. Expose aussi une chaîne d'indication qui dit à l'utilisateur comment installer, le cas échéant.

- [ ] **Étape 1 : écrire le test qui échoue**

Crée `tests/mining/test_install.py` :

```python
"""Tests de diapason.mining._install."""
from __future__ import annotations

import sys
from unittest.mock import patch

import pytest


def test_pearl_packages_available_returns_false_when_pearl_mining_missing():
    from diapason.mining import _install

    fake_modules = dict(sys.modules)
    fake_modules.pop("pearl_mining", None)
    fake_modules.pop("pearl_gateway", None)
    with patch.dict(sys.modules, fake_modules, clear=True):
        assert _install.pearl_packages_available() is False


def test_pearl_packages_available_returns_true_when_all_present():
    """Quand les trois sont importables, renvoie True."""
    from diapason.mining import _install

    # Installe trois faux modules pour que importlib.util.find_spec renvoie
    # une valeur vraie.
    import types
    fakes = {
        name: types.ModuleType(name)
        for name in ("pearl_mining", "pearl_gateway", "miner_base")
    }
    with patch.dict(sys.modules, fakes):
        assert _install.pearl_packages_available() is True


def test_install_hint_is_actionable():
    """L'indication doit nommer l'extra et le chemin de construction depuis la référence figée."""
    from diapason.mining._install import install_hint

    h = install_hint()
    assert "mining-pearl-cpu" in h
    assert "uv sync" in h or "pip install" in h
```

- [ ] **Étape 2 : lancer le test pour vérifier qu'il échoue**

Lance : `uv run pytest tests/mining/test_install.py -v`
Attendu : ÉCHEC — `ImportError: cannot import name '_install' from 'diapason.mining'`

- [ ] **Étape 3 : écrire `_install.py`**

Crée `src/diapason/mining/_install.py` :

```python
"""Détection et indications d'installation des paquets Python Pearl amont.

Le fournisseur cpu-pearl dépend de trois paquets amont : ``pearl_mining``,
``pearl_gateway`` et ``miner_base``. Ils ne sont pas sur PyPI en mai 2026 ; le
plan de mise en œuvre prévoit un repli par construction depuis la référence
figée. Ce module est la source unique de vérité pour savoir si
l'environnement de l'utilisateur est prêt.
"""
from __future__ import annotations

import importlib.util


def _module_available(name: str) -> bool:
    """True si ``import name`` réussirait dans l'environnement courant."""
    return importlib.util.find_spec(name) is not None


def pearl_packages_available() -> bool:
    """Les trois paquets Python Pearl sont importables.

    Renvoie False si l'un d'eux manque. Emploie ``install_hint()`` pour montrer
    l'étape suivante à l'utilisateur.
    """
    return all(
        _module_available(m)
        for m in ("pearl_mining", "pearl_gateway", "miner_base")
    )


def install_hint() -> str:
    """Instruction lisible pour installer les paquets Pearl.

    Aujourd'hui (rien n'est publié sur PyPI) nous pointons vers l'extra
    optionnel. Quand Pearl publiera des wheels, le message restera juste,
    puisque l'extra marchera toujours.
    """
    return (
        "installe avec `uv sync --extra mining-pearl-cpu`. "
        "Si les wheels Pearl ne sont pas encore sur PyPI, voir "
        "tools/pearl-reference-oracle/README.md pour la construction depuis "
        "la référence figée."
    )
```

- [ ] **Étape 4 : lancer le test pour vérifier qu'il passe**

Lance : `uv run pytest tests/mining/test_install.py -v`
Attendu : SUCCÈS — les trois tests au vert.

- [ ] **Étape 5 : committer**

```bash
git add src/diapason/mining/_install.py tests/mining/test_install.py
git commit -m "feat(mining): détection des paquets Pearl disponibles (spec B v1, tâche 3)"
```

---

## Tâche 4 : repli par construction depuis la référence figée dans `_install.py`

**Fichiers :**
- Modifier : `src/diapason/mining/_install.py`
- Modifier : `tests/mining/test_install.py`

Tant que Pearl ne publie pas sur PyPI, il faut construire `py-pearl-mining` depuis les sources. Cette tâche ajoute une aide qui le fait au premier `mine init`. Simulée dans les tests ; réellement appelée seulement dans un vrai terminal.

- [ ] **Étape 1 : écrire les tests qui échouent**

Ajoute à la fin de `tests/mining/test_install.py` :

```python
import subprocess


def test_build_from_pin_clones_when_missing(tmp_path, monkeypatch):
    """Si le dossier de cache local est vide, build_from_pin clone d'abord."""
    from diapason.mining import _install

    cache_dir = tmp_path / "pearl"
    monkeypatch.setattr(_install, "_resolve_clone_dir", lambda: cache_dir)
    calls = []
    monkeypatch.setattr(
        subprocess,
        "check_call",
        lambda args, **kw: calls.append(list(args)),
    )

    _install.build_from_pin(pinned_ref="abc123")

    # Le premier appel doit être `git clone` ; le ou les suivants,
    # l'installation maturin/uv.
    assert calls[0][:2] == ["git", "clone"]
    assert "abc123" in " ".join(calls[1]) or "abc123" in " ".join(calls[0])


def test_build_from_pin_skips_clone_when_present(tmp_path, monkeypatch):
    """Si le cache contient déjà le dossier .git, on saute le clone."""
    from diapason.mining import _install

    cache_dir = tmp_path / "pearl"
    (cache_dir / ".git").mkdir(parents=True)
    monkeypatch.setattr(_install, "_resolve_clone_dir", lambda: cache_dir)
    calls = []
    monkeypatch.setattr(
        subprocess,
        "check_call",
        lambda args, **kw: calls.append(list(args)),
    )

    _install.build_from_pin(pinned_ref="abc123")

    # Pas de git clone, mais un checkout puis la construction.
    assert not any(c[:2] == ["git", "clone"] for c in calls)
    assert any(c[:2] == ["git", "checkout"] for c in calls)
```

- [ ] **Étape 2 : lancer les tests pour vérifier qu'ils échouent**

Lance : `uv run pytest tests/mining/test_install.py -v`
Attendu : ÉCHEC — `AttributeError: module 'diapason.mining._install' has no attribute 'build_from_pin'`

- [ ] **Étape 3 : implémenter `build_from_pin`**

Ajoute à la fin de `src/diapason/mining/_install.py` :

```python
import os
import subprocess
from pathlib import Path

from ._constants import (
    CPU_PEARL_LOCAL_CLONE_DIR,
    PEARL_CPU_PACKAGES,
    PEARL_PINNED_REF,
    PEARL_REPO,
)


def _resolve_clone_dir() -> Path:
    """Renvoie le dossier où vit le clone de Pearl. À remplacer dans les tests."""
    return Path(os.path.expanduser(CPU_PEARL_LOCAL_CLONE_DIR))


def build_from_pin(pinned_ref: str = PEARL_PINNED_REF) -> Path:
    """Clone Pearl à ``pinned_ref`` et installe les paquets Python Pearl.

    Idempotent : si le clone existe, on fait fetch + checkout au lieu de
    recloner. Renvoie le dossier de clone résolu.
    """
    clone_dir = _resolve_clone_dir()
    if not (clone_dir / ".git").is_dir():
        clone_dir.mkdir(parents=True, exist_ok=True)
        subprocess.check_call(["git", "clone", PEARL_REPO, str(clone_dir)])
    else:
        subprocess.check_call(["git", "fetch", "--all"], cwd=clone_dir)
    subprocess.check_call(["git", "checkout", pinned_ref], cwd=clone_dir)

    # Construit py-pearl-mining (extension Rust) avec maturin
    py_pearl_mining_dir = clone_dir / "py-pearl-mining"
    subprocess.check_call(
        ["maturin", "build", "--release", "--interpreter", "python"],
        cwd=py_pearl_mining_dir,
    )

    # Retrouve la wheel produite par maturin et l'installe, avec les paquets
    # purement Python depuis leurs dossiers source.
    wheels_dir = py_pearl_mining_dir / "target" / "wheels"
    wheels = sorted(wheels_dir.glob("py_pearl_mining-*.whl"))
    if not wheels:
        raise RuntimeError(f"maturin n'a produit aucune wheel dans {wheels_dir}")
    wheel_path = wheels[-1]

    # Installe dans l'ordre des dépendances. Le `--no-deps` empêche uv de
    # re-résoudre les paquets frères de l'espace de travail ; on les installe
    # un par un.
    subprocess.check_call(["uv", "pip", "install", "--no-deps", str(wheel_path)])
    for pkg_name in ("miner-utils", "pearl-gateway", "miner-base"):
        pkg_dir = clone_dir / "miner" / pkg_name
        if pkg_dir.is_dir():
            subprocess.check_call(
                ["uv", "pip", "install", "--no-deps", str(pkg_dir)]
            )

    return clone_dir
```

- [ ] **Étape 4 : lancer les tests pour vérifier qu'ils passent**

Lance : `uv run pytest tests/mining/test_install.py -v`
Attendu : SUCCÈS — les cinq tests au vert.

- [ ] **Étape 5 : lint**

Lance : `uv run ruff check src/diapason/mining/_install.py tests/mining/test_install.py`
Attendu : aucune erreur.

- [ ] **Étape 6 : committer**

```bash
git add src/diapason/mining/_install.py tests/mining/test_install.py
git commit -m "feat(mining): repli de construction des wheels Pearl depuis la référence figée (spec B v1, tâche 4)"
```

---

## Tâche 5 : `_miner_loop_main.py` — le point d'entrée du sous-processus de minage CPU

**Fichiers :**
- Créer : `src/diapason/mining/_miner_loop_main.py`
- Tester : `tests/mining/test_miner_loop.py`

C'est la tâche *consistante*. Le sous-processus de la boucle de minage se connecte à `pearl-gateway` en JSON-RPC sur TCP, interroge `getMiningInfo`, appelle `pearl_mining.mine()` et soumet via `submitPlainProof`. Un seul fichier, aucune hiérarchie de classes — c'est juste une boucle d'événements.

- [ ] **Étape 1 : écrire le test qui échoue**

Crée `tests/mining/test_miner_loop.py` :

```python
"""Tests de diapason.mining._miner_loop_main."""
from __future__ import annotations

import asyncio
import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def fake_mining_info_response():
    """Réponse getMiningInfo simulée — en-tête incomplet en base64 + cible."""
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "incomplete_header_bytes": base64.b64encode(b"\x00" * 76).decode(),
            "target": 0x1D2FFFFF,
        },
    }


def test_decode_mining_info_returns_header_and_target(fake_mining_info_response):
    from diapason.mining._miner_loop_main import _decode_mining_info

    header_bytes, target = _decode_mining_info(fake_mining_info_response["result"])
    assert isinstance(header_bytes, (bytes, bytearray))
    assert len(header_bytes) == 76
    assert target == 0x1D2FFFFF


def test_encode_plain_proof_round_trips():
    """On encode une PlainProof en base64 et les octets ne sont pas vides."""
    from diapason.mining._miner_loop_main import _encode_plain_proof

    fake_proof = MagicMock()
    fake_proof.serialize.return_value = b"PROOF_BYTES_DUMMY"
    encoded = _encode_plain_proof(fake_proof)
    assert encoded == base64.b64encode(b"PROOF_BYTES_DUMMY").decode()


def test_jsonrpc_envelope_shape():
    """L'enveloppe JSON-RPC est conforme au JSON_RPC_SCHEMA de la passerelle."""
    from diapason.mining._miner_loop_main import _make_request

    req = _make_request("getMiningInfo", {}, request_id=42)
    assert req["jsonrpc"] == "2.0"
    assert req["method"] == "getMiningInfo"
    assert req["id"] == 42
    assert req["params"] == {}
```

- [ ] **Étape 2 : lancer les tests pour vérifier qu'ils échouent**

Lance : `uv run pytest tests/mining/test_miner_loop.py -v`
Attendu : ÉCHEC — le module n'existe pas.

- [ ] **Étape 3 : implémenter les fonctions d'aide**

Crée `src/diapason/mining/_miner_loop_main.py` :

```python
"""Point d'entrée du sous-processus de la boucle de minage CPU.

Se lance avec :
    python -m diapason.mining._miner_loop_main \
        --gateway-host 127.0.0.1 --gateway-port 8337 \
        --m 256 --n 128 --k 1024 --rank 32

Se connecte à pearl-gateway, réclame du travail, lance pearl_mining.mine() et
renvoie les preuves. Prévu pour être tué par SIGTERM depuis le fournisseur
parent ; pas de poignée de main d'arrêt — la passerelle de Pearl encaisse
proprement la déconnexion d'un client.

Ce module EST le sous-processus ; le processus OJ parent ne l'importe jamais
directement (il le lance par ``python -m``). Cela garde le graphe d'import du
parent libre de pearl_mining, qui est une dépendance optionnelle.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import sys
from typing import Any

logger = logging.getLogger("diapason.mining.miner_loop")


def _make_request(method: str, params: dict[str, Any], request_id: int) -> dict[str, Any]:
    """Construit une enveloppe de requête JSON-RPC 2.0 au schéma de la passerelle."""
    return {"jsonrpc": "2.0", "method": method, "params": params, "id": request_id}


def _decode_mining_info(result: dict[str, Any]) -> tuple[bytes, int]:
    """Décode le résultat de getMiningInfo en (incomplete_header_bytes, target)."""
    header_b64 = result["incomplete_header_bytes"]
    target = int(result["target"])
    return base64.b64decode(header_b64), target


def _encode_plain_proof(plain_proof: Any) -> str:
    """Sérialise une PlainProof en base64 pour submitPlainProof."""
    return base64.b64encode(plain_proof.serialize()).decode()


async def _read_response(reader: asyncio.StreamReader) -> dict[str, Any]:
    """Lit une ligne de réponse JSON-RPC sur la socket de la passerelle."""
    line = await reader.readline()
    if not line:
        raise ConnectionError("la passerelle a fermé la connexion")
    return json.loads(line)


async def _send_request(writer: asyncio.StreamWriter, request: dict[str, Any]) -> None:
    """Écrit une requête JSON-RPC suivie d'un saut de ligne."""
    writer.write(json.dumps(request).encode() + b"\n")
    await writer.drain()


async def _mine_one_round(
    pearl_mining_module: Any,
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    *,
    request_id: int,
    m: int,
    n: int,
    k: int,
    rank: int,
) -> bool:
    """Prend du travail, mine, soumet. True si la preuve est acceptée, False sinon."""
    # 1. Réclame du travail à la passerelle
    await _send_request(writer, _make_request("getMiningInfo", {}, request_id))
    info_response = await _read_response(reader)
    if "error" in info_response:
        logger.warning("erreur getMiningInfo : %s", info_response["error"])
        return False
    header_bytes, target = _decode_mining_info(info_response["result"])

    # 2. Reconvertit header_bytes en IncompleteBlockHeader et lance mine().
    #    L'IncompleteBlockHeader de Pearl expose from_bytes() dans
    #    py-pearl-mining ; si le nom de l'API diffère, corrige-le au premier
    #    test d'intégration.
    header = pearl_mining_module.IncompleteBlockHeader.from_bytes(header_bytes)
    mining_config = _build_mining_config(pearl_mining_module, k=k, rank=rank)

    plain_proof = pearl_mining_module.mine(
        m, n, k, header, mining_config, signal_range=None, wrong_jackpot_hash=False
    )

    # 3. Soumet la preuve
    submit_params = {
        "plain_proof": _encode_plain_proof(plain_proof),
        "mining_job": {
            "incomplete_header_bytes": base64.b64encode(header_bytes).decode(),
            "target": target,
        },
    }
    await _send_request(writer, _make_request("submitPlainProof", submit_params, request_id + 1))
    submit_response = await _read_response(reader)
    if "error" in submit_response:
        logger.warning("submitPlainProof rejeté : %s", submit_response["error"])
        return False
    return True


def _build_mining_config(pearl_mining_module: Any, *, k: int, rank: int):
    """Construit la MiningConfiguration amont avec les motifs par défaut."""
    from ._constants import (
        CPU_PEARL_DEFAULT_COLS_PATTERN,
        CPU_PEARL_DEFAULT_ROWS_PATTERN,
    )

    return pearl_mining_module.MiningConfiguration(
        common_dim=k,
        rank=rank,
        mma_type=pearl_mining_module.MMAType.Int7xInt7ToInt32,
        rows_pattern=pearl_mining_module.PeriodicPattern.from_list(
            CPU_PEARL_DEFAULT_ROWS_PATTERN
        ),
        cols_pattern=pearl_mining_module.PeriodicPattern.from_list(
            CPU_PEARL_DEFAULT_COLS_PATTERN
        ),
        reserved=pearl_mining_module.MiningConfiguration.RESERVED,
    )


async def _main_loop(args: argparse.Namespace) -> None:
    import pearl_mining

    reader, writer = await asyncio.open_connection(args.gateway_host, args.gateway_port)
    request_id = 0
    try:
        while True:
            request_id += 2
            try:
                accepted = await _mine_one_round(
                    pearl_mining,
                    reader,
                    writer,
                    request_id=request_id,
                    m=args.m,
                    n=args.n,
                    k=args.k,
                    rank=args.rank,
                )
            except Exception:  # noqa: BLE001 — journalise et réessaie
                logger.exception("tour de minage échoué ; nouvelle tentative après pause")
                await asyncio.sleep(1.0)
                continue
            if accepted:
                logger.info("part acceptée")
    finally:
        writer.close()
        await writer.wait_closed()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--gateway-host", default="127.0.0.1")
    p.add_argument("--gateway-port", type=int, default=8337)
    p.add_argument("--m", type=int, default=256)
    p.add_argument("--n", type=int, default=128)
    p.add_argument("--k", type=int, default=1024)
    p.add_argument("--rank", type=int, default=32)
    return p.parse_args(argv)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args()
    try:
        asyncio.run(_main_loop(args))
    except KeyboardInterrupt:
        sys.exit(0)
```

- [ ] **Étape 4 : lancer les tests pour vérifier qu'ils passent**

Lance : `uv run pytest tests/mining/test_miner_loop.py -v`
Attendu : SUCCÈS — les trois tests au vert.

- [ ] **Étape 5 : lint**

Lance : `uv run ruff check src/diapason/mining/_miner_loop_main.py tests/mining/test_miner_loop.py`
Attendu : aucune erreur.

- [ ] **Étape 6 : committer**

```bash
git add src/diapason/mining/_miner_loop_main.py tests/mining/test_miner_loop.py
git commit -m "feat(mining): point d'entrée du sous-processus de minage CPU (spec B v1, tâche 5)"
```

---

## Tâche 6 : lanceur de sous-processus (`_pearl_subprocess.py`)

**Fichiers :**
- Créer : `src/diapason/mining/_pearl_subprocess.py`
- Tester : `tests/mining/test_pearl_subprocess.py`

Le lanceur gère les *deux* sous-processus — `pearl-gateway` et la boucle de minage — comme un tout. Cycle de vie : `start()`, `stop()`, `is_running()`. Pas de bricolage de fichiers PID ici ; on garde les objets `Popen` en mémoire tant que le processus OJ est vivant.

- [ ] **Étape 1 : écrire le test qui échoue**

Crée `tests/mining/test_pearl_subprocess.py` :

```python
"""Tests de diapason.mining._pearl_subprocess."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def fake_popen():
    p = MagicMock()
    p.poll.return_value = None  # tourne toujours
    p.pid = 12345
    return p


def test_launcher_start_spawns_two_processes(fake_popen, tmp_path):
    from diapason.mining._pearl_subprocess import PearlSubprocessLauncher

    with patch("subprocess.Popen", return_value=fake_popen) as mock_popen:
        launcher = PearlSubprocessLauncher(
            gateway_host="127.0.0.1",
            gateway_port=8337,
            metrics_port=8339,
            pearld_rpc_url="http://localhost:44107",
            pearld_rpc_user="rpcuser",
            pearld_rpc_password="testpw",
            wallet_address="prl1qtest",
            log_dir=tmp_path,
        )
        launcher.start(m=256, n=128, k=1024, rank=32)
        assert mock_popen.call_count == 2  # passerelle + boucle de minage


def test_launcher_stop_terminates_both(fake_popen, tmp_path):
    from diapason.mining._pearl_subprocess import PearlSubprocessLauncher

    with patch("subprocess.Popen", return_value=fake_popen):
        launcher = PearlSubprocessLauncher(
            gateway_host="127.0.0.1",
            gateway_port=8337,
            metrics_port=8339,
            pearld_rpc_url="http://localhost:44107",
            pearld_rpc_user="rpcuser",
            pearld_rpc_password="testpw",
            wallet_address="prl1qtest",
            log_dir=tmp_path,
        )
        launcher.start(m=256, n=128, k=1024, rank=32)
        launcher.stop()
        assert fake_popen.terminate.call_count >= 2


def test_launcher_is_running_false_when_either_exited(fake_popen, tmp_path):
    from diapason.mining._pearl_subprocess import PearlSubprocessLauncher

    fake_dead = MagicMock()
    fake_dead.poll.return_value = 1  # terminé
    fake_dead.pid = 12346

    with patch("subprocess.Popen", side_effect=[fake_popen, fake_dead]):
        launcher = PearlSubprocessLauncher(
            gateway_host="127.0.0.1",
            gateway_port=8337,
            metrics_port=8339,
            pearld_rpc_url="http://localhost:44107",
            pearld_rpc_user="rpcuser",
            pearld_rpc_password="testpw",
            wallet_address="prl1qtest",
            log_dir=tmp_path,
        )
        launcher.start(m=256, n=128, k=1024, rank=32)
        assert launcher.is_running() is False
```

- [ ] **Étape 2 : lancer les tests pour vérifier qu'ils échouent**

Lance : `uv run pytest tests/mining/test_pearl_subprocess.py -v`
Attendu : ÉCHEC — le module n'existe pas.

- [ ] **Étape 3 : implémenter `PearlSubprocessLauncher`**

Crée `src/diapason/mining/_pearl_subprocess.py` :

```python
"""Lanceur de sous-processus pour le fournisseur cpu-pearl.

Gère deux sous-processus :
- ``pearl-gateway`` (le service Python de Pearl), qui parle à pearld et sert
  d'intermédiaire pour les parts du mineur.
- ``diapason.mining._miner_loop_main`` (ce dépôt), qui interroge la passerelle
  et lance ``pearl_mining.mine()``.

Le cycle de vie est en mémoire : tant que cet objet vit, les deux
sous-processus vivent. Le fournisseur le détient ; le JSON du sidecar note les
PID pour la reprise après plantage.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

_GATEWAY_TERMINATE_GRACE_SECONDS = 5.0
_MINER_LOOP_TERMINATE_GRACE_SECONDS = 2.0


@dataclass(slots=True)
class _ProcessHandles:
    gateway: subprocess.Popen
    miner_loop: subprocess.Popen


class PearlSubprocessLauncher:
    def __init__(
        self,
        *,
        gateway_host: str,
        gateway_port: int,
        metrics_port: int,
        pearld_rpc_url: str,
        pearld_rpc_user: str,
        pearld_rpc_password: str,
        wallet_address: str,
        log_dir: Path,
    ) -> None:
        self.gateway_host = gateway_host
        self.gateway_port = gateway_port
        self.metrics_port = metrics_port
        self.pearld_rpc_url = pearld_rpc_url
        self.pearld_rpc_user = pearld_rpc_user
        self.pearld_rpc_password = pearld_rpc_password
        self.wallet_address = wallet_address
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._handles: _ProcessHandles | None = None

    def start(self, *, m: int, n: int, k: int, rank: int) -> None:
        env = self._build_gateway_env()

        # Lance la passerelle. ``pearl-gateway`` est le point d'entrée console
        # qu'expose le pyproject.toml du paquet pearl_gateway.
        gateway_log = (self.log_dir / "pearl-gateway.log").open("a", buffering=1)
        gateway = subprocess.Popen(
            ["pearl-gateway"],
            env=env,
            stdout=gateway_log,
            stderr=subprocess.STDOUT,
        )

        # Lance la boucle de minage, pointée vers la passerelle.
        miner_log = (self.log_dir / "cpu-pearl-miner.log").open("a", buffering=1)
        miner_loop = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "diapason.mining._miner_loop_main",
                "--gateway-host",
                self.gateway_host,
                "--gateway-port",
                str(self.gateway_port),
                "--m",
                str(m),
                "--n",
                str(n),
                "--k",
                str(k),
                "--rank",
                str(rank),
            ],
            stdout=miner_log,
            stderr=subprocess.STDOUT,
        )

        self._handles = _ProcessHandles(gateway=gateway, miner_loop=miner_loop)

    def stop(self) -> None:
        if self._handles is None:
            return
        # Arrête d'abord la boucle de minage, puis la passerelle.
        for proc, grace in (
            (self._handles.miner_loop, _MINER_LOOP_TERMINATE_GRACE_SECONDS),
            (self._handles.gateway, _GATEWAY_TERMINATE_GRACE_SECONDS),
        ):
            if proc.poll() is None:
                proc.terminate()
                deadline = time.monotonic() + grace
                while time.monotonic() < deadline and proc.poll() is None:
                    time.sleep(0.05)
                if proc.poll() is None:
                    proc.kill()
        self._handles = None

    def is_running(self) -> bool:
        if self._handles is None:
            return False
        return (
            self._handles.gateway.poll() is None
            and self._handles.miner_loop.poll() is None
        )

    def pids(self) -> tuple[int, int] | None:
        if self._handles is None:
            return None
        return (self._handles.gateway.pid, self._handles.miner_loop.pid)

    def _build_gateway_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env.update(
            {
                "PEARL_GATEWAY_HOST": self.gateway_host,
                "PEARL_GATEWAY_PORT": str(self.gateway_port),
                "PEARL_GATEWAY_METRICS_PORT": str(self.metrics_port),
                "PEARLD_RPC_URL": self.pearld_rpc_url,
                "PEARLD_RPC_USER": self.pearld_rpc_user,
                "PEARLD_RPC_PASSWORD": self.pearld_rpc_password,
                "PEARLD_MINING_ADDRESS": self.wallet_address,
                # dit à pearl-gateway d'employer TCP pour le RPC du mineur,
                # ce à quoi se connecte le sous-processus de la boucle.
                "MINER_RPC_TRANSPORT": "tcp",
            }
        )
        return env
```

> **Note sur les noms de variables d'environnement :** les noms exacts que lit pearl-gateway (`PEARL_GATEWAY_HOST`, `PEARL_GATEWAY_PORT`, etc.) viennent de `pearl/miner/pearl-gateway/src/pearl_gateway/config.py`. Vérifie-les à la première intégration : ouvre ce fichier et recopie les vrais noms `Field(env=...)` dans le dictionnaire `_build_gateway_env` ci-dessus. Si les noms diffèrent, c'est une correction d'une ligne par variable ; le cycle de vie autour n'est pas touché.

- [ ] **Étape 4 : lancer les tests pour vérifier qu'ils passent**

Lance : `uv run pytest tests/mining/test_pearl_subprocess.py -v`
Attendu : SUCCÈS — les trois tests au vert.

- [ ] **Étape 5 : lint**

Lance : `uv run ruff check src/diapason/mining/_pearl_subprocess.py tests/mining/test_pearl_subprocess.py`
Attendu : aucune erreur.

- [ ] **Étape 6 : committer**

```bash
git add src/diapason/mining/_pearl_subprocess.py tests/mining/test_pearl_subprocess.py
git commit -m "feat(mining): lanceur de sous-processus Pearl (spec B v1, tâche 6)"
```

---

## Tâche 7 : vérifier les noms de variables d'environnement contre la configuration de pearl-gateway

**Fichiers :**
- Modifier : `src/diapason/mining/_pearl_subprocess.py`

Tâche ponctuelle de recherche-et-correction, pour que les noms devinés à la tâche 6 correspondent à la vraie configuration de Pearl.

- [ ] **Étape 1 : localiser la configuration de pearl-gateway**

Lance : `find ~/.diapason/cache/pearl/miner/pearl-gateway -name config.py -path '*pearl_gateway*' 2>/dev/null || find / -name config.py -path '*pearl_gateway*' 2>/dev/null | head -3`

Attendu : `pearl-gateway/src/pearl_gateway/config.py` (le chemin dépend de l'endroit où Pearl a été cloné). Si le fichier n'est pas encore sur le disque, lance `python -m diapason.mining._install` (ajouté à la tâche 4), ou clone Pearl à la main d'abord.

- [ ] **Étape 2 : lire le fichier de configuration**

Cherche les annotations `Field(env=...)` sur `MinerSettings` / `PearlGatewayConfig`. Relève tous les noms de variables d'environnement qu'il accepte.

Lance : `grep -nE 'env\s*=' <chemin-vers-pearl-gateway/config.py> | head -20`

Sortie attendue : des lignes comme `Field(default="...", env="PEARL_GATEWAY_HOST")`, qui montrent les noms canoniques.

- [ ] **Étape 3 : remplacer les noms de variables dans `_build_gateway_env`**

Ouvre `src/diapason/mining/_pearl_subprocess.py` et remplace chaque nom deviné par le vrai. Garde la structure du dictionnaire ; seules les clés changent.

Si un nom attendu n'existe pas (par exemple si pearl-gateway n'a pas de `*_METRICS_PORT` séparé), supprime la ligne plutôt que de traîner une variable sans effet.

- [ ] **Étape 4 : relancer les tests**

Lance : `uv run pytest tests/mining/test_pearl_subprocess.py -v`
Attendu : SUCCÈS — les trois mêmes tests, aucune régression (le test simule Popen, donc un changement de nom de variable ne l'atteint pas).

- [ ] **Étape 5 : committer**

```bash
git add src/diapason/mining/_pearl_subprocess.py
git commit -m "fix(mining): aligner les noms de variables sur la configuration de pearl-gateway (spec B v1, tâche 7)"
```

---

## Tâche 8 : `CpuPearlProvider` — détection de capacité

**Fichiers :**
- Créer : `src/diapason/mining/cpu_pearl.py`
- Tester : `tests/mining/test_cpu_pearl.py`

Implémente la méthode de classe `MiningProvider.detect()` de l'ABC de la spec A. C'est la première chose que demandent `mine doctor` et `mine init`. Indépendant du moteur : renvoie « pris en charge » sur tout hôte darwin/linux où les paquets Pearl sont installés.

- [ ] **Étape 1 : écrire les tests qui échouent**

Crée `tests/mining/test_cpu_pearl.py` :

```python
"""Tests de diapason.mining.cpu_pearl.CpuPearlProvider."""
from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture
def darwin_apple_hw():
    """Un HardwareInfo décrivant un Mac Apple Silicon."""
    from diapason.mining._stubs import HardwareInfo, GpuInfo

    return HardwareInfo(
        platform="darwin",
        cpu_arch="arm64",
        gpu=GpuInfo(vendor="apple", model="M2 Max", vram_gb=96.0),
    )


@pytest.fixture
def linux_nvidia_hw():
    """Un HardwareInfo décrivant une machine H100."""
    from diapason.mining._stubs import HardwareInfo, GpuInfo

    return HardwareInfo(
        platform="linux",
        cpu_arch="x86_64",
        gpu=GpuInfo(vendor="nvidia", model="H100", vram_gb=80.0, compute_cap="9.0a"),
    )


@pytest.fixture
def windows_hw():
    """Un HardwareInfo décrivant un hôte Windows (non pris en charge en v1)."""
    from diapason.mining._stubs import HardwareInfo

    return HardwareInfo(platform="win32", cpu_arch="x86_64", gpu=None)


def test_detect_supported_on_apple_silicon(darwin_apple_hw):
    from diapason.mining.cpu_pearl import CpuPearlProvider

    with patch(
        "diapason.mining._install.pearl_packages_available", return_value=True
    ):
        cap = CpuPearlProvider.detect(darwin_apple_hw, engine_id="ollama", model="any")
        assert cap.supported is True
        assert cap.reason is None


def test_detect_supported_on_linux_too(linux_nvidia_hw):
    """La v1 de cpu-pearl est indépendante du moteur et peu exigeante sur la plateforme."""
    from diapason.mining.cpu_pearl import CpuPearlProvider

    with patch(
        "diapason.mining._install.pearl_packages_available", return_value=True
    ):
        cap = CpuPearlProvider.detect(
            linux_nvidia_hw, engine_id="anything", model="any"
        )
        assert cap.supported is True


def test_detect_unsupported_on_windows(windows_hw):
    from diapason.mining.cpu_pearl import CpuPearlProvider

    with patch(
        "diapason.mining._install.pearl_packages_available", return_value=True
    ):
        cap = CpuPearlProvider.detect(windows_hw, engine_id="any", model="any")
        assert cap.supported is False
        assert "win32" in cap.reason.lower() or "windows" in cap.reason.lower()


def test_detect_unsupported_when_pearl_not_installed(darwin_apple_hw):
    from diapason.mining.cpu_pearl import CpuPearlProvider

    with patch(
        "diapason.mining._install.pearl_packages_available", return_value=False
    ):
        cap = CpuPearlProvider.detect(darwin_apple_hw, engine_id="any", model="any")
        assert cap.supported is False
        assert "mining-pearl-cpu" in cap.reason
```

- [ ] **Étape 2 : lancer les tests pour vérifier qu'ils échouent**

Lance : `uv run pytest tests/mining/test_cpu_pearl.py -v`
Attendu : ÉCHEC — `CpuPearlProvider` introuvable.

- [ ] **Étape 3 : implémenter le `detect` du fournisseur**

Crée `src/diapason/mining/cpu_pearl.py` :

```python
"""Fournisseur de minage Pearl sur CPU (découplé de l'inférence).

Spec B v1 : enveloppe la fonction ``mine()`` pure Rust de Pearl via
py-pearl-mining et lance le pearl-gateway de Pearl comme sous-processus frère.
Marche sur tout hôte où py-pearl-mining se construit — vérifié sur macOS
arm64 (M2 Max) dans la spec B.

Indépendant du moteur : ce fournisseur ne se branche pas sur la pile
d'inférence de l'utilisateur. L'utilisateur garde le moteur qu'il veut ; le
minage tourne à côté.
"""
from __future__ import annotations

from . import _install
from ._stubs import HardwareInfo, MiningCapabilities, MiningConfig, MiningProvider, MiningStats


class CpuPearlProvider(MiningProvider):
    provider_id = "cpu-pearl"

    @classmethod
    def detect(cls, hw: HardwareInfo, engine_id: str, model: str) -> MiningCapabilities:
        # Verrou de plateforme v1 : darwin et linux seulement. Windows demande
        # plus d'enquête (le Taskfile du mineur de Pearl écarte Windows du
        # chemin d'installation du minage CPU, même si l'algorithme lui-même
        # est portable).
        if hw.platform not in {"darwin", "linux"}:
            return MiningCapabilities(
                supported=False,
                reason=f"la v1 de cpu-pearl ne gère que darwin/linux ; cet hôte est '{hw.platform}'",
            )
        if not _install.pearl_packages_available():
            return MiningCapabilities(
                supported=False,
                reason=f"paquets Python Pearl non installés — {_install.install_hint()}",
            )
        # Pas de contrôle d'engine_id : cpu-pearl est découplé de l'inférence.
        # L'estimation du taux de hachage est reportée à un étalonnage unique
        # pendant `mine init` (intégration du cycle de vie, tâche 9).
        return MiningCapabilities(supported=True)
```

- [ ] **Étape 4 : lancer les tests pour vérifier qu'ils passent**

Lance : `uv run pytest tests/mining/test_cpu_pearl.py -v`
Attendu : SUCCÈS — les quatre tests au vert.

- [ ] **Étape 5 : lint**

Lance : `uv run ruff check src/diapason/mining/cpu_pearl.py tests/mining/test_cpu_pearl.py`
Attendu : aucune erreur.

- [ ] **Étape 6 : committer**

```bash
git add src/diapason/mining/cpu_pearl.py tests/mining/test_cpu_pearl.py
git commit -m "feat(mining): détection de capacité du fournisseur cpu-pearl (spec B v1, tâche 8)"
```

---

## Tâche 9 : `CpuPearlProvider` — start/stop/is_running/stats

**Fichiers :**
- Modifier : `src/diapason/mining/cpu_pearl.py`
- Modifier : `tests/mining/test_cpu_pearl.py`

Relie les méthodes de cycle de vie du fournisseur au lanceur de sous-processus, ainsi qu'au sidecar et à l'adaptateur de télémétrie de la spec A.

- [ ] **Étape 1 : écrire les tests qui échouent**

Ajoute à la fin de `tests/mining/test_cpu_pearl.py` :

```python
def test_start_writes_sidecar_and_returns_running(darwin_apple_hw, tmp_path, monkeypatch):
    from diapason.mining.cpu_pearl import CpuPearlProvider
    from diapason.mining._stubs import MiningConfig

    monkeypatch.setattr(
        "diapason.mining.cpu_pearl._sidecar_path",
        lambda: tmp_path / "mining.json",
    )

    fake_launcher = type(
        "FakeLauncher",
        (),
        {
            "start": lambda self, **kw: None,
            "stop": lambda self: None,
            "is_running": lambda self: True,
            "pids": lambda self: (11111, 22222),
        },
    )()

    with patch(
        "diapason.mining.cpu_pearl.PearlSubprocessLauncher",
        return_value=fake_launcher,
    ):
        provider = CpuPearlProvider()
        cfg = MiningConfig(
            provider="cpu-pearl",
            wallet_address="prl1qtest",
            extra={
                "gateway_port": 8337,
                "metrics_port": 8339,
                "pearld_rpc_url": "http://localhost:44107",
                "pearld_rpc_user": "rpcuser",
                "pearld_rpc_password_env": "TESTPW",
                "m": 256, "n": 128, "k": 1024, "rank": 32,
            },
        )
        monkeypatch.setenv("TESTPW", "secret")
        provider.start(cfg)
        assert provider.is_running() is True
        sidecar_text = (tmp_path / "mining.json").read_text()
        assert '"provider": "cpu-pearl"' in sidecar_text
        assert "11111" in sidecar_text
        assert "22222" in sidecar_text
        # le secret ne doit PAS apparaître dans le sidecar
        assert "secret" not in sidecar_text
```

- [ ] **Étape 2 : lancer le test pour vérifier qu'il échoue**

Lance : `uv run pytest tests/mining/test_cpu_pearl.py::test_start_writes_sidecar_and_returns_running -v`
Attendu : ÉCHEC — `start` et `is_running` ne sont pas implémentés.

- [ ] **Étape 3 : implémenter les méthodes de cycle de vie**

Remplace `src/diapason/mining/cpu_pearl.py` par l'implémentation complète :

```python
"""Fournisseur de minage Pearl sur CPU (découplé de l'inférence).

Spec B v1 : enveloppe la fonction ``mine()`` pure Rust de Pearl via
py-pearl-mining et lance le pearl-gateway de Pearl comme sous-processus frère.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import urllib.request

from . import _install
from ._constants import (
    CPU_PEARL_DEFAULT_K,
    CPU_PEARL_DEFAULT_M,
    CPU_PEARL_DEFAULT_N,
    CPU_PEARL_DEFAULT_RANK,
)
from ._pearl_subprocess import PearlSubprocessLauncher
from ._stubs import HardwareInfo, MiningCapabilities, MiningConfig, MiningProvider, MiningStats


def _sidecar_path() -> Path:
    return Path(os.path.expanduser("~/.diapason/runtime/mining.json"))


def _log_dir() -> Path:
    return Path(os.path.expanduser("~/.diapason/logs/mining"))


class CpuPearlProvider(MiningProvider):
    provider_id = "cpu-pearl"

    def __init__(self) -> None:
        self._launcher: PearlSubprocessLauncher | None = None
        self._config: MiningConfig | None = None
        self._started_at: float | None = None

    @classmethod
    def detect(cls, hw: HardwareInfo, engine_id: str, model: str) -> MiningCapabilities:
        if hw.platform not in {"darwin", "linux"}:
            return MiningCapabilities(
                supported=False,
                reason=f"la v1 de cpu-pearl ne gère que darwin/linux ; cet hôte est '{hw.platform}'",
            )
        if not _install.pearl_packages_available():
            return MiningCapabilities(
                supported=False,
                reason=f"paquets Python Pearl non installés — {_install.install_hint()}",
            )
        return MiningCapabilities(supported=True)

    def start(self, config: MiningConfig) -> None:
        extra = dict(config.extra or {})
        password_env = extra.get("pearld_rpc_password_env", "PEARLD_RPC_PASSWORD")
        password = os.environ.get(password_env, "")

        self._launcher = PearlSubprocessLauncher(
            gateway_host=extra.get("gateway_host", "127.0.0.1"),
            gateway_port=int(extra.get("gateway_port", 8337)),
            metrics_port=int(extra.get("metrics_port", 8339)),
            pearld_rpc_url=extra.get("pearld_rpc_url", "http://localhost:44107"),
            pearld_rpc_user=extra.get("pearld_rpc_user", "rpcuser"),
            pearld_rpc_password=password,
            wallet_address=config.wallet_address,
            log_dir=_log_dir(),
        )
        self._launcher.start(
            m=int(extra.get("m", CPU_PEARL_DEFAULT_M)),
            n=int(extra.get("n", CPU_PEARL_DEFAULT_N)),
            k=int(extra.get("k", CPU_PEARL_DEFAULT_K)),
            rank=int(extra.get("rank", CPU_PEARL_DEFAULT_RANK)),
        )
        self._config = config
        self._started_at = time.time()
        self._write_sidecar()

    def stop(self) -> None:
        if self._launcher is not None:
            self._launcher.stop()
        self._launcher = None
        self._config = None
        self._started_at = None
        sp = _sidecar_path()
        if sp.exists():
            sp.unlink()

    def is_running(self) -> bool:
        return self._launcher is not None and self._launcher.is_running()

    def stats(self) -> MiningStats:
        if not self.is_running() or self._launcher is None:
            return MiningStats(provider_id=self.provider_id)

        # L'adaptateur de métriques de passerelle de la spec A fait l'analyse.
        # Lire une fois, analyser, renvoyer. On réutilise l'adaptateur du
        # fournisseur vllm-pearl ; les noms de métriques sont identiques.
        from ._gateway_metrics import parse_gateway_metrics

        try:
            extra = (self._config.extra or {}) if self._config else {}
            metrics_port = int(extra.get("metrics_port", 8339))
            host = extra.get("gateway_host", "127.0.0.1")
            with urllib.request.urlopen(
                f"http://{host}:{metrics_port}/metrics", timeout=2.0
            ) as resp:
                text = resp.read().decode()
        except Exception as e:  # noqa: BLE001
            return MiningStats(
                provider_id=self.provider_id,
                last_error=f"métriques de la passerelle injoignables : {e}",
            )
        return parse_gateway_metrics(text, provider_id=self.provider_id)

    def _write_sidecar(self) -> None:
        if self._launcher is None or self._config is None:
            return
        pids = self._launcher.pids() or (None, None)
        extra = self._config.extra or {}
        sidecar = {
            "provider": self.provider_id,
            "started_at": self._started_at,
            "wallet_address": self._config.wallet_address,
            "gateway_url": (
                f"http://{extra.get('gateway_host', '127.0.0.1')}:"
                f"{extra.get('gateway_port', 8337)}"
            ),
            "metrics_url": (
                f"http://{extra.get('gateway_host', '127.0.0.1')}:"
                f"{extra.get('metrics_port', 8339)}/metrics"
            ),
            "gateway_pid": pids[0],
            "miner_loop_pid": pids[1],
        }
        sp = _sidecar_path()
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(json.dumps(sidecar, indent=2))
```

- [ ] **Étape 4 : lancer les tests**

Lance : `uv run pytest tests/mining/test_cpu_pearl.py -v`
Attendu : SUCCÈS — les cinq tests au vert.

- [ ] **Étape 5 : lint**

Lance : `uv run ruff check src/diapason/mining/cpu_pearl.py`
Attendu : aucune erreur.

- [ ] **Étape 6 : committer**

```bash
git add src/diapason/mining/cpu_pearl.py tests/mining/test_cpu_pearl.py
git commit -m "feat(mining): cycle de vie du fournisseur cpu-pearl (spec B v1, tâche 9)"
```

---

## Tâche 10 : enregistrer `CpuPearlProvider` dans `MinerRegistry`

**Fichiers :**
- Modifier : `src/diapason/mining/__init__.py`

`MinerRegistry` existe depuis la spec A ; il suffit d'appeler `register("cpu-pearl")` au chargement du module et de survivre à la fixture autouse `clear_registries` de `tests/conftest.py` grâce au motif `ensure_registered()`.

- [ ] **Étape 1 : lire le `__init__.py` existant de la spec A**

Lance : `cat src/diapason/mining/__init__.py`

Attendu : le fichier importe déjà `vllm_pearl` et expose `ensure_registered`. On calque le même motif pour cpu_pearl.

- [ ] **Étape 2 : ajouter l'enregistrement de cpu_pearl**

Ajoute à la fin de `src/diapason/mining/__init__.py` (ou modifie, si la spec A a déjà défini `ensure_registered`) :

```python
def _register_cpu_pearl() -> None:
    """Enregistre CpuPearlProvider dans MinerRegistry. Idempotent."""
    from diapason.core.registry import MinerRegistry  # type: ignore

    if MinerRegistry.contains("cpu-pearl"):
        return
    try:
        from .cpu_pearl import CpuPearlProvider
    except ImportError:
        # py-pearl-mining et consorts ne sont pas installés — ce n'est pas
        # grave, le fournisseur ne s'enregistre que si l'extra optionnel est
        # présent. detect() affichera un message clair disant d'installer
        # avec --extra mining-pearl-cpu.
        return
    MinerRegistry.register("cpu-pearl")(CpuPearlProvider)


# Appelé à l'import pour que le registre soit peuplé dès que diapason.mining
# est importé. La fixture autouse de conftest vide les registres entre les
# tests ; on compte sur le rappel de _register_cpu_pearl depuis
# `ensure_registered`.
_register_cpu_pearl()


def ensure_registered() -> None:
    """Réenregistre tous les fournisseurs de minage — pour les tests qui vident le registre."""
    _register_vllm_pearl()  # ajouté par la spec A
    _register_cpu_pearl()
```

- [ ] **Étape 3 : lancer tous les tests de minage**

Lance : `uv run pytest tests/mining/ -v`
Attendu : SUCCÈS — tous les tests de ce plan, plus ceux de la spec A, toujours au vert.

- [ ] **Étape 4 : passer un balayage plus large pour attraper les régressions**

Lance : `uv run pytest tests/ -v --co -q | tail -30; uv run pytest tests/ -x -q 2>&1 | tail -30`
Attendu : le même nombre de tests réussis qu'avant cette tâche.

- [ ] **Étape 5 : committer**

```bash
git add src/diapason/mining/__init__.py
git commit -m "feat(mining): enregistrer le fournisseur cpu-pearl (spec B v1, tâche 10)"
```

---

## Tâche 11 : documentation destinée à l'utilisateur

**Fichiers :**
- Créer : `docs/user-guide/mining-apple-silicon.md`

Le guide honnête. Cale les attentes au bon niveau ; ne survends pas le taux de hachage.

- [ ] **Étape 1 : écrire le document**

Crée `docs/user-guide/mining-apple-silicon.md` :

````markdown
# Miner Pearl sur Apple Silicon (et autres hôtes CPU)

Diapason peut miner la chaîne [Pearl](https://github.com/pearl-research-labs/pearl)
sur les Mac Apple Silicon (M1/M2/M3/M4) grâce au fournisseur `cpu-pearl`. **C'est
la v1** : du minage CPU découplé. Ton flux de travail LLM local habituel (Ollama,
MLX-LM, llama.cpp, vLLM) n'est pas touché ; le minage tourne en arrière-plan,
dans un processus séparé.

## Des attentes honnêtes

**Le taux de hachage d'un CPU Apple Silicon est très loin de ce que produit une
H100 avec le `vllm-miner` de Pearl.** Un ordre de grandeur approximatif, qui
dépend de la difficulté du réseau :

- M2 Max / M4 Max : ≪ 1 part par seconde à la difficulté habituelle du réseau principal
- H100 avec `vllm-miner` : nettement plus, et le travail de minage est amorti
  sur de vraies inférences LLM

Si tu veux miner pour le rendement, ce n'est pas le bon chemin. Si tu veux
participer au réseau avec le matériel que tu possèdes déjà, sans rien acheter de
spécial, c'est celui-là.

Une v2 ajoutera l'accélération par le GPU Apple, via PyTorch MPS ou un greffon
MLX maison. Une v3 pourrait ajouter un noyau Metal natif. **Ni l'une ni l'autre
n'est livrée aujourd'hui.**

## Prérequis

- macOS arm64 (M1, M2, M3, M4) — ou Linux x86_64 / aarch64
- Python 3.12 (`brew install python@3.12`, ou `uv venv --python 3.12`)
- La chaîne d'outils Rust (`brew install rust`, ou `curl https://sh.rustup.rs -sSf | sh`)
- Ton propre nœud [`pearld`](https://github.com/pearl-research-labs/pearl#node)
  en marche, RPC joignable sur `http://localhost:44107`
- Une adresse de portefeuille Pearl Taproot, obtenue avec `oyster` (la CLI de
  portefeuille de Pearl)
- ~1 Go de disque libre pour le clone des sources Pearl et les artefacts de
  construction

## Installer

```bash
# depuis ton dépôt Diapason
uv sync --extra mining-pearl-cpu
```

Si les wheels Pearl ne sont pas encore sur PyPI (toujours vrai au 5 mai 2026),
`uv sync` échouera parce qu'aucun des paquets n'y existe. En attendant la
publication, construis en local :

```bash
diapason mine init    # OJ détectera les wheels manquantes et proposera de
                    # construire depuis la référence figée ; compte 3 à
                    # 5 minutes au premier lancement, surtout de la
                    # compilation Rust
```

`mine init` va :
1. Cloner Pearl à la version contre laquelle OJ a été testé
2. Lancer `maturin build --release` pour `py-pearl-mining`
3. Installer la wheel produite, plus les paquets `miner-base` et `pearl-gateway`
4. T'accompagner dans la configuration de l'adresse de portefeuille et du RPC pearld
5. Lancer un étalonnage pour estimer ton nombre de parts par heure

## Lancer

```bash
# démarrer le minage
diapason mine start

# voir l'état en direct
diapason mine status

# matrice des capacités (précieuse quand quelque chose cloche)
diapason mine doctor

# arrêter le minage
diapason mine stop

# suivre les journaux
diapason mine logs -f
```

## Lire `mine doctor`

Chaque ligne est un contrôle. `✓` veut dire qu'il est passé ; `✗` montre la
correction à faire.

```
$ diapason mine doctor
Matériel
  Fabricant du GPU     apple                            ✓
  Puce Apple           M2 Max                           ✓
Installation Pearl
  py-pearl-mining      0.1.0 (cp312-abi3-macos-arm64)   ✓
  miner-base           0.1.0                            ✓
  pearl-gateway        0.1.0                            ✓
Nœud Pearl
  RPC                  http://localhost:44107           ✓
  Hauteur de bloc      442107 (synchronisé)             ✓
Portefeuille
  Format d'adresse     prl1q...                         ✓
Capacité du fournisseur
  cpu-pearl            PRIS EN CHARGE  (étalonné à 0,X part/h sur M2 Max)
Notes
  - C'est du minage découplé : ton inférence LLM habituelle n'est pas touchée
  - Le taux de hachage est très loin de celui d'une H100 ; voir plus haut
  - Minage accéléré par Metal : prévu pour la v2, pas encore disponible
Session
  Sidecar              absent (à l'arrêt)
```

## Limites

- **Windows n'est pas pris en charge en v1.** Le mineur pur Rust de Pearl se
  construit sur Windows en principe, mais le chemin d'installation
  multiplateforme n'est pas testé. Passe par WSL2 s'il le faut.
- **Aucun couplage à l'inférence pour l'instant.** La v1 est un processus
  séparé : ton CPU mine, ton GPU fait l'inférence. Ils ne partagent pas le
  travail. La v2 change cela.
- **Pas encore de PyTorch-MPS.** La v1 reste sur le chemin CPU. La v2 déplacera
  les calculs vers MPS pour accélérer avec le GPU Apple.
- **Pas de pool multi-machines.** Minage solo seulement. Le travail sur les
  pools est une spec à part
  ([Spec A §8.5](../design/2026-05-05-vllm-pearl-mining-integration-design.md)).

## Dépannage

| Symptôme | Cause probable | Correction |
|---|---|---|
| `mine doctor` dit `paquets Python Pearl non installés` | Les wheels ne sont pas encore construites | Lance `diapason mine init` |
| Le journal de `pearl-gateway` montre `connection refused` vers `http://localhost:44107` | `pearld` ne tourne pas | Démarre `pearld` selon le README de Pearl |
| `mine status` montre `last_error: métriques de la passerelle injoignables` | `pearl-gateway` a planté | Regarde `~/.diapason/logs/mining/pearl-gateway.log` |
| La construction échoue avec `error: linker 'cc' not found` | Les outils en ligne de commande Xcode ne sont pas installés | `xcode-select --install` |
| `maturin build` se plaint de `tikv-jemallocator` | SDK macOS trop ancien | Mets macOS / Xcode à jour |

Pour tout ce qui n'est pas dans cette liste, récupère `~/.diapason/logs/mining/`
et ouvre un ticket sur https://github.com/carlitoetienne01-spec/Diapason/issues.

## Ce qui change en v2 / v3

- **v2 (quelques mois) :** accélération PyTorch-MPS, plus un greffon optionnel
  dans MLX-LM ou `llama-cpp-python`. Même configuration `cpu-pearl` ; on y passe
  via un nouveau fournisseur `apple-mps-pearl` quand la v2 sortira.
- **v3 (seulement si les performances de la v2 ne suffisent pas) :** un noyau
  Metal natif, contribué en amont chez Pearl. Aucun changement visible pour
  l'utilisateur, à part un taux de hachage plus élevé.
````

- [ ] **Étape 2 : lint du markdown**

Lance : `uv run ruff check docs/user-guide/mining-apple-silicon.md 2>&1 | tail -5 || true`

(Ruff ne vérifie pas le markdown ; la commande ne fait rien. Vérifie simplement que le fichier existe et s'affiche.)

Lance : `head -20 docs/user-guide/mining-apple-silicon.md`
Attendu : la ligne de titre et le paragraphe d'introduction.

- [ ] **Étape 3 : committer**

```bash
git add docs/user-guide/mining-apple-silicon.md
git commit -m "docs: guide du minage Pearl sur Apple Silicon (spec B v1, tâche 11)"
```

---

## Tâche 12 : test de fumée d'intégration final (manuel / marqueur `live`)

**Fichiers :**
- Modifier : `tests/mining/test_cpu_pearl.py`

Un vrai test de bout en bout qui démarre le fournisseur sur la machine de développement, tourne une trentaine de secondes et vérifie qu'au moins un tour de minage a eu lieu. Marqué `live` pour rester derrière `pytest -m live` et sortir de la CI par défaut.

- [ ] **Étape 1 : ajouter le test réel**

Ajoute à la fin de `tests/mining/test_cpu_pearl.py` :

```python
@pytest.mark.live
@pytest.mark.slow
def test_provider_runs_end_to_end_on_this_host(tmp_path, monkeypatch):
    """Test réel : démarre le fournisseur, tourne 30 s, vérifie que la boucle a produit quelque chose.

    Exige :
    - py-pearl-mining construit et installé
    - pearl-gateway et miner-base installés
    - soit pearld en marche, soit un environnement de passerelle bouchonné (ce
      dernier est plus dur à monter ; en v1 on compte sur pearld disponible
      en local)
    """
    pytest.importorskip("pearl_mining")
    pytest.importorskip("pearl_gateway")

    from diapason.mining.cpu_pearl import CpuPearlProvider
    from diapason.mining._stubs import MiningConfig

    monkeypatch.setattr(
        "diapason.mining.cpu_pearl._sidecar_path",
        lambda: tmp_path / "mining.json",
    )
    monkeypatch.setattr(
        "diapason.mining.cpu_pearl._log_dir",
        lambda: tmp_path / "logs",
    )
    monkeypatch.setenv("TEST_PEARLD_PASSWORD", "test")

    cfg = MiningConfig(
        provider="cpu-pearl",
        wallet_address="prl1q" + "0" * 32,
        extra={
            "gateway_port": 18337,  # port haut, pour ne pas heurter une vraie session
            "metrics_port": 18339,
            "pearld_rpc_url": "http://localhost:44107",
            "pearld_rpc_user": "rpcuser",
            "pearld_rpc_password_env": "TEST_PEARLD_PASSWORD",
        },
    )
    provider = CpuPearlProvider()
    provider.start(cfg)

    import time
    deadline = time.monotonic() + 30
    saw_running = False
    while time.monotonic() < deadline:
        if provider.is_running():
            saw_running = True
        time.sleep(1.0)

    provider.stop()

    log_dir = tmp_path / "logs"
    if log_dir.exists():
        for log_file in log_dir.glob("*.log"):
            print(f"--- {log_file.name} ---")
            print(log_file.read_text()[:2000])

    assert saw_running, "le fournisseur n'a jamais signalé is_running"
```

- [ ] **Étape 2 : lancer le test réel (seulement sur un hôte avec la pile Pearl complète)**

Lance : `uv run pytest tests/mining/test_cpu_pearl.py::test_provider_runs_end_to_end_on_this_host -v -m live`
Attendu : SUCCÈS si l'hôte a Pearl installé et `pearld` en marche. Sauté par `importorskip` sinon.

- [ ] **Étape 3 : vérifier que la CI par défaut l'exclut toujours**

Lance : `uv run pytest tests/mining/ -v -m "not live and not cloud"`
Attendu : tous les autres tests du plan passent toujours ; le test réel est collecté mais désélectionné.

- [ ] **Étape 4 : committer**

```bash
git add tests/mining/test_cpu_pearl.py
git commit -m "test(mining): test de fumée de bout en bout pour cpu-pearl (spec B v1, tâche 12)"
```

---

## Tâche 13 : mises à jour de REVIEW.md et CLAUDE.md

**Fichiers :**
- Modifier : `CLAUDE.md`
- Modifier : `REVIEW.md` (si la spec A l'a ajouté ; sinon, sauter)

De tout petits panneaux indicateurs, pour que les futurs agents trouvent le chemin cpu-pearl.

- [ ] **Étape 1 : ajouter un paragraphe à la section `## Architecture` de CLAUDE.md**

Trouve le paragraphe `mining` qu'a ajouté la spec A. Ajoute à la suite :

```
Le sous-système `mining` comprend aussi le fournisseur `cpu-pearl` (spec B v1)
pour les hôtes sans CUDA, Apple Silicon compris. Il lance la fonction `mine()`
pure Rust de Pearl via `py-pearl-mining`, plus le `pearl-gateway` de Pearl comme
sous-processus frère ; découplé de l'inférence (le moteur MLX/Ollama/llamacpp de
l'utilisateur n'est pas touché). La v2 à venir (accélération par le GPU Apple via
PyTorch MPS) et la v3 (noyau Metal natif) sont suivies dans
docs/design/2026-05-05-apple-silicon-pearl-mining-design.md.
```

- [ ] **Étape 2 : ajouter une ligne à la section « Registry compliance » de REVIEW.md, si elle existe**

Lance : `grep -n "MinerRegistry" REVIEW.md 2>/dev/null || echo "pas encore de ligne"`

Si une ligne existe depuis la spec A, ajoute-lui une sœur qui note que `cpu-pearl` est le deuxième fournisseur enregistré, et que les relecteurs doivent vérifier que `_register_vllm_pearl` et `_register_cpu_pearl` sont tous deux appelés depuis `ensure_registered`.

- [ ] **Étape 3 : committer**

```bash
git add CLAUDE.md REVIEW.md 2>/dev/null  # REVIEW.md peut ne pas exister ; ce n'est pas grave
git commit -m "docs: pointer vers le fournisseur cpu-pearl dans CLAUDE.md (spec B v1, tâche 13)"
```

---

## Liste de contrôle d'autorelecture

Passe chacun de ces points sur le plan final :

**1. Couverture de la spec** — les sections §13 de la spec B face aux tâches :

- §13.1 Architecture (sous-processus + fournisseur + sidecar) → tâches 5, 6, 9
- §13.2 Disposition des modules → tâches 5, 6, 8, 9, 10
- §13.3 Extra optionnel → tâche 2
- §13.4 Détection de capacité → tâche 8
- §13.5 Cycle de vie → tâches 6, 7, 9
- §13.6 Configuration → réutilise la spec A ; documenté dans le guide utilisateur (tâche 11)
- §13.7 Surface de doctor → le `mine doctor` de la spec A existe déjà ; la ligne cpu-pearl est remplie par le `stats()` de la tâche 9 et par la détection de capacité de la tâche 8. *(Pas de tâche séparée ; l'intégration passe par la CLI existante.)*
- §13.8 Anti-objectifs → garantis par ce que le plan ne fait PAS (pas de greffon MLX, pas de Metal, pas de couplage à l'inférence)
- §13.9 Critères de sortie → tâche 12 (fumée réelle), tâche 11 (docs) ; trouver un bloc sur le réseau de test relève de l'exploitation, pas du code
- §13.10 v2/v3 — explicitement hors périmètre, mentionné dans le guide utilisateur

**2. Contrôle de cohérence des types :**

- `MiningProvider`, `MinerRegistry`, `MiningCapabilities`, `MiningConfig`, `MiningStats`, `HardwareInfo` — tous issus du `_stubs.py` de la spec A. Employés à l'identique dans les tâches 8 à 10.
- `provider_id = "cpu-pearl"` — employé aux tâches 8, 9, 10.
- Les noms de clés du sidecar (`provider`, `wallet_address`, `gateway_url`, `metrics_url`, `gateway_pid`, `miner_loop_pid`, `started_at`) — définis dans le `_write_sidecar` de la tâche 9 et relus par l'assertion de la tâche 12.
- `_install.pearl_packages_available()` et `_install.install_hint()` — définis à la tâche 3, employés à la tâche 8.
- `_install.build_from_pin()` — défini à la tâche 4, appelé depuis l'orchestration de `mine init` du plan de la spec A.

**3. Balayage des trous laissés en attente :**

- Aucun « TBD », « TODO » ni « à implémenter plus tard » dans les blocs de code.
- Un seul endroit est volontairement marqué « recherche-et-correction » : la tâche 7 vérifie les noms de variables d'environnement contre la configuration de Pearl. La correction est mécanique (remplacer des chaînes) ; la recherche est bornée (lire un fichier de Pearl).
- Les noms de variables d'environnement de `_pearl_subprocess.py`, à la tâche 6, sont les meilleures suppositions et la tâche 7 les affine. Ce n'est pas un trou laissé en attente — la tâche 7 est la correction explicite.

**4. Ce qui est réutilisé de la spec A (contrôle de bon sens — tout cela doit déjà exister) :**

- l'ABC `MiningProvider` dans `src/diapason/mining/_stubs.py`
- la classe `MinerRegistry` dans `src/diapason/core/registry.py`
- les dataclasses `MiningConfig`, `MiningCapabilities`, `MiningStats`, `HardwareInfo`
- la convention d'emplacement du sidecar `~/.diapason/runtime/mining.json`
- l'adaptateur `parse_gateway_metrics`
- les sous-commandes CLI `mine init|start|stop|status|doctor`

Si l'un d'eux manque au moment d'attaquer la tâche 1, **arrête-toi et exécute d'abord la spec A.** Ne redouble pas cette infrastructure ici.

---

## Passation d'exécution

Plan terminé, enregistré dans `docs/design/2026-05-05-apple-silicon-pearl-mining-plan-v1.md`. Deux façons de l'exécuter :

**1. Par sous-agents (recommandé)** — dépêche un sous-agent neuf par tâche, avec une relecture en deux temps. Bon pour paralléliser relecture et exécution, et les tâches d'ici sont bien bornées.

**2. Exécution en ligne** — exécute les tâches dans cette session avec `superpowers:executing-plans`. Plus rapide de bout en bout, la relecture est groupée aux points de contrôle.

L'utilisateur fait la spec A par sous-agents (selon sa consigne). La même approche vaut pour la spec B v1 une fois le plan de la spec A terminé ; la dépendance les rend naturellement séquentielles.
