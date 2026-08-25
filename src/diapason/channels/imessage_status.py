"""Constater dans chat.db qu'un message est réellement parti.

Atlas, panier « Ensuite », 24 août 2026. MessagesSendTool proclamait
« Message sent » sur la seule foi du code retour d'osascript — or Messages
accepte le texte puis échoue parfois en silence (le « Not Delivered » que
seul l'écran montre). La base ~/Library/Messages/chat.db, elle, dit vrai :
``is_sent``, ``is_delivered`` et ``error`` sur chaque rangée sortante.

Lecture seule, trois issues explicites — jamais un [] qui confond « pas
trouvé » avec « pas le droit de regarder » :

- ``unreadable`` : Accès complet au disque manquant (le remède est dans le
  détail) ;
- ``not_found`` : rien d'aussi récent pour ce destinataire ;
- ``found`` : la rangée, avec son verdict.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

_APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)
_DEFAULT_DB_PATH = str(Path.home() / "Library" / "Messages" / "chat.db")


def _dt_to_apple_ns(quand: datetime) -> int:
    """L'inverse de _apple_ts_to_datetime (connectors/imessage.py)."""
    if quand.tzinfo is None:
        quand = quand.replace(tzinfo=timezone.utc)
    return int((quand - _APPLE_EPOCH).total_seconds() * 1_000_000_000)


@dataclass(frozen=True)
class Constat:
    issue: str  # "found" | "not_found" | "unreadable"
    guid: str = ""
    is_sent: bool = False
    is_delivered: bool = False
    error: int = 0
    detail: str = ""


def _normaliser_handle(recipient: str) -> str:
    return (recipient or "").strip()


def find_outgoing(
    recipient: str,
    sent_after: datetime,
    *,
    db_path: str = _DEFAULT_DB_PATH,
) -> Constat:
    """La dernière rangée SORTANTE vers ce destinataire depuis ``sent_after``.

    Calque la jointure de poll_new_messages (imessage_daemon.py) mais côté
    ``is_from_me = 1`` et SANS filtre sur ``text`` — NULL possible sur les
    macOS récents (attributedBody).
    """
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.OperationalError as exc:
        return Constat(issue="unreadable", detail=str(exc))
    try:
        row = conn.execute(
            "SELECT m.guid, m.is_sent, m.is_delivered, m.error "
            "FROM message m "
            "JOIN chat_message_join cmj ON cmj.message_id = m.ROWID "
            "JOIN chat c ON c.ROWID = cmj.chat_id "
            "WHERE m.is_from_me = 1 AND m.date >= ? "
            "AND c.chat_identifier = ? "
            "ORDER BY m.date DESC LIMIT 1",
            (_dt_to_apple_ns(sent_after), _normaliser_handle(recipient)),
        ).fetchone()
    except sqlite3.OperationalError as exc:
        # Base ouverte mais requête refusée (TCC partiel, schéma inattendu).
        return Constat(issue="unreadable", detail=str(exc))
    finally:
        conn.close()
    if row is None:
        return Constat(issue="not_found")
    guid, is_sent, is_delivered, error = row
    return Constat(
        issue="found",
        guid=str(guid or ""),
        is_sent=bool(is_sent),
        is_delivered=bool(is_delivered),
        error=int(error or 0),
    )


def status_by_guid(guid: str, *, db_path: str = _DEFAULT_DB_PATH) -> Constat:
    """Re-vérifier plus tard, quand le « Not Delivered » tardif est possible."""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.OperationalError as exc:
        return Constat(issue="unreadable", detail=str(exc))
    try:
        row = conn.execute(
            "SELECT guid, is_sent, is_delivered, error FROM message "
            "WHERE guid = ? LIMIT 1",
            (guid,),
        ).fetchone()
    except sqlite3.OperationalError as exc:
        return Constat(issue="unreadable", detail=str(exc))
    finally:
        conn.close()
    if row is None:
        return Constat(issue="not_found")
    g, is_sent, is_delivered, error = row
    return Constat(
        issue="found",
        guid=str(g or ""),
        is_sent=bool(is_sent),
        is_delivered=bool(is_delivered),
        error=int(error or 0),
    )


def remede_fda() -> str:
    """Le remède quand chat.db est illisible, pour les contenus d'outils."""
    return (
        "Full Disk Access is missing: System Settings → Privacy & Security → "
        "Full Disk Access → add Diapason."
    )


__all__ = [
    "Constat",
    "find_outgoing",
    "remede_fda",
    "status_by_guid",
]
