"""Decorator-based registry for runtime discovery of pluggable components.

Adapted from IPW's ``src/ipw/core/registry.py``.  Each typed subclass gets its
own isolated storage so registrations in one registry never leak into another.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Dict, Generic, Tuple, Type, TypeVar

if TYPE_CHECKING:
    from diapason.agents._stubs import BaseAgent
    from diapason.engine._stubs import InferenceEngine
    from diapason.memory.store import FactStore
    from diapason.tools.storage._stubs import MemoryBackend

T = TypeVar("T")


@dataclass(frozen=True)
class _LazyEntry:
    """Une clé déclarée dont le module n'est pas encore chargé."""

    module: str

    def __repr__(self) -> str:  # pragma: no cover - confort de débogage
        return f"<lazy {self.module}>"


class RegistryBase(Generic[T]):
    """Generic registry base class with class-specific entry isolation."""

    @classmethod
    def _entries(cls) -> Dict[str, T]:
        attr_name = f"_registry_entries_{cls.__name__}"
        storage = getattr(cls, attr_name, None)
        if storage is None:
            storage: Dict[str, T] = {}
            setattr(cls, attr_name, storage)
        return storage

    @classmethod
    def register(cls, key: str) -> Callable[[T], T]:
        """Decorator that registers *entry* under *key*."""

        def decorator(entry: T) -> T:
            entries = cls._entries()
            # Une DÉCLARATION paresseuse n'est pas un enregistrement : le vrai
            # la remplace. Sans quoi importer le module directement — ce que
            # font les tests — se heurterait à la clé qu'il vient lui-même de
            # faire déclarer.
            if key in entries and not isinstance(entries[key], _LazyEntry):
                raise ValueError(f"{cls.__name__} already has an entry for '{key}'")
            entries[key] = entry
            return entry

        return decorator

    @classmethod
    def register_value(cls, key: str, value: T) -> T:
        """Imperatively register a *value* under *key*."""
        entries = cls._entries()
        if key in entries and not isinstance(entries[key], _LazyEntry):
            raise ValueError(f"{cls.__name__} already has an entry for '{key}'")
        entries[key] = value
        return value

    @classmethod
    def register_lazy(cls, key: str, module: str) -> None:
        """Déclarer *key* sans charger son module.

        Importer un moteur « pour déclencher son enregistrement » fait payer
        ses dépendances à TOUT LE MONDE, y compris à qui ne s'en servira
        jamais. MESURÉ : charger ``colbert_backend`` ou ``faiss_backend``
        tirait ``torch`` et ``numpy`` — puis échouait sur une dépendance
        absente, et l'échec était avalé. Le coût restait, pas le moteur. Or un
        ``numpy`` cassé fait alors tomber ``diapason serve`` au démarrage, pour
        un moteur que personne n'a demandé.

        Le module n'est donc chargé qu'à la première question portant sur
        cette clé.
        """
        entries = cls._entries()
        if key not in entries:
            entries[key] = _LazyEntry(module)

    @classmethod
    def _resolve(cls, key: str) -> None:
        """Charger le module d'une clé paresseuse, si c'en est une."""
        entries = cls._entries()
        entry = entries.get(key)
        if not isinstance(entry, _LazyEntry):
            return
        # Retirer le marqueur AVANT d'importer : le module s'enregistre
        # lui-même par décorateur et refuserait une clé déjà prise.
        del entries[key]
        try:
            importlib.import_module(entry.module)
        except ImportError:
            # Dépendance absente : la clé disparaît, exactement comme
            # aujourd'hui où l'import échouait au chargement du paquet.
            pass

    @classmethod
    def get(cls, key: str) -> T:
        """Retrieve the entry for *key*, raising ``KeyError`` if missing."""
        cls._resolve(key)
        try:
            return cls._entries()[key]
        except KeyError as exc:
            raise KeyError(
                f"{cls.__name__} does not have an entry for '{key}'"
            ) from exc

    @classmethod
    def create(cls, key: str, *args: Any, **kwargs: Any) -> Any:
        """Look up *key* and instantiate it with the given arguments."""
        entry = cls.get(key)
        if not callable(entry):
            raise TypeError(
                f"{cls.__name__} entry '{key}' is not callable"
                " and cannot be instantiated"
            )
        return entry(*args, **kwargs)

    @classmethod
    def items(cls) -> Tuple[Tuple[str, T], ...]:
        """Return all ``(key, entry)`` pairs as a tuple."""
        return tuple(cls._entries().items())

    @classmethod
    def keys(cls) -> Tuple[str, ...]:
        """Return all registered keys as a tuple."""
        return tuple(cls._entries().keys())

    @classmethod
    def contains(cls, key: str) -> bool:
        """Check whether *key* is registered.

        Résout une entrée paresseuse : répondre « oui » puis échouer à la
        créer serait pire que de payer l'import ici. L'appelant qui pose la
        question sur cette clé précise est justement celui qui va s'en servir.
        """
        cls._resolve(key)
        return key in cls._entries()

    @classmethod
    def clear(cls) -> None:
        """Remove all entries (useful in tests)."""
        cls._entries().clear()


# ---------------------------------------------------------------------------
# Typed subclass registries — one per primitive
# ---------------------------------------------------------------------------


class ModelRegistry(RegistryBase[Any]):
    """Registry for ``ModelSpec`` objects."""


class EngineRegistry(RegistryBase[Type["InferenceEngine"]]):
    """Registry for inference engine backends."""


class MemoryRegistry(RegistryBase[Type["MemoryBackend"]]):
    """Registry for memory / retrieval backends."""


class FactStoreRegistry(RegistryBase[Type["FactStore"]]):
    """Registry for automatic-memory fact store backends."""


class AgentRegistry(RegistryBase[Type["BaseAgent"]]):
    """Registry for agent implementations."""


class ToolRegistry(RegistryBase[Any]):
    """Registry for tool specifications."""


class RouterPolicyRegistry(RegistryBase[Any]):
    """Registry for router policy implementations."""


class BenchmarkRegistry(RegistryBase[Any]):
    """Registry for benchmark implementations."""


class ChannelRegistry(RegistryBase[Any]):
    """Registry for channel implementations."""


class LearningRegistry(RegistryBase[Any]):
    """Registry for learning policies."""


class SkillRegistry(RegistryBase[Any]):
    """Registry for skill manifests."""


class SpeechRegistry(RegistryBase[Any]):
    """Registry for speech backend implementations."""


class CompressionRegistry(RegistryBase[Any]):
    """Registry for context compression strategies."""


class TTSRegistry(RegistryBase[Any]):
    """Registry for text-to-speech backend implementations."""


class ConnectorRegistry(RegistryBase[Any]):
    """Registry for data source connectors (Gmail, Slack, etc.)."""


class MinerRegistry(RegistryBase[Any]):
    """Registry for Pearl mining provider implementations.

    Each provider implements the ``MiningProvider`` ABC defined in
    ``diapason.mining._stubs``. Registry keys are short lowercase strings
    such as ``"vllm-pearl"`` (CUDA + Hopper) and (future) ``"mlx-pearl"``,
    ``"llamacpp-pearl-metal"``, ``"ollama-pearl"``.
    """


__all__ = [
    "AgentRegistry",
    "BenchmarkRegistry",
    "ChannelRegistry",
    "CompressionRegistry",
    "ConnectorRegistry",
    "EngineRegistry",
    "FactStoreRegistry",
    "LearningRegistry",
    "MemoryRegistry",
    "MinerRegistry",
    "ModelRegistry",
    "RegistryBase",
    "RouterPolicyRegistry",
    "SkillRegistry",
    "SpeechRegistry",
    "TTSRegistry",
    "ToolRegistry",
]
