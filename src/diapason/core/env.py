"""Environment variables — one idiom, with backward compatibility.

The project was renamed OpenJarvis → Diapason, so the variables become
``DIAPASON_*``. Renaming them outright would break every existing setup
SILENTLY: a shell profile, a CI job or a systemd unit exporting
``OPENJARVIS_HOME`` would simply stop being read, with no error — the worst
possible failure mode for a configuration contract.

So each variable is read through :func:`get`, which tries, in order:

1. ``DIAPASON_<NAME>``  — the new name, always wins;
2. the legacy name(s) — ``OPENJARVIS_<NAME>`` and/or ``JARVIS_<NAME>``.

A legacy hit is logged once at DEBUG with the new name to migrate to, so the
old spelling keeps working while telling you it is old.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_warned: set[str] = set()


def _legacy_names(name: str) -> tuple[str, ...]:
    """Historical spellings for a bare variable name.

    Both prefixes existed side by side (``OPENJARVIS_HOME`` but
    ``JARVIS_NUM_CTX``), so both are tried rather than guessing which one a
    given variable used.
    """
    return (f"OPENJARVIS_{name}", f"JARVIS_{name}")


def get(name: str, default: Optional[str] = None) -> Optional[str]:
    """Return ``DIAPASON_<name>``, falling back to the legacy spellings.

    ``name`` is the bare suffix: ``get("HOME")`` reads ``DIAPASON_HOME``, then
    ``OPENJARVIS_HOME``, then ``JARVIS_HOME``.
    """
    new = f"DIAPASON_{name}"
    value = os.environ.get(new)
    if value is not None:
        return value

    for legacy in _legacy_names(name):
        value = os.environ.get(legacy)
        if value is not None:
            if legacy not in _warned:
                _warned.add(legacy)
                logger.debug(
                    "%s is the old name for %s; it still works, but prefer %s",
                    legacy,
                    new,
                    new,
                )
            return value
    return default


def is_set(name: str) -> bool:
    """True when the variable is set under any accepted spelling."""
    return get(name) is not None


def names(name: str) -> tuple[str, ...]:
    """Every spelling read for ``name``, new first — handy for diagnostics."""
    return (f"DIAPASON_{name}", *_legacy_names(name))
