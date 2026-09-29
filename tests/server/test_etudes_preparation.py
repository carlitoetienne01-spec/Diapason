"""§5/§100 : le format de génération réduit les copies, pas les vérifications."""

import pytest

from diapason.etudes.preparation import ProgrammePreparation


def brouillon():
    return {
        "title": "Les fractions",
        "objectives": ["Reconnaître une moitié"],
        "lesson": "Une moitié partage une unité en deux parts égales.",
        "essentials": ["Deux moitiés forment une unité."],
        "choiceQuestions": [
            {
                "prompt": "Quelle fraction désigne une moitié ?",
                "objective": "Reconnaître une moitié",
                "choices": ["1/2", "1/3"],
                "answer": 0,
                "explanation": "Une des deux parts égales vaut une moitié.",
                "hint": "Compte les parts égales.",
                "quote": "S0P0",
            },
        ],
        "openQuestions": [
            {
                "prompt": "Explique deux moitiés.",
                "objective": "Reconnaître une moitié",
                "answer": "Deux moitiés font une unité.",
                "explanation": "1/2 + 1/2 = 1.",
                "hint": "Assemble les parts.",
                "criteria": ["Deux parts égales", "Une unité"],
                "quote": "S0P0",
            },
        ],
    }


class TestProgrammePreparation:
    def test_reconstruire_sans_deviner_ni_perdre_de_contenu(self):
        p = ProgrammePreparation.model_validate(brouillon()).developper(
            {"S0P0": (1, "Une moitié vaut 1/2.")}
        )
        assert p.questions[0].reponse == "1/2", "l'indice désigne un choix exact"
        assert p.questions[0].criteres == ["Choisir la bonne réponse."], (
            "le QCM vaut un point"
        )
        assert [q.identifiant for q in p.questions] == ["q1", "q2"]
        assert p.questions[1].reponse == "Deux moitiés font une unité."
        assert p.questions[1].criteres == ["Deux parts égales", "Une unité"]
        assert all(q.citation == "Une moitié vaut 1/2." for q in p.questions)
        assert all(q.source == 1 for q in p.questions), "la référence porte sa source"

    @pytest.mark.parametrize(
        "champ,valeur",
        [
            ("objective", "Un objectif absent"),
            ("answer", 4),
            ("answer", "A"),
            ("answer", True),
            ("quote", "S8P0"),
            ("choices", ["1/2", "1/2"]),
        ],
    )
    def test_une_reference_invalide_ne_devient_pas_un_corrige(self, champ, valeur):
        b = brouillon()
        b["choiceQuestions"][0][champ] = valeur
        with pytest.raises(ValueError):
            ProgrammePreparation.model_validate(b).developper({"S0P0": (0, "Source")})

    def test_une_reponse_ouverte_garde_son_bareme(self):
        b = brouillon()
        b["openQuestions"][0]["criteria"] = []
        with pytest.raises(ValueError):
            ProgrammePreparation.model_validate(b).developper({"S0P0": (0, "Source")})

    def test_pas_de_citation_inventee_sans_document(self):
        b = brouillon()
        for q in [*b["choiceQuestions"], *b["openQuestions"]]:
            q["quote"] = ""
        p = ProgrammePreparation.model_validate(b).developper({})
        assert all(q.source is None and not q.citation for q in p.questions)

    def test_un_long_choix_valide_nallonge_pas_artificiellement_le_critere(self):
        b = brouillon()
        b["choiceQuestions"][0]["choices"][0] = "a" * 500
        p = ProgrammePreparation.model_validate(b).developper({"S0P0": (0, "Source")})
        assert len(p.questions[0].reponse) == 500, "le choix reste intégral"
        assert len(p.questions[0].criteres) == 1, "le barème reste un point"
