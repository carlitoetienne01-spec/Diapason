"""Gardien : où l'appareil range les secrets qu'il garde entre deux lancements.

Conception : ``docs/development/compte-chiffre.md`` §2.10 (où vit chaque clé),
§2.11 (ce que la mémorisation protège vraiment) et étape 3 du §6.

Deux secrets passent par ici, et deux seulement :

- l'AMK, quand l'utilisateur a coché « Garder cet appareil déverrouillé »
  (décochée par défaut) ;
- le jeton de session, TOUJOURS dans le même protecteur que l'AMK quand il
  en existe un, même si l'AMK n'est pas mémorisée (§2.10).

Quatre protecteurs, dont le ``nom`` est la valeur que ``/v1/account/status``
renverra dans ``protector`` (§3.8) :

- ``keychain`` — trousseau de session macOS, par ``/usr/bin/security -i`` ;
- ``dpapi`` — ``CryptProtectData`` sous Windows, par ``ctypes`` ;
- ``file`` — fichier 0600 dans ``compte/``, et nulle part ailleurs ;
- ``memory`` — rien ne survit au processus.

Ce module ne décide pas QUAND mémoriser : il dit si c'est permis
(``memorisation_permise``) et range ce qu'on lui confie.
"""

from __future__ import annotations

import base64
import binascii
import errno
import json
import logging
import os
import re
import secrets
import stat
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from diapason.compte.cles import ErreurCompte
from diapason.core.permissions import POSIX, restreindre_au_proprietaire

__all__ = [
    "ELEMENT_AMK",
    "ELEMENT_SESSION",
    "ENTROPIE_DPAPI",
    "SERVICE_TROUSSEAU",
    "CheminRefuse",
    "DossierCompte",
    "ErreurGardien",
    "Protecteur",
    "ProtecteurDpapi",
    "ProtecteurFichier",
    "ProtecteurMemoire",
    "ProtecteurTrousseauMac",
    "choisir_protecteur",
    "exclure_de_time_machine",
    "interpreter_logon",
    "memorisation_permise",
    "motif_refus_memorisation",
    "preparer_dossier_compte",
    "sonder_mot_de_passe_windows",
]

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Constantes figées par la conception
# ----------------------------------------------------------------------

SERVICE_TROUSSEAU = "Diapason Compte"
NOM_DOSSIER = "compte"
ENTROPIE_DPAPI = b"diapason/compte/v1"

ELEMENT_AMK = "amk"
ELEMENT_SESSION = "session"
_ELEMENTS = frozenset({ELEMENT_AMK, ELEMENT_SESSION})

_SECURITY = "/usr/bin/security"
_TMUTIL = "/usr/bin/tmutil"

# 24/09/2026 : un appel à `security -i` mesuré sur ce Mac prend 27 ms, un
# `tmutil isexcluded` 86 ms. Dix secondes couvrent un Mac chargé ; au-delà,
# c'est une boîte de dialogue du trousseau qui attend un clic que personne
# ne fera (serveur lancé par launchd), et attendre davantage figerait la
# route qui a demandé le secret sans rien gagner.
_DELAI_COMMANDE_S = 10.0

# 24/09/2026 : `tmutil addexclusion` sur un dossier neuf prend 11,0 s sur ce
# Mac, quatre mesures sur quatre (contre 0,08 s pour `isexcluded`) — le
# délai de 10 s le tuait à chaque fois, et l'exclusion était dite ratée
# alors qu'elle aurait réussi. 30 s laisse près de trois fois la mesure.
# C'est aussi pourquoi on relit d'abord : l'exclusion est collante, et ces
# 11 s ne se paient qu'au premier usage (§2.10).
_DELAI_EXCLUSION_S = 30.0

# 24/09/2026 : la borne était de 4 Kio, et elle était fausse. `security -i`
# lit sa commande dans un tampon de 4 096 octets : mesuré sur ce Mac, une
# ligne de 4 096 octets (saut de ligne compris) passe, une de 4 097 est
# COUPÉE — la première moitié s'exécute (avec -U, elle écrase l'élément
# valide par un secret tronqué, que `lire` rendait ensuite sans lever), et la
# fin s'exécute comme une seconde commande (« unknown command "8d30" »). Le
# secret étant rangé en hexadécimal, 4 Kio en demandaient 8. L'AMK fait
# 32 o, le jeton `dps1_…` 48 caractères : 256 o les couvrent cinq fois, et
# la plus longue ligne possible (accountId de 128, service de 80) tient alors
# en 768 octets.
_SECRET_MAX_O = 256

# Borne de la ligne envoyée à `security -i`, vérifiée AVANT l'appel : un
# quart de la coupure mesurée (4 096), et au-dessus des 768 octets de la plus
# longue ligne légitime. Elle attrape toute régression de _SECRET_MAX_O ou
# des motifs ci-dessous avant qu'un secret tronqué n'écrase l'ancien.
_LIGNE_SECURITY_MAX_O = 1024

# 24/09/2026 : la ligne envoyée à `security -i` est ANALYSÉE par son
# interpréteur. Un accountId qui porterait un guillemet ou un saut de ligne
# y injecterait une seconde commande — `delete-generic-password` sur un
# autre service, par exemple. Les identifiants sont donc bornés à
# l'alphabet base64url (les UUID y entrent), et le service à des mots. Une
# ligne trop longue est l'autre chemin vers une seconde commande : voir
# _LIGNE_SECURITY_MAX_O.
_MOTIF_COMPTE = re.compile(r"[A-Za-z0-9_-]{1,128}")
_MOTIF_SERVICE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,79}")

# 24/09/2026 : un provisoire (`.<pid>.<hasard>.<nom>`) ne vit que le temps
# d'un fsync — quelques millisecondes. Un processus tué entre `os.open` et
# `os.replace` (SIGKILL, coupure de courant) le laissait pour toujours, AMK
# comprise. Au-delà de 60 s, soit mille fois la durée d'une écriture, il est
# abandonné, et `preparer_dossier_compte` le supprime.
_PROVISOIRE_ABANDONNE_S = 60.0

# 24/09/2026 : deux fils du même processus partageaient le même nom de
# provisoire ; sur 900 écritures concurrentes, 503 levaient une OSError brute
# et l'une pouvait rendre un succès après avoir rangé la valeur de l'autre.
# Les routes `def` de FastAPI tournent dans un pool de fils : un verrou
# sérialise les écritures et effacements de `compte/` dans ce processus.
_VERROU_DOSSIER = threading.Lock()

# Codes de `security` (Security.framework, SecBase.h).
_ERR_SEC_ITEM_NOT_FOUND = "-25300"
# `security -i` sort avec 44 quand la seule commande n'a rien trouvé.
_RC_INTROUVABLE = 44

# Codes Win32 rendus par LogonUserW (§2.11).
ERROR_LOGON_FAILURE = 1326
ERROR_ACCOUNT_RESTRICTION = 1327
CRYPTPROTECT_UI_FORBIDDEN = 0x1
_LOGON32_LOGON_INTERACTIVE = 2
_LOGON32_PROVIDER_DEFAULT = 0


# ----------------------------------------------------------------------
# Erreurs
# ----------------------------------------------------------------------


class ErreurGardien(ErreurCompte):
    """Le protecteur n'a pas pu ranger, lire ou effacer un secret."""

    code = "protectorUnavailable"


class CheminRefuse(ErreurGardien):
    """Le chemin où l'on s'apprêtait à écrire n'est pas le dossier du compte."""

    code = "unsafePath"


# ----------------------------------------------------------------------
# Exécution des commandes du système
# ----------------------------------------------------------------------

Executer = Callable[[Sequence[str], bytes | None], subprocess.CompletedProcess[bytes]]


def _executer_systeme(
    arguments: Sequence[str], entree: bytes | None
) -> subprocess.CompletedProcess[bytes]:
    """Lancer une commande SANS shell ; le secret, s'il y en a un, est dans
    ``entree`` — l'entrée standard — et jamais dans ``arguments``.

    Pas d'``env`` transmis en plus de celui du serveur : §2.10 interdit tout
    secret dans une variable d'environnement.
    """
    return subprocess.run(
        list(arguments),
        input=entree,
        capture_output=True,
        timeout=(
            _DELAI_EXCLUSION_S
            if list(arguments[:2]) == [_TMUTIL, "addexclusion"]
            else _DELAI_COMMANDE_S
        ),
        check=False,
    )


# ----------------------------------------------------------------------
# Le dossier du compte
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class DossierCompte:
    """Le dossier ``compte/``, validé. Ne se construit que par
    :func:`preparer_dossier_compte` — un ``Path`` nu ne suffit pas à
    ``ProtecteurFichier``, qui revalide avant chaque écriture."""

    chemin: Path
    # True : exclusion Time Machine confirmée par `tmutil isexcluded`.
    # False : tentée et non confirmée. None : sans objet (pas macOS).
    exclu_time_machine: bool | None


def _valider_racine(racine: object) -> Path:
    """La racine de configuration doit être un VRAI dossier, absolu.

    Piège déjà payé du dépôt : ``Path(MagicMock())`` est accepté, parce que
    ``__fspath__`` rend « MagicMock/<nom>/<id> ». 42 vraies bases SQLite
    ont dormi ainsi à la racine du dépôt. Ici, un double de test oublié
    écrirait une clé : on n'accepte donc qu'un ``str`` ou un ``Path``, et on
    refuse tout ce qui n'est pas un dossier existant.
    """
    if not isinstance(racine, (str, Path)):
        raise CheminRefuse(
            f"racine de configuration de type {type(racine).__name__} : "
            "seuls str et Path sont acceptés"
        )
    if isinstance(racine, str) and not racine.strip():
        raise CheminRefuse("racine de configuration vide")
    chemin = Path(racine)
    if not chemin.is_absolute():
        raise CheminRefuse(f"racine de configuration relative : {chemin}")
    if chemin == Path(chemin.anchor):
        raise CheminRefuse(f"racine de configuration à la racine du disque : {chemin}")
    try:
        etat = os.lstat(chemin)
    except FileNotFoundError:
        raise CheminRefuse(f"racine de configuration absente : {chemin}") from None
    if stat.S_ISLNK(etat.st_mode) or not stat.S_ISDIR(etat.st_mode):
        raise CheminRefuse(
            f"racine de configuration qui n'est pas un dossier : {chemin}"
        )
    return chemin


def _verifier_dossier(chemin: Path, racine: Path) -> None:
    """``compte/`` doit être un dossier réel, à nous, directement sous la racine."""
    try:
        etat = os.lstat(chemin)
    except FileNotFoundError:
        raise CheminRefuse(f"dossier du compte disparu : {chemin}") from None
    if stat.S_ISLNK(etat.st_mode) or not stat.S_ISDIR(etat.st_mode):
        raise CheminRefuse(f"dossier du compte qui n'est pas un dossier : {chemin}")
    if POSIX and etat.st_uid != os.getuid():
        raise CheminRefuse(f"dossier du compte à un autre utilisateur : {chemin}")
    if chemin.resolve().parent != racine.resolve():
        raise CheminRefuse(f"dossier du compte hors de la configuration : {chemin}")


def preparer_dossier_compte(
    racine: str | Path | None = None,
    *,
    plateforme: str | None = None,
    executer: Executer | None = None,
) -> DossierCompte:
    """Créer (ou reprendre) ``<config>/compte/`` en 0700 et l'exclure de Time Machine.

    ``racine`` vaut ``get_config_dir()`` en production ; les tests passent
    un dossier temporaire, jamais ``~/.diapason``.
    """
    if racine is None:
        from diapason.core.paths import get_config_dir

        racine = get_config_dir()
    racine_valide = _valider_racine(racine)
    chemin = racine_valide / NOM_DOSSIER
    try:
        os.mkdir(chemin, 0o700)
    except FileExistsError:
        pass
    _verifier_dossier(chemin, racine_valide)
    if POSIX:
        # mkdir passe par l'umask, et un dossier repris a pu être élargi.
        os.chmod(chemin, 0o700)
    with _VERROU_DOSSIER:
        try:
            abandonnes = _purger_provisoires(chemin, age_min_s=_PROVISOIRE_ABANDONNE_S)
        except OSError as exc:
            logger.warning("provisoires de compte/ non purgés : %s", exc.errno)
        else:
            if abandonnes:
                logger.warning("%d provisoire(s) abandonné(s) supprimé(s)", abandonnes)
    plateforme = plateforme or sys.platform
    exclu: bool | None = None
    if plateforme == "darwin":
        exclu = exclure_de_time_machine(chemin, executer=executer)
    return DossierCompte(chemin=chemin, exclu_time_machine=exclu)


def exclure_de_time_machine(dossier: Path, *, executer: Executer | None = None) -> bool:
    """Relire l'exclusion ; si elle manque, la poser (collante, sans sudo)
    puis la RELIRE.

    §2.11 : ``tmutil isexcluded ~/.diapason`` rendait ``[Included]`` le
    24/09/2026 — un fichier de clé dans ``compte/`` partait donc dans chaque
    sauvegarde. On ne rend ``True`` que si ``tmutil isexcluded`` le confirme :
    « addexclusion a rendu 0 » n'est pas la même chose que « exclu » (§100).
    """
    executer = executer or _executer_systeme

    def _exclu() -> bool:
        relu = executer([_TMUTIL, "isexcluded", str(dossier)], None)
        return relu.returncode == 0 and b"[Excluded]" in (relu.stdout or b"")

    try:
        if _exclu():
            return True
        pose = executer([_TMUTIL, "addexclusion", str(dossier)], None)
        if pose.returncode != 0:
            logger.warning("tmutil addexclusion a échoué (code %s)", pose.returncode)
            return False
        return _exclu()
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("tmutil injoignable : %s", exc)
        return False


# ----------------------------------------------------------------------
# Validation des entrées communes
# ----------------------------------------------------------------------


def _valider_compte(compte_id: object) -> str:
    if not isinstance(compte_id, str) or not _MOTIF_COMPTE.fullmatch(compte_id):
        raise ErreurGardien(
            "accountId hors de l'alphabet base64url (1 à 128 caractères)",
            code="accountIdInvalid",
        )
    return compte_id


def _valider_element(element: object) -> str:
    if not isinstance(element, str) or element not in _ELEMENTS:
        raise ErreurGardien(f"élément inconnu : {element!r}", code="elementInvalid")
    return str(element)


def _valider_secret(secret: object) -> bytes:
    # Un str n'est pas accepté : un jeton de session s'encode chez l'appelant,
    # sinon deux appelants l'encoderaient différemment et le relu différerait.
    if not isinstance(secret, (bytes, bytearray)):
        raise ErreurGardien("un secret est une suite d'octets", code="secretInvalid")
    if not 1 <= len(secret) <= _SECRET_MAX_O:
        raise ErreurGardien("secret vide ou trop long", code="secretInvalid")
    return bytes(secret)


# ----------------------------------------------------------------------
# Le contrat commun
# ----------------------------------------------------------------------


class Protecteur(Protocol):
    """Ce que tout protecteur sait faire. ``lire`` rend ``None`` pour
    « rien de rangé », et lève pour « illisible » : les confondre ferait
    passer un trousseau verrouillé pour un compte jamais mémorisé."""

    nom: str
    persistant: bool

    def ranger(self, compte_id: str, element: str, secret: bytes) -> None: ...

    def lire(self, compte_id: str, element: str) -> bytes | None: ...

    def effacer(self, compte_id: str, element: str) -> None: ...


# ----------------------------------------------------------------------
# macOS : le trousseau de session
# ----------------------------------------------------------------------


def _code_security(sortie_erreur: bytes) -> str | None:
    """Extraire « returned -25300 » sans jamais recopier le reste de stderr."""
    trouve = re.search(rb"returned (-?\d+)", sortie_erreur or b"")
    return trouve.group(1).decode("ascii") if trouve else None


class ProtecteurTrousseauMac:
    """Élément générique du trousseau par défaut, lu et écrit par
    ``/usr/bin/security -i``.

    Le secret n'est JAMAIS un argument : ``security add-generic-password -w
    <secret>`` l'exposerait à tout ``ps`` de la machine pendant l'appel.
    La commande est écrite sur l'ENTRÉE STANDARD de ``security -i`` ; seuls
    ``/usr/bin/security`` et ``-i`` apparaissent dans la table des processus.

    Le secret est rangé sous sa forme hexadécimale. Pourquoi pas ``-X`` :
    ``find-generic-password -w`` rend un mot de passe imprimable tel quel et
    un binaire en hexadécimal — une AMK dont les 32 octets tombent tous
    imprimables aurait été relue fausse, une fois sur quelques milliards,
    sans un mot.
    """

    nom = "keychain"
    persistant = True

    def __init__(
        self,
        service: str = SERVICE_TROUSSEAU,
        *,
        executer: Executer | None = None,
    ) -> None:
        if not isinstance(service, str) or not _MOTIF_SERVICE.fullmatch(service):
            raise ErreurGardien(
                f"nom de service refusé : {service!r}", code="serviceInvalid"
            )
        self.service = service
        self._executer = executer or _executer_systeme

    def _commande(self, ligne: str) -> subprocess.CompletedProcess[bytes]:
        entree = (ligne + "\n").encode("ascii")
        if len(entree) > _LIGNE_SECURITY_MAX_O:
            # Jamais la ligne dans le message : elle porte le secret.
            raise ErreurGardien(
                f"ligne de {len(entree)} octets pour security -i "
                f"(borne {_LIGNE_SECURITY_MAX_O}) : elle serait coupée",
                code="secretInvalid",
            )
        try:
            return self._executer([_SECURITY, "-i"], entree)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ErreurGardien(
                f"trousseau injoignable : {type(exc).__name__}",
                code="keychainUnavailable",
            ) from None

    def _designation(self, compte_id: str, element: str) -> str:
        compte = f"{_valider_compte(compte_id)}/{_valider_element(element)}"
        return f'-a "{compte}" -s "{self.service}"'

    def ranger(self, compte_id: str, element: str, secret: bytes) -> None:
        brut = _valider_secret(secret)
        designation = self._designation(compte_id, element)
        resultat = self._commande(
            f"add-generic-password -U {designation} -w {brut.hex()}"
        )
        if resultat.returncode != 0:
            code = _code_security(resultat.stderr)
            raise ErreurGardien(
                f"le trousseau a refusé l'écriture (code {code})",
                code="keychainUnavailable",
            )
        # §100 : « security a rendu 0 » n'est pas « c'est rangé ». La preuve
        # vient du trousseau lui-même, relu.
        if self.lire(compte_id, element) != brut:
            # Un élément qui ne rend pas ce qu'on y a mis serait relu au
            # prochain lancement comme s'il était bon : on l'efface.
            try:
                self.effacer(compte_id, element)
            except ErreurGardien:
                logger.warning("élément du trousseau faux, et non effaçable")
            raise ErreurGardien(
                "le trousseau ne rend pas ce qui vient d'y être rangé",
                code="keychainUnavailable",
            )

    def lire(self, compte_id: str, element: str) -> bytes | None:
        designation = self._designation(compte_id, element)
        resultat = self._commande(f"find-generic-password {designation} -w")
        code = _code_security(resultat.stderr)
        if resultat.returncode == 0:
            try:
                return bytes.fromhex(resultat.stdout.decode("ascii").strip())
            except (UnicodeDecodeError, ValueError):
                raise ErreurGardien(
                    "élément du trousseau illisible", code="keychainCorrupt"
                ) from None
        if code == _ERR_SEC_ITEM_NOT_FOUND or (
            code is None and resultat.returncode == _RC_INTROUVABLE
        ):
            return None
        # -25308 (interaction interdite) : trousseau verrouillé, session
        # ouverte par SSH… Ce n'est PAS « rien de rangé ».
        raise ErreurGardien(
            f"le trousseau refuse la lecture (code {code})", code="keychainUnavailable"
        )

    def effacer(self, compte_id: str, element: str) -> None:
        designation = self._designation(compte_id, element)
        resultat = self._commande(f"delete-generic-password {designation}")
        code = _code_security(resultat.stderr)
        if resultat.returncode == 0 or code == _ERR_SEC_ITEM_NOT_FOUND:
            return
        if code is None and resultat.returncode == _RC_INTROUVABLE:
            return
        raise ErreurGardien(
            f"le trousseau refuse l'effacement (code {code})",
            code="keychainUnavailable",
        )


# ----------------------------------------------------------------------
# Fichiers dans compte/ (ProtecteurFichier, et le blob DPAPI)
# ----------------------------------------------------------------------


def _exiger_dossier(dossier: object) -> DossierCompte:
    if not isinstance(dossier, DossierCompte):
        raise CheminRefuse(
            f"un DossierCompte est exigé, pas un {type(dossier).__name__}"
        )
    _verifier_dossier(dossier.chemin, dossier.chemin.parent)
    return dossier


def _indisponible(action: str, nom: str, exc: OSError) -> ErreurGardien:
    # Seul le nom de l'erreur système : jamais le contenu, jamais un chemin
    # qui n'est pas le nôtre.
    cause = errno.errorcode.get(exc.errno or 0, type(exc).__name__)
    return ErreurGardien(
        f"{action} de {nom} impossible : {cause}", code="protectedFileUnavailable"
    )


def _est_provisoire_de(nom_fichier: str, nom: str) -> bool:
    """``.<pid>.<hasard>.<nom>`` — le seul motif que ``_ecrire_dans_dossier``
    produit. Un ``.<nom>`` isolé n'en est pas un."""
    return (
        nom_fichier.startswith(".")
        and nom_fichier.endswith("." + nom)
        and len(nom_fichier) > len(nom) + 2
    )


def _purger_provisoires(
    chemin: Path, *, nom: str | None = None, age_min_s: float = 0.0
) -> int:
    """Supprimer les provisoires de ``compte/`` : ceux de ``nom``, ou tous
    ceux qui finissent par ``.key`` ; seulement ceux plus vieux que
    ``age_min_s``. Rend le nombre supprimé."""
    maintenant = time.time()
    supprimes = 0
    for entree in os.scandir(chemin):
        if not entree.name.startswith("."):
            continue
        if nom is not None and not _est_provisoire_de(entree.name, nom):
            continue
        if nom is None and not entree.name.endswith(".key"):
            continue
        try:
            etat = entree.stat(follow_symlinks=False)
            if age_min_s and maintenant - etat.st_mtime < age_min_s:
                continue
            os.unlink(entree.path)
            supprimes += 1
        except FileNotFoundError:
            pass
    return supprimes


def _ecrire_dans_dossier(dossier: DossierCompte, nom: str, contenu: bytes) -> None:
    """Écriture atomique d'un fichier 0600 DANS ``compte/``, jamais ailleurs.

    Le dossier est revalidé à chaque écriture : entre la préparation et
    maintenant, il a pu être remplacé par un lien.
    """
    dossier = _exiger_dossier(dossier)
    if "/" in nom or "\\" in nom or nom.startswith("."):
        raise CheminRefuse(f"nom de fichier refusé : {nom!r}")
    # 24/09/2026 : §2.10 veut `compte/session.key` « exclu de Time Machine »,
    # mais seule la mémorisation de l'AMK vérifiait l'exclusion ; le jeton
    # partait dans les sauvegardes quand `tmutil` avait échoué. False ne se
    # rencontre que sous macOS (None ailleurs, où c'est sans objet).
    if dossier.exclu_time_machine is False:
        raise ErreurGardien(
            f"{nom} refusé : compte/ n'est pas exclu de Time Machine",
            code="backupExclusionFailed",
        )
    cible = dossier.chemin / nom
    # Le provisoire porte le secret le temps d'un fsync : il FINIT par
    # « .key » comme le définitif, sinon `file_read` le lirait (§2.10 : la
    # politique ne filtre que le nom). Le hasard le rend propre à CET appel
    # (24/09/2026 : `.<pid>.<nom>` était commun à tous les fils).
    provisoire = dossier.chemin / f".{os.getpid()}.{secrets.token_hex(8)}.{nom}"
    drapeaux = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    drapeaux |= getattr(os, "O_NOFOLLOW", 0)
    with _VERROU_DOSSIER:
        try:
            descripteur = os.open(provisoire, drapeaux, 0o600)
        except OSError as exc:
            raise _indisponible("l'écriture", nom, exc) from None
        try:
            try:
                restreindre_au_proprietaire(descripteur)
                ecrit = 0
                while ecrit < len(contenu):
                    ecrit += os.write(descripteur, contenu[ecrit:])
                os.fsync(descripteur)
            finally:
                os.close(descripteur)
            os.replace(provisoire, cible)
        except BaseException as exc:
            # Un provisoire abandonné garderait le secret sous un autre nom,
            # hors de la portée d'effacer().
            try:
                os.unlink(provisoire)
            except FileNotFoundError:
                pass
            if isinstance(exc, OSError):
                raise _indisponible("l'écriture", nom, exc) from None
            raise


def _lire_dans_dossier(dossier: DossierCompte, nom: str) -> bytes | None:
    dossier = _exiger_dossier(dossier)
    # 24/09/2026 : sans O_NONBLOCK, une FIFO plantée à la place de amk.key
    # bloquait `os.open` pour toujours, et la route avec lui ; le test
    # S_ISREG venait après l'ouverture et n'y pouvait rien.
    drapeaux = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    drapeaux |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        descripteur = os.open(dossier.chemin / nom, drapeaux)
    except FileNotFoundError:
        return None
    except OSError as exc:
        # ELOOP : O_NOFOLLOW a rencontré un lien planté à la place du fichier.
        if exc.errno == errno.ELOOP:
            raise CheminRefuse(f"{nom} est un lien symbolique") from None
        raise _indisponible("la lecture", nom, exc) from None
    try:
        if not stat.S_ISREG(os.fstat(descripteur).st_mode):
            raise CheminRefuse(f"{nom} n'est pas un fichier ordinaire")
        morceaux = []
        while morceau := os.read(descripteur, 65536):
            morceaux.append(morceau)
        return b"".join(morceaux)
    except OSError as exc:
        raise _indisponible("la lecture", nom, exc) from None
    finally:
        os.close(descripteur)


def _effacer_dans_dossier(dossier: DossierCompte, nom: str) -> None:
    dossier = _exiger_dossier(dossier)
    with _VERROU_DOSSIER:
        try:
            os.unlink(dossier.chemin / nom)
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise _indisponible("l'effacement", nom, exc) from None
        # 24/09/2026 : un provisoire laissé par un processus tué survivait à
        # effacer() — décocher « Garder cet appareil déverrouillé » laissait
        # l'AMK sur le disque. Effacer un élément efface aussi ses provisoires.
        try:
            _purger_provisoires(dossier.chemin, nom=nom)
        except OSError as exc:
            raise _indisponible("l'effacement", nom, exc) from None


def _emballer(compte_id: str, element: str, donnees: bytes) -> bytes:
    # Le fichier nomme son compte : relu sous un autre accountId, il rend
    # None plutôt que la clé d'un autre compte.
    return json.dumps(
        {
            "v": 1,
            "accountId": compte_id,
            "element": element,
            "data": base64.b64encode(donnees).decode("ascii"),
        },
        sort_keys=True,
    ).encode("utf-8")


def _deballer(contenu: bytes, compte_id: str, element: str) -> bytes | None:
    try:
        objet = json.loads(contenu.decode("utf-8"))
        if not isinstance(objet, dict) or objet.get("v") != 1:
            raise ValueError("version")
        if objet.get("accountId") != compte_id or objet.get("element") != element:
            return None
        return base64.b64decode(objet["data"], validate=True)
    except (UnicodeDecodeError, ValueError, KeyError, TypeError, binascii.Error):
        raise ErreurGardien(
            "fichier de secret illisible", code="protectedFileCorrupt"
        ) from None


class ProtecteurFichier:
    """Fichier 0600 dans ``compte/`` : ``amk.key``, ``session.key``.

    Sous Linux, c'est le seul protecteur : il garde le jeton de session, pas
    l'AMK (``memorisation_permise`` le refuse). Sous macOS, il n'est l'AMK
    qu'en repli de D7, si la preuve ``ps`` du trousseau avait échoué. Le
    suffixe ``.key`` le fait refuser par ``file_read`` (étape 3 bis).
    Sous Windows, 0600 ne veut rien dire : l'ACL du profil protège, héritée,
    et ``core/permissions.py`` le dit.
    """

    nom = "file"
    persistant = True

    def __init__(self, dossier: DossierCompte) -> None:
        if not isinstance(dossier, DossierCompte):
            raise CheminRefuse(
                f"un DossierCompte est exigé, pas un {type(dossier).__name__}"
            )
        self.dossier = dossier

    @staticmethod
    def _nom(element: str) -> str:
        return f"{_valider_element(element)}.key"

    def ranger(self, compte_id: str, element: str, secret: bytes) -> None:
        brut = _valider_secret(secret)
        compte_id = _valider_compte(compte_id)
        _ecrire_dans_dossier(
            self.dossier, self._nom(element), _emballer(compte_id, element, brut)
        )

    def lire(self, compte_id: str, element: str) -> bytes | None:
        compte_id = _valider_compte(compte_id)
        contenu = _lire_dans_dossier(self.dossier, self._nom(element))
        return None if contenu is None else _deballer(contenu, compte_id, element)

    def effacer(self, compte_id: str, element: str) -> None:
        _valider_compte(compte_id)
        _effacer_dans_dossier(self.dossier, self._nom(element))


# ----------------------------------------------------------------------
# Windows : DPAPI
# ----------------------------------------------------------------------


def _dpapi(
    proteger: bool, donnees: bytes, entropie: bytes
) -> bytes:  # pragma: no cover
    """``CryptProtectData`` / ``CryptUnprotectData`` par ``ctypes``.

    ``CRYPTPROTECT_UI_FORBIDDEN`` : le serveur n'a pas de fenêtre ; une
    invite DPAPI attendrait un clic que personne ne verra.
    """
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):  # noqa: N801 - nom de l'API Win32
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        ]

    def _blob(octets: bytes) -> tuple[DATA_BLOB, object]:
        tampon = ctypes.create_string_buffer(octets, len(octets))
        return DATA_BLOB(
            len(octets), ctypes.cast(tampon, ctypes.POINTER(ctypes.c_char))
        ), tampon

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    fonction = crypt32.CryptProtectData if proteger else crypt32.CryptUnprotectData
    fonction.argtypes = [
        ctypes.POINTER(DATA_BLOB),
        ctypes.c_void_p,
        ctypes.POINTER(DATA_BLOB),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(DATA_BLOB),
    ]
    fonction.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    entree, _garde_entree = _blob(donnees)
    sel, _garde_sel = _blob(entropie)
    sortie = DATA_BLOB()
    if not fonction(
        ctypes.byref(entree),
        None,
        ctypes.byref(sel),
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(sortie),
    ):
        raise ErreurGardien(
            f"DPAPI a refusé (erreur Win32 {ctypes.get_last_error()})",
            code="dpapiUnavailable",
        )
    try:
        return ctypes.string_at(sortie.pbData, sortie.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(sortie.pbData, ctypes.c_void_p))


def _proteger_dpapi(donnees: bytes, entropie: bytes) -> bytes:  # pragma: no cover
    return _dpapi(True, donnees, entropie)


def _deproteger_dpapi(donnees: bytes, entropie: bytes) -> bytes:  # pragma: no cover
    return _dpapi(False, donnees, entropie)


class ProtecteurDpapi:
    """Blob DPAPI rangé dans ``compte/<element>.dpapi.key``.

    Entropie : ``b"diapason/compte/v1" + accountId`` (§2.10). DPAPI ne vaut
    que le mot de passe de la session Windows : ce protecteur garde toujours
    le jeton de session, mais l'AMK seulement si ``memorisation_permise`` le
    dit (§2.11).
    """

    nom = "dpapi"
    persistant = True

    def __init__(
        self,
        dossier: DossierCompte,
        *,
        proteger: Callable[[bytes, bytes], bytes] | None = None,
        deproteger: Callable[[bytes, bytes], bytes] | None = None,
    ) -> None:
        if not isinstance(dossier, DossierCompte):
            raise CheminRefuse(
                f"un DossierCompte est exigé, pas un {type(dossier).__name__}"
            )
        self.dossier = dossier
        self._proteger = proteger or _proteger_dpapi
        self._deproteger = deproteger or _deproteger_dpapi

    @staticmethod
    def _nom(element: str) -> str:
        return f"{_valider_element(element)}.dpapi.key"

    @staticmethod
    def _entropie(compte_id: str) -> bytes:
        return ENTROPIE_DPAPI + compte_id.encode("ascii")

    def ranger(self, compte_id: str, element: str, secret: bytes) -> None:
        brut = _valider_secret(secret)
        compte_id = _valider_compte(compte_id)
        blob = self._proteger(brut, self._entropie(compte_id))
        _ecrire_dans_dossier(
            self.dossier, self._nom(element), _emballer(compte_id, element, blob)
        )

    def lire(self, compte_id: str, element: str) -> bytes | None:
        compte_id = _valider_compte(compte_id)
        contenu = _lire_dans_dossier(self.dossier, self._nom(element))
        if contenu is None:
            return None
        blob = _deballer(contenu, compte_id, element)
        if blob is None:
            return None
        return self._deproteger(blob, self._entropie(compte_id))

    def effacer(self, compte_id: str, element: str) -> None:
        _valider_compte(compte_id)
        _effacer_dans_dossier(self.dossier, self._nom(element))


def interpreter_logon(reussi: bool, erreur: int) -> str:
    """Traduire ``LogonUserW(nom, ".", "", …)`` en ``present``, ``absent``
    ou ``indetermine`` (§2.11).

    Réussir avec un mot de passe vide, ou échouer par
    ``ERROR_ACCOUNT_RESTRICTION`` (la stratégie qui interdit l'ouverture
    réseau/interactive à un mot de passe vide) : il n'y en a pas.
    ``ERROR_LOGON_FAILURE`` : le vide est faux, donc il y en a un. Tout le
    reste — compte désactivé, type d'ouverture refusé, compte Microsoft mal
    nommé — est INDÉTERMINÉ, et §2.11 dit d'y refuser aussi.
    """
    if reussi or erreur == ERROR_ACCOUNT_RESTRICTION:
        return "absent"
    if erreur == ERROR_LOGON_FAILURE:
        return "present"
    return "indetermine"


# Le verdict de la sonde, une fois rendu (voir sonder_mot_de_passe_windows).
_SONDE_WINDOWS: dict[str, str] = {}


def sonder_mot_de_passe_windows() -> str:  # pragma: no cover
    """Sonder UNE fois par processus si la session Windows a un mot de passe.

    Une fois seulement : chaque essai avec un mot de passe vide sur un
    compte qui en a un compte comme un échec d'ouverture, et une stratégie
    de verrouillage à 3 ou 5 échecs fermerait la session de Carlito si
    ``/v1/account/status``, sondé en boucle par les vues, relançait l'essai.
    """
    if "etat" not in _SONDE_WINDOWS:
        _SONDE_WINDOWS["etat"] = _sonder_logon_vide()
    return _SONDE_WINDOWS["etat"]


def _sonder_logon_vide() -> str:  # pragma: no cover
    if os.name != "nt":
        return "indetermine"
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    taille = wintypes.DWORD(257)
    tampon = ctypes.create_unicode_buffer(taille.value)
    if not advapi32.GetUserNameW(tampon, ctypes.byref(taille)):
        return "indetermine"
    jeton = wintypes.HANDLE()
    advapi32.LogonUserW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.LogonUserW.restype = wintypes.BOOL
    reussi = bool(
        advapi32.LogonUserW(
            tampon.value,
            ".",
            "",
            _LOGON32_LOGON_INTERACTIVE,
            _LOGON32_PROVIDER_DEFAULT,
            ctypes.byref(jeton),
        )
    )
    erreur = 0 if reussi else ctypes.get_last_error()
    if reussi:
        kernel32.CloseHandle(jeton)
    return interpreter_logon(reussi, erreur)


# ----------------------------------------------------------------------
# Mémoire seule
# ----------------------------------------------------------------------


class ProtecteurMemoire:
    """Rien ne survit au processus. C'est le protecteur quand aucun dossier
    du compte n'a pu être préparé : mieux vaut redemander le mot de passe
    au prochain lancement que ranger un secret dans un chemin non validé."""

    nom = "memory"
    persistant = False

    def __init__(self) -> None:
        self._secrets: dict[tuple[str, str], bytes] = {}

    def ranger(self, compte_id: str, element: str, secret: bytes) -> None:
        brut = _valider_secret(secret)
        self._secrets[(_valider_compte(compte_id), _valider_element(element))] = brut

    def lire(self, compte_id: str, element: str) -> bytes | None:
        return self._secrets.get(
            (_valider_compte(compte_id), _valider_element(element))
        )

    def effacer(self, compte_id: str, element: str) -> None:
        self._secrets.pop((_valider_compte(compte_id), _valider_element(element)), None)


# ----------------------------------------------------------------------
# Choix et permission
# ----------------------------------------------------------------------


def choisir_protecteur(
    dossier: DossierCompte | None,
    *,
    plateforme: str | None = None,
    repli_fichier_mac: bool = False,
    executer: Executer | None = None,
) -> Protecteur:
    """Le protecteur de CET appareil (§2.10).

    ``repli_fichier_mac`` est la bascule de D7 : si la preuve ``ps`` de
    l'étape 3 avait vu le secret, l'AMK irait dans ``compte/`` plutôt que
    dans le trousseau. Elle a réussi le 24/09/2026 : la valeur par défaut
    reste le trousseau.
    """
    if dossier is None:
        return ProtecteurMemoire()
    plateforme = plateforme or sys.platform
    if plateforme == "darwin":
        if repli_fichier_mac:
            return ProtecteurFichier(dossier)
        return ProtecteurTrousseauMac(executer=executer)
    if plateforme == "win32":
        return ProtecteurDpapi(dossier)
    return ProtecteurFichier(dossier)


def motif_refus_memorisation(
    protecteur: Protecteur,
    *,
    plateforme: str | None = None,
    sonde_windows: Callable[[], str] | None = None,
) -> str | None:
    """Pourquoi « Garder cet appareil déverrouillé » est refusé, en code
    camelCase pour le bundle — ou ``None`` si c'est permis.

    §5 : l'écran doit pouvoir dire POURQUOI la case est grisée ; un simple
    booléen l'aurait laissé deviner.
    """
    plateforme = plateforme or sys.platform
    if not protecteur.persistant:
        return "noPersistentProtector"
    if protecteur.nom == "keychain":
        return None
    if protecteur.nom == "dpapi":
        etat = (sonde_windows or sonder_mot_de_passe_windows)()
        if etat == "present":
            return None
        if etat == "absent":
            return "windowsAccountWithoutPassword"
        return "windowsPasswordUndetermined"
    if protecteur.nom == "file":
        # §2.10 : sous Linux, pas de mémorisation de l'AMK. Sous macOS, le
        # fichier n'est admis qu'en repli D7, ET exclu de Time Machine —
        # sinon la clé partirait dans chaque sauvegarde en clair.
        if plateforme != "darwin":
            return "notOnThisPlatform"
        dossier = getattr(protecteur, "dossier", None)
        if dossier is None or dossier.exclu_time_machine is not True:
            return "backupExclusionFailed"
        return None
    return "noPersistentProtector"


def memorisation_permise(
    protecteur: Protecteur,
    *,
    plateforme: str | None = None,
    sonde_windows: Callable[[], str] | None = None,
) -> bool:
    """``rememberAllowed`` de ``/v1/account/status`` (§3.8)."""
    return (
        motif_refus_memorisation(
            protecteur, plateforme=plateforme, sonde_windows=sonde_windows
        )
        is None
    )
