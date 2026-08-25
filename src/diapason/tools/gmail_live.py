"""Gmail en direct — chercher tout l'historique, archiver, corbeille.

Atlas, grand chantier n°1, 25 août 2026. Le connecteur déclarait
gmail_search_emails depuis des mois sans qu'AUCUN code ne l'exécute — une
main fantôme. Or l'index local ne porte que les mails de la fenêtre de
synchronisation (~200) : « retrouve le mail de la banque de mars » a
besoin de l'API, avec la vraie syntaxe de recherche Gmail.

Trois outils, tous is_local=False — la doctrine du trajet de la DONNÉE
(voice_mac_tools, leçon mail_send) : la requête part chez Google, l'effet
d'un archivage vit chez Google. Le garde structurel de BaseTool les coupe
de lui-même si [privacy] local_only redevient true — aucun code à écrire
pour ça. Les actions passent par la cloche : PRIVACY.md promet « archiver
ou mettre à la corbeille uniquement sur sa demande explicite », et la
cloche EST cette demande constatée.
"""

from __future__ import annotations

import logging
from typing import Any

from diapason.core.registry import ToolRegistry
from diapason.core.types import ToolResult
from diapason.tools._stubs import BaseTool, ToolSpec

logger = logging.getLogger(__name__)

_RESULTATS_MAX = 15


def _connecteur():
    """Le connecteur Gmail, ou un message d'aveu s'il n'est pas branché."""
    from diapason.connectors.gmail import GmailConnector

    connecteur = GmailConnector()
    if not connecteur.is_connected():
        return None
    return connecteur


def _entetes(message: dict) -> dict:
    """From / Subject / Date depuis la charge utile d'un message Gmail."""
    import html

    entetes = {
        e.get("name", "").lower(): e.get("value", "")
        for e in (message.get("payload") or {}).get("headers", [])
    }
    return {
        "id": message.get("id", ""),
        "thread_id": message.get("threadId", ""),
        "from": entetes.get("from", ""),
        "subject": entetes.get("subject", "(sans objet)"),
        "date": entetes.get("date", ""),
        "snippet": html.unescape(message.get("snippet", "")),
        "url": f"https://mail.google.com/mail/u/0/#all/{message.get('id', '')}",
    }


_PAS_CONNECTE = (
    "Gmail is not connected. Ask the user to connect it in Sources de données → Gmail."
)


@ToolRegistry.register("gmail_search")
class GmailSearchTool(BaseTool):
    """Chercher dans TOUT l'historique Gmail, en direct."""

    tool_id = "gmail_search"
    # La REQUÊTE de l'utilisateur part chez Google : distant, par trajet de
    # la donnée — même si le code tourne ici.
    is_local = False

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="gmail_search",
            description=(
                "Search the user's ENTIRE Gmail history live, with Gmail "
                "query syntax (from:, subject:, before:/after:, is:unread, "
                "has:attachment). Use it when knowledge_search finds nothing "
                "— the local index only holds recent mail. Results carry "
                "[gmail id=…] for mail_archive / mail_trash / "
                "knowledge_get_document."
            ),
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Gmail search query.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "1-15, default 8.",
                    },
                },
                "required": ["query"],
            },
            category="communication",
            requires_confirmation=False,
            timeout_seconds=90.0,
            metadata={"risk": "read_only", "reversible": True},
        )

    def execute(self, **params: Any) -> ToolResult:
        query = str(params.get("query") or "").strip()
        if not query:
            return ToolResult(
                tool_name="gmail_search",
                content="Need a Gmail search query.",
                success=False,
            )
        try:
            plafond = int(params.get("max_results") or 8)
        except (TypeError, ValueError):
            plafond = 8
        plafond = max(1, min(_RESULTATS_MAX, plafond))
        try:
            from diapason.connectors.gmail import (
                _gmail_api_get_message,
                _gmail_api_list_messages,
            )

            connecteur = _connecteur()
            if connecteur is None:
                return ToolResult(
                    tool_name="gmail_search", content=_PAS_CONNECTE, success=False
                )
            reponse = connecteur._call_with_refresh(
                _gmail_api_list_messages, query=query
            )
            ids = [m.get("id") for m in (reponse.get("messages") or [])][:plafond]
            resultats = [
                _entetes(connecteur._call_with_refresh(_gmail_api_get_message, mid))
                for mid in ids
                if mid
            ]
        except Exception as exc:  # noqa: BLE001 - l'outil répond, ne lève pas
            return ToolResult(
                tool_name="gmail_search",
                content=f"Gmail search failed: {str(exc)[:160]}",
                success=False,
            )
        if not resultats:
            return ToolResult(
                tool_name="gmail_search",
                content=f"Aucun mail pour « {query} » dans Gmail.",
                success=True,
                metadata={"num_results": 0},
            )
        lignes = [f"{len(resultats)} mail(s) pour « {query} » :"]
        for i, r in enumerate(resultats, start=1):
            extrait = " ".join(r["snippet"].split())[:140]
            lignes.append(
                f"{i}. {r['subject']} — {r['from']} ({r['date'][:16]}) "
                f"[gmail id={r['id']}] : {extrait}"
            )
        return ToolResult(
            tool_name="gmail_search",
            content="\n".join(lignes),
            success=True,
            metadata={"num_results": len(resultats), "resultats": resultats},
        )


class _ActionGmail(BaseTool):
    """Socle des actions Gmail : cloche obligatoire, constat honnête."""

    is_local = False
    _verbe = ""

    def _agir(self, connecteur, message_id: str) -> None:
        raise NotImplementedError

    def execute(self, **params: Any) -> ToolResult:
        message_id = str(params.get("message_id") or "").strip()
        if not message_id:
            return ToolResult(
                tool_name=self.tool_id,
                content=(
                    "Need a message_id — gmail_search and digest_collect "
                    "print it as [gmail id=…]."
                ),
                success=False,
            )
        try:
            connecteur = _connecteur()
            if connecteur is None:
                return ToolResult(
                    tool_name=self.tool_id, content=_PAS_CONNECTE, success=False
                )
            self._agir(connecteur, message_id)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                tool_name=self.tool_id,
                content=f"Gmail refused: {str(exc)[:160]}",
                success=False,
            )
        return ToolResult(
            tool_name=self.tool_id,
            content=self._verbe.format(id=message_id),
            success=True,
            metadata={"message_id": message_id, "persistence": "remote"},
        )


@ToolRegistry.register("mail_archive")
class MailArchiveTool(_ActionGmail):
    """Archiver un mail — il quitte la boîte, reste dans Tous les messages."""

    tool_id = "mail_archive"
    _verbe = (
        "Archived [gmail id={id}] — out of the inbox, still in All Mail (reversible)."
    )

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="mail_archive",
            description=(
                "Archive one Gmail message (remove it from the inbox; it "
                "stays in All Mail). ONLY when the user explicitly asked. "
                "message_id comes from gmail_search or digest_collect "
                "([gmail id=…])."
            ),
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "message_id": {
                        "type": "string",
                        "description": "The Gmail message id.",
                    },
                },
                "required": ["message_id"],
            },
            category="communication",
            requires_confirmation=True,
            timeout_seconds=30.0,
            metadata={"risk": "routine_write", "reversible": True},
        )

    def _agir(self, connecteur, message_id: str) -> None:
        connecteur.archive_message(message_id)


@ToolRegistry.register("mail_trash")
class MailTrashTool(_ActionGmail):
    """Mettre un mail à la corbeille Gmail — récupérable 30 jours."""

    tool_id = "mail_trash"
    _verbe = "Moved [gmail id={id}] to Gmail's Trash — recoverable for 30 days."

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="mail_trash",
            description=(
                "Move one Gmail message to Gmail's Trash (recoverable for "
                "30 days). ONLY when the user explicitly asked. message_id "
                "comes from gmail_search or digest_collect ([gmail id=…])."
            ),
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "message_id": {
                        "type": "string",
                        "description": "The Gmail message id.",
                    },
                },
                "required": ["message_id"],
            },
            category="communication",
            requires_confirmation=True,
            timeout_seconds=30.0,
            metadata={"risk": "impactful", "reversible": True},
        )

    def _agir(self, connecteur, message_id: str) -> None:
        connecteur.delete_message(message_id)


__all__ = ["GmailSearchTool", "MailArchiveTool", "MailTrashTool"]
