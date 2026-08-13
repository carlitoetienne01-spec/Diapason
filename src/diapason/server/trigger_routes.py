"""Local trigger poll API — clap / wake-word → frontend Talk."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query

from diapason.channels.local_trigger import default_trigger_path


def create_trigger_router() -> APIRouter:
    router = APIRouter(prefix="/v1/triggers", tags=["triggers"])

    @router.get("/poll")
    def poll_triggers(
        since: int = Query(0, ge=0, description="Byte offset into the trigger JSONL"),
        path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return local-trigger events emitted after the requested byte offset."""
        p = Path(path).expanduser() if path else default_trigger_path()
        if not p.is_file():
            return {"events": [], "offset": 0, "path": str(p)}
        size = p.stat().st_size
        offset = min(max(0, since), size)
        events: List[Dict[str, Any]] = []
        with p.open("r", encoding="utf-8") as f:
            f.seek(offset)
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    events.append({"event": "raw", "content": line})
            new_offset = f.tell()
        return {"events": events, "offset": new_offset, "path": str(p)}

    return router
