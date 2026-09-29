"""§5/§100 : la voix et le chat manipulent la même épreuve, jamais un doublon."""

import asyncio

import pytest

from diapason.etudes.magasin import MagasinEtudes, vue_publique
from tests.server.test_etudes import demande, programme
from tests.server.test_etudes_routes import Moteur


@pytest.fixture
def service(tmp_path):
    from diapason.etudes.service import ServiceEtudes

    return ServiceEtudes(MagasinEtudes(tmp_path / "etudes.db"), Moteur())


class TestContinuiteEtude:
    @pytest.mark.asyncio
    async def test_un_premier_cours_est_prepare_avant_de_pouvoir_etre_demarre(
        self, service
    ):
        """§100 : la voix appelait start avec un identifiant fictif sans étude."""
        from diapason.etudes.conversation import (
            ContexteEtudes,
            etat_pour_modele,
            utiliser_contexte,
        )

        with utiliser_contexte(
            ContexteEtudes(
                service,
                "fil-test",
                "local",
                asyncio.get_running_loop(),
                demande="Prépare-moi un cours sur les fractions",
            )
        ):
            etat = await etat_pour_modele()
        assert "action=prepare" in etat
        assert "action=start" not in etat, "un cours absent ne peut pas démarrer"
        assert "sessionId=id" not in etat, "un exemple ne fournit pas de faux id"

    @pytest.mark.parametrize(
        "texte,attendu",
        [
            ("une question ouverte, deux questions au total", 2),
            ("Fais 12 questions", 12),
            ("J'ai deux heures", None),
            ("Deux questions ou trois questions ?", None),
            ("100 questions", 100),
        ],
    )
    def test_la_quantite_explicite_ne_devient_pas_le_defaut(self, texte, attendu):
        from diapason.etudes.conversation import nombre_questions_explicite

        assert nombre_questions_explicite(texte) == attendu

    @pytest.mark.asyncio
    async def test_le_modele_voit_le_materiel_et_la_question_sans_le_corrige(
        self, service
    ):
        from diapason.etudes.conversation import (
            ContexteEtudes,
            etat_pour_modele,
            utiliser_contexte,
        )

        s = service.depot.creer(demande(), programme())
        service.depot.modifier(s["id"], s["version"], "start", {})
        sources = [d.model_dump(by_alias=True) for d in demande().sources]
        with utiliser_contexte(
            ContexteEtudes(
                service,
                "fil-test",
                "local",
                asyncio.get_running_loop(),
                sources=sources,
            )
        ):
            etat = await etat_pour_modele()
        assert "cours.txt" in etat and s["id"] in etat
        assert "Quelle fraction" in etat and '"answer"' not in etat
        assert "Deux moitiés font une unité" not in etat

    def test_les_documents_prepares_sont_partages_et_supprimes_avec_le_fil(
        self, tmp_path
    ):
        depot = MagasinEtudes(tmp_path / "etudes.db")
        sources = [s.model_dump(by_alias=True) for s in demande().sources]
        depot.garder_sources("fil-test", sources)
        assert MagasinEtudes(depot.chemin).lire_sources("fil-test") == sources
        depot.supprimer_conversation("fil-test")
        assert depot.lire_sources("fil-test") == []
        with pytest.raises(ValueError, match="supprimée"):
            depot.garder_sources("fil-test", sources)

    def test_la_question_courante_survit_au_changement_de_canal(self, tmp_path):
        depot = MagasinEtudes(tmp_path / "etudes.db")
        s = depot.creer(demande(), programme())
        s = depot.modifier(s["id"], s["version"], "start", {})
        s = depot.modifier(s["id"], s["version"], "navigate", {"questionId": "q2"})
        assert (
            vue_publique(MagasinEtudes(depot.chemin).lire(s["id"]))["currentQuestionId"]
            == "q2"
        ), "la voix doit reprendre la question choisie à l'écran"

    @pytest.mark.asyncio
    async def test_le_test_oral_reutilise_les_sources_et_reponses_ecrites(
        self, service
    ):
        from diapason.etudes.conversation import ContexteEtudes, utiliser_contexte
        from diapason.tools.etudier import EtudierTool

        s = service.depot.creer(demande(mode="practice"), programme())
        contexte = ContexteEtudes(
            service, "fil-test", "local", asyncio.get_running_loop()
        )
        with utiliser_contexte(contexte):
            outil = EtudierTool()
            r = await asyncio.to_thread(outil.execute, action="read")
            assert r.success, r.content
            etude = r.metadata["study"]
            assert etude["sources"][0]["name"] == "cours.txt"
            r = await asyncio.to_thread(
                outil.execute,
                action="start",
                sessionId=s["id"],
                version=etude["version"],
            )
            etude = r.metadata["study"]
            r = await asyncio.to_thread(
                outil.execute,
                action="answer",
                sessionId=s["id"],
                version=etude["version"],
                choiceIndex=1,
            )
            assert not r.success, (
                "aucune réponse ne doit être inventée sans parole d'étudiant"
            )
            contexte.demande = "Je choisis la première réponse."
            r = await asyncio.to_thread(
                outil.execute,
                action="answer",
                sessionId=s["id"],
                version=etude["version"],
                choiceIndex=1,
            )
            assert r.success, r.content
            etude = r.metadata["study"]
            relu = vue_publique(service.depot.lire(s["id"]))
            assert relu["responses"]["q1"]["text"] == "1/2"
            assert relu["responses"]["q1"]["spokenText"] == contexte.demande
            r = await asyncio.to_thread(
                outil.execute,
                action="check",
                sessionId=s["id"],
                version=etude["version"],
            )
            assert r.success and r.metadata["study"]["grades"]["q1"]["score"] == 1

    @pytest.mark.asyncio
    async def test_une_reponse_libre_conserve_les_mots_de_letudiant(self, service):
        from diapason.etudes.conversation import ContexteEtudes, utiliser_contexte
        from diapason.tools.etudier import EtudierTool

        s = service.depot.creer(demande(), programme())
        s = service.depot.modifier(s["id"], s["version"], "start", {})
        s = service.depot.modifier(
            s["id"], s["version"], "navigate", {"questionId": "q2"}
        )
        contexte = ContexteEtudes(
            service,
            "fil-test",
            "local",
            asyncio.get_running_loop(),
            demande="Deux moitiés forment une unité.",
        )
        with utiliser_contexte(contexte):
            r = await asyncio.to_thread(
                EtudierTool().execute,
                action="answer",
                sessionId=s["id"],
                version=s["version"],
            )
        assert r.success, r.content
        assert (
            service.depot.lire(s["id"])["responses"]["q2"]["text"] == contexte.demande
        )

    @pytest.mark.asyncio
    async def test_lexamen_ne_divulgue_ni_cours_ni_indice_ni_correction(self, service):
        from diapason.etudes.conversation import ContexteEtudes, utiliser_contexte
        from diapason.tools.etudier import EtudierTool

        s = service.depot.creer(demande(), programme())
        s = service.depot.modifier(s["id"], s["version"], "start", {})
        with utiliser_contexte(
            ContexteEtudes(service, "fil-test", "local", asyncio.get_running_loop())
        ):
            outil = EtudierTool()
            for action in ("lesson", "source", "hint", "check"):
                r = await asyncio.to_thread(
                    outil.execute,
                    action=action,
                    sessionId=s["id"],
                    version=s["version"],
                )
                assert not r.success, f"{action} ne doit pas aider pendant l'examen"
            r = await asyncio.to_thread(outil.execute, action="read")
        assert r.metadata["study"]["lesson"] == ""
        assert "answer" not in r.metadata["study"]["questions"][0]

    @pytest.mark.asyncio
    async def test_un_autre_fil_et_une_version_perimee_sont_refuses(self, service):
        from diapason.etudes.conversation import ContexteEtudes, utiliser_contexte
        from diapason.tools.etudier import EtudierTool

        s = service.depot.creer(demande(), programme())
        with utiliser_contexte(
            ContexteEtudes(service, "autre-fil", "local", asyncio.get_running_loop())
        ):
            r = await asyncio.to_thread(
                EtudierTool().execute, action="read", sessionId=s["id"]
            )
        assert not r.success and "fractions" not in r.content.lower()
        service.depot.modifier(s["id"], s["version"], "start", {})
        with utiliser_contexte(
            ContexteEtudes(
                service,
                "fil-test",
                "local",
                asyncio.get_running_loop(),
                demande="ma réponse",
            )
        ):
            r = await asyncio.to_thread(
                EtudierTool().execute,
                action="answer",
                sessionId=s["id"],
                version=s["version"],
                choiceIndex=1,
            )
        assert not r.success, "la réponse ne doit pas écraser un autre canal"

    @pytest.mark.asyncio
    async def test_preparer_ne_demande_pas_au_modele_de_recopier_les_documents(
        self, service
    ):
        from diapason.etudes.conversation import ContexteEtudes, utiliser_contexte
        from diapason.tools.etudier import EtudierTool

        sources = [s.model_dump(by_alias=True) for s in demande().sources]
        contexte = ContexteEtudes(
            service, "fil-test", "local", asyncio.get_running_loop(), sources=sources
        )
        with utiliser_contexte(contexte):
            r = await asyncio.to_thread(
                EtudierTool().execute,
                action="prepare",
                sessionId="nouveau",
                topic="Les fractions",
                questionCount=2,
            )
        assert r.success, r.content
        s = service.depot.lire(r.metadata["study"]["id"])
        assert s["sources"] == sources, "les sources originales arrivent au générateur"

    def test_loutil_sans_discussion_active_naccede_a_aucune_etude(self):
        from diapason.tools.etudier import EtudierTool

        r = EtudierTool().execute(action="list")
        assert not r.success

    @pytest.mark.asyncio
    async def test_le_contexte_ne_fuit_pas_entre_deux_appels(self, service):
        from diapason.etudes.conversation import ContexteEtudes, utiliser_contexte
        from diapason.tools.etudier import EtudierTool

        service.depot.creer(demande(), programme())

        async def lire(fil):
            with utiliser_contexte(
                ContexteEtudes(service, fil, "local", asyncio.get_running_loop())
            ):
                return await asyncio.to_thread(EtudierTool().execute, action="list")

        a, b = await asyncio.gather(lire("fil-test"), lire("autre-fil"))
        assert len(a.metadata["sessions"]) == 1 and b.metadata["sessions"] == []

    def test_la_trousse_et_le_telephone_connaissent_loutil(self):
        from diapason.core.origine_telephone import outil_permis_au_telephone
        from diapason.server.routes import _TROUSSE_ASSISTANT
        from diapason.speech.realtime.tools import DEFAULT_VOICE_TOOL_IDS

        assert "study" in _TROUSSE_ASSISTANT and "study" in DEFAULT_VOICE_TOOL_IDS
        assert outil_permis_au_telephone("study")

    @pytest.mark.asyncio
    async def test_le_demarrage_annonce_exige_une_epreuve_active(self, service):
        """§100 : l'essai réel annonçait un test encore à l'état prêt."""
        from diapason.etudes.conversation import (
            ContexteEtudes,
            etat_pour_modele,
            preuve_manquante,
            utiliser_contexte,
        )
        from diapason.tools.etudier import EtudierTool

        s = service.depot.creer(demande(), programme())
        with utiliser_contexte(
            ContexteEtudes(service, "fil-test", "local", asyncio.get_running_loop())
        ):
            await etat_pour_modele()
            for annonce in ("Je lance le test.", "L’examen est démarré."):
                assert preuve_manquante(annonce), "une annonce ne démarre pas l'examen"
            assert not preuve_manquante("Veux-tu commencer le test ?")
            resultat = await asyncio.to_thread(
                EtudierTool().execute,
                action="start",
                sessionId=s["id"],
                version=s["version"],
            )
            assert resultat.success
            assert not preuve_manquante("Je lance le test.")
