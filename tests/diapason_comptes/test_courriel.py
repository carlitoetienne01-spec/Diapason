"""Courriels : fil dédié, budgets, circuit, modèles.

Conception : ``docs/development/compte-chiffre.md`` §3.1, §3.5, D8, D12 et
étape 4 du §6 (« Courriel »). Aucun courriel réel : ``FauxExpediteur``.
"""

from __future__ import annotations

import os
import time

from diapason_comptes.courriel import (
    GENRES_CODES,
    GENRES_SECURITE,
    PIED_EN,
    PIED_FR,
    FileCourriels,
    rediger,
)
from diapason_comptes.limites import BUDGET_CODES, BUDGET_SECURITE
from diapason_comptes.validation import b64url
from tests.diapason_comptes._outils import HEURE_MS, FauxExpediteur


def _envois(service, budget: str) -> int:
    with service.ctx.base.lecture() as conn:
        return service.ctx.courrier.budgets.envois_du_jour(
            conn, budget, service.horloge()
        )


class TestFilDedie:
    def test_un_expediteur_bloque_60_s_ne_retarde_pas_health(self, fabrique):
        """§3.1 — les courriels ne passent JAMAIS par ``BackgroundTasks``,
        qui partage le pool des routes ``def`` : quarante envois bloqués et
        ``/health`` ne répondait plus. Ici, un fil à part."""
        expediteur = FauxExpediteur()
        expediteur.retenir = True
        service = fabrique(expediteur=expediteur)
        r = service.post(
            "/signup/start", {"email": "lent@exemple.org", "termsVersion": 1}
        )
        assert r.status_code == 202, "la route ne fait que déposer"
        assert expediteur.entre.wait(5), "l'expéditeur est entré dans son envoi"

        debut = time.monotonic()
        for _ in range(20):
            assert service.get("/health").status_code == 200, "/health répond"
        r = service.post(
            "/signup/start", {"email": "autre@exemple.org", "termsVersion": 1}
        )
        duree = time.monotonic() - debut
        assert r.status_code == 202, "une autre inscription dépose aussi"
        assert duree < 2.0, f"expéditeur bloqué, mais /health en {duree:.2f} s"
        expediteur.relache.set()
        expediteur.attendre("lent@exemple.org", "code_inscription")

    def test_une_file_pleine_abandonne_sans_attendre(self):
        """§3.1 — ``put_nowait`` : file pleine, l'envoi est abandonné et
        compté, jamais attendu par la route."""
        expediteur = FauxExpediteur()
        expediteur.retenir = True
        file = FileCourriels(expediteur, taille=1)
        message = rediger(
            "code_inscription", "a@exemple.org", bytes(33), origine_publique=None
        )
        try:
            debut = time.monotonic()
            resultats = [file.deposer(message) for _ in range(5)]
            assert time.monotonic() - debut < 0.5, "aucun dépôt n'attend"
            assert not all(resultats), "au moins un dépôt refusé"
            assert file.abandons >= 1, "l'abandon est compté"
        finally:
            expediteur.relache.set()
            file.arreter()


class TestBudgets:
    def test_mail_unavailable_quand_le_budget_des_codes_est_epuise(self, fabrique):
        """§3.5 — budget épuisé : 503 ``mailUnavailable`` sur ``signup/start``,
        ``vault/code`` et ``reset/request``. C'est un état GLOBAL : il ne dit
        rien d'une adresse, connue ou non."""
        service = fabrique(budget_codes=2)
        inscrit = service.inscrire("budget@exemple.org")
        r = service.post(
            "/signup/start", {"email": "deux@exemple.org", "termsVersion": 1}
        )
        assert r.status_code == 202, "deuxième code du jour"
        for chemin, corps, en_tetes in (
            ("/signup/start", {"email": "trois@exemple.org", "termsVersion": 1}, {}),
            ("/reset/request", {"email": inscrit.email}, {}),
            ("/reset/request", {"email": "inconnue@exemple.org"}, {}),
            ("/vault/code", {}, inscrit.bearer),
        ):
            r = service.post(chemin, corps, headers=en_tetes)
            assert r.status_code == 503, f"{chemin} : budget épuisé"
            assert r.json() == {"error": {"code": "mailUnavailable"}}

    def test_mail_unavailable_quand_le_circuit_est_ouvert(self, fabrique):
        """§3.5 — cinq échecs de Resend de suite en 10 min ouvrent le circuit :
        mieux vaut dire « indisponible » que promettre un code qui ne part pas
        (§100)."""
        expediteur = FauxExpediteur()
        expediteur.echouer = True
        service = fabrique(
            expediteur=expediteur,
            file_courriels=lambda e: FileCourriels(e, delai_nouvel_essai_s=0.01),
        )
        for i in range(3):
            service.horloge.avancer(2 * HEURE_MS)
            r = service.post(
                "/signup/start", {"email": f"panne{i}@exemple.org", "termsVersion": 1}
            )
            assert r.status_code == 202, f"dépôt {i}"
        limite = time.monotonic() + 5
        while (
            not service.ctx.courrier.file.circuit_ouvert() and time.monotonic() < limite
        ):
            time.sleep(0.01)
        assert service.ctx.courrier.file.circuit_ouvert(), (
            "circuit ouvert après 5 échecs"
        )
        r = service.post(
            "/signup/start", {"email": "apres@exemple.org", "termsVersion": 1}
        )
        assert r.status_code == 503, "plus de promesse de code"
        assert r.json() == {"error": {"code": "mailUnavailable"}}

    def test_le_budget_des_avis_de_securite_n_est_pas_consommable_sans_authentification(
        self, fabrique
    ):
        """§3.5, D12 — un inconnu qui martèle ``signup/start``, ``login`` ou
        ``reset/request`` n'épuise JAMAIS le budget réservé aux avis de
        sécurité : « nouvelle connexion » part encore après."""
        service = fabrique(budget_securite=1)
        inscrit = service.inscrire("reserve@exemple.org")
        assert _envois(service, BUDGET_SECURITE) == 0, "l'inscription n'en consomme pas"
        for i in range(10):
            service.horloge.avancer(2 * HEURE_MS // 10)
            client = service.depuis(f"10.9.{i}.1")
            service.post("/signup/start", {"email": inscrit.email, "termsVersion": 1})
            service.post("/reset/request", {"email": inscrit.email})
            for _ in range(5):
                client.post(
                    "/api/v1/login",
                    json={"email": inscrit.email, "authKey": b64url(os.urandom(32))},
                )
            client.post(
                "/api/v1/reset/confirm", json={"email": inscrit.email, "code": "000000"}
            )
            client.post(
                "/api/v1/recovery/unwrap",
                json={
                    "email": inscrit.email,
                    "recoveryAuthKey": b64url(os.urandom(32)),
                },
            )
        assert _envois(service, BUDGET_SECURITE) == 0, (
            "aucune action non authentifiée n'a puisé dans le budget réservé"
        )
        assert _envois(service, BUDGET_CODES) > 0, "le budget des codes, lui, a servi"
        r = service.connecter(inscrit, service.depuis("192.0.2.77"))
        assert r.status_code == 200, r.text
        service.expediteur.attendre(inscrit.email, "nouvelle_connexion")


class TestModeles:
    def test_chaque_courriel_est_bilingue_porte_le_pied_et_aucun_jeton(self):
        """§3.5 — FR puis EN, le pied « ne vous demandera jamais… », aucun
        lien porteur de jeton (les liens ``diapason://`` sont morts) et, pour
        « nouvelle connexion », ni IP ni lieu (D8, D11)."""
        for genre in GENRES_CODES | GENRES_SECURITE:
            m = rediger(
                genre,
                "a@exemple.org",
                bytes(33),
                origine_publique="https://exemple.invalid",
                code="123456",
                date_ms=1_790_000_000_000,
            )
            assert PIED_FR in m.texte and PIED_EN in m.texte, f"pied de {genre}"
            assert "diapason://" not in m.texte, f"aucun lien profond dans {genre}"
            assert "token" not in m.texte.lower(), f"aucun jeton dans {genre}"
            assert m.texte.index(PIED_FR) < m.texte.index(PIED_EN), "FR puis EN"
        connexion = rediger(
            "nouvelle_connexion", "a@exemple.org", bytes(33), origine_publique=None
        )
        assert "IP" not in connexion.texte, "aucune IP (D11)"
        assert "nouvelle_connexion" in GENRES_SECURITE, "avis de sécurité"


class TestBudgetReserve:
    """§3.5 — le budget des avis de sécurité « est réservé et ne peut pas
    être épuisé par un inconnu ». Une fois les inscriptions ouvertes,
    n'importe qui est titulaire d'un compte : jusqu'au 24/09/2026, vingt
    ``/login`` d'un compte à soi vidaient le budget du jour, et le « mot de
    passe changé » d'un autre compte ne partait plus, sans un mot."""

    def test_des_connexions_en_boucle_n_etouffent_pas_mot_de_passe_change(
        self, fabrique
    ):
        service = fabrique(budget_securite=20)
        intrus = [service.inscrire(f"intrus{i}@exemple.org") for i in range(3)]
        victime = service.inscrire("victime@exemple.org")
        for compte in intrus:
            for _ in range(20):
                assert service.connecter(compte).status_code == 200
        r = service.post(
            "/vault/commit",
            service.corps_commit(victime, nouvelle_auth=os.urandom(32)),
            headers=victime.bearer,
        )
        assert r.status_code == 200, r.text
        service.expediteur.attendre(victime.email, "mot_de_passe_change")

    def test_un_compte_ne_recoit_pas_plus_de_dix_avis_par_jour(self, fabrique):
        """§3.5 — « par adresse, sur TOUS les envois » : 10 par jour, avis de
        sécurité compris."""
        service = fabrique()
        intrus = service.inscrire("bavard@exemple.org")
        for _ in range(30):
            assert service.connecter(intrus).status_code == 200
        service.ctx.courrier.file.arreter()
        recus = service.expediteur.messages(intrus.email, "nouvelle_connexion")
        assert len(recus) == 10, f"{len(recus)} avis « nouvelle connexion »"


class TestPied:
    def test_chaque_courriel_se_termine_par_la_phrase_de_securite(self):
        """§3.5 — « Chaque courriel se TERMINE par » la phrase de sécurité ;
        les liens vers les pages légales passaient après elle."""
        for genre in GENRES_CODES | GENRES_SECURITE:
            m = rediger(
                genre,
                "a@exemple.org",
                bytes(33),
                origine_publique="https://exemple.invalid",
                code="123456",
                date_ms=1_790_000_000_000,
            )
            assert m.texte.endswith(PIED_EN), f"{genre} finit par le pied"
            assert "https://exemple.invalid/confidentialite" in m.texte, (
                f"{genre} garde le lien vers /confidentialite"
            )
