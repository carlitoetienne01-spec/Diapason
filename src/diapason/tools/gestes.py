"""Les gestes d'une seconde — volume, musique, presse-papiers, capture, vitaux.

Atlas, panier « Ensuite », 24 août 2026. « Monte le son » n'avait aucun
outil : l'assistant passait par shell_exec — donc par la cloche, un clic et
jusqu'à quarante-cinq secondes d'attente pour un geste qu'une main fait en
une seconde. La jurisprudence est celle d'open_anything (desktop_tools.py) :
un geste VISIBLE et RÉVERSIBLE ne se gate pas derrière une approbation.

Chaque outil constate au lieu de proclamer : après une commande de lecture,
on redemande au lecteur son état réel ; la capture rend le chemin du fichier
qui existe ; les vitaux disent « illisible » plutôt que d'inventer. Les
fonctions de décision sont pures et testables sans matériel ; subprocess ne
s'appelle que via ``_run``, que les tests remplacent.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from diapason.core.registry import ToolRegistry
from diapason.core.types import ToolResult
from diapason.tools._stubs import BaseTool, ToolSpec

logger = logging.getLogger(__name__)


def _run(cmd: list[str], *, timeout: float = 8.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _osascript(
    script: str, *, timeout: float = 8.0
) -> subprocess.CompletedProcess[str]:
    return _run(["osascript", "-e", script], timeout=timeout)


def _hors_mac(tool_name: str) -> ToolResult:
    return ToolResult(
        tool_name=tool_name,
        success=False,
        content="Ce geste n'existe que sur macOS.",
        metadata={"persistence": "unchanged"},
    )


# ---------------------------------------------------------------------------
# Le volume.
# ---------------------------------------------------------------------------

_PAS_VOLUME = 10


@ToolRegistry.register("volume_control")
class VolumeControlTool(BaseTool):
    """Le volume de sortie du Mac — lire, régler, couper."""

    tool_id = "volume_control"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="volume_control",
            description=(
                "Adjust or read this Mac's output volume. Use it the moment "
                "the user says louder / quieter / mute / « monte le son » / "
                "« mets le volume à N » — never claim the volume changed "
                "without calling it."
            ),
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["up", "down", "set", "mute", "unmute", "get"],
                        "description": "What to do with the output volume.",
                    },
                    "level": {
                        "type": "integer",
                        "description": "Target volume 0-100, only for action=set.",
                    },
                },
                "required": ["action"],
            },
            category="system",
            # Visible et réversible (le geste inverse est le même geste) :
            # pas de cloche, comme open_anything — desktop_tools.py:327-334.
            requires_confirmation=False,
            timeout_seconds=20.0,
            metadata={"risk": "read_only", "reversible": True},
        )

    def execute(self, **params: Any) -> ToolResult:
        if sys.platform != "darwin":
            return self._refus_hors_mac()
        action = str(params.get("action") or "").strip().lower()

        if action == "set":
            try:
                niveau = int(params.get("level"))
            except (TypeError, ValueError):
                return ToolResult(
                    tool_name="volume_control",
                    success=False,
                    content="Il me faut un niveau entre 0 et 100.",
                    metadata={"persistence": "unchanged"},
                )
            niveau = max(0, min(100, niveau))
            ordre = f"set volume output volume {niveau}"
        elif action == "up":
            ordre = (
                "set volume output volume "
                f"((output volume of (get volume settings)) + {_PAS_VOLUME})"
            )
        elif action == "down":
            ordre = (
                "set volume output volume "
                f"((output volume of (get volume settings)) - {_PAS_VOLUME})"
            )
        elif action == "mute":
            ordre = "set volume output muted true"
        elif action == "unmute":
            ordre = "set volume output muted false"
        elif action == "get":
            ordre = ""
        else:
            return ToolResult(
                tool_name="volume_control",
                success=False,
                content="Action inconnue : up, down, set, mute, unmute ou get.",
                metadata={"persistence": "unchanged"},
            )

        try:
            if ordre:
                fait = _osascript(ordre)
                if fait.returncode != 0:
                    return ToolResult(
                        tool_name="volume_control",
                        success=False,
                        content=f"Réglage impossible : {fait.stderr.strip()[:120]}",
                        metadata={"persistence": "unchanged"},
                    )
            # Constater, ne pas proclamer : on relit le volume réel après coup.
            lu = _osascript(
                "output volume of (get volume settings) & "
                "output muted of (get volume settings)"
            )
            volume, coupe = interpreter_volume(lu.stdout)
        except Exception as exc:  # noqa: BLE001 - un geste raté se dit, sans lever
            return ToolResult(
                tool_name="volume_control",
                success=False,
                content=f"Réglage impossible : {str(exc)[:120]}",
                metadata={"persistence": "unchanged"},
            )

        if coupe:
            contenu = "Son coupé."
        elif volume is None:
            contenu = "C'est fait." if ordre else "Volume illisible."
        else:
            contenu = f"Volume à {volume} %."
        return ToolResult(
            tool_name="volume_control",
            success=True,
            content=contenu,
            metadata={
                "volume": volume,
                "muted": coupe,
                "persistence": "unchanged",
            },
        )

    def _refus_hors_mac(self) -> ToolResult:
        return _hors_mac("volume_control")


def interpreter_volume(sortie: str) -> tuple[Optional[int], bool]:
    """(volume, coupé) depuis « 62, false » — (None, False) si illisible."""
    morceaux = [m.strip() for m in (sortie or "").strip().split(",")]
    try:
        volume = int(morceaux[0])
    except (ValueError, IndexError):
        return None, False
    coupe = len(morceaux) > 1 and morceaux[1].lower() == "true"
    return volume, coupe


# ---------------------------------------------------------------------------
# La musique — contrôle de transport du lecteur DÉJÀ en marche.
# ---------------------------------------------------------------------------

# Un `tell application "X"` LANCE X si elle est éteinte, et un tell littéral
# vers une app non installée ouvre à la compilation une boîte « Où se
# trouve X ? » qu'aucun try ne rattrape (même piège que etat_bureau.py).
# On ne parle donc qu'à un lecteur CONSTATÉ en marche via pgrep — s'il
# tourne, il est installé. Spotify d'abord : c'est le lecteur de la maison.
_LECTEURS = ("Spotify", "Music")

_ORDRES_LECTEUR = {
    "playpause": "playpause",
    "play": "play",
    "pause": "pause",
    "next": "next track",
    "previous": "previous track",
}

_ETAT_LECTEUR = (
    'tell application "{app}" to (player state as string) & "\\n" & '
    '(name of current track) & " — " & (artist of current track)'
)


def lecteur_en_marche(runner=None) -> Optional[str]:
    """Le premier lecteur dont le processus tourne — None sinon."""
    for lecteur in _LECTEURS:
        if (runner or _run)(["pgrep", "-x", lecteur]).returncode == 0:
            return lecteur
    return None


@ToolRegistry.register("media_control")
class MediaControlTool(BaseTool):
    """Pause, reprise, piste suivante/précédente — sur le lecteur en marche."""

    tool_id = "media_control"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="media_control",
            description=(
                "Transport control for whatever is ALREADY playing in Spotify "
                "or Music: pause, resume, next/previous track, or ask what is "
                "playing. « mets pause », « chanson suivante », « qu'est-ce "
                "qui joue ? ». To START something new by name, use "
                "spotify_play or open_anything instead."
            ),
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "playpause",
                            "play",
                            "pause",
                            "next",
                            "previous",
                            "now_playing",
                        ],
                        "description": "Transport action on the running player.",
                    },
                },
                "required": ["action"],
            },
            category="system",
            # Visible et réversible (pause ↔ play) : pas de cloche.
            requires_confirmation=False,
            timeout_seconds=20.0,
            metadata={"risk": "read_only", "reversible": True},
        )

    def execute(self, **params: Any) -> ToolResult:
        if sys.platform != "darwin":
            return _hors_mac("media_control")
        action = str(params.get("action") or "").strip().lower()
        if action not in _ORDRES_LECTEUR and action != "now_playing":
            return ToolResult(
                tool_name="media_control",
                success=False,
                content=(
                    "Action inconnue : playpause, play, pause, next, previous "
                    "ou now_playing."
                ),
                metadata={"persistence": "unchanged"},
            )

        lecteur = lecteur_en_marche()
        if lecteur is None:
            return ToolResult(
                tool_name="media_control",
                success=False,
                content=(
                    "Ni Spotify ni Musique ne tourne. Pour lancer quelque "
                    "chose, call spotify_play or open_anything with what to "
                    "play."
                ),
                metadata={"persistence": "unchanged"},
            )

        try:
            if action != "now_playing":
                ordre = f'tell application "{lecteur}" to {_ORDRES_LECTEUR[action]}'
                fait = _osascript(ordre)
                if fait.returncode != 0:
                    return ToolResult(
                        tool_name="media_control",
                        success=False,
                        content=(
                            f"{lecteur} n'a pas répondu : {fait.stderr.strip()[:120]}"
                        ),
                        metadata={"persistence": "unchanged"},
                    )
            # Constater, ne pas proclamer (la régression spotify_play : « the
            # model told the user the music was on while nothing played ») :
            # on redemande au lecteur son état RÉEL et la piste en cours.
            etat, piste = interpreter_etat_lecteur(
                _osascript(_ETAT_LECTEUR.format(app=lecteur)).stdout
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                tool_name="media_control",
                success=False,
                content=f"{lecteur} n'a pas répondu : {str(exc)[:120]}",
                metadata={"persistence": "unchanged"},
            )

        if etat == "playing" and piste:
            contenu = f"Lecture : {piste} ({lecteur})."
        elif etat == "playing":
            contenu = f"Lecture en cours sur {lecteur}."
        elif etat == "paused":
            contenu = f"En pause sur {lecteur}."
        elif action == "now_playing":
            contenu = f"Rien ne joue sur {lecteur}."
        else:
            contenu = f"Arrêté sur {lecteur}."
        return ToolResult(
            tool_name="media_control",
            success=True,
            content=contenu,
            metadata={
                "player": lecteur,
                "state": etat,
                "track": piste,
                "persistence": "unchanged",
            },
        )


def interpreter_etat_lecteur(sortie: str) -> tuple[str, str]:
    """(état, « Titre — Artiste ») — champs vides si le lecteur s'est tu."""
    lignes = (sortie or "").strip().split("\n")
    etat = lignes[0].strip().lower() if lignes else ""
    piste = lignes[1].strip() if len(lignes) > 1 else ""
    return etat, piste


# ---------------------------------------------------------------------------
# Le presse-papiers — lecture, avec un arbitrage assumé.
# ---------------------------------------------------------------------------

_PRESSE_PAPIERS_MAX = 800


@ToolRegistry.register("clipboard_read")
class ClipboardReadTool(BaseTool):
    """Ce que contient le presse-papiers, en texte."""

    tool_id = "clipboard_read"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="clipboard_read",
            description=(
                "Read the text currently on the clipboard. Use it when the "
                "user refers to what they just copied: « qu'est-ce que j'ai "
                "copié ? », « traduis ce que je viens de copier », « ajoute "
                "ça à ma note ». Text only — images and files are reported, "
                "not read."
            ),
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {},
            },
            category="system",
            # Arbitrage assumé (24 août 2026) : c'est une LECTURE qui verse
            # dans le contexte ce que l'utilisateur vient de copier — parfois
            # un secret. Pas de cloche (modèle local, la donnée ne quitte pas
            # la machine, et 45 s d'attente tueraient le geste à la voix),
            # mais texte seulement et tronqué : une bannière, pas un tuyau.
            requires_confirmation=False,
            timeout_seconds=10.0,
            metadata={"risk": "read_only", "reversible": True},
        )

    def execute(self, **params: Any) -> ToolResult:
        if sys.platform != "darwin":
            return _hors_mac("clipboard_read")
        try:
            from diapason.desktop.clipboard import lire_texte

            texte = lire_texte()
        except Exception as exc:  # noqa: BLE001 - PyObjC absent ou pasteboard fermé
            return ToolResult(
                tool_name="clipboard_read",
                success=False,
                content=f"Presse-papiers illisible : {str(exc)[:120]}",
                metadata={"persistence": "unchanged"},
            )
        if not texte:
            return ToolResult(
                tool_name="clipboard_read",
                success=True,
                content=(
                    "Le presse-papiers ne contient pas de texte "
                    "(une image ou un fichier, peut-être)."
                ),
                metadata={"empty": True, "persistence": "unchanged"},
            )
        tronque = len(texte) > _PRESSE_PAPIERS_MAX
        extrait = texte[:_PRESSE_PAPIERS_MAX]
        suite = f" … (tronqué, {len(texte)} caractères en tout)" if tronque else ""
        return ToolResult(
            tool_name="clipboard_read",
            success=True,
            content=f"Presse-papiers : « {extrait} »{suite}",
            metadata={
                "length": len(texte),
                "truncated": tronque,
                "persistence": "unchanged",
            },
        )


# ---------------------------------------------------------------------------
# La capture d'écran — un fichier daté sur le Bureau, comme Cmd+Maj+3.
# ---------------------------------------------------------------------------


@ToolRegistry.register("screen_snap")
class ScreenSnapTool(BaseTool):
    """Une capture d'écran, déposée sur le Bureau."""

    tool_id = "screen_snap"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="screen_snap",
            description=(
                "Take a screenshot and SAVE it as a dated PNG on the "
                "Desktop, like Cmd+Shift+3 — « prends une capture d'écran », "
                "« screenshot ». To LOOK at the screen and answer a "
                "question about it, use screen_describe instead."
            ),
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {},
            },
            category="system",
            # Écrit UN fichier NEUF, horodaté, jamais par-dessus un autre —
            # visible sur le Bureau et réversible d'un glissement vers la
            # corbeille : pas de cloche (même régime qu'open_anything).
            requires_confirmation=False,
            # screencapture porte son propre timeout de 30 s : le nôtre doit
            # être plus large, sinon les deux se marchent dessus.
            timeout_seconds=40.0,
            metadata={"risk": "routine_write", "reversible": True},
        )

    def execute(self, **params: Any) -> ToolResult:
        if sys.platform != "darwin":
            return _hors_mac("screen_snap")
        try:
            from diapason.desktop.screen_capture import capture_screen_to_temp

            temporaire = capture_screen_to_temp()
            horodatage = datetime.now().strftime("%Y-%m-%d à %Hh%M.%S")
            destination = (
                Path.home() / "Desktop" / (f"Capture Diapason {horodatage}.png")
            )
            shutil.move(str(temporaire), destination)
        except Exception as exc:  # noqa: BLE001 - dont le refus Screen Recording
            return ToolResult(
                tool_name="screen_snap",
                success=False,
                content=f"Capture impossible : {str(exc)[:200]}",
                metadata={"persistence": "unchanged"},
            )
        return ToolResult(
            tool_name="screen_snap",
            success=True,
            content=f"Capture posée sur le Bureau : {destination.name}",
            metadata={"path": str(destination), "persistence": "local"},
        )


# ---------------------------------------------------------------------------
# Les vitaux — batterie, Wi-Fi, disque. Trois lectures, aucune inférence.
# ---------------------------------------------------------------------------

_INTERFACE_RESEAU = "en0"

# Constaté le 24 août 2026 : sur macOS récent, `networksetup
# -getairportnetwork` répond « not associated » même connecté, et le SSID
# est caviardé (« <redacted> ») pour tout processus sans permission
# Localisation. On lit donc ce qui reste constatable : le SSID quand macOS
# veut bien le donner (ipconfig getsummary), sinon le fait d'être connecté
# (ipconfig getifaddr rend une adresse).
_SSID_RE = re.compile(r"^\s*SSID\s*:\s*(.+)$", re.M)


def interpreter_wifi(sortie_getsummary: str, sortie_getifaddr: str) -> str:
    """La phrase réseau : nom du Wi-Fi, « connecté », ou « pas de réseau »."""
    m = _SSID_RE.search(sortie_getsummary or "")
    ssid = m.group(1).strip() if m else ""
    if ssid and ssid != "<redacted>":
        return f"Wi-Fi : {ssid}"
    if (sortie_getifaddr or "").strip():
        return "Réseau : connecté"
    return "pas de réseau"


def formater_disque(libre: int, total: int) -> str:
    """« 210 Go libres sur 494 » — en Go décimaux, comme le Finder."""
    return f"{libre / 1e9:.0f} Go libres sur {total / 1e9:.0f}"


@ToolRegistry.register("system_vitals")
class SystemVitalsTool(BaseTool):
    """Batterie, Wi-Fi et disque en une phrase."""

    tool_id = "system_vitals"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="system_vitals",
            description=(
                "Read this Mac's vitals: battery level and charging state, "
                "current Wi-Fi network, free disk space. « il reste combien "
                "de batterie ? », « je suis sur quel réseau ? », « il me "
                "reste de la place ? ». Never answer these from memory."
            ),
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {},
            },
            category="system",
            requires_confirmation=False,
            timeout_seconds=20.0,
            metadata={"risk": "read_only", "reversible": True},
        )

    def execute(self, **params: Any) -> ToolResult:
        if sys.platform != "darwin":
            return _hors_mac("system_vitals")
        morceaux: list[str] = []
        details: dict[str, Any] = {}

        # La batterie — en gardant l'erreur : lire_batterie() de tick.py rend
        # None aussi bien pour « pas de batterie » que pour « pmset a planté »,
        # et un aplomb faux est pire qu'un aveu.
        try:
            from diapason.heartbeat.tick import etat_batterie

            pmset = _run(["pmset", "-g", "batt"])
            if pmset.returncode != 0:
                morceaux.append("batterie illisible")
            else:
                mesure = etat_batterie(pmset.stdout)
                if mesure is None:
                    morceaux.append("sur secteur (pas de batterie interne)")
                else:
                    pourcent, en_decharge = mesure
                    etat = "en décharge" if en_decharge else "en charge"
                    morceaux.append(f"Batterie {pourcent} % ({etat})")
                    details["battery"] = pourcent
                    details["discharging"] = en_decharge
        except Exception:  # noqa: BLE001
            morceaux.append("batterie illisible")

        try:
            phrase_reseau = interpreter_wifi(
                _run(["ipconfig", "getsummary", _INTERFACE_RESEAU]).stdout,
                _run(["ipconfig", "getifaddr", _INTERFACE_RESEAU]).stdout,
            )
            morceaux.append(phrase_reseau)
            details["network"] = phrase_reseau
        except Exception:  # noqa: BLE001
            morceaux.append("réseau illisible")

        try:
            usage = shutil.disk_usage(Path.home())
            morceaux.append(f"Disque : {formater_disque(usage.free, usage.total)}")
            details["diskFreeBytes"] = usage.free
        except OSError:
            morceaux.append("disque illisible")

        details["persistence"] = "unchanged"
        return ToolResult(
            tool_name="system_vitals",
            success=True,
            content=" · ".join(morceaux) + ".",
            metadata=details,
        )


__all__ = [
    "ClipboardReadTool",
    "MediaControlTool",
    "ScreenSnapTool",
    "SystemVitalsTool",
    "VolumeControlTool",
    "formater_disque",
    "interpreter_etat_lecteur",
    "interpreter_volume",
    "interpreter_wifi",
    "lecteur_en_marche",
]
