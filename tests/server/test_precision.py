"""29/09/2026 : une question à trou reçoit une question, pas une fourchette.

Importe ``question_a_poser`` et ``demande_completee``. Pas de route, pas
de schéma. Carlito : « Quand je lui demande la température sans préciser
de ville, il doit me poser la question. Si c'est ambigu, toujours, pas
seulement pour la météo. »
"""

from diapason.core.types import Message, Role
from diapason.server.precision import (
    DANS_QUELLE_VILLE,
    DE_QUEL_ENDROIT,
    DE_QUEL_MATCH,
    DE_QUEL_PAYS,
    demande_completee,
    meteo_heritee,
    question_a_poser,
    reponse_meteo,
    sujet_quitte,
)


class TestLaQuestion:
    def test_la_temperature_sans_ville_se_demande(self):
        phrase = "Dis-moi Diabazon, il fait quelle température maintenant ?"
        assert question_a_poser(phrase) == DANS_QUELLE_VILLE, (
            "Diabazon est l'assistant, pas une ville"
        )
        assert question_a_poser("Quel temps fait-il ce soir ?") == DANS_QUELLE_VILLE
        assert question_a_poser("il pleut ?") == DANS_QUELLE_VILLE

    def test_une_ville_nommee_ne_se_redemande_pas(self):
        assert question_a_poser("Quel temps fait-il à Lyon ?") is None
        assert question_a_poser("météo à lyon") is None
        assert question_a_poser("Quel temps fait-il à Ottawa ce soir ?") is None
        assert question_a_poser("Météo à Tokyo") is None

    def test_un_pays_n_est_pas_une_ville(self):
        assert question_a_poser("Météo en France") == DANS_QUELLE_VILLE, (
            "la France entière n'est pas une température"
        )

    def test_les_autres_trous_ont_leur_question(self):
        assert question_a_poser("Combien d'habitants ?") == DE_QUEL_ENDROIT
        assert question_a_poser("Quelle est la capitale ?") == DE_QUEL_PAYS
        assert question_a_poser("Quel est le score ?") == DE_QUEL_MATCH
        assert question_a_poser("Qui a gagné ?") == DE_QUEL_MATCH

    def test_un_sujet_deja_nomme_passe(self):
        assert question_a_poser("Qui a gagné le match hier ?") is None
        assert question_a_poser("Quelle est la capitale de la France ?") is None
        assert question_a_poser("Combien d'habitants à Lyon ?") is None
        assert question_a_poser("Qui est le président actuel du Canada ?") is None
        assert question_a_poser("parle-moi de ce pays") is None, (
            "« ce pays » reste le rappel du fil, pas une question neuve"
        )


class TestLaSuite:
    def test_lyon_complete_la_temperature(self):
        fil = [
            Message(
                role=Role.USER,
                content="il fait quelle température maintenant ?",
            ),
            Message(role=Role.ASSISTANT, content=DANS_QUELLE_VILLE),
            Message(role=Role.USER, content="Lyon"),
        ]
        obtenu = demande_completee("Lyon", fil)
        assert obtenu == "il fait quelle température maintenant à Lyon ?", (
            "la ville dite ensuite reprend la question"
        )

    def test_la_voix_sans_le_message_courant_dans_l_historique(self):
        historique = [
            {"role": "user", "content": "il fait quelle température maintenant ?"},
            {"role": "assistant", "content": DANS_QUELLE_VILLE},
        ]
        assert (
            demande_completee("à lyon", historique)
            == "il fait quelle température maintenant à Lyon ?"
        )

    def test_oui_n_est_pas_une_ville(self):
        fil = [
            ("user", "Quel temps fait-il ?"),
            ("assistant", DANS_QUELLE_VILLE),
        ]
        assert demande_completee("oui", fil) is None
        assert demande_completee("je ne sais pas", fil) is None

    def test_une_nouvelle_question_ne_complete_pas(self):
        fil = [
            ("user", "il fait quelle température maintenant ?"),
            ("assistant", DANS_QUELLE_VILLE),
        ]
        assert demande_completee("et le premier ministre ?", fil) is None

    def test_le_pays_complete_la_capitale(self):
        fil = [
            ("user", "Quelle est la capitale ?"),
            ("assistant", DE_QUEL_PAYS),
        ]
        obtenu = demande_completee("la France", fil)
        assert obtenu == "Quelle est la capitale de La France ?", (
            "le pays dit ensuite reprend la question"
        )


class TestLaMeteoHeritee:
    """29/09/2026 : « Et pour Trois-Rivières ? » après la météo n'avait
    pas le mot météo. Le tour n'entrait pas dans la prévision, et
    Diapason annonçait une recherche sans aucun degré."""

    def test_et_pour_une_ville_reprend_la_prevision(self):
        fil = [
            ("user", "Il fait quelle température maintenant ?"),
            ("assistant", "Dans quelle ville ?"),
            ("user", "Montréal"),
            ("assistant", "Environnement Canada indique 12°C."),
            ("user", "Et pour Trois-Rivières ?"),
        ]
        assert (
            meteo_heritee("Et pour Trois-Rivières ?", fil)
            == "Quel temps fait-il à Trois-Rivières ?"
        )

    def test_et_pour_lyon_reprend_aussi(self):
        fil = [
            ("user", "Quel temps fait-il à Montréal ?"),
            ("assistant", "Environnement Canada indique 12°C."),
            ("user", "Et pour Lyon ?"),
        ]
        assert meteo_heritee("Et pour Lyon ?", fil) == "Quel temps fait-il à Lyon ?"

    def test_un_oui_apres_l_annonce_reprend_la_ville_deja_dite(self):
        fil = [
            ("user", "Et pour Trois-Rivières ?"),
            (
                "assistant",
                "Je vérifie la météo pour Trois-Rivières. Attends, je n'ai "
                "pas encore de résultat précis. Je fais une nouvelle "
                "recherche ciblée ?",
            ),
            ("user", "Oui, tu peux faire une nouvelle recherche ciblée."),
        ]
        assert (
            meteo_heritee("Oui, tu peux faire une nouvelle recherche ciblée.", fil)
            == "Quel temps fait-il à Trois-Rivières ?"
        )

    def test_sans_meteo_derriere_on_ne_devine_pas(self):
        fil = [
            ("user", "Parle-moi de cette équipe."),
            ("assistant", "Laquelle ?"),
            ("user", "Et pour Trois-Rivières ?"),
        ]
        assert meteo_heritee("Et pour Trois-Rivières ?", fil) is None
        assert (
            meteo_heritee(
                "Qui est le maire de Trois-Rivières ?",
                [("user", "Quel temps fait-il à Montréal ?")],
            )
            is None
        )

    def test_une_annonce_sans_degre_est_remplacee_par_le_chiffre_lu(self):
        question = "Quel temps fait-il à Trois-Rivières ?"
        corpus = "Ce soir et cette nuit\n3°C\nEnvironnement Canada"
        assert (
            reponse_meteo(
                question,
                "Je lance la recherche météo pour Trois-Rivières.",
                corpus,
                officielle_lue=True,
            )
            == "Environnement Canada indique 3°C."
        )
        assert (
            reponse_meteo(
                question,
                "Ce soir, 3 °C.",
                corpus,
                officielle_lue=True,
            )
            == ""
        )


class TestLeChangementDeSujet:
    """29/09/2026 : après Brossard, « une recette pour faire des pâtes »
    devenait une ville, puis « je parle plus de météo » relisait Ottawa."""

    _FIL = [
        ("user", "C'est quoi la température pour aujourd'hui ?"),
        ("assistant", "À Brossard, il fait 15 °C."),
        ("user", "C'est quoi la température pour Montréal ?"),
        ("assistant", "Environnement Canada indique 15°C."),
    ]

    def test_une_recette_ne_reprend_pas_la_meteo(self):
        demande = (
            "Je veux avoir une recette pour faire des pâtes. "
            "Est-ce que tu peux me faire des recommandations ?"
        )
        assert sujet_quitte(demande)
        assert meteo_heritee(demande, self._FIL) is None
        assert question_a_poser(demande) is None

    def test_dire_qu_on_quitte_la_meteo_quitte_la_meteo(self):
        demande = (
            "Là maintenant je parle plus de météo, "
            "je parle des recettes pour faire des pâtes."
        )
        assert sujet_quitte(demande)
        assert meteo_heritee(demande, self._FIL) is None
        assert question_a_poser(demande) is None, (
            "quitter la météo ne redemande pas la ville"
        )
        from diapason.server.actualite import question_d_actualite

        assert question_d_actualite(demande) is False, (
            "nommer la météo pour la quitter ne relance pas la prévision"
        )

    def test_une_ville_nommee_reste_une_prevision(self):
        assert question_a_poser("C'est quoi la température pour Montréal ?") is None
        assert (
            meteo_heritee("Et pour Trois-Rivières ?", self._FIL)
            == "Quel temps fait-il à Trois-Rivières ?"
        )
