"""Une connexion SQLite ouverte doit finir fermée.

Constaté en production le 20 août 2026 : le serveur est tombé sur
« OSError: [Errno 24] Too many open files ». lsof montrait mesh.db ouvert
114 fois par le même processus, contre une limite launchd de 256. Le serveur
restait vivant et lié au port 8000, mais n'acceptait plus aucune connexion —
une panne totale, et totalement silencieuse.

La cause : ``with sqlite3.connect(...) as conn`` ne ferme pas la connexion.
Ce gestionnaire de contexte ne gère que la TRANSACTION.

Ces tests comptent les descripteurs réellement ouverts par le processus. Une
relecture du code ne peut pas prouver ce que ce compte prouve.
"""

import os
import secrets
import sqlite3

import pytest

from diapason.mesh.commands import RemoteCommand, now_ms
from diapason.mesh.queue import CommandQueue


def descripteurs_ouverts() -> int:
    """Combien de descripteurs ce processus tient réellement, maintenant."""
    try:
        return len(os.listdir("/dev/fd"))
    except OSError:  # pragma: no cover - plateforme sans /dev/fd
        pytest.skip("/dev/fd indisponible sur cette plateforme")


def commande() -> RemoteCommand:
    return RemoteCommand(
        version=1,
        command_id=f"cmd_{secrets.token_hex(8)}",
        owner_id="owner_1",
        origin_device_id="dev_phone",
        target_device_id="mac-1",
        tool="desktop.open",
        arguments={"cible": "note"},
        created_at_ms=now_ms(),
        expires_at_ms=now_ms() + 300_000,
        nonce=secrets.token_hex(12),
        idempotency_key=f"idem_{secrets.token_hex(8)}",
        requires_confirmation=False,
    )


# Marge : le ramasse-miettes et le journal peuvent bouger d'un ou deux
# descripteurs sans que rien ne fuie. Une vraie fuite se compte en dizaines.
MARGE = 4
TOURS = 60


@pytest.fixture
def file_attente(tmp_path):
    return CommandQueue(tmp_path / "mesh.db")


def test_les_lectures_ne_fuient_pas(file_attente: CommandQueue) -> None:
    file_attente.history(limit=1)  # chauffe : le schéma s'ouvre une fois
    avant = descripteurs_ouverts()
    for _ in range(TOURS):
        file_attente.history(limit=1)
    fuite = descripteurs_ouverts() - avant
    assert fuite <= MARGE, f"{fuite} descripteurs fuités en {TOURS} lectures"


def test_les_ecritures_ne_fuient_pas(file_attente: CommandQueue) -> None:
    file_attente.enqueue(commande())
    avant = descripteurs_ouverts()
    for _ in range(TOURS):
        file_attente.enqueue(commande())
    fuite = descripteurs_ouverts() - avant
    assert fuite <= MARGE, f"{fuite} descripteurs fuités en {TOURS} écritures"


def test_ouvrir_la_file_a_repetition_ne_fuit_pas(tmp_path) -> None:
    """Le constructeur ouvre lui aussi une connexion pour migrer le schéma."""
    chemin = tmp_path / "mesh.db"
    CommandQueue(chemin)
    avant = descripteurs_ouverts()
    for _ in range(TOURS):
        CommandQueue(chemin)
    fuite = descripteurs_ouverts() - avant
    assert fuite <= MARGE, f"{fuite} descripteurs fuités en {TOURS} ouvertures"


def test_une_ecriture_est_bien_committee_avant_la_fermeture(tmp_path) -> None:
    """Le piège du correctif : fermer avant de committer perdrait l'écriture.

    Dans ``with closing(conn) as conn, conn:`` le second est quitté en premier,
    donc la transaction commit AVANT la fermeture. Inverser les deux ferait
    passer ce test à côté d'une perte de données silencieuse — d'où la
    relecture depuis une file NEUVE, seule preuve que le disque a reçu.
    """
    chemin = tmp_path / "mesh.db"
    cmd = commande()
    CommandQueue(chemin).enqueue(cmd)

    relu = CommandQueue(chemin).get(cmd.command_id)
    assert relu, "l'écriture n'a pas survécu à la fermeture de la connexion"
    # La file rend du camelCase : c'est le format que lit le téléphone.
    assert relu["commandId"] == cmd.command_id


# --- les deux autres porteurs de connexions du mesh ----------------------


def test_le_registre_ne_fuit_pas(tmp_path) -> None:
    from diapason.mesh.registry import DeviceRegistry

    registre = DeviceRegistry(tmp_path / "mesh.db")
    registre.list_devices()
    avant = descripteurs_ouverts()
    for _ in range(TOURS):
        registre.list_devices()
    fuite = descripteurs_ouverts() - avant
    assert fuite <= MARGE, f"{fuite} descripteurs fuités en {TOURS} lectures"


def test_le_magasin_de_nonces_ne_fuit_pas(tmp_path) -> None:
    """Le site le plus chaud du mesh : un passage par commande reçue."""
    from diapason.mesh.commands import NonceStore

    magasin = NonceStore(tmp_path / "mesh.db")
    magasin.spend(secrets.token_hex(8), "dev_phone")
    avant = descripteurs_ouverts()
    for _ in range(TOURS):
        magasin.spend(secrets.token_hex(8), "dev_phone")
    fuite = descripteurs_ouverts() - avant
    assert fuite <= MARGE, f"{fuite} descripteurs fuités en {TOURS} écritures"


# --- la fenêtre où la connexion n'appartient à personne ------------------


class ConnexionRetive:
    """Une connexion qui s'ouvre puis refuse d'être configurée."""

    def __init__(self) -> None:
        self.fermee = False
        self.row_factory = None

    def execute(self, *_args, **_kwargs):
        raise sqlite3.OperationalError("disque plein")

    def close(self) -> None:
        self.fermee = True


@pytest.mark.parametrize(
    "fabrique",
    [
        lambda chemin: _sans_init(CommandQueue, chemin),
        lambda chemin: _sans_init_registre(chemin),
        lambda chemin: _sans_init_nonces(chemin),
    ],
    ids=["file", "registre", "nonces"],
)
def test_une_fabrique_qui_echoue_referme_la_connexion(
    monkeypatch, tmp_path, fabrique
) -> None:
    """Entre l'ouverture et le retour, personne d'autre ne peut fermer.

    Un PRAGMA qui lève — base corrompue, disque plein, verrou exclusif —
    laissait la connexion orpheline : elle n'atteignait jamais le ``closing()``
    de l'appelant et fuyait exactement comme avant le correctif.
    """
    retive = ConnexionRetive()
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: retive)
    porteur = fabrique(tmp_path / "mesh.db")
    with pytest.raises(sqlite3.OperationalError):
        porteur._connect()
    assert retive.fermee, "la connexion orpheline n'a pas été refermée"


def _sans_init(classe, chemin):
    """Instancier sans __init__ : celui-ci migrerait le schéma."""
    objet = classe.__new__(classe)
    objet.db_path = chemin
    return objet


def _sans_init_registre(chemin):
    from diapason.mesh.registry import DeviceRegistry

    return _sans_init(DeviceRegistry, chemin)


def _sans_init_nonces(chemin):
    from diapason.mesh.commands import NonceStore

    return _sans_init(NonceStore, chemin)
