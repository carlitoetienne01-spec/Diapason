"""Storage primitive — persistent searchable storage."""

from __future__ import annotations

# Always-available backend
import diapason.tools.storage.sqlite  # noqa: E402,F401
from diapason.core.registry import MemoryRegistry
from diapason.tools.storage._stubs import MemoryBackend, RetrievalResult
from diapason.tools.storage.chunking import Chunk, ChunkConfig, chunk_text
from diapason.tools.storage.context import ContextConfig, inject_context
from diapason.tools.storage.ingest import ingest_path, read_document

# Moteurs optionnels : déclarés, pas chargés.
#
# Les importer « pour déclencher l'enregistrement » faisait payer leurs
# dépendances à tout le monde. MESURÉ : colbert_backend et faiss_backend
# tiraient torch et numpy, PUIS échouaient sur une dépendance absente — l'échec
# était avalé, le coût restait. Or importer diapason.cli chargeait ainsi numpy,
# et un numpy cassé fait tomber « diapason serve » au démarrage, pour un moteur
# que personne n'a demandé.
#
# Chacun est désormais chargé à la première question portant sur sa clé.

for _cle, _module in (
    ("bm25", "diapason.tools.storage.bm25"),
    ("faiss", "diapason.tools.storage.faiss_backend"),
    ("colbert", "diapason.tools.storage.colbert_backend"),
    ("hybrid", "diapason.tools.storage.hybrid"),
    ("dense", "diapason.tools.storage.dense"),
):
    MemoryRegistry.register_lazy(_cle, _module)


__all__ = [
    "Chunk",
    "ChunkConfig",
    "ContextConfig",
    "MemoryBackend",
    "RetrievalResult",
    "chunk_text",
    "inject_context",
    "ingest_path",
    "read_document",
]
