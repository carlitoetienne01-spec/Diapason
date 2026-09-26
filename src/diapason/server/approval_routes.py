"""REST endpoints for the proactive-agent approval queue."""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Dict, Optional

from diapason.tools.approval_store import (
    STATUS_APPROVED,
    STATUS_DENIED,
    ApprovalStore,
    PendingAction,
)

try:
    from fastapi import APIRouter, HTTPException
except ImportError:
    raise ImportError("fastapi is required for approval routes")

logger = logging.getLogger(__name__)

router = APIRouter()

# Singleton that shares the same DB file as ProactiveAgent (WAL mode is safe)
_store: Optional[ApprovalStore] = None


def _get_store() -> ApprovalStore:
    global _store
    if _store is None:
        _store = ApprovalStore()
    return _store


def _serialize(action: PendingAction) -> Dict[str, Any]:
    return {
        "id": action.id,
        "action_type": action.action_type,
        "description": action.description,
        "payload": action.payload,
        "permission_key": action.permission_key,
        "tier": action.tier,
        "status": action.status,
        "created_at": action.created_at,
        "expires_at": action.expires_at,
    }


# 26/09/2026, phase 5 du plan mobile : ces trois routes lisaient et
# écrivaient SQLite sur la boucle d'événements (CLAUDE.md §5, « une route
# async qui appelle du bloquant gèle tout »). La cloche du Mac les relit
# toutes les secondes quand une demande attend, et le téléphone les sonde
# désormais aussi ; ``sqlite3`` attend jusqu'à 5 s un verrou tenu par un
# autre écrivain (le pont d'approbation, l'agent proactif) — cinq secondes
# pendant lesquelles le flux du chat, la voix et la cloche elle-même se
# taisent. Le travail passe dans un fil.
#
# Le verrou garde ce que la boucle garantissait sans le dire : « lire la
# demande, vérifier qu'elle attend, écrire la décision » était atomique
# parce que rien ne s'intercalait entre deux lignes sans ``await``. Dans des
# fils, le Mac qui approuve et le téléphone qui refuse la même demande
# passeraient tous deux le contrôle ``pending`` — et le second écraserait la
# décision du premier au lieu de recevoir 409. Il sert aussi la connexion
# unique du magasin, partagée entre fils (``check_same_thread=False``).
_verrou = threading.Lock()


def _lister() -> Dict[str, Any]:
    with _verrou:
        store = _get_store()
        store.expire_stale()
        actions = store.list_pending()
        return {"actions": [_serialize(a) for a in actions], "count": len(actions)}


def _decider(action_id: str, statut: str) -> None:
    with _verrou:
        store = _get_store()
        action = store.get_action(action_id)
        if action is None:
            raise HTTPException(status_code=404, detail="Action not found")
        if action.status != "pending":
            # A stale bell (10 s poll) must not resurrect a timed-out or
            # already-decided action into a phantom "approved".
            raise HTTPException(409, f"Action already {action.status}")
        store.update_status(action_id, statut)


@router.get("/v1/approvals/pending")
async def list_pending_approvals() -> Dict[str, Any]:
    return await asyncio.to_thread(_lister)


@router.post("/v1/approvals/{action_id}/approve")
async def approve_action(action_id: str) -> Dict[str, Any]:
    await asyncio.to_thread(_decider, action_id, STATUS_APPROVED)
    logger.info("Action %s approved via UI", action_id)
    return {"status": "approved", "id": action_id}


@router.post("/v1/approvals/{action_id}/deny")
async def deny_action(action_id: str) -> Dict[str, Any]:
    await asyncio.to_thread(_decider, action_id, STATUS_DENIED)
    logger.info("Action %s denied via UI", action_id)
    return {"status": "denied", "id": action_id}


__all__ = ["router"]
