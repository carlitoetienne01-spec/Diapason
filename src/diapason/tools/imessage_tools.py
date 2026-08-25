"""« Lis ma conversation avec Maman » — chat.db, en lecture, honnêtement.

Atlas, grand chantier n°1, 25 août 2026. imessage_get_conversation était
déclaré depuis des mois sans exécuteur. L'outil vit ici : données
strictement locales (chat.db en lecture seule), le petit nom résolu par le
même résolveur que messages_send, et les trois issues explicites de la
maison — trouvé, rien, ou illisible-avec-le-remède (l'Accès complet au
disque manque encore sur cette machine : l'outil l'avoue, il ne se tait
pas).
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

from diapason.core.registry import ToolRegistry
from diapason.core.types import ToolResult
from diapason.tools._stubs import BaseTool, ToolSpec

logger = logging.getLogger(__name__)

_DB_PAR_DEFAUT = str(Path.home() / "Library" / "Messages" / "chat.db")


def lire_conversation(
    identifiant: str, *, limite: int = 30, db_path: str = _DB_PAR_DEFAUT
) -> dict:
    """Les derniers messages avec un correspondant — issues explicites.

    {"issue": "unreadable"|"not_found"|"found", "messages": [...],
    "sans_texte": n}. Les rangées au texte NULL (attributedBody des macOS
    récents) sont comptées, pas inventées.
    """
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.OperationalError as exc:
        return {"issue": "unreadable", "detail": str(exc), "messages": []}
    try:
        lignes = conn.execute(
            "SELECT m.text, m.is_from_me, m.date "
            "FROM message m "
            "JOIN chat_message_join cmj ON cmj.message_id = m.ROWID "
            "JOIN chat c ON c.ROWID = cmj.chat_id "
            "WHERE c.chat_identifier = ? "
            "ORDER BY m.date DESC LIMIT ?",
            (identifiant.strip(), max(1, limite)),
        ).fetchall()
    except sqlite3.OperationalError as exc:
        # TCC a deux portes : l'ouverture peut réussir et la PREMIÈRE
        # lecture échouer (leçon du connecteur imessage).
        return {"issue": "unreadable", "detail": str(exc), "messages": []}
    finally:
        conn.close()
    if not lignes:
        return {"issue": "not_found", "messages": [], "sans_texte": 0}
    from diapason.connectors.imessage import _apple_ts_to_datetime

    messages = []
    sans_texte = 0
    for texte, de_moi, date_ns in reversed(lignes):
        if not texte:
            sans_texte += 1
            continue
        messages.append(
            {
                "texte": texte,
                "de_moi": bool(de_moi),
                "quand": _apple_ts_to_datetime(int(date_ns or 0)).isoformat(
                    timespec="minutes"
                ),
            }
        )
    return {"issue": "found", "messages": messages, "sans_texte": sans_texte}


@ToolRegistry.register("imessage_conversation")
class IMessageConversationTool(BaseTool):
    """La conversation Messages avec quelqu'un, lue dans chat.db."""

    tool_id = "imessage_conversation"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="imessage_conversation",
            description=(
                "Read the recent iMessage/SMS conversation with someone: "
                "« qu'est-ce que maman m'a écrit ? », « lis ma conversation "
                "avec Gaël ». contact can be a NAME as spoken (resolved from "
                "local contacts), a phone, or an iMessage email. Read-only."
            ),
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "contact": {
                        "type": "string",
                        "description": "Name as spoken, phone, or email.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Messages to read (default 30).",
                    },
                },
                "required": ["contact"],
            },
            category="communication",
            requires_confirmation=False,
            timeout_seconds=15.0,
            metadata={"risk": "read_only", "reversible": True},
        )

    def execute(self, **params: Any) -> ToolResult:
        import sys as _sys

        if _sys.platform != "darwin":
            return ToolResult(
                tool_name="imessage_conversation",
                content="imessage_conversation is only implemented on macOS.",
                success=False,
            )
        contact = str(params.get("contact") or "").strip()
        if not contact:
            return ToolResult(
                tool_name="imessage_conversation",
                content="Need a contact (name, phone, or email).",
                success=False,
            )
        try:
            limite = int(params.get("max_results") or 30)
        except (TypeError, ValueError):
            limite = 30
        limite = max(1, min(100, limite))

        # Le même résolveur que messages_send : « maman » → +509…
        from diapason.tools.voice_mac_tools import _resoudre_ou_avouer

        identifiant, fiche, aveu = _resoudre_ou_avouer(
            contact, "imessage_conversation"
        )
        if aveu is not None:
            return aveu

        constat = lire_conversation(identifiant, limite=limite)
        if constat["issue"] == "unreadable":
            from diapason.channels.imessage_status import remede_fda

            return ToolResult(
                tool_name="imessage_conversation",
                content=f"Cannot read the Messages database — {remede_fda()}",
                success=False,
                metadata={"reason": "unreadable"},
            )
        qui = fiche or identifiant
        if constat["issue"] == "not_found" or not constat["messages"]:
            return ToolResult(
                tool_name="imessage_conversation",
                content=f"Aucune conversation Messages avec {qui}.",
                success=True,
                metadata={"found": False, "contact": identifiant},
            )
        lignes = [f"Derniers messages avec {qui} :"]
        for m in constat["messages"]:
            auteur = "Moi" if m["de_moi"] else qui
            texte = " ".join(m["texte"].split())[:200]
            lignes.append(f"[{m['quand'][5:16]}] {auteur} : {texte}")
        if constat["sans_texte"]:
            lignes.append(
                f"({constat['sans_texte']} message(s) sans texte lisible — "
                "images ou effets, non décodés)"
            )
        return ToolResult(
            tool_name="imessage_conversation",
            content="\n".join(lignes),
            success=True,
            metadata={
                "found": True,
                "contact": identifiant,
                "count": len(constat["messages"]),
                "skipped": constat["sans_texte"],
                "persistence": "unchanged",
            },
        )


__all__ = ["IMessageConversationTool", "lire_conversation"]
