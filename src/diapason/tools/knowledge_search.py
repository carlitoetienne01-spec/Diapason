"""KnowledgeSearchTool — filtered BM25 retrieval with source attribution.

Wraps ``KnowledgeStore`` so agents can search ingested documents by text query
and optional provenance filters (source, doc_type, author, date range).
Optionally delegates to a ``TwoStageRetriever`` for BM25 + reranking.

Depuis le 23 août 2026, l'outil sait aussi se construire SEUL : sans magasin
injecté, il monte à la première recherche la même pile hybride que la
recherche profonde — KnowledgeStore + OllamaEmbedder (nomic-embed-text) +
HybridSearch (BM25 et vecteurs, fusion RRF). C'est ce qui l'a fait entrer
dans la trousse du chat : le savoir personnel (notes Obsidian, Apple Notes,
documents ingérés) était indexé, embarqué… et inaccessible au modèle.
Ollama absent = repli BM25 seul, jamais un échec.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

from diapason.connectors.store import KnowledgeStore
from diapason.core.registry import ToolRegistry
from diapason.core.types import ToolResult
from diapason.tools._stubs import BaseTool, ToolSpec

if TYPE_CHECKING:
    from diapason.connectors.retriever import TwoStageRetriever

logger = logging.getLogger(__name__)


@ToolRegistry.register("knowledge_search")
class KnowledgeSearchTool(BaseTool):
    """Search the knowledge store using filtered BM25 retrieval.

    Results include source attribution so agents can cite provenance.
    When a ``TwoStageRetriever`` is supplied it is used in place of the
    store's direct ``retrieve`` method, enabling optional semantic reranking.
    """

    tool_id = "knowledge_search"

    def __init__(
        self,
        store: Optional[KnowledgeStore] = None,
        retriever: Optional["TwoStageRetriever"] = None,
    ) -> None:
        self._store = store
        self._retriever = retriever
        self._hybride: Any = None  # monté paresseusement, voir _pile_hybride

    def _pile_hybride(self) -> Any:
        """La pile de la recherche profonde, montée une fois, ou None."""
        if self._hybride is not None:
            return self._hybride
        try:
            from diapason.connectors.embeddings import OllamaEmbedder
            from diapason.connectors.hybrid_search import HybridSearch

            magasin = KnowledgeStore()
            embedder: Optional[OllamaEmbedder] = OllamaEmbedder()
            if embedder is not None and not embedder.is_available():
                logger.warning(
                    "knowledge_search : embedder Ollama indisponible, BM25 seul"
                )
                embedder = None
            self._hybride = HybridSearch(magasin, embedder)
        except Exception as exc:  # noqa: BLE001 - l'outil répond, ne lève pas
            logger.warning("knowledge_search : pile hybride impossible (%s)", exc)
            self._hybride = None
        return self._hybride

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="knowledge_search",
            description=(
                "Recherche dans le savoir personnel de l'utilisateur : ses"
                " notes Obsidian, ses Apple Notes et ses documents ingérés"
                " (recherche hybride texte + sens). À utiliser dès que la"
                " question porte sur SES notes, SES écrits, SES projets"
                " documentés — « qu'est-ce que j'ai noté sur… », « retrouve"
                " ma note… ». Filtres optionnels par source et par dates."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Full-text search query.",
                    },
                    "source": {
                        "type": "string",
                        "description": (
                            "Filter by source connector"
                            " (e.g. 'gmail', 'slack', 'obsidian')."
                        ),
                    },
                    "doc_type": {
                        "type": "string",
                        "description": (
                            "Filter by document type"
                            " (e.g. 'email', 'message', 'document')."
                        ),
                    },
                    "author": {
                        "type": "string",
                        "description": "Filter by author.",
                    },
                    "since": {
                        "type": "string",
                        "description": (
                            "Exclude documents before this ISO 8601 timestamp."
                        ),
                    },
                    "until": {
                        "type": "string",
                        "description": (
                            "Exclude documents after this ISO 8601 timestamp."
                        ),
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Maximum number of results (default 10).",
                    },
                },
                "required": ["query"],
            },
            category="knowledge",
        )

    def execute(self, **params: Any) -> ToolResult:
        query: str = params.get("query", "")
        if not query:
            return ToolResult(
                tool_name="knowledge_search",
                content="No query provided.",
                success=False,
            )

        top_k: int = int(params.get("top_k", 10))
        source: Optional[str] = params.get("source")
        doc_type: Optional[str] = params.get("doc_type")
        author: Optional[str] = params.get("author")
        since: Optional[str] = params.get("since")
        until: Optional[str] = params.get("until")

        if self._retriever is not None:
            results = self._retriever.retrieve(
                query,
                top_k=top_k,
                source=source or "",
                doc_type=doc_type or "",
                author=author or "",
                since=since or "",
                until=until or "",
            )
        elif self._store is not None:
            results = self._store.retrieve(
                query,
                top_k=top_k,
                source=source,
                doc_type=doc_type,
                author=author,
                since=since,
                until=until,
            )
        else:
            # Construction nue (la trousse du chat) : la pile hybride.
            hybride = self._pile_hybride()
            if hybride is None:
                return ToolResult(
                    tool_name="knowledge_search",
                    content="Le savoir personnel est inaccessible pour le moment.",
                    success=False,
                )
            return self._chercher_en_hybride(
                hybride,
                query,
                top_k=top_k,
                source=source,
                author=author,
                since=since,
                until=until,
            )

        if not results:
            return ToolResult(
                tool_name="knowledge_search",
                content="No relevant results found.",
                success=True,
                metadata={"num_results": 0},
            )

        lines: list[str] = []
        for i, result in enumerate(results, start=1):
            meta = result.metadata
            src_label = result.source or meta.get("source", "")
            title = meta.get("title", "")
            result_author = meta.get("author", "")
            url = meta.get("url", "")

            # Build header line
            header_parts: list[str] = []
            if src_label:
                header_parts.append(f"[{src_label}]")
            if title:
                header_parts.append(title)
            if result_author:
                header_parts.append(f"by {result_author}")
            if url:
                header_parts.append(f"({url})")

            header = " ".join(header_parts) if header_parts else "(unknown source)"
            lines.append(f"**Result {i}:** {header}")
            lines.append(result.content)
            lines.append("")

        formatted = "\n".join(lines).rstrip()

        return ToolResult(
            tool_name="knowledge_search",
            content=formatted,
            success=True,
            metadata={"num_results": len(results)},
        )

    def _chercher_en_hybride(
        self,
        hybride: Any,
        query: str,
        *,
        top_k: int,
        source: Optional[str],
        author: Optional[str],
        since: Optional[str],
        until: Optional[str],
    ) -> ToolResult:
        """La branche autonome : HybridSearch, résultats parlés en français."""
        from datetime import datetime

        def _date(brut: Optional[str]) -> Optional[datetime]:
            if not brut:
                return None
            try:
                return datetime.fromisoformat(str(brut))
            except ValueError:
                return None

        debut, fin = _date(since), _date(until)
        try:
            touches = hybride.search(
                query,
                person=author or None,
                time_range=(debut, fin) if (debut or fin) else None,
                sources=[source] if source else None,
                limit=max(1, min(int(top_k), 10)),
            )
        except Exception as exc:  # noqa: BLE001 - l'outil répond, ne lève pas
            logger.warning("knowledge_search : recherche en échec (%s)", exc)
            return ToolResult(
                tool_name="knowledge_search",
                content="La recherche dans le savoir personnel a échoué.",
                success=False,
            )

        if not touches:
            return ToolResult(
                tool_name="knowledge_search",
                content="Rien trouvé dans les notes et documents personnels.",
                success=True,
                metadata={"num_results": 0},
            )

        # Le content est écrit pour être LU (voix comprise) ; le détail
        # structuré vit dans metadata, comme partout dans la trousse.
        lignes = [f"{len(touches)} extrait(s) du savoir personnel :"]
        extraits = []
        for i, touche in enumerate(touches, start=1):
            titre = (touche.title or "sans titre").strip()
            fragment = " ".join((touche.content_snippet or "").split())[:300]
            lignes.append(f"{i}. [{touche.source}] {titre} — {fragment}")
            extraits.append(
                {
                    "titre": titre,
                    "source": touche.source,
                    "extrait": fragment,
                    "date": touche.timestamp,
                    "score": round(float(touche.score), 4),
                    # Le dernier kilomètre (Atlas, 25 août 2026) : sans ces
                    # trois champs, impossible de remonter de l'extrait au
                    # document — knowledge_get_document les attend, et l'url
                    # est le deep-link (Gmail, Drive) que l'usager peut
                    # ouvrir. hybrid_search les portait déjà ; ils étaient
                    # jetés ici.
                    "doc_id": touche.document_id,
                    "url": touche.url,
                    "thread_id": touche.thread_id,
                }
            )
        return ToolResult(
            tool_name="knowledge_search",
            content="\n".join(lignes),
            success=True,
            metadata={"num_results": len(touches), "resultats": extraits},
        )


@ToolRegistry.register("knowledge_get_document")
class KnowledgeGetDocumentTool(BaseTool):
    """Le document ENTIER derrière un extrait de recherche.

    Le dernier kilomètre (Atlas, 25 août 2026) : knowledge_search rend des
    extraits de 300 caractères alors que l'index porte le corps COMPLET des
    mails et des notes. Cet outil recoud les chunks — « retrouve le mail de
    X sur Y » devient recherche puis lecture, corps entier, même hors ligne,
    même Ollama éteint.
    """

    tool_id = "knowledge_get_document"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="knowledge_get_document",
            description=(
                "Read the FULL document behind a knowledge_search result: "
                "pass the doc_id from its metadata (e.g. 'gmail:19fec…'). "
                "Returns the whole body — use it when the 300-char excerpt "
                "is not enough: reading a full email, a whole note. "
                "Truncates very long documents; pass max_chars to read more."
            ),
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "doc_id": {
                        "type": "string",
                        "description": "The doc_id from knowledge_search metadata.",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "Body cap (default 6000, max 20000).",
                    },
                },
                "required": ["doc_id"],
            },
            category="memory",
            requires_confirmation=False,
            timeout_seconds=15.0,
            metadata={"risk": "read_only", "reversible": True},
        )

    def execute(self, **params: Any) -> ToolResult:
        doc_id = str(params.get("doc_id") or "").strip()
        if not doc_id:
            return ToolResult(
                tool_name="knowledge_get_document",
                content="Need a doc_id — knowledge_search metadata carries it.",
                success=False,
            )
        try:
            plafond = int(params.get("max_chars") or 6000)
        except (TypeError, ValueError):
            plafond = 6000
        plafond = max(500, min(20000, plafond))
        try:
            magasin = KnowledgeStore()
            doc = magasin.get_document(doc_id)
        except Exception as exc:  # noqa: BLE001 - l'outil répond, ne lève pas
            return ToolResult(
                tool_name="knowledge_get_document",
                content=f"Lecture impossible : {str(exc)[:160]}",
                success=False,
            )
        if doc is None:
            return ToolResult(
                tool_name="knowledge_get_document",
                content=(
                    f"Aucun document {doc_id!r} dans l'index. Le doc_id vient "
                    "de knowledge_search — refais la recherche."
                ),
                success=False,
                metadata={"found": False},
            )
        corps = doc["content"]
        tronque = len(corps) > plafond
        extrait = corps[:plafond]
        entete = f"[{doc['source']}] {doc['title']}"
        if doc["author"]:
            entete += f" — {doc['author']}"
        if doc["timestamp"]:
            entete += f" ({doc['timestamp'][:10]})"
        suite = (
            f"\n… (tronqué : {len(corps)} caractères en tout — "
            "repasse avec max_chars pour la suite)"
            if tronque
            else ""
        )
        return ToolResult(
            tool_name="knowledge_get_document",
            content=f"{entete}\n\n{extrait}{suite}",
            success=True,
            metadata={
                "doc_id": doc_id,
                "source": doc["source"],
                "url": doc["url"],
                "thread_id": doc["thread_id"],
                "chars": len(corps),
                "truncated": tronque,
                "chunks": doc["chunks"],
                "persistence": "unchanged",
            },
        )


__all__ = ["KnowledgeGetDocumentTool", "KnowledgeSearchTool"]
