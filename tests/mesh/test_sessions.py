"""Les sessions d'appareil — plan de la phase 2, étape 1 (26/09/2026).

Ce que ces tests refusent, chacun nommé : une révocation qui laisse la
session ouverte (un cache de validité), une session orpheline qu'un
réappairage retrouverait (``PRAGMA foreign_keys`` oublié), un jeton lisible
dans une copie de ``mesh.db``, et un ticket qui ouvre deux sessions.
"""

from __future__ import annotations

import base64
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest

from diapason.mesh.registry import DeviceRegistry, MeshError
from diapason.mesh.sessions import (
    SESSION_TOUCH_INTERVAL_MS,
    SESSION_TTL_MS,
    TICKET_TTL_MS,
    DeviceSessions,
)
from diapason.security.signing import generate_keypair

PHONE = "dev_le_telephone"


def _enroler(registry: DeviceRegistry, device_id: str = PHONE) -> None:
    invitation = registry.create_pairing("Téléphone")
    registry.redeem_pairing(
        invitation["pairingToken"],
        device_id=device_id,
        public_key_b64=base64.b64encode(generate_keypair().public_key).decode(),
        name="Téléphone",
        platform="ANDROID",
        device_type="PHONE",
    )


@pytest.fixture
def monde(tmp_path):
    registry = DeviceRegistry(tmp_path / "mesh.db")
    _enroler(registry)
    return registry, DeviceSessions(registry)


def _ouvrir(sessions: DeviceSessions, device_id: str = PHONE) -> str:
    ticket = sessions.issue_ticket(device_id)["ticket"]
    ouverte = sessions.redeem_ticket(ticket)
    assert ouverte is not None, "un ticket neuf doit ouvrir une session"
    return ouverte["sessionToken"]


class TestUneSessionSOuvreParUnTicket:
    def test_le_ticket_ouvre_une_session_de_douze_heures(self, monde):
        """§5 du plan mobile : 12 h, et le jeton ne vaut que pour son appareil."""
        _, sessions = monde
        ticket = sessions.issue_ticket(PHONE)
        assert ticket["expiresInSeconds"] == TICKET_TTL_MS // 1000 == 60

        ouverte = sessions.redeem_ticket(ticket["ticket"])
        assert ouverte["deviceId"] == PHONE
        assert ouverte["maxAgeSeconds"] == SESSION_TTL_MS // 1000 == 12 * 3600
        vue = sessions.verify_session(ouverte["sessionToken"])
        assert vue is not None and vue["deviceId"] == PHONE, (
            "la session ouverte doit être reconnue"
        )

    def test_un_ticket_ne_sert_qu_une_fois(self, monde):
        _, sessions = monde
        ticket = sessions.issue_ticket(PHONE)["ticket"]
        assert sessions.redeem_ticket(ticket) is not None
        assert sessions.redeem_ticket(ticket) is None, (
            "un ticket dépensé ne doit pas ouvrir une seconde session"
        )

    def test_un_ticket_perime_n_ouvre_rien(self, monde, tmp_path):
        _, sessions = monde
        ticket = sessions.issue_ticket(PHONE)["ticket"]
        with closing(sqlite3.connect(tmp_path / "mesh.db")) as conn, conn:
            conn.execute("UPDATE mesh_session_tickets SET expires_at_ms = 1")
        assert sessions.redeem_ticket(ticket) is None, (
            "un ticket expiré depuis 1970 ne doit rien ouvrir"
        )

    def test_un_appareil_inconnu_ou_revoque_n_obtient_pas_de_ticket(self, monde):
        registry, sessions = monde
        with pytest.raises(MeshError):
            sessions.issue_ticket("dev_inconnu")
        registry.revoke(PHONE)
        with pytest.raises(MeshError):
            sessions.issue_ticket(PHONE)

    @pytest.mark.parametrize(
        "valeur",
        [None, 42, "", "diapason_session_x", "n'importe quoi", "diapason_ticket_" * 50],
    )
    def test_une_valeur_etrangere_est_un_refus_pas_une_exception(self, monde, valeur):
        """La passerelle lit ces valeurs dans un cookie envoyé par n'importe qui."""
        _, sessions = monde
        assert sessions.redeem_ticket(valeur) is None
        assert sessions.verify_session(valeur) is None


class TestLaRevocationCoupeAussitot:
    def test_la_session_est_refusee_juste_apres_revoke(self, monde):
        """Étape 1 : « la session est refusée juste après revoke() »."""
        registry, sessions = monde
        jeton = _ouvrir(sessions)
        assert sessions.verify_session(jeton) is not None

        registry.revoke(PHONE)
        assert sessions.verify_session(jeton) is None, (
            "une session doit mourir avec la confiance de son appareil"
        )

    def test_la_confiance_est_relue_a_chaque_appel_sans_cache(self, monde, tmp_path):
        """Même si la ligne de session survivait, la jointure la refuse.

        On retire la confiance à la main, SANS passer par revoke() qui efface
        aussi les sessions : c'est la jointure elle-même qu'on éprouve.
        """
        _, sessions = monde
        jeton = _ouvrir(sessions)
        assert sessions.verify_session(jeton) is not None
        with closing(sqlite3.connect(tmp_path / "mesh.db")) as conn, conn:
            conn.execute("UPDATE mesh_devices SET trust_level='REVOKED'")
        assert sessions.verify_session(jeton) is None, (
            "verify_session a répondu d'après une confiance périmée"
        )

    def test_un_ticket_emis_avant_la_revocation_ne_s_echange_plus(self, monde):
        """L'enveloppe et la révocation peuvent se croiser : le ticket perd."""
        registry, sessions = monde
        ticket = sessions.issue_ticket(PHONE)["ticket"]
        registry.revoke(PHONE)
        assert sessions.redeem_ticket(ticket) is None

    def test_un_ticket_ne_s_echange_plus_quand_la_confiance_tombe_sans_revoke(
        self, monde, tmp_path
    ):
        """Le contrôle TRUSTED de redeem_ticket lui-même, sans revoke() — qui
        efface déjà les tickets et masquait son absence (contre-épreuve du
        26/09/2026 : la sous-requête retirée, 225 tests restaient verts)."""
        _, sessions = monde
        ticket = sessions.issue_ticket(PHONE)["ticket"]
        with closing(sqlite3.connect(tmp_path / "mesh.db")) as conn, conn:
            conn.execute("UPDATE mesh_devices SET trust_level='REVOKED'")
        assert sessions.redeem_ticket(ticket) is None, (
            "un ticket a ouvert une session pour un appareil qui n'est plus sûr"
        )

    def test_revoke_efface_les_lignes_de_session(self, monde, tmp_path):
        registry, sessions = monde
        _ouvrir(sessions)
        sessions.issue_ticket(PHONE)
        registry.revoke(PHONE)
        with closing(sqlite3.connect(tmp_path / "mesh.db")) as conn:
            restantes = conn.execute("SELECT COUNT(*) FROM mesh_sessions").fetchone()
            tickets = conn.execute(
                "SELECT COUNT(*) FROM mesh_session_tickets"
            ).fetchone()
        assert (restantes[0], tickets[0]) == (0, 0), (
            "un appareil révoqué ne doit laisser ni session ni ticket"
        )

    def test_une_session_expiree_est_refusee(self, monde, tmp_path):
        _, sessions = monde
        jeton = _ouvrir(sessions)
        with closing(sqlite3.connect(tmp_path / "mesh.db")) as conn, conn:
            conn.execute("UPDATE mesh_sessions SET expires_at_ms = 1")
        assert sessions.verify_session(jeton) is None


class TestOublierEmporteLesSessions:
    def test_les_connexions_du_registre_activent_les_cles_etrangeres(self, monde):
        """Sans ce PRAGMA, la cascade déclarée dans le schéma ne fait rien."""
        _, sessions = monde
        with closing(sessions._connect()) as conn:
            actif = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert actif == 1, "PRAGMA foreign_keys doit valoir ON sur chaque connexion"

    def test_forget_efface_ses_lignes(self, monde, tmp_path):
        """Étape 1 : « forget() efface ses lignes »."""
        registry, sessions = monde
        _ouvrir(sessions)
        sessions.issue_ticket(PHONE)
        registry.forget(PHONE)
        with closing(sqlite3.connect(tmp_path / "mesh.db")) as conn:
            sessions_restantes = conn.execute(
                "SELECT COUNT(*) FROM mesh_sessions"
            ).fetchone()[0]
            tickets_restants = conn.execute(
                "SELECT COUNT(*) FROM mesh_session_tickets"
            ).fetchone()[0]
        assert sessions_restantes == 0, "forget() a laissé une session orpheline"
        assert tickets_restants == 0, "forget() a laissé un ticket orphelin"

    def test_un_reappairage_ne_retrouve_pas_l_ancienne_session(self, monde):
        """Le risque nommé par le plan : réappairé sous le même identifiant."""
        registry, sessions = monde
        jeton = _ouvrir(sessions)
        registry.forget(PHONE)
        _enroler(registry)
        assert sessions.verify_session(jeton) is None, (
            "le téléphone réappairé a retrouvé une session d'avant l'oubli"
        )


class TestLeJetonNEstJamaisEnClair:
    def test_ni_le_jeton_ni_le_ticket_ne_sont_dans_la_base(self, monde, tmp_path):
        """Étape 1 : « le jeton en clair est introuvable dans la base ».

        Vérifié sur les octets des fichiers (base ET journal WAL), pas
        seulement sur les colonnes qu'on croit connaître.
        """
        _, sessions = monde
        ticket = sessions.issue_ticket(PHONE)["ticket"]
        jeton = sessions.redeem_ticket(ticket)["sessionToken"]

        octets = b""
        for chemin in tmp_path.glob("mesh.db*"):
            octets += chemin.read_bytes()
        with closing(sqlite3.connect(tmp_path / "mesh.db")) as conn:
            octets += "\n".join(conn.iterdump()).encode("utf-8")

        assert octets, "la base doit exister"
        assert jeton.encode() not in octets, "le jeton de session est en clair"
        assert ticket.encode() not in octets, "le ticket est en clair"
        secret_du_jeton = jeton.removeprefix("diapason_session_").encode()
        assert secret_du_jeton not in octets

    def test_la_liste_ne_rend_jamais_le_jeton(self, monde):
        _, sessions = monde
        jeton = _ouvrir(sessions)
        listees = sessions.list_sessions(PHONE)
        assert len(listees) == 1
        assert jeton not in repr(listees)
        assert set(listees[0]) == {
            "sessionId",
            "createdAtMs",
            "lastUsedAtMs",
            "expiresAtMs",
        }, "champs sur le fil en camelCase, et rien d'autre"
        assert len(listees[0]["sessionId"]) == 16, (
            "le sessionId est un préfixe court du hachage, pas le hachage entier"
        )


class TestDeuxEchangesConcurrents:
    def test_un_meme_ticket_ne_fait_qu_un_gagnant(self, monde):
        """Étape 1 : « deux échanges concurrents du même ticket ne donnent
        qu'un seul gagnant » — ici seize, lâchés ensemble, chacun sur sa
        propre connexion."""
        _, sessions = monde
        ticket = sessions.issue_ticket(PHONE)["ticket"]
        concurrents = 16
        depart = threading.Barrier(concurrents)

        def echanger(_):
            depart.wait()
            return sessions.redeem_ticket(ticket)

        with ThreadPoolExecutor(max_workers=concurrents) as pool:
            resultats = list(pool.map(echanger, range(concurrents)))

        gagnants = [r for r in resultats if r is not None]
        assert len(gagnants) == 1, f"{len(gagnants)} sessions pour un seul ticket"
        assert len(sessions.list_sessions(PHONE)) == 1


class TestFermerSansRevoquer:
    def test_fermer_les_sessions_laisse_l_appareil_appaire(self, monde):
        registry, sessions = monde
        jeton = _ouvrir(sessions)
        autre = _ouvrir(sessions)
        assert sessions.close_device_sessions(PHONE) == 2
        assert sessions.verify_session(jeton) is None
        assert sessions.verify_session(autre) is None
        assert registry.get(PHONE)["trustLevel"] == "TRUSTED"
        assert sessions.verify_session(_ouvrir(sessions)) is not None, (
            "l'appareil doit pouvoir rouvrir une session avec sa clé"
        )

    def test_fermer_emporte_aussi_les_tickets(self, monde):
        """« Fermer ses sessions » depuis le Mac : un ticket émis dans la
        minute d'avant ne doit pas en rouvrir une (la docstring promet
        « every session and ticket »)."""
        _, sessions = monde
        ticket = sessions.issue_ticket(PHONE)["ticket"]
        sessions.close_device_sessions(PHONE)
        assert sessions.redeem_ticket(ticket) is None, (
            "un ticket a survécu à la fermeture et rouvert une session"
        )

    def test_fermer_une_session_n_en_ferme_qu_une(self, monde):
        _, sessions = monde
        jeton = _ouvrir(sessions)
        autre = _ouvrir(sessions)
        assert sessions.close_session(jeton) is True
        assert sessions.verify_session(jeton) is None
        assert sessions.verify_session(autre) is not None


class TestLaDerniereActivite:
    def test_elle_n_est_ecrite_qu_une_fois_par_minute(self, monde, tmp_path):
        """Chaque GET de la WebView n'a pas à devenir une écriture."""
        _, sessions = monde
        jeton = _ouvrir(sessions)
        with closing(sqlite3.connect(tmp_path / "mesh.db")) as conn, conn:
            conn.execute("UPDATE mesh_sessions SET last_used_at_ms = 1000")
        sessions.verify_session(jeton)
        premiere = sessions.list_sessions(PHONE)[0]["lastUsedAtMs"]
        assert premiere > 1000, "une activité vieille de 56 ans doit être rafraîchie"

        sessions.verify_session(jeton)
        seconde = sessions.list_sessions(PHONE)[0]["lastUsedAtMs"]
        assert seconde == premiere, (
            f"réécrite avant {SESSION_TOUCH_INTERVAL_MS} ms : une écriture par GET"
        )
