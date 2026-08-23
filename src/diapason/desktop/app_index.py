"""Cached macOS application index used by low-latency launch actions."""

from __future__ import annotations

import threading
import time
import unicodedata
from pathlib import Path

# Le nom PARLÉ vers le nom SUR DISQUE. macOS affiche des noms français dans le
# Finder mais range les applications sous leur nom anglais — « Musique » est
# Music.app, « Réglages Système » est System Settings.app — et ``open -a``
# n'accepte que le nom sur disque. Constaté le 23 août 2026 : « ouvre-moi
# Apple TV » échouait, l'application s'appelant TV.app, et tout nom français
# échouait avec elle. L'assistant est parlé en français ; sans cette table,
# la moitié du Mac lui était fermée.
_ALIAS: dict[str, str] = {
    "apple tv": "TV",
    "tele": "TV",
    "television": "TV",
    "musique": "Music",
    "apple music": "Music",
    "reglages": "System Settings",
    "reglages systeme": "System Settings",
    "parametres": "System Settings",
    "parametres systeme": "System Settings",
    "preferences systeme": "System Settings",
    "calendrier": "Calendar",
    "rappels": "Reminders",
    "plans": "Maps",
    "cartes": "Maps",
    "livres": "Books",
    "bourse": "Stocks",
    "meteo": "Weather",
    "horloge": "Clock",
    "calculatrice": "Calculator",
    "dictaphone": "Voice Memos",
    "localiser": "Find My",
    "apercu": "Preview",
    "mots de passe": "Passwords",
    "balados": "Podcasts",
    "podcasts": "Podcasts",
    "actualites": "News",
    "courrier": "Mail",
    "moniteur d'activite": "Activity Monitor",
    "utilitaire de disque": "Disk Utility",
    "capture d'ecran": "Screenshot",
    "domicile": "Home",
    "photo booth": "Photo Booth",
}


def _normalise(texte: str) -> str:
    """Minuscules, sans accents, espaces resserrés — la clé de comparaison."""
    decompose = unicodedata.normalize("NFD", str(texte or ""))
    sans_accents = "".join(c for c in decompose if not unicodedata.combining(c))
    return " ".join(sans_accents.casefold().split())


class MacAppIndex:
    """Resolve app names without rescanning three directories per command."""

    def __init__(self, ttl_s: float = 300.0) -> None:
        self.ttl_s = max(1.0, float(ttl_s))
        self._items: tuple[str, ...] = ()
        self._updated = 0.0
        self._lock = threading.Lock()

    @staticmethod
    def _scan() -> tuple[str, ...]:
        names: set[str] = set()
        for root in (
            Path("/Applications"),
            Path("/Applications/Utilities"),
            Path("/System/Applications"),
            # Terminal, Console, Utilitaire de disque, Moniteur d'activité :
            # tout le quotidien d'un utilisateur vit ici, jamais balayé.
            Path("/System/Applications/Utilities"),
            Path.home() / "Applications",
        ):
            if not root.is_dir():
                continue
            try:
                names.update(p.stem for p in root.iterdir() if p.suffix == ".app")
            except OSError:
                continue
        return tuple(sorted(names, key=str.casefold))

    def refresh(self) -> tuple[str, ...]:
        with self._lock:
            self._items = self._scan()
            self._updated = time.monotonic()
            return self._items

    def applications(self) -> tuple[str, ...]:
        if self._items and time.monotonic() - self._updated < self.ttl_s:
            return self._items
        return self.refresh()

    def resolve(self, name: str) -> str | None:
        raw = (name or "").strip()
        if raw.lower().endswith(".app"):
            raw = raw[:-4]
        if not raw:
            return None
        needle = _normalise(raw)

        # « Apple TV », « Apple Music » : la marque n'est pas dans le nom du
        # fichier. On essaie avec ET sans le préfixe — « Apple Configurator »
        # existe bel et bien sous ce nom, le préfixe n'est donc pas toujours
        # de trop.
        candidats_parles = [needle]
        if needle.startswith("apple "):
            candidats_parles.append(needle[len("apple "):])

        installees = self.applications()
        par_cle = {_normalise(c): c for c in installees}

        for parle in candidats_parles:
            # 1 · l'alias parlé → nom sur disque, s'il est installé.
            vise = _ALIAS.get(parle)
            if vise is not None:
                cle_visee = _normalise(vise)
                present = par_cle.get(cle_visee)
                if present is None:
                    # « Voice Memos » est VoiceMemos.app sur disque : l'alias
                    # doit retrouver l'application même quand macOS colle les
                    # mots du nom de fichier.
                    compact_vise = cle_visee.replace(" ", "")
                    for cle, candidat in par_cle.items():
                        if cle.replace(" ", "") == compact_vise:
                            present = candidat
                            break
                if present is not None:
                    return present
            # 2 · le nom exact, insensible aux accents et aux espaces.
            present = par_cle.get(parle)
            if present is not None:
                return present
            compact = parle.replace(" ", "")
            for cle, candidate in par_cle.items():
                if cle.replace(" ", "") == compact:
                    return candidate

        # 3 · l'inclusion, dans les deux sens — « visual studio » trouve
        # « Visual Studio Code », « quicktime » trouve « QuickTime Player ».
        partial: list[str] = []
        for parle in candidats_parles:
            compact = parle.replace(" ", "")
            for cle, candidate in par_cle.items():
                cle_compacte = cle.replace(" ", "")
                if compact and compact in cle_compacte:
                    partial.append(candidate)
                elif set(cle.split()) and set(cle.split()) <= set(parle.split()):
                    # Sens inverse par MOTS entiers, jamais par sous-chaîne :
                    # « phone » vit au milieu de « dictaphone », et l'inclusion
                    # brute rendait Phone.app pour le Dictaphone.
                    partial.append(candidate)
        if partial:
            return min(partial, key=len)
        # Launch Services may know apps outside the indexed roots.
        return raw


APP_INDEX = MacAppIndex()

__all__ = ["APP_INDEX", "MacAppIndex"]
