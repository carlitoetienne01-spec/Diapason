"""Deterministic date resolution shared by the Succès API and DIA tools."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

DEFAULT_TIMEZONE = "America/Toronto"


@dataclass(frozen=True, slots=True)
class DateResolution:
    status: Literal["exact", "ambiguous", "unrecognized"]
    value: str | None = None
    options: tuple[str, ...] = ()


_WEEKDAYS = {
    "lundi": 0,
    "monday": 0,
    "madi": 1,
    "mardi": 1,
    "tuesday": 1,
    "mekredi": 2,
    "mercredi": 2,
    "wednesday": 2,
    "jedi": 3,
    "jeudi": 3,
    "thursday": 3,
    "vandredi": 4,
    "vendredi": 4,
    "friday": 4,
    "samdi": 5,
    "samedi": 5,
    "saturday": 5,
    "dimanch": 6,
    "dimanche": 6,
    "sunday": 6,
}


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.strip().lower())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _today(timezone: str, now: datetime | date | None) -> date:
    if isinstance(now, datetime):
        if now.tzinfo is None:
            return now.date()
        return now.astimezone(ZoneInfo(timezone)).date()
    if isinstance(now, date):
        return now
    return datetime.now(ZoneInfo(timezone)).date()


def _next_weekday(day: date, weekday: int) -> date:
    delta = (weekday - day.weekday()) % 7
    return day + timedelta(days=delta or 7)


def resolve_date_expression(
    expression: str | None,
    *,
    timezone: str = DEFAULT_TIMEZONE,
    now: datetime | date | None = None,
) -> DateResolution:
    """Resolve common French, Haitian Creole and English date expressions.

    Ambiguous phrases such as ``vendredi prochain`` deliberately return two
    choices and never write data. This ports the legacy PHP assistant rule.
    """

    raw = (expression or "").strip()
    if not raw:
        return DateResolution("unrecognized")
    folded = _fold(raw)
    today = _today(timezone, now)

    try:
        parsed = date.fromisoformat(raw)
    except ValueError:
        parsed = None
    if parsed is not None:
        return DateResolution("exact", parsed.isoformat())

    french = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", folded)
    if french:
        try:
            parsed = date(
                int(french.group(3)), int(french.group(2)), int(french.group(1))
            )
        except ValueError:
            return DateResolution("unrecognized")
        return DateResolution("exact", parsed.isoformat())

    relative = {
        "aujourd'hui": 0,
        "aujourdhui": 0,
        "today": 0,
        "jodi a": 0,
        "jodia": 0,
        "demain": 1,
        "tomorrow": 1,
        "demen": 1,
        "apres-demain": 2,
        "apres demain": 2,
        "day after tomorrow": 2,
        "apre demen": 2,
        "hier": -1,
        "yesterday": -1,
        "ye": -1,
    }
    if folded in relative:
        return DateResolution(
            "exact", (today + timedelta(days=relative[folded])).isoformat()
        )

    plus = re.fullmatch(r"\+(\d{1,4})\s*j", folded)
    if plus:
        return DateResolution(
            "exact", (today + timedelta(days=int(plus.group(1)))).isoformat()
        )

    in_amount = re.fullmatch(
        r"(?:dans|in)\s+(\d{1,4})\s+(jour|jours|day|days|semaine|semaines|week|weeks)",
        folded,
    )
    if in_amount:
        amount = int(in_amount.group(1))
        if "semaine" in in_amount.group(2) or "week" in in_amount.group(2):
            amount *= 7
        return DateResolution("exact", (today + timedelta(days=amount)).isoformat())

    if folded in {"ce weekend", "ce week-end", "this weekend"}:
        saturday = today + timedelta(days=(5 - today.weekday()) % 7)
        return DateResolution("exact", saturday.isoformat())
    if folded in {"semaine prochaine", "la semaine prochaine", "next week"}:
        monday = today + timedelta(days=(7 - today.weekday()))
        return DateResolution("exact", monday.isoformat())

    weekday_match = re.fullmatch(r"([a-z]+)(?:\s+(prochain|prochaine|next))?", folded)
    if weekday_match and weekday_match.group(1) in _WEEKDAYS:
        first = _next_weekday(today, _WEEKDAYS[weekday_match.group(1)])
        if weekday_match.group(2):
            return DateResolution(
                "ambiguous",
                options=(first.isoformat(), (first + timedelta(days=7)).isoformat()),
            )
        return DateResolution("exact", first.isoformat())

    return DateResolution("unrecognized")


def normalize_time(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    match = re.fullmatch(r"(\d{1,2})(?::|h)(\d{2})", raw.lower())
    if not match:
        raise ValueError("L'heure doit être au format HH:mm.")
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        raise ValueError("L'heure doit être comprise entre 00:00 et 23:59.")
    return f"{hour:02d}:{minute:02d}"


__all__ = [
    "DEFAULT_TIMEZONE",
    "DateResolution",
    "normalize_time",
    "resolve_date_expression",
]
