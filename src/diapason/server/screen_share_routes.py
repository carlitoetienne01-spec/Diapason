"""Screen share status HTTP (for Talk UI badge)."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter


def create_screen_share_router() -> APIRouter:
    router = APIRouter(prefix="/v1/screen_share", tags=["screen_share"])

    @router.get("/status")
    def get_status() -> Dict[str, Any]:
        from diapason.desktop.screen_share import get_screen_share

        return get_screen_share().status()

    return router
