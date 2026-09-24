"""La serrure : l'AMK et le trousseau déverrouillés, en un seul endroit.

Conception : ``docs/development/compte-chiffre.md`` §2.10 (« un seul objet
``Serrure`` dans ``app.state`` ») et §3.8 (``unlock`` : 5 essais, puis 30 s).

Un seul objet détient l'AMK en mémoire. Deux copies — une par vue, ou une
par route — auraient survécu l'une à l'autre : « Verrouiller » dans la
fenêtre aurait laissé le mini-panneau déverrouillé, et le voyant aurait
menti (§78 du cahier : le voyant dit la vérité).

L'AMK vit dans un ``bytearray`` écrasé au verrouillage. On ne promet rien
de plus (§2.10) : Python copie les ``bytes`` que ``cryptography`` reçoit, et
les DEK du trousseau sont des ``bytes`` immuables.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from diapason.compte.cles import LONGUEUR_CLE, ErreurCompte, en_octets
from diapason.compte.trousseau import Trousseau

__all__ = [
    "ATTENTE_DEVERROUILLAGE_S",
    "ESSAIS_DEVERROUILLAGE",
    "CompteVerrouille",
    "LimiteDeverrouillage",
    "Ouverture",
    "Serrure",
    "TropDEssais",
]

# §3.8 : 5 essais, puis 30 s. Le seau large de ``/v1/account/*`` compte les
# requêtes, pas les échecs ; sans cette limite propre, un programme de la
# session (A7) essaierait 120 mots de passe par minute contre l'enveloppe
# locale — chacun coûte 0,5 s d'Argon2id, c'est-à-dire un cœur occupé en
# permanence. Cinq essais couvrent les fautes de frappe d'une personne ;
# 30 s arrêtent un essai en boucle sans punir un humain.
ESSAIS_DEVERROUILLAGE = 5
ATTENTE_DEVERROUILLAGE_S = 30


class CompteVerrouille(ErreurCompte):
    """423 côté local, JAMAIS 401 : ``apiFetch`` rejoue les 401 en
    rafraîchissant la clé d'API locale (§3.7, §3.8)."""

    code = "accountLocked"


class TropDEssais(ErreurCompte):
    code = "tooManyAttempts"

    def __init__(self, message: str, *, retry_after_s: int) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


@dataclass(frozen=True)
class Ouverture:
    """Ce que rend :meth:`Serrure.exiger` : une COPIE de l'AMK."""

    account_id: str
    incarnation: int
    amk: bytes
    trousseau: Trousseau

    def __repr__(self) -> str:  # jamais l'AMK dans une trace
        return (
            f"Ouverture(account_id={self.account_id!r}, "
            f"incarnation={self.incarnation}, epoque={self.trousseau.current_epoch})"
        )


class Serrure:
    def __init__(self) -> None:
        self._verrou = threading.Lock()
        self._amk: bytearray | None = None
        self._trousseau: Trousseau | None = None
        self._account_id: str | None = None
        self._incarnation: int | None = None

    @property
    def ouverte(self) -> bool:
        with self._verrou:
            return self._amk is not None

    @property
    def account_id(self) -> str | None:
        with self._verrou:
            return self._account_id

    def ouvrir(
        self, amk: bytes, trousseau: Trousseau, *, account_id: str, incarnation: int
    ) -> None:
        amk = en_octets(amk, "AMK", LONGUEUR_CLE)
        if not isinstance(trousseau, Trousseau):
            raise TypeError("la serrure garde un Trousseau déchiffré")
        with self._verrou:
            self._effacer()
            self._amk = bytearray(amk)
            self._trousseau = trousseau
            self._account_id = account_id
            self._incarnation = incarnation

    def fermer(self) -> None:
        with self._verrou:
            self._effacer()

    def _effacer(self) -> None:
        if self._amk is not None:
            for i in range(len(self._amk)):
                self._amk[i] = 0
        self._amk = None
        self._trousseau = None
        self._account_id = None
        self._incarnation = None

    def exiger(self) -> Ouverture:
        """L'AMK et le trousseau, ou 423 ``accountLocked``."""
        with self._verrou:
            if (
                self._amk is None
                or self._trousseau is None
                or self._account_id is None
                or self._incarnation is None
            ):
                raise CompteVerrouille("le compte est verrouillé sur cet appareil")
            return Ouverture(
                account_id=self._account_id,
                incarnation=self._incarnation,
                amk=bytes(self._amk),
                trousseau=self._trousseau,
            )


class LimiteDeverrouillage:
    """Cinq échecs, puis trente secondes (§3.8). Une réussite remet à zéro.

    Ce sont les ÉCHECS qui comptent : cinq déverrouillages réussis dans la
    journée — fermer, rouvrir l'app — ne doivent pas faire attendre.
    """

    def __init__(
        self,
        *,
        essais: int = ESSAIS_DEVERROUILLAGE,
        attente_s: int = ATTENTE_DEVERROUILLAGE_S,
        horloge: Callable[[], float] = time.monotonic,
    ) -> None:
        self._essais = essais
        self._attente_s = attente_s
        self._horloge = horloge
        self._echecs = 0
        self._bloque_jusqua: float | None = None
        self._verrou = threading.Lock()

    def verifier(self) -> None:
        with self._verrou:
            if self._bloque_jusqua is None:
                return
            reste = self._bloque_jusqua - self._horloge()
            if reste > 0:
                raise TropDEssais(
                    "trop d'essais de mot de passe",
                    retry_after_s=max(1, math.ceil(reste)),
                )
            # L'attente est finie : cinq nouveaux essais.
            self._bloque_jusqua = None
            self._echecs = 0

    def echec(self) -> None:
        with self._verrou:
            self._echecs += 1
            if self._echecs >= self._essais:
                self._bloque_jusqua = self._horloge() + self._attente_s

    def reussite(self) -> None:
        with self._verrou:
            self._echecs = 0
            self._bloque_jusqua = None
