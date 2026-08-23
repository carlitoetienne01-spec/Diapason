"""Rappels et Calendrier : créer ce que l'utilisateur dicte.

Suite directe des actions dans les applications (23 août 2026) : après
« cherche dans l'App Store » et « écris dans Notes », voici « rappelle-moi
d'appeler le dentiste demain à 15 heures » et « ajoute un rendez-vous
coiffeur demain à 10 heures ». Mains occupées, zéro clavier.

Les dates parlées passent par ``resolve_date_expression`` — le même analyseur
que le module Succès : français, créole haïtien et anglais, et surtout le
REFUS des dates ambiguës. « Vendredi prochain » peut désigner deux jours ;
plutôt que d'en choisir un en silence, l'outil rend les deux propositions et
le modèle fait préciser. Un rendez-vous posé le mauvais jour est pire
qu'une question de plus.

La date part vers AppleScript en NOMBRES (année, mois, jour, heure, minute),
jamais en texte : ``date "…"`` se lit selon la langue du système, et une
machine anglaise inverserait jour et mois. Poser ``day of d to 1`` avant le
mois évite le débordement (31 → mois suivant). Comme partout, le texte de
l'utilisateur passe en argv, hors de portée de toute évasion.
"""

from __future__ import annotations

import re
from typing import Any

from diapason.core.registry import ToolRegistry
from diapason.tools._stubs import BaseTool, ToolResult, ToolSpec
from diapason.tools.app_actions import _osascript

_DUREE_DEFAUT_MIN = 60


def _date_parlee(valeur: str) -> tuple[str, str] | tuple[None, str]:
    """(« YYYY-MM-DD », "") ou (None, message d'erreur honnête)."""
    from diapason.succes.dates import resolve_date_expression

    brut = str(valeur or "").strip()
    if not brut:
        return None, "Il manque le jour."
    resolution = resolve_date_expression(brut)
    if resolution.status == "ambiguous":
        options = " ou ".join(resolution.options)
        return None, (
            f"« {brut} » peut désigner deux jours : {options}. Fais préciser."
        )
    if resolution.status != "exact" or not resolution.value:
        return None, f"Je n'ai pas reconnu le jour « {brut} »."
    return resolution.value, ""


def _heure_parlee(valeur: str) -> tuple[int, int] | tuple[None, str]:
    """« 15:00 », « 15h », « 15 h 30 », « 9 heures » → (heure, minute)."""
    brut = (
        str(valeur or "").strip().lower().replace("heures", "h").replace("heure", "h")
    )
    if not brut:
        return None, "Il manque l'heure."
    m = re.fullmatch(r"(\d{1,2})\s*(?::|h)?\s*(\d{2})?", brut)
    if not m:
        return None, f"Je n'ai pas reconnu l'heure « {valeur} »."
    heure, minute = int(m.group(1)), int(m.group(2) or 0)
    if heure > 23 or minute > 59:
        return None, "L'heure doit tenir entre 00:00 et 23:59."
    return heure, minute


_SCRIPT_DATE = """
  set d to current date
  set time of d to 0
  set day of d to 1
  set year of d to (item 1 of argv as integer)
  set month of d to (item 2 of argv as integer)
  set day of d to (item 3 of argv as integer)
  set time of d to (item 4 of argv as integer) * 3600 + (item 5 of argv as integer) * 60
"""


@ToolRegistry.register("reminders_write")
class RemindersWriteTool(BaseTool):
    """Create, list or complete reminders in the Apple Reminders app."""

    tool_id = "reminders_write"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="reminders_write",
            description=(
                "The Apple Reminders app. Create a reminder — « rappelle-moi "
                "d'appeler le dentiste demain à 15 h » —, list the pending "
                "ones, or mark one done by its name. Spoken days work: "
                "aujourd'hui, demain, lundi… For Succès tasks use "
                "succes_tasks instead; this is the system Reminders app."
            ),
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["create", "list", "complete"],
                    },
                    "name": {
                        "type": "string",
                        "description": (
                            "Reminder text (create) or name to match (complete)."
                        ),
                    },
                    "date": {
                        "type": "string",
                        "description": (
                            "Spoken or exact day: demain, lundi, 2026-08-25."
                        ),
                    },
                    "time": {"type": "string", "description": "Optional: 15:00, 15 h."},
                },
                "required": ["action"],
            },
            category="system",
            timeout_seconds=25.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        action = str(params.get("action") or "")
        if action == "create":
            return self._creer(params)
        if action == "list":
            return self._lister()
        if action == "complete":
            return self._cocher(str(params.get("name") or ""))
        return ToolResult(
            tool_name="reminders_write",
            content="L'action doit être create, list ou complete.",
            success=False,
        )

    def _creer(self, params: dict) -> ToolResult:
        nom = str(params.get("name") or "").strip()
        if not nom:
            return ToolResult(
                tool_name="reminders_write",
                content="Il manque le texte du rappel.",
                success=False,
            )
        date_brute = str(params.get("date") or "").strip()
        if date_brute:
            jour, erreur = _date_parlee(date_brute)
            if jour is None:
                return ToolResult(
                    tool_name="reminders_write", content=erreur, success=False
                )
            heure, minute = 9, 0  # sans heure dite, un rappel du matin
            if str(params.get("time") or "").strip():
                hm = _heure_parlee(str(params.get("time")))
                if hm[0] is None:
                    return ToolResult(
                        tool_name="reminders_write", content=hm[1], success=False
                    )
                heure, minute = hm
            a, m, j = jour.split("-")
            script = (
                "on run argv\n"
                + _SCRIPT_DATE
                + """
  tell application "Reminders"
    make new reminder with properties {name:item 6 of argv, due date:d}
  end tell
  return "ok"
end run"""
            )
            ok, sortie = _osascript(script, a, m, j, str(heure), str(minute), nom)
            quand = f" pour le {jour} à {heure:02d}:{minute:02d}"
        else:
            script = """
on run argv
  tell application "Reminders"
    make new reminder with properties {name:item 1 of argv}
  end tell
  return "ok"
end run"""
            ok, sortie = _osascript(script, nom)
            quand = ""
        if not ok:
            return ToolResult(
                tool_name="reminders_write",
                content=f"Rappels n'a pas répondu : {sortie}",
                success=False,
            )
        return ToolResult(
            tool_name="reminders_write",
            content=f"Rappel « {nom} » créé{quand}.",
            success=True,
        )

    def _lister(self) -> ToolResult:
        script = """
on run argv
  tell application "Reminders"
    set lignes to ""
    set restants to (reminders whose completed is false)
    set n to count of restants
    repeat with r in restants
      set quand to ""
      if due date of r is not missing value then ¬
        set quand to " — " & (due date of r as text)
      set lignes to lignes & (name of r) & quand & linefeed
    end repeat
    return (n as text) & linefeed & lignes
  end tell
end run"""
        ok, sortie = _osascript(script)
        if not ok:
            return ToolResult(
                tool_name="reminders_write",
                content=f"Rappels n'a pas répondu : {sortie}",
                success=False,
            )
        lignes = [x for x in sortie.split("\n") if x.strip()]
        compte = lignes[0] if lignes else "0"
        details = lignes[1:13]
        return ToolResult(
            tool_name="reminders_write",
            content=f"{compte} rappel(s) en attente.",
            success=True,
            metadata={"count": int(compte or 0), "reminders": details},
        )

    def _cocher(self, nom: str) -> ToolResult:
        if not nom.strip():
            return ToolResult(
                tool_name="reminders_write",
                content="Quel rappel faut-il cocher ?",
                success=False,
            )
        script = """
on run argv
  tell application "Reminders"
    set cibles to (reminders whose completed is false ¬
      and name contains (item 1 of argv))
    if (count of cibles) is 0 then return "absent"
    set completed of item 1 of cibles to true
    return name of item 1 of cibles
  end tell
end run"""
        ok, sortie = _osascript(script, nom)
        if not ok:
            return ToolResult(
                tool_name="reminders_write",
                content=f"Rappels n'a pas répondu : {sortie}",
                success=False,
            )
        if sortie == "absent":
            return ToolResult(
                tool_name="reminders_write",
                content=f"Aucun rappel en attente ne contient « {nom} ».",
                success=False,
            )
        return ToolResult(
            tool_name="reminders_write",
            content=f"Rappel « {sortie} » coché.",
            success=True,
        )


@ToolRegistry.register("calendar_add")
class CalendarAddTool(BaseTool):
    """Create a calendar event from a dictated request."""

    tool_id = "calendar_add"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="calendar_add",
            description=(
                "Create an event in the Mac Calendar — « ajoute un rendez-vous "
                "coiffeur demain à 10 h ». Needs a summary, a day (spoken days "
                "work: demain, lundi…) and a start time; duration defaults to "
                "one hour. To READ the agenda use calendar_query."
            ),
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "summary": {"type": "string", "description": "Event title."},
                    "date": {
                        "type": "string",
                        "description": "Spoken or exact day: demain, 2026-08-25.",
                    },
                    "time": {"type": "string", "description": "Start: 10:00, 10 h."},
                    "duration_minutes": {"type": "integer"},
                    "calendar": {
                        "type": "string",
                        "description": (
                            "Calendar name; default: the first personal one."
                        ),
                    },
                },
                "required": ["summary", "date", "time"],
            },
            category="system",
            timeout_seconds=30.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        titre = str(params.get("summary") or "").strip()
        if not titre:
            return ToolResult(
                tool_name="calendar_add",
                content="Il manque le titre du rendez-vous.",
                success=False,
            )
        jour, erreur = _date_parlee(str(params.get("date") or ""))
        if jour is None:
            return ToolResult(tool_name="calendar_add", content=erreur, success=False)
        hm = _heure_parlee(str(params.get("time") or ""))
        if hm[0] is None:
            return ToolResult(tool_name="calendar_add", content=hm[1], success=False)
        heure, minute = hm
        try:
            duree = max(5, min(24 * 60, int(params.get("duration_minutes") or 0)))
        except (TypeError, ValueError):
            duree = _DUREE_DEFAUT_MIN
        if not params.get("duration_minutes"):
            duree = _DUREE_DEFAUT_MIN
        calendrier = str(params.get("calendar") or "").strip()

        a, m, j = jour.split("-")
        script = (
            "on run argv\n"
            + _SCRIPT_DATE
            + """
  set fin to d + (item 6 of argv as integer) * 60
  set voulu to item 7 of argv
  tell application "Calendar"
    if voulu is "" then
      set cible to first calendar whose writable is true
    else
      if not (exists calendar voulu) then
        set AppleScript's text item delimiters to ", "
        set liste to (name of calendars) as text
        set AppleScript's text item delimiters to ""
        return "?" & linefeed & liste
      end if
      set cible to calendar voulu
    end if
    tell cible
      make new event with properties ¬
        {summary:item 8 of argv, start date:d, end date:fin}
    end tell
    return name of cible
  end tell
end run"""
        )
        ok, sortie = _osascript(
            script, a, m, j, str(heure), str(minute), str(duree), calendrier, titre
        )
        if not ok:
            return ToolResult(
                tool_name="calendar_add",
                content=f"Calendrier n'a pas répondu : {sortie}",
                success=False,
            )
        if sortie.startswith("?"):
            noms = sortie.split("\n", 1)[1] if "\n" in sortie else ""
            return ToolResult(
                tool_name="calendar_add",
                content=(
                    f"Aucun calendrier « {calendrier} ». Ceux qui existent : {noms}."
                ),
                success=False,
            )
        return ToolResult(
            tool_name="calendar_add",
            content=(
                f"Rendez-vous « {titre} » ajouté au calendrier {sortie}, "
                f"le {jour} à {heure:02d}:{minute:02d} ({duree} min)."
            ),
            success=True,
        )


__all__ = ["CalendarAddTool", "RemindersWriteTool"]
