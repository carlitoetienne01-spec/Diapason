"""Le tick de jour — la veille entre le briefing du matin et la nuit.

Atlas, 24 août 2026 : rien ne tournait entre 07:00 et 03:30 — pas de
« rendez-vous dans 20 minutes », pas de batterie faible signalée, pas de
rappel interne. Le tick est cette veille : toutes les quinze minutes,
launchd le réveille (StartInterval — l'ordonnanceur interne calcule ses
crons en UTC et n'est volontairement PAS utilisé), il regarde trois
choses et se tait s'il n'y a rien :

1. L'AGENDA — un événement qui commence dans la fenêtre à venir se
   notifie, une seule fois (l'état retient ce qui a déjà été dit).
2. Les RAPPELS de ROUTINES.json (kind « reminder ») dont l'horaire cron
   est passé depuis le dernier tick — livrés par notification + journal.
3. La BATTERIE — sous le seuil et en décharge, une alerte, une seule par
   passage sous le seuil.

Aucune inférence : le tick doit coûter moins d'une seconde et ne jamais
disputer le créneau Ollama à la voix. Tout est injectable pour les tests.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, List, Optional, Sequence

logger = logging.getLogger(__name__)

FENETRE_AGENDA_MIN = 25
SEUIL_BATTERIE = 15
INTERVALLE_DEFAUT_S = 900


# ---------------------------------------------------------------------------
# Un mini-cron LOCAL : minute heure jour mois jour-de-semaine.
# Champs admis : « * », un nombre, une liste « a,b,c », un pas « */k ».
# C'est tout — et c'est déjà plus que ce que les rappels demandent. Le
# reste est refusé BRUYAMMENT : un horaire illisible ne doit pas devenir
# « jamais » en silence.
# ---------------------------------------------------------------------------

_CHAMP_RE = re.compile(r"^(\*|\d{1,2}(?:,\d{1,2})*|\*/\d{1,2})$")


def _champ_correspond(champ: str, valeur: int) -> bool:
    if champ == "*":
        return True
    if champ.startswith("*/"):
        pas = int(champ[2:])
        return pas > 0 and valeur % pas == 0
    return valeur in {int(x) for x in champ.split(",")}


def cron_correspond(expression: str, moment: datetime) -> bool:
    """Vrai si l'expression cron (5 champs) désigne cette minute LOCALE."""
    champs = (expression or "").split()
    if len(champs) != 5 or not all(_CHAMP_RE.match(c) for c in champs):
        raise ValueError(f"Horaire cron illisible : {expression!r}")
    minute, heure, jour, mois, dow = champs
    return (
        _champ_correspond(minute, moment.minute)
        and _champ_correspond(heure, moment.hour)
        and _champ_correspond(jour, moment.day)
        and _champ_correspond(mois, moment.month)
        # cron : 0 = dimanche ; Python : lundi = 0.
        and _champ_correspond(dow, (moment.weekday() + 1) % 7)
    )


def echu_depuis(expression: str, depuis: datetime, jusqua: datetime) -> bool:
    """Une minute de (depuis, jusqua] correspond-elle à l'expression ?

    Borné à quatre heures : un tick qui a dormi plus longtemps rattrape au
    plus quatre heures de rappels — pas la semaine entière au réveil.
    """
    debut = max(depuis, jusqua - timedelta(hours=4))
    curseur = (debut + timedelta(minutes=1)).replace(second=0, microsecond=0)
    while curseur <= jusqua:
        if cron_correspond(expression, curseur):
            return True
        curseur += timedelta(minutes=1)
    return False


# ---------------------------------------------------------------------------
# L'état du tick — ce qui a déjà été dit, pour ne jamais le redire.
# ---------------------------------------------------------------------------


@dataclass
class TickEtat:
    dernier_tick: str = ""
    pings_agenda: List[str] = field(default_factory=list)
    batterie_signalee: bool = False

    @classmethod
    def charger(cls, chemin: Path) -> "TickEtat":
        try:
            brut = json.loads(chemin.read_text(encoding="utf-8"))
            return cls(
                dernier_tick=str(brut.get("dernier_tick", "")),
                pings_agenda=[str(x) for x in brut.get("pings_agenda", [])][-200:],
                batterie_signalee=bool(brut.get("batterie_signalee", False)),
            )
        except (OSError, ValueError):
            return cls()

    def sauver(self, chemin: Path) -> None:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(
            json.dumps(
                {
                    "dernier_tick": self.dernier_tick,
                    "pings_agenda": self.pings_agenda[-200:],
                    "batterie_signalee": self.batterie_signalee,
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )


# ---------------------------------------------------------------------------
# Les trois regards.
# ---------------------------------------------------------------------------

_LIGNE_EVENEMENT_RE = re.compile(r"^(\d{1,2}):(\d{2}) — (.+)$")


def evenements_imminents(
    contenu_agenda: str, maintenant: datetime, fenetre_min: int = FENETRE_AGENDA_MIN
) -> List[tuple[str, int, str]]:
    """(clé, minutes restantes, titre) pour chaque événement dans la fenêtre.

    ``contenu_agenda`` est la sortie de calendar_query pour aujourd'hui
    (« 14:30 — Dentiste » par ligne) — le format est à nous des deux côtés.
    """
    imminents: List[tuple[str, int, str]] = []
    for ligne in (contenu_agenda or "").splitlines():
        m = _LIGNE_EVENEMENT_RE.match(ligne.strip())
        if not m:
            continue
        heure, minute, titre = int(m.group(1)), int(m.group(2)), m.group(3).strip()
        debut = maintenant.replace(hour=heure, minute=minute, second=0, microsecond=0)
        restants = int((debut - maintenant).total_seconds() // 60)
        if 0 <= restants <= fenetre_min:
            cle = f"{maintenant.date().isoformat()}:{heure:02}:{minute:02}:{titre}"
            imminents.append((cle, restants, titre))
    return imminents


def lire_agenda_du_jour() -> str:
    from diapason.tools.voice_mac_tools import CalendarQueryTool

    resultat = CalendarQueryTool().execute(when="aujourd'hui")
    return resultat.content if resultat.success else ""


_BATTERIE_RE = re.compile(r"(\d{1,3})%.*?(discharging|charging|charged|AC)", re.S)


def etat_batterie(sortie_pmset: str) -> Optional[tuple[int, bool]]:
    """(pourcentage, en_decharge) depuis `pmset -g batt` — None si illisible."""
    m = _BATTERIE_RE.search(sortie_pmset or "")
    if not m:
        return None
    return int(m.group(1)), m.group(2) == "discharging"


def lire_batterie() -> Optional[tuple[int, bool]]:
    try:
        r = subprocess.run(
            ["pmset", "-g", "batt"], capture_output=True, text=True, timeout=5.0
        )
        return etat_batterie(r.stdout)
    except Exception:  # noqa: BLE001 - pas de batterie n'est pas une panne
        return None


# ---------------------------------------------------------------------------
# Le tick lui-même.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Passage:
    notifications: List[tuple[str, str]]
    rappels_livres: int
    erreurs: List[str]


def faire_le_tick(
    maintenant: Optional[datetime] = None,
    *,
    workspace: Optional[Path] = None,
    agenda: Optional[Callable[[], str]] = None,
    batterie: Optional[Callable[[], Optional[tuple[int, bool]]]] = None,
    notifier: Optional[Callable[[str, str], Any]] = None,
    routines: Optional[Sequence[Any]] = None,
) -> Passage:
    """Un passage : trois regards, notifications dédupliquées, état sauvé."""
    from diapason.heartbeat.livraison import livrer

    if maintenant is None:
        maintenant = datetime.now()
    if workspace is None:
        from diapason.core.paths import get_config_dir

        workspace = get_config_dir() / "workspace"
    chemin_etat = Path(workspace) / "TICK_STATE.json"
    etat = TickEtat.charger(chemin_etat)

    if notifier is None:
        notifier = lambda titre, corps: livrer(titre, corps)  # noqa: E731

    notifications: List[tuple[str, str]] = []
    erreurs: List[str] = []

    # 1. L'agenda imminent.
    try:
        contenu = (agenda or lire_agenda_du_jour)()
        for cle, restants, titre in evenements_imminents(contenu, maintenant):
            if cle in etat.pings_agenda:
                continue
            etat.pings_agenda.append(cle)
            quand = "maintenant" if restants == 0 else f"dans {restants} min"
            notifications.append(("Rendez-vous", f"{quand} : {titre}"))
    except Exception as exc:  # noqa: BLE001 - un regard raté n'arrête pas le tick
        erreurs.append(f"agenda : {exc}")

    # 2. Les rappels dus.
    rappels_livres = 0
    try:
        if routines is None:
            from diapason.heartbeat.routines import load_routines

            routines = load_routines(workspace)
        depuis = (
            datetime.fromisoformat(etat.dernier_tick)
            if etat.dernier_tick
            else maintenant - timedelta(minutes=15)
        )
        for routine in routines:
            if not getattr(routine, "enabled", False):
                continue
            if (getattr(routine, "kind", "") or "").strip().lower() != "reminder":
                continue
            try:
                if not echu_depuis(
                    str(getattr(routine, "schedule", "") or ""), depuis, maintenant
                ):
                    continue
            except ValueError as exc:
                erreurs.append(str(exc))
                continue
            message = str(
                (getattr(routine, "payload", None) or {}).get("message")
                or getattr(routine, "name", "")
                or "Rappel"
            )
            notifications.append(("Rappel", message))
            rappels_livres += 1
            try:
                from diapason.heartbeat.routines import record_run

                record_run(
                    routine.id, success=True, result=message, workspace=workspace
                )
            except Exception:  # noqa: BLE001 - l'historique est un bonus
                pass
    except Exception as exc:  # noqa: BLE001
        erreurs.append(f"rappels : {exc}")

    # 3. La batterie.
    try:
        mesure = (batterie or lire_batterie)()
        if mesure is not None:
            pourcent, en_decharge = mesure
            if pourcent <= SEUIL_BATTERIE and en_decharge:
                if not etat.batterie_signalee:
                    etat.batterie_signalee = True
                    notifications.append(
                        ("Batterie", f"{pourcent} % — pense au chargeur.")
                    )
            else:
                etat.batterie_signalee = False
    except Exception as exc:  # noqa: BLE001
        erreurs.append(f"batterie : {exc}")

    for titre, corps in notifications:
        try:
            notifier(titre, corps)
        except Exception as exc:  # noqa: BLE001
            erreurs.append(f"livraison : {exc}")

    etat.dernier_tick = maintenant.isoformat()
    # Les pings d'hier n'ont plus de raison d'occuper l'état.
    prefixe = maintenant.date().isoformat()
    etat.pings_agenda = [c for c in etat.pings_agenda if c.startswith(prefixe)]
    etat.sauver(chemin_etat)

    if notifications or erreurs:
        logger.info(
            "tick : %d notification(s), %d rappel(s), %d erreur(s)",
            len(notifications),
            rappels_livres,
            len(erreurs),
        )
    return Passage(
        notifications=notifications, rappels_livres=rappels_livres, erreurs=erreurs
    )


__all__ = [
    "FENETRE_AGENDA_MIN",
    "INTERVALLE_DEFAUT_S",
    "Passage",
    "SEUIL_BATTERIE",
    "TickEtat",
    "cron_correspond",
    "echu_depuis",
    "etat_batterie",
    "evenements_imminents",
    "faire_le_tick",
]
