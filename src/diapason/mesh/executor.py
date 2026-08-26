"""Carrying out a verified command on THIS device.

By the time anything here runs, the command has already survived every check
of spec §9. What remains is the narrowest possible action — and the
discipline of spec §34: a remote tool never touches storage directly, it
asks the same services the local UI asks. Otherwise the mesh becomes a second
source of truth, and the two drift.

Screens are opened by publishing an event the desktop shell listens to, not
by driving the window from here: the app already knows how to route
``success://…``, and duplicating that knowledge would guarantee the two
disagree eventually.
"""

from __future__ import annotations

import logging
from typing import Any

from diapason.mesh.commands import RemoteCommand, now_ms

logger = logging.getLogger(__name__)

__all__ = [
    "local_executor",
    "pending_navigations",
    "push_navigation",
    "shell_is_collecting",
]

# Routes waiting for the shell to pick up. Bounded: a UI that never collects
# them must not grow into a memory leak, and a stale route is worthless
# anyway — the user has moved on.
_MAX_PENDING = 16
_pending: list[dict[str, Any]] = []

# When a shell last emptied this queue. `None` means never — this process has
# been running without any window attached to it.
_last_collection_ms: int | None = None

# How long a shell may go quiet before we stop counting it as present.
#
# `MeshHost.tsx` chains `setTimeout(tick, 2000)`, so a visible window collects
# thirty times a minute. A hidden one does not: browsers and WKWebView clamp
# background timers, and past five minutes hidden Chrome drops them to roughly
# ONE PER MINUTE. Ninety seconds therefore covers a whole throttled cycle plus
# jitter. It is not 2000 ms for that reason, and not ten minutes because a
# window closed ten minutes ago will never show anything again — and saying it
# will is the exact lie this constant exists to stop.
_COLLECTION_WINDOW_MS = 90_000


def push_navigation(entry: dict[str, Any]) -> bool:
    """Queue one entry for the shell. False when the queue is full.

    It used to evict the OLDEST — `del _pending[:-_MAX_PENDING]` — and say
    nothing. Those oldest entries had already been answered SUCCESS to the
    device that sent them, so dropping them turned a past promise into a lie
    after the fact, and nothing anywhere recorded it.

    `flush_pending` delivers up to twenty commands per device in one tick
    (`dispatch.limit_per_device`) while this queue holds sixteen, so the case
    is reachable the moment a peer comes back from an hour offline.

    Refusing the NEWEST is the only policy under which every SUCCESS already
    handed out stays true. The new command gets an honest failure instead,
    which its sender can act on — the evicted ones could not.
    """
    if len(_pending) >= _MAX_PENDING:
        logger.warning(
            "shell queue full (%d): refusing a new entry rather than "
            "dropping one already answered SUCCESS",
            _MAX_PENDING,
        )
        return False
    _pending.append(entry)
    return True


def _queue_full() -> dict[str, Any]:
    return {
        "ok": False,
        "errorCode": "SHELL_QUEUE_FULL",
        "userSafeMessage": (
            "Cet appareil a trop de demandes en attente d'affichage : "
            "celle-ci n'a pas été prise."
        ),
    }


def pending_navigations(*, drain: bool = True) -> list[dict[str, Any]]:
    """What the shell should open, oldest first.

    A draining read is the ONLY evidence this process has that a window is
    attached: nothing registers, nothing announces itself, the shell simply
    polls. `drain=False` is a diagnostic read and deliberately does not count
    — looking is not collecting, and a debugging `curl` must not make the
    machine believe someone is watching the screen.
    """
    global _last_collection_ms
    items = list(_pending)
    if drain:
        _last_collection_ms = now_ms()
        _pending.clear()
    return items


def shell_is_collecting(*, now: int | None = None) -> bool:
    """Has a window emptied the queue recently enough to still be there?

    26 August 2026. Every handler below used to push an entry onto `_pending`
    and return a sentence in the past tense — "Notification affichée.",
    "L'élément est affiché." — having displayed precisely nothing. The only
    code that displays anything is the React shell polling `/v1/mesh/inbox`.

    It cost a real evening: a Windows PC ran the Python server with no window
    open at all. Notifications sent from the Mac were answered SUCCESS /
    "Notification affichée.", recorded as such on both machines, while the
    entries sat in `_pending` until the seventeenth pushed the first out
    silently. Nobody saw a thing, and every screen said otherwise (§100).

    This does not prove the notification WILL be shown — the shell could be
    denied permission by the OS a second later. It proves the far more useful
    negative: that nobody is there to show it.
    """
    if _last_collection_ms is None:
        return False
    return (now if now is not None else now_ms()) - _last_collection_ms < (
        _COLLECTION_WINDOW_MS
    )


def _no_shell() -> dict[str, Any]:
    """The honest refusal, per §5: say what is missing and what to do."""
    return {
        "ok": False,
        "errorCode": "NO_SHELL",
        "userSafeMessage": (
            "Aucune fenêtre Diapason n'est ouverte sur cet appareil : "
            "rien n'a pu être affiché."
        ),
    }


def _navigate(command: RemoteCommand) -> dict[str, Any]:
    route = str(command.arguments.get("route") or "")
    if not shell_is_collecting():
        return _no_shell()
    place = push_navigation(
        {
            "route": route,
            "commandId": command.command_id,
            "originDeviceId": command.origin_device_id,
            "receivedAtMs": command.created_at_ms,
        }
    )
    if not place:
        return _queue_full()
    return {"ok": True, "route": route, "userSafeMessage": f"Écran ouvert : {route}."}


def _show_resource(command: RemoteCommand) -> dict[str, Any]:
    kind = str(command.arguments.get("resourceType") or "")
    resource_id = str(command.arguments.get("resourceId") or "")
    # Universal routes (spec §25) are the app's stable vocabulary; the shell
    # translates them per platform.
    plural = {
        "task": "tasks",
        "project": "projects",
        "note": "notes",
        "habit": "habits",
    }
    route = f"success://{plural.get(kind, kind)}/{resource_id}"
    if not shell_is_collecting():
        return _no_shell()
    place = push_navigation(
        {
            "route": route,
            "commandId": command.command_id,
            "originDeviceId": command.origin_device_id,
            "resourceType": kind,
            "resourceId": resource_id,
            "receivedAtMs": command.created_at_ms,
        }
    )
    if not place:
        return _queue_full()
    return {"ok": True, "route": route, "userSafeMessage": "L'élément est affiché."}


def _open(command: RemoteCommand) -> dict[str, Any]:
    if not shell_is_collecting():
        return _no_shell()
    place = push_navigation(
        {
            "route": "success://today",
            "commandId": command.command_id,
            "originDeviceId": command.origin_device_id,
            "focus": True,
            "receivedAtMs": command.created_at_ms,
        }
    )
    if not place:
        return _queue_full()
    return {"ok": True, "userSafeMessage": "Succès est au premier plan."}


def _notify(command: RemoteCommand) -> dict[str, Any]:
    title = str(command.arguments.get("title") or "")
    body = str(command.arguments.get("body") or "")
    # Nothing here displays anything: the entry is handed to the shell, which
    # is the only thing on this machine that owns a screen. With no shell,
    # pushing would be worse than refusing — the entry would surface hours
    # later, out of context, or be dropped by `_MAX_PENDING` without a word.
    if not shell_is_collecting():
        return _no_shell()
    place = push_navigation(
        {
            "notification": {"title": title, "body": body},
            "commandId": command.command_id,
            "originDeviceId": command.origin_device_id,
            "receivedAtMs": command.created_at_ms,
        }
    )
    if not place:
        return _queue_full()
    # Deliberately not "affichée": handing it over is what just happened,
    # displaying it is what the shell will do next. A collecting window
    # closes that gap in about two seconds — but `_COLLECTION_WINDOW_MS`
    # tolerates ninety, so the honest width of this claim is up to ninety
    # seconds, not two. Saying "two" here would be the same shape of lie the
    # sentence itself was rewritten to remove.
    return {"ok": True, "userSafeMessage": "Notification remise à la fenêtre ouverte."}


def _desktop_open(command: RemoteCommand) -> dict[str, Any]:
    """Ouvre une application, une URL, un fichier ou une recherche SUR CETTE
    MACHINE, à la demande d'un appareil appairé.

    Les quatre autres outils du maillage pilotent Succès. Celui-ci pilote le
    bureau, et c'est un pouvoir d'une autre nature : le propriétaire l'a
    demandé explicitement, en connaissant les trois portées possibles
    (validation, liste blanche, ouvert) et en choisissant la troisième.

    Ce qui protège ne dépend pas de ce choix et ne peut pas être désactivé
    par l'appelant : seul un appareil APPAIRÉ peut émettre, chaque ordre
    porte une signature Ed25519 liée à sa clé publique enregistrée et à ses
    arguments exacts, le nonce interdit le rejeu, l'ordre expire, et
    révoquer l'appareil coupe tout immédiatement.

    La cible n'est PAS interprétée ici : elle est passée à ``open_anything``,
    qui possède déjà ses propres garde-fous. Réimplémenter ce tri à côté
    aurait créé un second jeu de règles à maintenir, et c'est ainsi que deux
    chemins finissent par diverger.
    """
    target = str(command.arguments.get("target") or "").strip()
    if not target:
        return {
            "ok": False,
            "userSafeMessage": "Aucune cible à ouvrir n'a été indiquée.",
        }

    from diapason.core.registry import ToolRegistry

    try:
        outil = ToolRegistry.get("open_anything")()
    except Exception as exc:  # noqa: BLE001 - outil absent = refus, pas 500
        logger.warning("open_anything indisponible : %s", exc)
        return {
            "ok": False,
            "userSafeMessage": "L'ouverture d'applications n'est pas "
            "disponible sur cet ordinateur.",
        }

    kind = str(command.arguments.get("kind") or "auto")
    resultat = outil.execute(target=target, kind=kind)
    # Le verdict de l'outil est relayé tel quel. Annoncer « ouvert » sur un
    # échec serait précisément le défaut que l'audit a passé la semaine à
    # retirer d'ici.
    if resultat.success:
        return {
            "ok": True,
            "userSafeMessage": resultat.content or f"{target} est ouvert.",
        }
    # Le contenu de l'outil ne peut PAS tenir seul quand il a échoué.
    # Constaté le 26 août 2026 sur le PC Windows de Carlito : pour une
    # application inexistante, `open_anything` rend success=False avec le
    # contenu « Started ApplicationQuiNExistePasDuTout ». Relayer cette
    # phrase telle quelle donnerait un échec dont le message annonce un
    # succès — le §100 exactement à l'envers.
    return {
        "ok": False,
        "userSafeMessage": (
            f"Échec de l'ouverture : {resultat.content}"
            if resultat.content
            else "Échec de l'ouverture."
        ),
    }


# One handler per tool, resolved by exact name. No dynamic dispatch on a
# string the sender controls — that is how a narrow catalogue quietly
# becomes a universal one.
_HANDLERS = {
    "app.navigate": _navigate,
    "app.show_resource": _show_resource,
    "app.open": _open,
    "notifications.show": _notify,
    # Pilote le BUREAU, pas Succès — voir _desktop_open.
    "desktop.open": _desktop_open,
}


def local_executor(command: RemoteCommand) -> dict[str, Any]:
    handler = _HANDLERS.get(command.tool)
    if handler is None:
        # Unreachable in practice — verify_command already rejects unknown
        # tools — but a missing handler must fail loudly, not silently
        # succeed, if the catalogue and this table ever drift apart.
        raise KeyError(f"Aucun exécuteur pour « {command.tool} ».")
    result = handler(command)
    if "ok" not in result:
        # Unreachable while `test_executor.py` holds: every handler in the
        # table above is checked to state its verdict. Kept because the cost
        # of the two branches is not symmetric — guessing "success" here is
        # how the whole §100 defect of 26 August 2026 began.
        logger.error("handler for %s returned no 'ok' field", command.tool)
        return {
            **result,
            "ok": False,
            "errorCode": "EXECUTOR_SILENT",
            "userSafeMessage": "Cet appareil n'a pas su dire si l'action a abouti.",
        }
    return result
