"""Délais de connexion, plafond par adresse, codes à usage unique.

Conception : ``docs/development/compte-chiffre.md`` §3.3, §3.5 et étape 4
du §6 (« Limites et codes »).
"""

from __future__ import annotations

import os
import threading

from diapason_comptes import jetons
from diapason_comptes.base import Base
from diapason_comptes.limites import (
    FAMILLE_CONNEXION,
    LimiteurConnexions,
    prefixe_ip,
)
from diapason_comptes.validation import b64url
from tests.diapason_comptes._outils import (
    DEBUT_MS,
    MINUTE_MS,
    code_de,
    secrets_de_test,
)


def _mauvais_login(client, email: str):
    return client.post(
        "/api/v1/login", json={"email": email, "authKey": b64url(os.urandom(32))}
    )


class TestPrefixes:
    def test_une_ip_devient_son_prefixe_24_ou_48(self):
        """§3.5 — le délai porte sur (adresse, préfixe) : une box qui change
        d'IP dans son /24 reste le même compteur, et l'IP entière n'est
        jamais gardée (D11)."""
        assert prefixe_ip("203.0.113.77") == "203.0.113.0/24", "IPv4 → /24"
        assert prefixe_ip("2001:db8:1:2:3::4") == "2001:db8:1::/48", "IPv6 → /48"
        assert prefixe_ip("::ffff:198.51.100.9") == "198.51.100.0/24", "IPv4 mappée"


class TestDelaisDeConnexion:
    def test_cinq_echecs_gratuits_puis_deux_minutes_pour_ce_prefixe_seulement(
        self, service
    ):
        """§3.5 — 5 échecs gratuits par (adresse, préfixe), puis 2^(n−5) min :
        2 min au 6e échec. Jusqu'au 24/09/2026, le code calculait 2^(n−6),
        une minute, et chaque délai de la suite valait la moitié du texte.
        Un autre préfixe n'est pas puni pour celui-là, et une réussite remet
        à zéro."""
        inscrit = service.inscrire("delai@exemple.org")
        attaquant = service.depuis("203.0.113.10")
        for n in range(6):
            r = _mauvais_login(attaquant, inscrit.email)
            assert r.status_code == 401, f"échec n°{n + 1} compté, pas encore bloqué"
        bloque = _mauvais_login(attaquant, inscrit.email)
        assert bloque.status_code == 429, "le 7e essai attend"
        assert bloque.json()["error"] == {
            "code": "tooManyAttempts",
            "retryAfterS": 120,
        }
        assert bloque.headers["retry-after"] == "120", "Retry-After pour le client"

        ailleurs = service.connecter(inscrit, service.depuis("198.51.100.4"))
        assert ailleurs.status_code == 200, "un autre préfixe n'est pas bloqué"

        service.horloge.avancer(MINUTE_MS + 1000)
        assert service.connecter(inscrit, attaquant).status_code == 429, (
            "une minute ne suffit pas : le 6e échec coûte deux minutes"
        )
        service.horloge.avancer(MINUTE_MS)
        assert service.connecter(inscrit, attaquant).status_code == 200, (
            "après les deux minutes, la bonne clé passe"
        )
        assert _mauvais_login(attaquant, inscrit.email).status_code == 401, (
            "la réussite a remis le compteur à zéro"
        )

    def test_le_delai_double_et_plafonne_a_une_heure(self, tmp_path):
        """§3.5 — 2, 4, 8… min (2^(n−5)), jamais plus de 60 : pas de
        verrouillage permanent qu'un inconnu pourrait infliger à une adresse."""
        base = Base(tmp_path / "limites.db")
        limiteur = LimiteurConnexions(secrets_de_test())
        attendus = [0, 0, 0, 0, 0, 120, 240, 480, 960, 1920, 3600, 3600, 3600]
        vus = []
        with base.transaction() as conn:
            for _ in attendus:
                limiteur.echec(conn, "a@exemple.org", "p", DEBUT_MS)
                vus.append(limiteur.attente_s(conn, "a@exemple.org", "p", DEBUT_MS))
        base.fermer()
        assert vus == attendus, f"délais {vus}"

    def test_cent_echecs_de_prefixes_differents_bloquent_l_adresse_pour_la_journee(
        self, service
    ):
        """§3.5 — plafond lâche par adresse, toutes IP confondues : 100 échecs
        par jour, puis blocage des NOUVELLES connexions pour la journée et un
        seul courriel « connexions bloquées ». Les appareils déjà connectés
        ne sont pas touchés (risque résiduel dit dans la conception)."""
        inscrit = service.inscrire("plafond@exemple.org")
        for i in range(20):
            client = service.depuis(f"10.{i}.0.1")
            for _ in range(5):
                assert _mauvais_login(client, inscrit.email).status_code == 401
        neuf = service.connecter(inscrit, service.depuis("192.0.2.1"))
        assert neuf.status_code == 429, "la bonne clé d'un préfixe neuf attend aussi"
        assert service.get("/account", headers=inscrit.bearer).status_code == 200, (
            "une session existante n'est pas touchée"
        )
        service.expediteur.attendre(inscrit.email, "connexions_bloquees")
        service.ctx.courrier.file.arreter()
        assert (
            len(service.expediteur.messages(inscrit.email, "connexions_bloquees")) == 1
        ), "un seul avis par jour"
        service.horloge.avancer(24 * 60 * MINUTE_MS + 1)
        assert (
            service.connecter(inscrit, service.depuis("192.0.2.1")).status_code == 200
        ), "le lendemain, la connexion repasse"

    def test_les_echecs_de_reset_confirm_comptent_avec_ceux_de_login(self, service):
        """§3.4 — sinon deviner un code de réinitialisation serait un second
        guichet, sans délai, à côté de ``/login``."""
        inscrit = service.inscrire("guichet@exemple.org")
        client = service.depuis("203.0.113.20")
        for _ in range(3):
            r = client.post(
                "/api/v1/reset/confirm", json={"email": inscrit.email, "code": "000000"}
            )
            assert r.status_code == 400, "code faux"
        for _ in range(3):
            assert _mauvais_login(client, inscrit.email).status_code == 401
        assert _mauvais_login(client, inscrit.email).status_code == 429, (
            "3 + 3 échecs : le 7e essai attend, quel que soit le guichet"
        )
        r = client.post(
            "/api/v1/reset/confirm", json={"email": inscrit.email, "code": "000000"}
        )
        assert r.status_code == 429, "et reset/confirm attend aussi"

    def test_trente_echecs_par_heure_bloquent_une_ip_toutes_adresses(self, service):
        """§3.5 — par IP, en mémoire : 30 échecs par heure. Sans lui, un robot
        essaie 5 mots de passe gratuits sur chaque adresse d'une liste."""
        client = service.depuis("203.0.113.30")
        for i in range(30):
            r = _mauvais_login(client, f"liste{i}@exemple.org")
            assert r.status_code == 401, f"échec {i + 1}"
        r = _mauvais_login(client, "encore@exemple.org")
        assert r.status_code == 429, "la 31e tentative de l'heure attend"


class TestCodes:
    def test_de_deux_consommations_concurrentes_une_seule_gagne(self, tmp_path):
        """§3.3 — consommation atomique : deux ``signup/verify`` simultanés
        avec le bon code ne créent pas deux jetons d'inscription."""
        base = Base(tmp_path / "codes.db")
        secrets_ = secrets_de_test()
        index = secrets_.index_courriel("course@exemple.org")
        for tour in range(25):
            with base.transaction() as conn:
                jetons.enregistrer_code(
                    conn, secrets_, index, "inscription", "123456", DEBUT_MS + tour
                )
            depart = threading.Barrier(2)
            gagnants: list[bool] = []

            def consommer() -> None:
                depart.wait()
                with base.transaction() as conn:
                    gagnants.append(
                        jetons.consommer_code(
                            conn,
                            secrets_,
                            index,
                            "inscription",
                            "123456",
                            DEBUT_MS + tour,
                        )
                    )

            fils = [threading.Thread(target=consommer) for _ in range(2)]
            for fil in fils:
                fil.start()
            for fil in fils:
                fil.join()
            assert sorted(gagnants) == [False, True], f"tour {tour} : {gagnants}"
        base.fermer()

    def test_un_code_meurt_apres_cinq_essais(self, service):
        """§3.5 — cinq essais par code : au-delà, même le bon code est refusé
        et il faut en demander un autre (au plus 10 par jour)."""
        email = "essais@exemple.org"
        service.post("/signup/start", {"email": email, "termsVersion": 1})
        code = code_de(service.expediteur.attendre(email, "code_inscription"))
        faux = "000000" if code != "000000" else "111111"
        for _ in range(5):
            r = service.post("/signup/verify", {"email": email, "code": faux})
            assert r.status_code == 400, "code faux"
        r = service.post("/signup/verify", {"email": email, "code": code})
        assert r.status_code == 400, "le bon code est mort après cinq essais"

    def test_un_code_expire_apres_quinze_minutes(self, service):
        """§3.5 — 15 min de validité."""
        email = "expire@exemple.org"
        service.post("/signup/start", {"email": email, "termsVersion": 1})
        code = code_de(service.expediteur.attendre(email, "code_inscription"))
        service.horloge.avancer(15 * MINUTE_MS + 1)
        r = service.post("/signup/verify", {"email": email, "code": code})
        assert r.status_code == 400, "code expiré"

    def test_seul_le_hmac_du_code_est_garde(self, service):
        """§3.3 — un SHA-256 nu d'un code à six chiffres se renverse en un
        million d'essais ; le HMAC poivré, non, sans ``comptes.env``."""
        email = "hmac@exemple.org"
        service.post("/signup/start", {"email": email, "termsVersion": 1})
        code = code_de(service.expediteur.attendre(email, "code_inscription"))
        with service.ctx.base.lecture() as conn:
            (mac,) = conn.execute("SELECT code_mac FROM codes").fetchone()
        assert code.encode() not in mac, "le code n'est pas en clair"
        assert len(mac) == 33, "version + HMAC-SHA256"
        assert FAMILLE_CONNEXION == b"connexion", "familles de compteurs stables"


class TestConnexionsBloquees:
    """§3.5 — « connexions bloquées », une fois par jour, au titulaire."""

    def _cent_echecs(self, service, email: str) -> None:
        for i in range(20):
            client = service.depuis(f"10.{i}.0.1")
            for _ in range(5):
                assert _mauvais_login(client, email).status_code == 401

    def test_aucun_avis_vers_une_adresse_sans_compte(self, service):
        """§100 — « votre compte Diapason » écrit à une adresse qui n'en a
        pas est un faux énoncé. Jusqu'au 24/09/2026, cent échecs sur
        n'importe quelle adresse faisaient écrire le service à ce tiers, une
        fois par jour, sur le budget des codes. Le budget est compté
        pareil (aucune énumération), mais rien ne part."""
        from diapason_comptes.limites import BUDGET_CODES

        self._cent_echecs(service, "sans.compte@exemple.org")
        service.ctx.courrier.file.arreter()
        assert service.expediteur.messages("sans.compte@exemple.org") == [], (
            "aucun courriel vers une adresse sans compte"
        )
        with service.ctx.base.lecture() as conn:
            envois = service.ctx.courrier.budgets.envois_du_jour(
                conn, BUDGET_CODES, service.horloge()
            )
        assert envois == 1, "le budget est compté comme pour un vrai compte"

    def test_cent_echecs_ne_touchent_pas_au_budget_de_securite(self, service):
        """§3.5 — « connexions bloquées » est déclenché par des échecs, donc
        par n'importe qui : il puise dans le budget des codes. Le test du
        budget réservé s'arrêtait à 60 échecs, sous le seuil ; un avis
        déplacé vers le budget réservé y passait inaperçu."""
        from diapason_comptes.limites import BUDGET_SECURITE

        inscrit = service.inscrire("seuil@exemple.org")
        self._cent_echecs(service, inscrit.email)
        service.expediteur.attendre(inscrit.email, "connexions_bloquees")
        with service.ctx.base.lecture() as conn:
            securite = service.ctx.courrier.budgets.envois_du_jour(
                conn, BUDGET_SECURITE, service.horloge()
            )
        assert securite == 0, "le budget réservé n'a pas bougé"
