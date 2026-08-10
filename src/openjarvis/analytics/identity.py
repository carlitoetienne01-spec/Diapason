"""Anonymous identity for external analytics.

One UUID v4 per install, persisted to disk on first use. The same file
is referenced by ``scripts/install/install.sh`` so install-time beacon
events tie back to the same person across the install→first-run funnel.

No email, no name, no hardware fingerprint — just an opaque UUID.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from openjarvis.core.config import AnalyticsConfig


def get_or_create_anon_id(path: Path | str) -> str:
    """Return the persisted anon ID, generating one on first call.

    Idempotent across processes — if the file already exists with a
    non-empty value, return it; otherwise generate a fresh UUID v4 and
    write atomically (rename-after-write so a crashed write leaves no
    half-file).
    """
    p = Path(path)
    if p.exists():
        existing = p.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    new_id = str(uuid.uuid4())
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(new_id + "\n", encoding="utf-8")
    tmp.replace(p)
    return new_id


def reset_anon_id(path: Path | str) -> str:
    """Delete the persisted ID and generate a fresh one (privacy reset)."""
    p = Path(path)
    if p.exists():
        p.unlink()
    return get_or_create_anon_id(p)


def is_analytics_enabled(cfg: AnalyticsConfig) -> bool:
    """Return True if analytics is enabled in config.

    Local-only mode overrides ``[analytics] enabled``, which ships as True
    with a hard-coded PostHog host and project key. Telemetry is anonymous and
    carries no conversation content, but "nothing leaves this machine" that
    still phones home on every launch is not a promise — it is a caveat.

    This single predicate is the whole gate: ``AnalyticsClient.__init__``
    consults it before calling ``_init_sdk``, so under local-only no PostHog
    client is ever constructed and the project key is never read.
    """
    if not cfg.enabled:
        return False
    from openjarvis.core.local_mode import local_only

    return not local_only()
