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
    """Minuscules, sans accents, apostrophes pliées — la clé de comparaison.

    L'apostrophe TYPOGRAPHIQUE (') des noms macOS — « Moniteur d'activité » —
    doit rencontrer l'apostrophe droite (') de la transcription vocale.
    """
    brut = str(texte or "").replace("’", "'")
    decompose = unicodedata.normalize("NFD", brut)
    sans_accents = "".join(c for c in decompose if not unicodedata.combining(c))
    return " ".join(sans_accents.casefold().split())


class MacAppIndex:
    """Resolve app names without rescanning three directories per command."""

    def __init__(self, ttl_s: float = 300.0) -> None:
        self.ttl_s = max(1.0, float(ttl_s))
        self._items: tuple[str, ...] = ()
        self._affiches: dict[str, str] = {}
        self._updated = 0.0
        self._lock = threading.Lock()

    @staticmethod
    def _nom_affiche(app: Path) -> str | None:
        """Le nom FRANÇAIS que le Finder montre, lu dans le bundle même.

        macOS range les applications sous leur nom anglais mais les affiche
        localisés — « Échecs » est Chess.app. L'utilisateur parle le nom
        affiché ; sans cette lecture, un quart du Mac lui restait injoignable
        (mesuré le 23 août 2026 : 23 noms français ratés sur 87). Une table
        écrite à la main ne gagne jamais cette course ; le bundle, si.
        """
        import plistlib

        # Moderne : Resources/InfoPlist.loctable, {locale: {clé: valeur}}.
        chemin = app / "Contents" / "Resources" / "InfoPlist.loctable"
        if chemin.exists():
            try:
                with open(chemin, "rb") as f:
                    table = plistlib.load(f)
                for locale in ("fr", "fr_FR", "fr_CA"):
                    entree = table.get(locale) or {}
                    nom = entree.get("CFBundleDisplayName") or entree.get(
                        "CFBundleName"
                    )
                    if nom:
                        return str(nom)
            except Exception:  # noqa: BLE001 - un bundle illisible n'arrête rien
                pass
        # Classique : Resources/fr.lproj/InfoPlist.strings.
        for lproj in ("fr.lproj", "fr_FR.lproj", "fr_CA.lproj"):
            chemin = app / "Contents" / "Resources" / lproj / "InfoPlist.strings"
            if chemin.exists():
                try:
                    with open(chemin, "rb") as f:
                        table = plistlib.load(f)
                    nom = table.get("CFBundleDisplayName") or table.get("CFBundleName")
                    if nom:
                        return str(nom)
                except Exception:  # noqa: BLE001
                    pass
        return None

    @classmethod
    def _scan(cls) -> tuple[tuple[str, str | None], ...]:
        """(nom sur disque, nom affiché en français ou None) pour chaque app."""
        chemins: list[Path] = [
            # Le Finder n'est nulle part ailleurs — et « ouvre le Finder »
            # est probablement la phrase la plus naturelle du Mac.
            Path("/System/Library/CoreServices/Finder.app"),
            Path("/System/Library/CoreServices/Screen Sharing.app"),
        ]
        for root in (
            Path("/Applications"),
            Path("/Applications/Utilities"),
            Path("/System/Applications"),
            # Terminal, Console, Utilitaire de disque, Moniteur d'activité :
            # tout le quotidien d'un utilisateur vit ici, jamais balayé.
            Path("/System/Applications/Utilities"),
            # Utilitaire d'archive, Utilitaire d'annuaire, et consorts.
            Path("/System/Library/CoreServices/Applications"),
            Path.home() / "Applications",
        ):
            if not root.is_dir():
                continue
            try:
                for p in root.iterdir():
                    if p.suffix == ".app":
                        chemins.append(p)
                    elif p.is_dir() and root == Path("/Applications"):
                        # Les éditeurs qui installent en dossier — un seul
                        # niveau, sans récursion aveugle.
                        try:
                            chemins.extend(q for q in p.iterdir() if q.suffix == ".app")
                        except OSError:
                            continue
            except OSError:
                continue
        vus: set[str] = set()
        paires: list[tuple[str, str | None]] = []
        for chemin in chemins:
            if chemin.stem in vus or not chemin.exists():
                continue
            vus.add(chemin.stem)
            paires.append((chemin.stem, cls._nom_affiche(chemin)))
        return tuple(sorted(paires, key=lambda x: x[0].casefold()))

    def refresh(self) -> tuple[str, ...]:
        with self._lock:
            paires = self._scan()
            self._items = tuple(nom for nom, _ in paires)
            self._affiches = {
                _normalise(affiche): nom
                for nom, affiche in paires
                if affiche and _normalise(affiche) != _normalise(nom)
            }
            self._updated = time.monotonic()
            return self._items

    def applications(self) -> tuple[str, ...]:
        if self._items and time.monotonic() - self._updated < self.ttl_s:
            return self._items
        return self.refresh()

    def _noms_affiches(self) -> dict[str, str]:
        self.applications()  # garantit un balayage frais
        return getattr(self, "_affiches", {})

    def resolve(self, name: str) -> str | None:
        """Le nom pour ``open -a`` : l'installé si on le trouve, sinon le brut.

        Launch Services connaît des applications hors des dossiers balayés —
        le repli sur le nom brut reste donc utile. Qui veut savoir si l'app
        est RÉELLEMENT installée utilise ``lookup``, qui rend None.
        """
        return self.lookup(name) or ((name or "").strip().removesuffix(".app") or None)

    def lookup(self, name: str) -> str | None:
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
            candidats_parles.append(needle[len("apple ") :])

        installees = self.applications()
        par_cle = {_normalise(c): c for c in installees}
        affiches = self._noms_affiches()

        for parle in candidats_parles:
            # Le nom AFFICHÉ d'abord : c'est celui que l'utilisateur voit et
            # prononce. « Échecs » → Chess.app, lu dans le bundle même.
            present = affiches.get(parle)
            if present is not None:
                return present
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
        tous = dict(par_cle)
        tous.update(affiches)
        for parle in candidats_parles:
            compact = parle.replace(" ", "")
            for cle, candidate in tous.items():
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
        return None


APP_INDEX = MacAppIndex()

__all__ = ["APP_INDEX", "MacAppIndex"]
