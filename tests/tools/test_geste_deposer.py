"""« Envoie ça sur mon téléphone » — le geste, terminé à la voix.

Spatial Mesh, gestes — 25 août 2026. Fermer le poing retient ce que l'écran
affiche ; ouvrir la main le dépose. Mais quand plusieurs appareils sont
capables, le serveur POSE la question « vers lequel ? », et jusqu'ici la
seule façon d'y répondre était de cliquer.

Le maillon manquant n'était pas un réglage : AUCUN outil, aucun chemin
vocal, aucun chemin chat ne connaissait l'existence du presse-papiers
spatial. `handoff_continue` repartait de l'écran courant, donc répondre
« sur l'iPad » après avoir attrapé un projet envoyait ce qui était affiché
à cet instant — pas ce qui était dans la main.
"""

from __future__ import annotations

# Armer le mode gestes exige Vision : sans lui, /v1/gestures/arm rend 503, la
# session n'existe pas, et chaque test qui lit son état casse en KeyError ou
# en AttributeError. Quarante-huit échecs à la première exécution de CI, le
# 26 août 2026 — pas des défauts du code, des tests qui exigeaient sans dire.
import sys  # noqa: E402
from unittest.mock import patch

import pytest

from diapason.desktop import contexte_app as ca
from diapason.desktop import presse_papiers_spatial as pp
from diapason.server import gestes_routes as gr


def _vision_indisponible() -> bool:
    if sys.platform != "darwin":
        return True
    from diapason.desktop.vision_mains import disponible

    return not disponible()


pytestmark = pytest.mark.skipif(
    _vision_indisponible(),
    reason="Vision indisponible : API macOS, extra `desktop` requis",
)


@pytest.fixture(autouse=True)
def _table_rase():
    ca.oublier()
    pp.vider()
    gr.desarmer()
    yield
    ca.oublier()
    pp.vider()
    gr.desarmer()


def _outil():
    from diapason.tools.gestes_spatiaux import GesteDeposerTool

    return GesteDeposerTool()


def _appareil(nom, capacites=("app.show_resource", "app.navigate")):
    return {
        "deviceId": f"dev_{nom}",
        "name": nom,
        "trustLevel": "TRUSTED",
        "capabilities": list(capacites),
    }


def _attraper_un_projet():
    ca.poser_contexte(
        "/succes/projects",
        ressource_type="project",
        ressource_id="p1",
        ressource_titre="Zéro à Héro",
    )
    return pp.attraper()


class TestLaMainEstLeSeulReferent:
    def test_une_main_vide_se_dit_au_lieu_d_envoyer(self):
        """L'OUTIL le dit — parce qu'on l'a appelé. Le contexte, lui, se
        tait : une phrase « ta main est vide » à chaque tour de chaque
        session n'apprendrait rien à personne."""
        resultat = _outil().execute(device_phrase="mon téléphone")
        assert resultat.success is False
        assert resultat.metadata["status"] == "NOTHING_HELD"
        assert "vide" in resultat.content

    def test_il_ne_demande_aucun_identifiant_de_ressource(self):
        """Un outil qui accepterait « envoie le projet p1 » laisserait le
        modèle inventer ce qu'il envoie — ce que le geste existe pour
        éviter."""
        proprietes = _outil().spec.parameters["properties"]
        assert set(proprietes) == {"device_phrase", "device_id"}

    def test_il_declare_le_meme_risque_que_mesh_send(self):
        """Cela change ce qui s'affiche sur un écran près duquel
        l'utilisateur n'est peut-être pas : la cloche s'applique."""
        assert _outil().spec.metadata["risk"] == "outward_action"


class TestLaMainSeDitDansLeContexte:
    def test_le_contexte_nomme_ce_qui_est_tenu(self):
        _attraper_un_projet()
        attendu = "Dans la main (geste) : le projet « Zéro à Héro »."
        assert pp.decrire(pp.tenu()) == attendu

    def test_la_main_et_l_ecran_ne_se_confondent_pas(self):
        """Les deux phrases se suivent souvent. « Dans la main » et « Dans
        Diapason » se ressemblent assez pour que le modèle envoie l'un en
        croyant l'autre — c'est le défaut que ce raccordement corrige."""
        _attraper_un_projet()
        assert pp.decrire(pp.tenu()).startswith("Dans la main (geste)")
        assert ca.decrire(ca.dernier_contexte()).startswith("Dans Diapason")


class TestRepondreALaQuestionDejaPosee:
    """Le point le plus subtil : ne JAMAIS ouvrir une seconde question.

    Sans cela, un clic à l'écran et une réponse à la voix envoient deux fois.
    """

    def _poser_la_question(self):
        gr.armer()
        _attraper_un_projet()
        with (
            patch(
                "diapason.mesh.registry.DeviceRegistry.list_devices",
                return_value=[_appareil("iPad"), _appareil("PC du bureau")],
            ),
            patch(
                "diapason.mesh.presence.presence_of", return_value={"state": "ONLINE"}
            ),
            patch("diapason.mesh.dispatch.dispatch_command"),
        ):
            resultat = gr._deposer()
        assert resultat["reason"] == "AMBIGUOUS"
        return resultat

    def test_la_voix_tranche_parmi_les_candidats_mesures(self):
        self._poser_la_question()
        with patch(
            "diapason.mesh.dispatch.dispatch_command",
            return_value={
                "status": "SUCCESS",
                "userSafeMessage": "Le projet est affiché sur Succès.",
            },
        ) as envoi:
            resultat = _outil().execute(device_phrase="iPad")
        assert resultat.success is True
        assert envoi.call_args.kwargs["target_device_id"] == "dev_iPad"
        assert resultat.content == "Le projet est affiché sur Succès."

    def test_le_jeton_de_la_question_sert_de_cle_d_idempotence(self):
        """Un clic ET une phrase ne doivent envoyer qu'une fois."""
        attendu = gr.choix_en_attente
        self._poser_la_question()
        jeton = attendu()["jeton"]
        with patch(
            "diapason.mesh.dispatch.dispatch_command",
            return_value={"status": "SUCCESS", "userSafeMessage": "Affiché."},
        ) as envoi:
            _outil().execute(device_phrase="iPad")
        assert envoi.call_args.kwargs["idempotency_key"] == jeton

    def test_un_nom_qui_ne_correspond_a_rien_repose_la_question(self):
        """Une transcription approximative ne doit pas inventer une cible."""
        self._poser_la_question()
        with patch("diapason.mesh.dispatch.dispatch_command") as envoi:
            resultat = _outil().execute(device_phrase="la télévision du salon")
        assert resultat.success is False
        assert resultat.metadata["status"] == "AMBIGUOUS"
        assert "iPad" in resultat.content
        envoi.assert_not_called(), "rien ne part vers un appareil non proposé"

    def test_repondre_ferme_la_question(self):
        self._poser_la_question()
        with patch(
            "diapason.mesh.dispatch.dispatch_command",
            return_value={"status": "SUCCESS", "userSafeMessage": "Affiché."},
        ):
            _outil().execute(device_phrase="iPad")
        assert gr.choix_en_attente() is None
        assert pp.tenu() is None, "l'envoi fait, la main s'ouvre pour de bon"


class TestSansQuestionEnAttente:
    def test_un_seul_appareil_capable_recoit_directement(self):
        gr.armer()
        _attraper_un_projet()
        with (
            patch(
                "diapason.mesh.registry.DeviceRegistry.list_devices",
                return_value=[_appareil("iPad")],
            ),
            patch(
                "diapason.mesh.presence.presence_of", return_value={"state": "ONLINE"}
            ),
            patch(
                "diapason.mesh.dispatch.dispatch_command",
                return_value={"status": "SUCCESS", "userSafeMessage": "Affiché."},
            ) as envoi,
        ):
            resultat = _outil().execute(device_phrase="iPad")
        assert resultat.success is True
        assert envoi.call_args.kwargs["arguments"] == {
            "resourceType": "project",
            "resourceId": "p1",
        }

    def test_un_nom_qu_on_ne_resout_pas_garde_le_poing_ferme(self):
        """Rien n'a été dispatché, donc rien n'est consommé.

        C'est la règle de tout le chantier : la main ne se vide que sur une
        issue TERMINALE. Une phrase qu'on n'a pas su résoudre n'en est pas
        une — l'utilisateur doit pouvoir redire le nom.
        """
        gr.armer()
        _attraper_un_projet()
        with (
            patch(
                "diapason.mesh.registry.DeviceRegistry.list_devices",
                return_value=[_appareil("iPad"), _appareil("PC du bureau")],
            ),
            patch("diapason.mesh.dispatch.dispatch_command") as envoi,
        ):
            resultat = _outil().execute(device_phrase="quelque chose d'autre")
        assert resultat.success is False
        envoi.assert_not_called(), "rien ne part vers un appareil non résolu"
        assert pp.tenu() is not None, "un refus ne consomme pas ce qu'il refuse"

    def test_un_appareil_nomme_mais_hors_ligne_est_mis_en_file(self):
        """Différence DÉLIBÉRÉE avec le geste, et elle se justifie.

        Le geste ne mesure aucune direction : il ne propose donc que les
        appareils joignables, et refuse s'il n'y en a pas. À la voix,
        l'utilisateur a NOMMÉ l'appareil — le mettre en file pour qu'il le
        récupère au réveil respecte ce qu'il a demandé, et la phrase rendue
        vient du répartiteur, pas de nous.
        """
        gr.armer()
        _attraper_un_projet()
        with (
            patch(
                "diapason.mesh.registry.DeviceRegistry.list_devices",
                return_value=[_appareil("iPad")],
            ),
            patch(
                "diapason.mesh.dispatch.dispatch_command",
                return_value={
                    "status": "QUEUED",
                    "userSafeMessage": "C'est prêt pour iPad.",
                },
            ) as envoi,
        ):
            resultat = _outil().execute(device_phrase="iPad")
        envoi.assert_called_once()
        assert resultat.success is False, "« pas encore » n'est pas « fait »"
        assert resultat.content == "C'est prêt pour iPad."
        assert pp.tenu() is None, "un envoi a eu lieu : l'intention est consommée"


class TestLesDeuxTrousses:
    def test_l_outil_est_atteignable_au_chat(self):
        from diapason.server.routes import _TROUSSE_ASSISTANT

        assert "geste_deposer" in _TROUSSE_ASSISTANT

    def test_l_outil_est_atteignable_a_la_voix(self):
        """Contrairement à mesh_send : il ne choisit ni l'objet ni l'action,
        et devant une question il tranche dans une liste fermée."""
        from diapason.speech.realtime.tools import list_voice_tool_ids

        assert "geste_deposer" in list_voice_tool_ids()

    def test_le_chargeur_de_modules_le_connait(self):
        """Sans cette troisième entrée, la voix le filtrerait en silence."""
        from diapason.speech.realtime.tools import _TOOL_MODULES

        modules = {m for m, _ in _TOOL_MODULES}
        assert "diapason.tools.gestes_spatiaux" in modules
