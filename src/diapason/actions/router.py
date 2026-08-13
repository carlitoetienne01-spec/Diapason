"""Conservative FR/EN router for obvious desktop commands."""

from __future__ import annotations

import re

from diapason.actions.models import ActionPlan, ActionRisk
from diapason.desktop.voice_commands import parse_voice_command

# Never put these operations on the confirmation-free path.  They are either
# externally committing, destructive, privileged, or too easy to trigger by
# accident.  The normal agent path remains available and fail-closed.
_BLOCKED = re.compile(
    r"\b(?:envoie|envoyer|send|supprime|supprimer|delete|efface|erase|"
    r"ach[eè]te|acheter|buy|purchase|paie|payer|pay|installe|installer|install|"
    r"d[ée]sinstalle|uninstall|red[ée]marre|restart|[ée]teins|shutdown|"
    r"sudo|mot de passe|password|virement|transfer)\b",
    re.IGNORECASE,
)

_OPEN_AND_TYPE = re.compile(
    r"^\s*(?:ouvre|open|lance|launch|d[ée]marre|start)\s+"
    r"(?P<app>.+?)\s+(?:et|puis|ensuite|and|then)\s+"
    r"(?:[ée]cris|ecris|write|tape|type|colle|paste|r[ée]dige|redige|"
    r"compose|draft)\s+(?P<text>.+?)\s*$",
    re.IGNORECASE,
)
_TYPE_IN_APP = re.compile(
    r"^\s*(?:[ée]cris|ecris|write|tape|type|colle|paste|r[ée]dige|redige|"
    r"compose|draft)\s+"
    r"(?P<text>.+?)\s+(?:dans|into|in)\s+"
    r"(?:l['’]?application\s+|l['’]?app\s+|the\s+app\s+)?(?P<app>.+?)\s*$",
    re.IGNORECASE,
)
_TYPE_FRONTMOST = re.compile(
    r"^\s*(?:tape|type|colle|paste)\s+(?P<text>.+?)\s+"
    r"(?:ici|l[àa]|dans l['’]application active|in the (?:current|active) app)\s*$",
    re.IGNORECASE,
)
_UNSAFE_TYPE_TARGETS = {
    "terminal",
    "iterm",
    "iterm2",
    "powershell",
    "command prompt",
    "invite de commandes",
    "system settings",
    "réglages système",
    "activity monitor",
}
_SHELL_LIKE_TEXT = re.compile(
    r"(?:^|\s)(?:sudo\b|rm\s+-|shutdown\b|reboot\b|curl\b|wget\b|"
    r"osascript\b|powershell\b|cmd(?:\.exe)?\b|bash\b|zsh\b|sh\s+-c\b)",
    re.IGNORECASE,
)
_GENERATIVE_TEXT = re.compile(
    r"^\s*(?:(?:moi|me)\s+)?(?:un|une|le|la|du|de\s+la|a|an|the)\s+"
    r"(?:(?:court|courte|bref|br[èe]ve|professionnel|professionnelle|"
    r"d[ée]taill[ée]|short|brief|professional|detailed)\s+){0,3}"
    r"(?:r[ée]sum[ée]|summary|po[èe]me|poem|lettre|letter|rapport|report|"
    r"article|message|texte|text|liste|list|note|brouillon|draft)\b",
    re.IGNORECASE,
)


def _clean(value: str) -> str:
    return value.strip().strip(" \t\r\n\"'“”«»")


def _resolve_app(raw: str) -> str:
    candidate = _clean(raw)
    action = parse_voice_command(f"ouvre {candidate}")
    if action.kind == "focus_app" and action.target:
        return action.target
    return candidate


def _unsafe_type_target(app: str) -> bool:
    key = app.casefold().strip()
    if key.endswith(".app"):
        key = key[:-4]
    return key in _UNSAFE_TYPE_TARGETS


class FastActionRouter:
    """Route only explicit commands that do not need model interpretation."""

    def route(self, text: str) -> ActionPlan | None:
        raw = (text or "").strip()
        if not raw or len(raw) > 20_000 or _BLOCKED.search(raw):
            return None

        # The frontmost phrase is a special case of the broader "in app"
        # grammar and must win first.
        match = _TYPE_FRONTMOST.match(raw)
        if match:
            body = _clean(match.group("text"))
            if (
                body
                and "\n" not in body
                and "\r" not in body
                and not _SHELL_LIKE_TEXT.search(body)
            ):
                return ActionPlan(
                    kind="frontmost.type_text",
                    text=body,
                    confidence=0.96,
                    risk=ActionRisk.LOCAL,
                    reason="explicit frontmost typing command",
                )

        for pattern in (_OPEN_AND_TYPE, _TYPE_IN_APP):
            match = pattern.match(raw)
            if match:
                app = _resolve_app(match.group("app"))
                body = _clean(match.group("text"))
                if not app or not body or _unsafe_type_target(app):
                    return None
                return ActionPlan(
                    kind=(
                        "app.generate_and_type"
                        if _GENERATIVE_TEXT.search(body)
                        else "app.type_text"
                    ),
                    target=app,
                    text=body,
                    confidence=0.98,
                    risk=ActionRisk.LOCAL,
                    reason="explicit app + text command",
                )

        voice = parse_voice_command(raw)
        if voice.kind == "none":
            return None
        if voice.kind in {"mail_compose", "messages_compose"}:
            risk = ActionRisk.EXTERNAL_DRAFT
        else:
            risk = ActionRisk.LOCAL
        confidence = 0.99 if voice.kind in {"focus_app", "open_uri", "search"} else 0.93
        return ActionPlan(
            kind=f"voice.{voice.kind}",
            target=voice.target,
            confidence=confidence,
            risk=risk,
            arguments=dict(voice.extra or {}),
            reason="existing deterministic voice intent",
        )


__all__ = ["FastActionRouter"]
