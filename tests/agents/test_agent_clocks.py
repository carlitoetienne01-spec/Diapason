"""L'heure qu'un agent croit qu'il est, et le nom qu'il lui donne.

Trois agents avaient besoin du même calcul et l'avaient raté de la même
façon : afficher l'heure de la MACHINE sous le nom du fuseau CONFIGURÉ.
Quand les deux diffèrent, c'est pire qu'une heure fausse — l'heure est juste
et l'étiquette ment, donc rien, dans ce qu'on lit, ne permet de s'en
apercevoir.

L'agent proactif n'affiche pas seulement cette date : il décide sur elle
d'archiver ou de supprimer du courrier.
"""

from __future__ import annotations

import datetime as dt

import pytest


class TestNowInDitToujoursSonVraiFuseau:
    @pytest.fixture(autouse=True)
    def _outil(self):
        global now_in
        from diapason.core.utils import now_in  # noqa: F811
        globals()['now_in'] = now_in

    def test_un_fuseau_nomme_est_respecte(self):
        paris = now_in("Europe/Paris")
        assert paris.utcoffset() in (dt.timedelta(hours=1), dt.timedelta(hours=2))

    def test_vide_signifie_cette_machine(self):
        assert now_in("").utcoffset() == dt.datetime.now().astimezone().utcoffset()

    def test_le_resultat_porte_toujours_un_fuseau(self):
        """Un datetime naïf est ce qui a permis la confusion : il ne dit pas
        d'où il vient, donc on peut lui coller n'importe quelle étiquette."""
        for tz in ("", "Europe/Paris", "Asia/Tokyo", "Mars/Olympus"):
            assert now_in(tz).tzinfo is not None, tz

    def test_un_fuseau_inconnu_retombe_sur_la_machine(self):
        """Une coquille dans la configuration ne doit pas faire échouer un
        briefing ni une exécution planifiée."""
        assert now_in("Mars/Olympus").utcoffset() == (
            dt.datetime.now().astimezone().utcoffset()
        )


class TestAucunAgentNAffirmeUneVille:
    """Le défaut était « America/Los_Angeles » — une côte que le logiciel
    n'a aucune raison de connaître. Un assistant local-first lit l'horloge
    de la machine plutôt que de supposer où vit la personne."""

    def test_le_briefing(self):
        from diapason.core.config import DigestConfig

        assert DigestConfig().timezone == ""

    def test_l_agent_proactif(self):
        from diapason.core.config import ProactiveConfig

        assert ProactiveConfig().timezone == ""


class TestLaPhraseEnvoyeeAuModele:
    @pytest.fixture
    def agent(self):
        from diapason.agents.proactive_agent import ProactiveAgent

        a = ProactiveAgent.__new__(ProactiveAgent)
        a._timezone = ""
        a._approval_store = None
        return a

    def ligne_du_jour(self, agent) -> str:
        return next(
            ligne
            for ligne in agent._build_system_prompt().splitlines()
            if ligne.startswith("Today is")
        )

    def test_elle_nomme_le_fuseau_de_l_heure_qu_elle_donne(self, agent):
        """Elle disait « (America/Los_Angeles) » à côté d'une date de
        Toronto. Le nom vient maintenant de l'horodatage lui-même, donc les
        deux ne peuvent plus diverger."""
        maintenant = dt.datetime.now().astimezone()
        ligne = self.ligne_du_jour(agent)
        assert maintenant.tzname() in ligne
        assert "America/Los_Angeles" not in ligne

    def test_elle_donne_aussi_l_heure_et_le_decalage(self, agent):
        """La date seule ne se vérifie pas : deux fuseaux la partagent
        vingt et une heures sur vingt-quatre."""
        ligne = self.ligne_du_jour(agent)
        assert "UTC" in ligne
        assert maintenant_hhmm() in ligne

    def test_un_fuseau_explicite_est_suivi(self, agent):
        agent._timezone = "Asia/Tokyo"
        ligne = self.ligne_du_jour(agent)
        from diapason.core.utils import now_in

        tokyo = now_in("Asia/Tokyo")
        assert tokyo.strftime("%A, %B %d, %Y") in ligne


def maintenant_hhmm() -> str:
    return dt.datetime.now().astimezone().strftime("%H:%M")
