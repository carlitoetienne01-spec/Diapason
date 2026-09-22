"""La suite d'une conversation hérite de son sujet (server/suite.py).

21 septembre 2026, 23 h : « Raconte-moi l'histoire de ce pays » après « Qui
est le président actuel d'Haïti ? » recevait « de quel pays tu parles ? ».
"""

import pytest

from diapason.core.types import Message, Role
from diapason.engine._stubs import StreamChunk
from diapason.server.agentic_stream import stream_with_tools
from diapason.server.suite import (
    RAPPEL_DU_SUJET,
    avec_rappel,
    rappel_du_sujet,
    rappel_pour_la_voix,
    renvoi,
)

HAITI = "Qui est le president actuel d'Haïti"
REPONSE_HAITI = (
    "En septembre 2026, il n'y a pas de président élu à Haïti. Le poste reste "
    "vacant depuis l'assassinat de Jovenel Moïse en juillet 2021 [1]. C'est le "
    "gouvernement intérimaire dirigé par Alix Didier Fils-Aimé qui assure la "
    "fonction depuis février 2026 [1].\n\nLes élections présidentielles sont "
    "prévues entre le 20 juillet et le 13 octobre 2026 [2], mais elles n'ont "
    "pas encore eu lieu à cette date."
)


class TestCeQuiRenvoieAvant:
    @pytest.mark.parametrize(
        ("texte", "attendu"),
        [
            ("Raconte moi l'histoire de ce pays", "ce pays"),
            ("Raconte-moi l'histoire de cette équipe", "cette équipe"),
            ("Et sa capitale ?", "sa capitale"),
            ("Parle-moi de lui", "de lui"),
            ("Et lui ?", "Et lui ?"),
            ("Celui-ci est bon ?", "Celui-ci"),
            ("Quel temps fait-il là-bas ?", "là-bas"),
        ],
    )
    def test_les_demonstratifs_qui_designent_ce_qui_precede(self, texte, attendu):
        assert renvoi(texte) == attendu, "le mot tel qu'il a été écrit"

    @pytest.mark.parametrize(
        "texte",
        [
            "Quel temps fera-t-il ce soir ?",
            "C'est quoi le plan cette semaine ?",
            "Explique-moi ce que veut dire self aware",
            "Que veut dire ce mot : « Self Aware » ?",
            "Corrige ce texte : blabla",
            "Qui est le président actuel d'Haïti ?",
            "Qui a gagné la Coupe Stanley en 2026 ?",
            "",
        ],
    )
    def test_le_temps_la_tournure_et_le_message_lui_meme_ne_renvoient_pas(self, texte):
        assert renvoi(texte) is None, texte

    def test_une_demande_longue_porte_son_sujet(self):
        longue = "Raconte-moi l'histoire de ce pays " + "en détail, " * 30
        assert renvoi(longue) is None


class TestLeRappel:
    def test_cite_la_question_et_le_debut_de_la_reponse_sans_les_numeros(self):
        rappel = rappel_du_sujet(
            "Raconte moi l'histoire de ce pays", HAITI, REPONSE_HAITI
        )
        assert rappel is not None
        assert rappel.startswith("La demande renvoie à ce qui précède (« ce pays »)")
        assert f"question : « {HAITI} »" in rappel
        assert "Alix Didier Fils-Aimé" in rappel, (
            "le référent est dans la réponse citée"
        )
        assert "[1]" not in rappel and "[2]" not in rappel
        assert "13 octobre" not in rappel, "le début de la réponse seulement"
        assert rappel.endswith("ne redemande pas de quoi il s'agit.")

    def test_sans_question_avant_rien(self):
        assert rappel_du_sujet("Raconte moi l'histoire de ce pays", "") is None

    def test_sans_renvoi_rien(self):
        assert (
            rappel_du_sujet("Qui est le président du Sénat ?", HAITI, REPONSE_HAITI)
            is None
        )

    def test_sans_reponse_la_question_suffit(self):
        rappel = rappel_du_sujet("Et sa capitale ?", HAITI)
        assert rappel == RAPPEL_DU_SUJET.format(
            renvoi="sa capitale", question=HAITI, reponse=""
        )


class TestLeFil:
    def test_le_rappel_suit_la_demande(self):
        fil = [
            Message(role=Role.SYSTEM, content="identité"),
            Message(role=Role.USER, content=HAITI),
            Message(role=Role.ASSISTANT, content=REPONSE_HAITI),
            Message(role=Role.USER, content="Raconte moi l'histoire de ce pays"),
        ]
        avec = avec_rappel(fil)
        assert len(avec) == 5 and avec[-1].role == Role.SYSTEM
        assert "Alix Didier Fils-Aimé" in (avec[-1].content or "")
        assert avec[:4] == fil, "le fil n'est pas modifié, le rappel s'ajoute"

    def test_premier_message_sans_echange_avant(self):
        fil = [Message(role=Role.USER, content="Raconte moi l'histoire de ce pays")]
        assert avec_rappel(fil) == fil

    def test_une_demande_de_verification_entre_les_deux_n_est_pas_le_sujet(self):
        fil = [
            Message(role=Role.USER, content=HAITI),
            Message(role=Role.ASSISTANT, content="Jovenel Moïse."),
            Message(role=Role.USER, content="Vérifie ça."),
            Message(role=Role.ASSISTANT, content=REPONSE_HAITI),
            Message(role=Role.USER, content="Raconte moi l'histoire de ce pays"),
        ]
        rappel = avec_rappel(fil)[-1].content or ""
        assert f"question : « {HAITI} »" in rappel
        assert "Alix Didier" in rappel, "la réponse citée est la dernière, vérifiée"

    def test_une_image_jointe_n_a_pas_de_rappel(self):
        fil = [
            Message(role=Role.USER, content=HAITI),
            Message(role=Role.ASSISTANT, content=REPONSE_HAITI),
            Message(role=Role.USER, content="C'est quoi ce pays ?", images=["x"]),
        ]
        assert avec_rappel(fil) == fil, "« ce pays » désigne l'image"

    def test_pour_la_voix(self):
        historique = [
            {"role": "user", "content": HAITI},
            {"role": "assistant", "content": REPONSE_HAITI},
            {"role": "system", "content": "note"},
        ]
        rappel = rappel_pour_la_voix(historique, "Raconte-moi l'histoire de ce pays")
        assert rappel and rappel["role"] == "system"
        assert "Alix Didier Fils-Aimé" in rappel["content"]
        assert rappel_pour_la_voix([], "Raconte-moi l'histoire de ce pays") is None


class Moteur:
    def __init__(self):
        self.appels = []

    async def stream_full(self, msgs, **kwargs):
        self.appels.append(list(msgs))
        yield StreamChunk(content="En 1804, Haïti…", finish_reason="stop")


class TestAuFilDuChat:
    @pytest.mark.asyncio
    async def test_le_rappel_est_dans_le_premier_passage_avant_les_autres_consignes(
        self,
    ):
        moteur = Moteur()
        fil = [
            Message(role=Role.USER, content=HAITI),
            Message(role=Role.ASSISTANT, content=REPONSE_HAITI),
            Message(role=Role.USER, content="Raconte moi l'histoire de ce pays"),
        ]
        evts = [
            e
            async for e in stream_with_tools(
                moteur,
                "local",
                fil,
                tools=[],
                executor=None,
                interactive_questions=True,
                signal_textuel=False,
            )
        ]
        assert "".join(e.data for e in evts if e.kind == "token") == "En 1804, Haïti…"
        premier = moteur.appels[0]
        rappels = [
            m
            for m in premier
            if m.role == Role.SYSTEM
            and "La demande renvoie à ce qui précède" in (m.content or "")
        ]
        assert len(rappels) == 1
        assert premier.index(rappels[0]) == len(premier) - 1, "en fin de fil"
        assert (
            premier[0].role == Role.SYSTEM
            and "question" in (premier[0].content or "").lower()
        ), "la consigne des questions reste collée au premier système du fil"
        assert "La demande renvoie" not in (premier[0].content or "")
