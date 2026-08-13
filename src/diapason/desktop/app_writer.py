"""Reliable text insertion into a requested desktop application."""

from __future__ import annotations

import sys
from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class WriteResult:
    success: bool
    method: str = ""
    app: str = ""
    verified: bool = False
    detail: str = ""


def write_text(text: str, *, app_name: str = "", timeout_s: float = 2.0) -> WriteResult:
    """Focus *app_name* when supplied, insert text, and verify focus.

    The preferred AX path avoids touching the clipboard.  The fallback uses
    Diapason's clipboard-preserving paste implementation.  It never presses
    Return, clicks Send, or submits a form.
    """
    if not text:
        return WriteResult(False, detail="Aucun texte à écrire.")

    resolved = app_name.strip()
    focused = not bool(resolved)
    if resolved:
        from diapason.tools.desktop_tools import open_application

        opened = open_application(resolved)
        if not opened.success:
            return WriteResult(False, app=resolved, detail=opened.content)
        resolved = str(opened.metadata.get("app") or resolved)
        from diapason.desktop.frontmost import wait_until_frontmost

        focused = (
            wait_until_frontmost(resolved, timeout_s=timeout_s)
            if sys.platform == "darwin"
            else True
        )

    # Accessibility insertion is both faster and less invasive than paste.
    try:
        from diapason.desktop.accessibility import insert_text

        if insert_text(text):
            return WriteResult(
                True,
                method="accessibility",
                app=resolved,
                verified=focused,
                detail="Texte écrit par l’API d’accessibilité.",
            )
    except Exception:  # noqa: BLE001 - safe fallback is expected on many hosts
        pass

    from diapason.tools.desktop_tools import PasteToFrontmostTool

    pasted = PasteToFrontmostTool().execute(text=text)
    return WriteResult(
        pasted.success,
        method="clipboard" if pasted.success else "",
        app=resolved,
        verified=bool(pasted.success and focused),
        detail=pasted.content,
    )


__all__ = ["WriteResult", "write_text"]
