"""Reading the clock — the one fact a model cannot infer.

A language model has no sense of time. Asked the hour with nothing in its
context, it does not stay silent: it produces a plausible answer, because a
plausible answer is what it was trained to produce. The user then acts on a
time that was invented.

The system prompt carries a stamp taken when it was built, which is enough
for "what day is it" and wrong by the length of the conversation for "what
time is it". This tool is the second half: a clock that can be read again.

Deliberately read-only and free. The assistant should reach for it without
hesitating, because hesitating is how it ends up guessing instead.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from diapason.core.registry import ToolRegistry
from diapason.core.types import ToolResult
from diapason.tools._stubs import BaseTool, ToolSpec

_DAYS_FR = (
    "lundi",
    "mardi",
    "mercredi",
    "jeudi",
    "vendredi",
    "samedi",
    "dimanche",
)
_MONTHS_FR = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)


@ToolRegistry.register("current_time")
class CurrentTimeTool(BaseTool):
    """The current date and time, from this machine's clock."""

    tool_id = "current_time"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="current_time",
            description=(
                "Read the current date, time and timezone from this machine's "
                "clock. Use this whenever the answer depends on when 'now' is "
                "— the time, today's date, what day of the week it is, how "
                "long until something, or resolving 'tomorrow' and 'next "
                "week'. Never state a time or date from memory: you have no "
                "clock of your own and would be inventing one."
            ),
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "offset_days": {
                        "type": "integer",
                        "description": (
                            "Days from today, for resolving « demain » (1) or "
                            "« hier » (-1). Defaults to 0."
                        ),
                    }
                },
            },
            category="system",
            metadata={"risk": "read_only", "reversible": True},
        )

    def execute(self, **params: Any) -> ToolResult:
        offset = params.get("offset_days") or 0
        try:
            days = int(offset)
        except (TypeError, ValueError):
            days = 0
        # Bounded: a model that computes an offset wrongly should get a
        # refusal, not a date in the year 3000 that reads as authoritative.
        if abs(days) > 3650:
            return ToolResult(
                tool_name="current_time",
                success=False,
                content="Décalage hors de portée : indiquez au plus dix ans.",
                metadata={"persistence": "unchanged"},
            )

        now = datetime.now().astimezone()
        stamp = now + timedelta(days=days)

        offset_delta = stamp.utcoffset() or timedelta(0)
        total = int(offset_delta.total_seconds())
        sign = "+" if total >= 0 else "-"
        utc_offset = (
            f"UTC{sign}{abs(total) // 3600:02d}:{(abs(total) % 3600) // 60:02d}"
        )

        day_fr = _DAYS_FR[stamp.weekday()]
        month_fr = _MONTHS_FR[stamp.month - 1]
        readable = f"{day_fr} {stamp.day} {month_fr} {stamp.year}"

        # The sentence is what the assistant will echo, so it is written the
        # way a person says it. The structured fields are for anything that
        # needs to compute rather than repeat.
        content = (
            f"{readable} à {stamp.strftime('%H:%M')} ({stamp.tzname()}, {utc_offset})"
            if days == 0
            else f"{readable} (dans {days} jour(s))"
            if days > 0
            else f"{readable} (il y a {abs(days)} jour(s))"
        )

        return ToolResult(
            tool_name="current_time",
            success=True,
            content=content,
            metadata={
                "iso": stamp.isoformat(timespec="seconds"),
                "date": stamp.strftime("%Y-%m-%d"),
                "time": stamp.strftime("%H:%M:%S"),
                "weekday": day_fr,
                "timezone": stamp.tzname(),
                "utcOffset": utc_offset,
                "utcIso": stamp.astimezone(timezone.utc).isoformat(timespec="seconds"),
                "epochMs": int(stamp.timestamp() * 1000),
                "offsetDays": days,
                "persistence": "unchanged",
            },
        )
