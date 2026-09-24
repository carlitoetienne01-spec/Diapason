"""Un serveur de comptes en mémoire, et des appareils qui lui parlent.

Conception : ``docs/development/compte-chiffre.md`` étape 8 du §6 : « tests
de bout en bout contre ``diapason_comptes`` en mémoire, par
``httpx.Client(transport=httpx.MockTransport(...))`` ».

Aucun octet ne quitte la machine : le ``MockTransport`` remet chaque
requête au VRAI service ``diapason_comptes`` (le même code qu'au VPS),
monté dans un ``TestClient``. Le banc NOTE chaque requête — méthode,
chemin, en-têtes, corps — pour que les tests puissent y chercher ce qui ne
doit jamais partir (KEK, AMK, mot de passe) et vérifier l'ordre des appels
(rotation avant toute écriture). Il peut aussi FALSIFIER une réponse, pour
jouer un VPS hostile (§4.12).

Argon2id tourne ici à 64 Kio et une passe (:func:`argon_rapide`) : les
parcours dérivent des dizaines de clés, et 0,5 s chacune rendrait la suite
interminable. La TABLE est remplacée, pas le code : ``parametres_kdf``,
le refus de ``kdfVersion`` inconnue et le plancher restent ceux de la
production.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

import httpx
from fastapi.testclient import TestClient

from diapason.compte import cles
from diapason.compte.gardien import ProtecteurMemoire, preparer_dossier_compte
from diapason.compte.service import ServiceCompte
from diapason.compte.transport import SERVEUR_COMPTES
from diapason_comptes.app import creer_app, creer_contexte
from diapason_comptes.secrets_serveur import Configuration
from tests.diapason_comptes._outils import (
    FauxExpediteur,
    Horloge,
    code_de,
    secrets_de_test,
)

# Un mot de passe par rôle, chacun assez singulier pour qu'une recherche
# dans les journaux ou les requêtes ne tombe jamais dessus par hasard.
MDP = "Canari-mot-de-passe-7Q2x"
MDP_2 = "Deuxieme-canari-du-compte-4Kp"
MDP_3 = "Troisieme-canari-du-compte-9Zm"
EMAIL = "carlito@exemple.test"


def argon_rapide(monkeypatch: Any) -> None:
    """kdfVersion 1 à 64 Kio, t=1, p=1 — pour la vitesse des parcours."""
    monkeypatch.setattr(cles, "VERSIONS_KDF", MappingProxyType({1: (64, 1, 1)}))


class ProtecteurPersistant(ProtecteurMemoire):
    """Un protecteur « trousseau » en mémoire : la mémorisation est permise
    (``motif_refus_memorisation`` rend ``None`` pour ``keychain``) sans
    toucher au vrai trousseau de session."""

    nom = "keychain"
    persistant = True


@dataclass
class Requete:
    methode: str
    chemin: str
    en_tetes: dict[str, str]
    contenu: bytes

    def json(self) -> Any:
        return json.loads(self.contenu) if self.contenu else None


Falsification = Callable[[Requete, httpx.Response], httpx.Response | None]


class Vps:
    """Le service ``diapason_comptes``, en mémoire, derrière un MockTransport."""

    def __init__(self, dossier: Path, horloge: Horloge | None = None) -> None:
        dossier.mkdir(parents=True, exist_ok=True)
        self.horloge = horloge or Horloge()
        self.expediteur = FauxExpediteur()
        configuration = Configuration(
            chemin_base=dossier / "comptes.db",
            chemin_journal=dossier / "evenements.jsonl",
            budget_codes_jour=1000,
            budget_securite_jour=1000,
            inscriptions_ouvertes=True,
        )
        self.ctx = creer_contexte(
            configuration,
            secrets_de_test(),
            self.expediteur,
            origine_publique="https://exemple.invalid",
            horloge=self.horloge,
            espace_libre=lambda _chemin: 100 * 10**9,
        )
        self.app = creer_app(self.ctx)
        self.client = TestClient(self.app, raise_server_exceptions=True)
        self.requetes: list[Requete] = []
        self.falsifier: Falsification | None = None
        self.hotes: set[str] = set()

    # --- Le pont -------------------------------------------------------

    def gerer(self, request: httpx.Request) -> httpx.Response:
        contenu = request.read()
        self.hotes.add(f"{request.url.scheme}://{request.url.host}")
        requete = Requete(
            methode=request.method,
            chemin=request.url.raw_path.decode("ascii"),
            en_tetes=dict(request.headers),
            contenu=contenu,
        )
        self.requetes.append(requete)
        en_tetes = {
            k: v
            for k, v in request.headers.items()
            if k.lower() not in {"host", "content-length"}
        }
        brute = self.client.request(
            request.method, requete.chemin, content=contenu, headers=en_tetes
        )
        reponse = httpx.Response(
            brute.status_code, headers=brute.headers, content=brute.content
        )
        if self.falsifier is not None:
            remplacee = self.falsifier(requete, reponse)
            if remplacee is not None:
                return remplacee
        return reponse

    def http(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.gerer))

    def chemins(self) -> list[str]:
        return [f"{r.methode} {r.chemin}" for r in self.requetes]

    # --- Courriels -----------------------------------------------------

    def plus_tard(self) -> None:
        """Deux minutes plus tard : le service n'envoie qu'un courriel par
        minute et par adresse (§3.5), et un test qui enchaîne deux codes
        dans la même minute ne recevrait pas le second."""
        self.horloge.avancer(2 * 60_000)

    def nombre(self, email: str, genre: str) -> int:
        return len(self.expediteur.messages(email, genre))

    def code(self, email: str, genre: str, nombre: int) -> str:
        return code_de(self.expediteur.attendre(email, genre, nombre))

    def fermer(self) -> None:
        self.expediteur.relache.set()
        self.ctx.fermer()


class Mono:
    """Horloge monotone à la main (délais de ``unlock``, attentes de 30 min)."""

    def __init__(self) -> None:
        self.s = 1000.0

    def __call__(self) -> float:
        return self.s

    def avancer(self, secondes: float) -> None:
        self.s += secondes


def appareil(
    vps: Vps,
    dossier: Path,
    *,
    protecteur: ProtecteurMemoire | None = None,
    nom: str = "Mac de test",
    mono: Mono | None = None,
    compter: Callable[[], int] | None = None,
    config: Any = None,
) -> ServiceCompte:
    dossier.mkdir(parents=True, exist_ok=True)
    return ServiceCompte(
        dossier=preparer_dossier_compte(dossier, plateforme="linux"),
        protecteur=protecteur if protecteur is not None else ProtecteurMemoire(),
        client_http=vps.http(),
        config=config,
        nom_appareil=lambda: nom,
        horloge_monotone=mono or Mono(),
        # L'heure du VPS, pas celle du Mac : ``resetPending`` compare
        # ``pendingResetAt`` (fixé par le VPS) à l'heure de l'appareil, et
        # le VPS de test démarre à une date fixe.
        horloge_ms=vps.horloge,
        compter_conversations=compter,
        # Le banc exerce les parcours : il ouvre les comptes explicitement.
        # Le défaut réel (fermés) est éprouvé par test_ouverture.py.
        ouverts=True,
    )


# ----------------------------------------------------------------------
# Parcours
# ----------------------------------------------------------------------


def extrait(rendu: dict[str, Any]) -> list[str]:
    """Les deux groupes demandés, d'une clé préparée (``recoveryKey``) ou
    proposée après une récupération ou une réinitialisation
    (``newRecoveryKey``)."""
    cle = rendu["recoveryKey"] if "recoveryKey" in rendu else rendu["newRecoveryKey"]
    groupes = cle.split("-")
    return [groupes[g - 1] for g in rendu["confirmGroups"]]


def inscrire(
    service: ServiceCompte,
    vps: Vps,
    email: str = EMAIL,
    mot_de_passe: str = MDP,
    *,
    avec_cle: bool = True,
    remember: bool = False,
) -> str | None:
    """P1 complet ; rend la clé de récupération affichée (ou ``None``)."""
    vps.plus_tard()
    avant = vps.nombre(email, "code_inscription")
    service.inscription_debut(email, True)
    service.inscription_code(vps.code(email, "code_inscription", avant + 1))
    rendu = service.inscription_preparer(mot_de_passe, remember)
    if avec_cle:
        service.inscription_terminer(extrait(rendu), None)
        return rendu["recoveryKey"]
    service.inscription_terminer(None, True)
    return None


def formes(secret: bytes) -> list[bytes]:
    """Les écritures sous lesquelles un secret pourrait voyager."""
    return [
        secret,
        secret.hex().encode(),
        base64.b64encode(secret),
        base64.urlsafe_b64encode(secret),
        base64.urlsafe_b64encode(secret).rstrip(b"="),
        base64.b64encode(secret).rstrip(b"="),
    ]


def reponse_json(statut: int, corps: dict[str, Any]) -> httpx.Response:
    return httpx.Response(statut, json=corps)


def octets_de(texte: str) -> bytes:
    return base64.urlsafe_b64decode(texte + "=" * (-len(texte) % 4))


__all__ = [
    "EMAIL",
    "MDP",
    "MDP_2",
    "MDP_3",
    "SERVEUR_COMPTES",
    "Mono",
    "ProtecteurPersistant",
    "Requete",
    "Vps",
    "appareil",
    "argon_rapide",
    "extrait",
    "formes",
    "inscrire",
    "octets_de",
    "reponse_json",
]
