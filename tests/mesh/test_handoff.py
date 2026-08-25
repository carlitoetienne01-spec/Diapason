"""« Continue ça sur mon téléphone » — et ce que l'outil refuse de promettre.

Spatial Mesh, handoff — 25 août 2026. Le client mobile ouvre un écran et
met en évidence une tâche ou un projet ; il ne sait restaurer ni onglet, ni
filtre, ni position. L'outil n'envoie donc rien de tout cela, et la phrase
qu'il rend vient du RÉCEPTEUR — jamais de ce qu'on a envoyé.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from diapason.desktop import contexte_app as ca


@pytest.fixture(autouse=True)
def _table_rase():
    ca.oublier()
    yield
    ca.oublier()


def _outil():
    from diapason.tools.mesh_tools import HandoffContinueTool

    return HandoffContinueTool()


class TestSansContexte:
    def test_rien_d_ouvert_se_dit_au_lieu_de_deviner(self):
        resultat = _outil().execute(device_phrase="mon téléphone")
        assert not resultat.success
        assert resultat.metadata["status"] == "NO_ACTIVE_CONTEXT"
        assert "ce que tu regardes" in resultat.content


class TestAvecUneRessource:
    def test_le_projet_ouvert_part_vers_l_appareil(self):
        ca.poser_contexte(
            "/succes/projects", ressource_type="project",
            ressource_id="p_42", ressource_titre="Zéro à Héro",
        )
        envois = []

        def faux_dispatch(**kw):
            envois.append(kw)
            return {
                "status": "SUCCESS",
                "userSafeMessage": "Le projet est affiché sur Succès.",
                "commandId": "c1",
            }

        with patch("diapason.mesh.dispatch.dispatch_command", faux_dispatch), patch.object(
            _outil().__class__, "_target", lambda self, p, moi: "dev_cible"
        ):
            resultat = _outil().execute(device_phrase="mon téléphone")

        assert resultat.success
        assert envois[0]["tool"] == "app.show_resource"
        assert envois[0]["arguments"] == {
            "resourceType": "project",
            "resourceId": "p_42",
        }
        # AUCUN état de vue n'est envoyé : le client ne sait pas le lire.
        assert set(envois[0]["arguments"]) == {"resourceType", "resourceId"}

    def test_la_phrase_vient_du_recepteur_pas_de_l_envoi(self):
        """Le récepteur seul sait ce qui s'est passé. Fabriquer la phrase à
        l'émission, c'est promettre ce qu'on n'a pas constaté."""
        ca.poser_contexte(
            "/succes/notes", ressource_type="note",
            ressource_id="n1", ressource_titre="Idées",
        )
        with patch(
            "diapason.mesh.dispatch.dispatch_command",
            lambda **kw: {
                "status": "SUCCESS",
                "userSafeMessage": "L'écran est ouvert sur Succès.",
            },
        ), patch.object(
            _outil().__class__, "_target", lambda self, p, moi: "dev_cible"
        ):
            resultat = _outil().execute(device_phrase="iPad")
        assert resultat.content == "L'écran est ouvert sur Succès."

    def test_un_echec_du_recepteur_reste_un_echec(self):
        ca.poser_contexte(
            "/succes/projects", ressource_type="project",
            ressource_id="p1", ressource_titre="X",
        )
        with patch(
            "diapason.mesh.dispatch.dispatch_command",
            lambda **kw: {
                "status": "OFFLINE",
                "userSafeMessage": "« iPad » est hors ligne.",
            },
        ), patch.object(
            _outil().__class__, "_target", lambda self, p, moi: "dev_cible"
        ):
            resultat = _outil().execute(device_phrase="iPad")
        assert not resultat.success
        assert "hors ligne" in resultat.content


class TestEcranSansRessource:
    def test_un_ecran_adressable_s_ouvre_ailleurs(self):
        ca.poser_contexte("/succes/tasks")
        envois = []
        with patch(
            "diapason.mesh.dispatch.dispatch_command",
            lambda **kw: envois.append(kw) or {"status": "SUCCESS", "userSafeMessage": "ok"},
        ), patch.object(
            _outil().__class__, "_target", lambda self, p, moi: "dev_cible"
        ):
            _outil().execute(device_phrase="téléphone")
        assert envois[0]["tool"] == "app.navigate"
        assert envois[0]["arguments"] == {"route": "success://tasks"}

    def test_un_ecran_qui_n_existe_pas_ailleurs_se_dit(self):
        """Les Finances n'ont pas de route success:// : le dire vaut mieux
        qu'ouvrir un écran approchant."""
        ca.poser_contexte("/succes/finances")
        resultat = _outil().execute(device_phrase="téléphone")
        assert not resultat.success
        assert "n'existe pas sur les autres appareils" in resultat.content


class TestContrat:
    def test_l_outil_est_dans_la_trousse_du_chat(self):
        from diapason.server.routes import _TROUSSE_ASSISTANT

        assert "handoff_continue" in _TROUSSE_ASSISTANT

    def test_il_ne_demande_aucun_identifiant_de_ressource(self):
        """Le modèle n'a aucun moyen de connaître un id : le lui demander
        garantirait qu'il l'invente."""
        props = _outil().spec.parameters["properties"]
        assert set(props) == {"device_phrase", "device_id"}


class TestLeVraiCheminDeResolution:
    """Sans ce test, un défaut d'initialisation restait invisible : tous les
    autres remplacent _target, donc n'exercent jamais la résolution réelle.
    Constaté le 25 août 2026 — l'outil levait AttributeError au premier
    appel véritable."""

    def test_aucune_flotte_rend_un_aveu_pas_une_exception(self, tmp_path):
        from diapason.mesh.registry import DeviceRegistry
        from diapason.tools.mesh_tools import HandoffContinueTool

        ca.poser_contexte(
            "/succes/projects", ressource_type="project",
            ressource_id="p1", ressource_titre="X",
        )
        outil = HandoffContinueTool()
        outil._registry = DeviceRegistry(tmp_path / "vide.db")
        resultat = outil.execute(device_phrase="mon téléphone")
        assert not resultat.success
        assert resultat.content, "un aveu lisible, jamais une trace de pile"
