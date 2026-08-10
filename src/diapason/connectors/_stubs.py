"""Base types for data source connectors."""

from __future__ import annotations

import functools
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional

from diapason.tools._stubs import ToolSpec

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Attachment:
    """A file attached to a document (email attachment, shared file, etc.)."""

    filename: str
    mime_type: str
    size_bytes: int
    sha256: str = ""
    content: bytes = field(default=b"", repr=False)


@dataclass(slots=True)
class Document:
    """Universal schema for data from any connector.

    All connectors normalize their output to this format before ingestion.

    v1 schema fields (``source_id``, ``participants_raw``, ``channel``) default
    to empty so existing connectors compile without modification; new
    connectors should populate them. The pipeline derives ``source_id`` from
    ``doc_id`` by stripping the ``{source}:`` prefix when not set explicitly.
    """

    doc_id: str
    source: str
    doc_type: str
    content: str
    title: str = ""
    author: str = ""
    participants: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)
    thread_id: Optional[str] = None
    url: Optional[str] = None
    attachments: List[Attachment] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    # v1 schema additions: defaulted empty so legacy connectors keep working.
    source_id: str = ""
    participants_raw: List[str] = field(default_factory=list)
    channel: Optional[str] = None


@dataclass(slots=True)
class SyncStatus:
    """Progress of a connector's sync operation."""

    state: str = "idle"
    items_synced: int = 0
    items_total: int = 0
    last_sync: Optional[datetime] = None
    cursor: Optional[str] = None
    error: Optional[str] = None


class BaseConnector(ABC):
    """Abstract base for data source connectors.

    Each connector knows how to authenticate with a service, bulk-sync
    its data as ``Document`` objects, and optionally expose MCP tools
    for real-time agent queries.
    """

    connector_id: str
    display_name: str
    auth_type: str  # "oauth" | "local" | "bridge" | "filesystem"

    # Does the DATA stay on this machine? Deliberately not derived from
    # ``auth_type``, which describes the credential mechanism and not the data
    # path: ``hackernews`` and ``news_rss`` both declare ``auth_type="local"``
    # meaning "needs no login", while one queries hacker-news.firebaseio.com
    # and the other fetches remote feeds. Conflating the two would have opened
    # exactly the hole this guard exists to close.
    #
    # Fail-closed: a connector that does not claim locality does not get it.
    is_local: bool = False

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Install the local-only guard on every connector subclass.

        ``sync`` is abstract, so a guard in its body would never run; it is
        wrapped at subclass-definition time instead.

        A refused connector yields NOTHING rather than raising. That is the
        honest degradation for this layer: ``digest_collect`` iterates several
        connectors, so a morning digest in local-only mode still contains
        Apple Health, Notes and iMessage instead of failing whole.
        """
        super().__init_subclass__(**kwargs)
        sync = cls.__dict__.get("sync")
        if sync is None or getattr(sync, "_local_only_guarded", False):
            return
        if getattr(sync, "__isabstractmethod__", False):
            return

        @functools.wraps(sync)
        def _guarded_sync(
            self: "BaseConnector", *args: Any, **kw: Any
        ) -> Iterator[Any]:
            if not getattr(self, "is_local", False):
                from diapason.core.local_mode import local_only

                if local_only():
                    name = getattr(self, "connector_id", "") or cls.__name__
                    logger.info(
                        "local-mode: connector %r is remote — yielding nothing", name
                    )
                    return iter(())
            return sync(self, *args, **kw)

        _guarded_sync._local_only_guarded = True  # type: ignore[attr-defined]
        cls.sync = _guarded_sync  # type: ignore[method-assign]

    @abstractmethod
    def is_connected(self) -> bool:
        """Return True if the connector has valid credentials."""

    @abstractmethod
    def disconnect(self) -> None:
        """Revoke credentials and clean up."""

    @abstractmethod
    def sync(
        self, *, since: Optional[datetime] = None, cursor: Optional[str] = None
    ) -> Iterator[Document]:
        """Yield documents from the data source.

        If *since* is given, only return items created/modified after that time.
        If *cursor* is given, resume from a previous checkpoint.
        """

    @abstractmethod
    def sync_status(self) -> SyncStatus:
        """Return current sync progress."""

    def auth_url(self) -> str:
        """Generate an OAuth consent URL.  Only relevant for auth_type='oauth'."""
        raise NotImplementedError(f"{self.connector_id} does not use OAuth")

    def handle_callback(self, code: str) -> None:
        """Handle the OAuth callback.  Only relevant for auth_type='oauth'."""
        raise NotImplementedError(f"{self.connector_id} does not use OAuth")

    def mcp_tools(self) -> List[ToolSpec]:
        """Return MCP tool specs for real-time agent queries.  Optional."""
        return []
