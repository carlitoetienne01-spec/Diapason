"""§5/§100 : une épreuve conserve les réponses et ne révèle pas son corrigé."""

import copy
import json

import pytest

from diapason.etudes.generation import corriger_qcm, valider_correction
from diapason.etudes.magasin import ConflitEtude, MagasinEtudes, vue_publique
from diapason.etudes.modeles import DemandeEtude, Programme, valider_sources


def demande(**changements):
    return DemandeEtude.model_validate(
        {
            "conversationId": "fil-test",
            "model": "local",
            "topic": "Fractions",
            "level": "Débutant",
            "mode": "exam",
            "questionCount": 2,
            "sources": [
                {
                    "name": "cours.txt",
                    "text": "Une moitié vaut 1/2. Deux moitiés font une unité.",
                    "truncated": False,
                }
            ],
            **changements,
        }
    )


def programme():
    return Programme.model_validate(
        {
            "title": "Les fractions",
            "objectives": ["Reconnaître une moitié"],
            "lesson": "Une moitié partage une unité en deux parts égales.",
            "essentials": ["Deux moitiés forment une unité."],
            "questions": [
                {
                    "id": "q1",
                    "kind": "choice",
                    "prompt": "Quelle fraction désigne une moitié ?",
                    "objective": "Reconnaître une moitié",
                    "choices": ["1/2", "1/3"],
                    "answer": "1/2",
                    "explanation": "La moitié vaut 1/2.",
                    "hint": "Pense à deux parts.",
                    "criteria": ["Choisir 1/2"],
                    "sourceIndex": 0,
                    "quote": "Une moitié vaut 1/2.",
                },
                {
                    "id": "q2",
                    "kind": "open",
                    "prompt": "Explique deux moitiés.",
                    "objective": "Reconnaître une moitié",
                    "choices": [],
                    "answer": "Deux moitiés font une unité.",
                    "explanation": "1/2 + 1/2 = 1.",
                    "hint": "Assemble les parts.",
                    "criteria": ["Deux parts égales", "Une unité"],
                    "sourceIndex": 0,
                    "quote": "Deux moitiés font une unité.",
                },
            ],
        }
    )


class TestContratPedagogique:
    def test_un_document_tronque_ne_devient_pas_un_cours_complet(self):
        with pytest.raises(ValueError, match="tronqué"):
            demande(sources=[{"name": "long.pdf", "text": "début", "truncated": True}])

    def test_une_source_et_son_extrait_doivent_exister(self):
        p = programme()
        valider_sources(p, demande())
        p.questions[0].citation = "Une réponse inventée"
        with pytest.raises(ValueError, match="extrait"):
            valider_sources(p, demande())

    def test_les_choix_et_les_identifiants_ne_sont_pas_ambigus(self):
        brut = programme().model_dump(by_alias=True)
        brut["questions"][0]["answer"] = "ailleurs"
        with pytest.raises(ValueError):
            Programme.model_validate(brut)
        brut = programme().model_dump(by_alias=True)
        brut["questions"][1]["id"] = "q1"
        with pytest.raises(ValueError):
            Programme.model_validate(brut)

    def test_le_qcm_ne_depend_pas_du_jugement_du_modele(self):
        q = programme().questions[0]
        assert corriger_qcm(q, "1/2")["score"] == 1, "le choix exact vaut un point"
        assert corriger_qcm(q, "1/3")["score"] == 0, (
            "le distracteur ne vaut aucun point"
        )

    def test_la_correction_libre_suit_chaque_critere_sans_score_invente(self):
        q = programme().questions[1]
        valide = valider_correction(
            q, {"criteriaMet": [True, False], "feedback": "Il manque l'unité."}
        )
        assert valide["score"] == 1 and valide["maxScore"] == 2
        with pytest.raises(ValueError):
            valider_correction(q, {"criteriaMet": [True], "feedback": "Trop court"})


class TestPersistanceDesEpreuves:
    def test_deux_etudes_conservent_leur_place_apres_reponse_et_redemarrage(
        self, tmp_path
    ):
        """§5 : la mise à jour du bilan ne déplace ni ne remplace un cours."""
        chemin = tmp_path / "etudes.db"
        magasin = MagasinEtudes(chemin)
        place = {"afterMessageId": "message-avant", "openedAt": 20}
        premiere = magasin.creer(demande(placement=place), programme(), 30)
        seconde = magasin.creer(demande(), programme(), 50)
        premiere = magasin.modifier(premiere["id"], 1, "start", {})
        magasin.modifier(
            premiere["id"],
            premiere["version"],
            "answer",
            {"questionId": "q1", "text": "1/2"},
        )
        reprises = MagasinEtudes(chemin).lister("fil-test")
        assert {e["id"] for e in reprises} == {premiere["id"], seconde["id"]}, (
            "les deux études restent présentes"
        )
        relue = next(e for e in reprises if e["id"] == premiere["id"])
        assert relue["placement"] == place and relue["createdAt"] == 30, (
            "le repère d'ouverture reste immuable"
        )
        assert relue["responses"]["q1"]["text"] == "1/2", "la réponse survit"

    def test_une_ancienne_etude_fige_son_repere_avant_sa_premiere_modification(
        self, tmp_path
    ):
        """§5 : les études antérieures restent lisibles sans se déplacer."""
        magasin = MagasinEtudes(tmp_path / "etudes.db")
        s = magasin.creer(demande(), programme())
        s.pop("createdAt")
        s.pop("placement")
        repere = s["updatedAt"]
        modifiee = magasin._ecrire(s, s["version"])
        public = vue_publique(modifiee)
        assert public["createdAt"] == repere and public["placement"] is None, (
            "le repère disponible est conservé sans inventer de message"
        )

    def test_lhistorique_ne_perd_pas_les_etudes_au_dela_de_cinquante(self, tmp_path):
        """§5 : la pagination implicite faisait disparaître les anciens blocs."""
        magasin = MagasinEtudes(tmp_path / "etudes.db")
        for _ in range(51):
            magasin.creer(demande(), programme())
        assert len(magasin.lister("fil-test")) == 51, "aucune étude masquée"

    def test_supprimer_le_fil_efface_les_etudes_et_refuse_une_preparation_tardive(
        self, tmp_path
    ):
        magasin = MagasinEtudes(tmp_path / "etudes.db")
        s = magasin.creer(demande(), programme())
        autre = magasin.creer(demande(conversationId="autre-fil"), programme())
        magasin.supprimer_conversation("fil-test")
        with pytest.raises(KeyError):
            magasin.lire(s["id"])
        with pytest.raises(ValueError, match="supprimée"):
            magasin.creer(demande(), programme())
        assert magasin.lire(autre["id"])["conversationId"] == "autre-fil", (
            "les autres discussions restent intactes"
        )

    def test_reprise_et_correction_cachee(self, tmp_path):
        chemin = tmp_path / "etudes.db"
        magasin = MagasinEtudes(chemin)
        s = magasin.creer(demande(), programme())
        public = vue_publique(s)
        assert "answer" not in json.dumps(public), "le corrigé reste au serveur"
        s = magasin.modifier(s["id"], s["version"], "start", {})
        s = magasin.modifier(
            s["id"], s["version"], "answer", {"questionId": "q1", "text": "1/3"}
        )
        relu = MagasinEtudes(chemin).lire(s["id"])
        assert relu["responses"]["q1"]["text"] == "1/3", (
            "une réponse survit au redémarrage"
        )
        assert "explanation" not in json.dumps(vue_publique(relu)), (
            "aucune correction avant la fin"
        )

    def test_une_autre_fenetre_necrase_pas_la_reponse(self, tmp_path):
        magasin = MagasinEtudes(tmp_path / "etudes.db")
        s = magasin.creer(demande(), programme())
        magasin.modifier(s["id"], s["version"], "start", {})
        with pytest.raises(ConflitEtude):
            magasin.modifier(s["id"], s["version"], "start", {})

    def test_pas_dindice_en_examen_ni_reponse_avant_demarrage(self, tmp_path):
        magasin = MagasinEtudes(tmp_path / "etudes.db")
        s = magasin.creer(demande(), programme())
        with pytest.raises(ValueError):
            magasin.modifier(
                s["id"], s["version"], "answer", {"questionId": "q1", "text": "1/2"}
            )
        s = magasin.modifier(s["id"], s["version"], "start", {})
        with pytest.raises(ValueError, match="examen"):
            magasin.modifier(s["id"], s["version"], "hint", {"questionId": "q1"})

    def test_une_correction_tardive_ne_note_pas_une_reponse_modifiee(self, tmp_path):
        magasin = MagasinEtudes(tmp_path / "etudes.db")
        s = magasin.creer(demande(), programme())
        s = magasin.modifier(s["id"], s["version"], "start", {})
        avant = copy.deepcopy(s)
        magasin.modifier(
            s["id"], s["version"], "answer", {"questionId": "q1", "text": "1/2"}
        )
        with pytest.raises(ConflitEtude):
            magasin.terminer(avant["id"], avant["version"], {})

    def test_les_indices_sont_enregistres_en_entrainement(self, tmp_path):
        magasin = MagasinEtudes(tmp_path / "etudes.db")
        s = magasin.creer(demande(mode="practice"), programme())
        s = magasin.modifier(s["id"], s["version"], "start", {})
        s = magasin.modifier(s["id"], s["version"], "hint", {"questionId": "q1"})
        assert vue_publique(s)["hints"]["q1"] == "Pense à deux parts."
        assert s["assisted"] == ["q1"], "une réussite aidée reste distincte"
