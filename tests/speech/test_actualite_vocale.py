"""§5/§100 à la voix : une question d'actualité dite au micro se vérifie, ou
la voix dit qu'elle répond de mémoire (21 septembre 2026).

« Qui est le premier ministre du Canada ? » au micro recevait « Justin
Trudeau » sans qu'une recherche parte, et rien ne le disait : le chat avait
ses gardes depuis la veille, la voix aucune.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from diapason.speech.realtime import actualite_vocale
from diapason.speech.realtime.actualite_vocale import (
    AVEU_VOCAL,
    AVEU_VOCAL_RECHERCHE,
    preparer_tour,
)
from diapason.speech.realtime.local_voice import LocalVoiceSession

PREMIER_MINISTRE = "Qui est le premier ministre du Canada ?"
RECHERCHE = {
    "ok": True,
    "content": (
        "[1] Mark Carney - Wikipedia — en.wikipedia.org · 2026-09-20\n"
        "Source: https://en.wikipedia.org/wiki/Mark_Carney\n"
        "Extrait: In 2025, Carney campaigned.\n\n"
        "[2] Premier ministre du Canada — Wikipédia — fr.wikipedia.org · 2026-08-14\n"
        "Source: https://fr.wikipedia.org/wiki/Premier_ministre_du_Canada\n"
        "Extrait: « À propos », consulté le 11 janvier 2026\n\n"
        "[3] Justin Trudeau - Wikipedia — en.wikipedia.org · 2026-09-19\n"
        "Source: https://en.wikipedia.org/wiki/Justin_Trudeau\n"
        "Extrait: Trudeau announced a film company."
    ),
    "metadata": {
        "engine": "brave/text",
        "sources": [
            {
                "ref": 1,
                "title": "Mark Carney - Wikipedia",
                "url": "https://en.wikipedia.org/wiki/Mark_Carney",
                "date": "2026-09-20",
            },
            {
                "ref": 2,
                "title": "Premier ministre du Canada — Wikipédia",
                "url": "https://fr.wikipedia.org/wiki/Premier_ministre_du_Canada",
                "date": "2026-08-14",
            },
            {
                "ref": 3,
                "title": "Justin Trudeau - Wikipedia",
                "url": "https://en.wikipedia.org/wiki/Justin_Trudeau",
                "date": "2026-09-19",
            },
        ],
    },
}
PAGE = {
    "ok": True,
    "content": (
        "[1] Premier ministre du Canada — Wikipédia — fr.wikipedia.org"
        " · publié 2002-11-24 · modifié 2026-08-14\n"
        "Source: https://fr.wikipedia.org/wiki/Premier_ministre_du_Canada\n"
        "Début : Premier ministre du Canada\n"
        "Titulaire actuel | Mark Carney | depuis le 14 mars 2025\n"
        "Mark Carney, le premier ministre actuel, a prêté serment le 14 mars 2025, "
        "après la démission de Justin Trudeau.\n"
    ),
    "metadata": {
        "url": "https://fr.wikipedia.org/wiki/Premier_ministre_du_Canada",
        "sources": [
            {
                "ref": 1,
                "title": "Premier ministre du Canada — Wikipédia",
                "url": "https://fr.wikipedia.org/wiki/Premier_ministre_du_Canada",
                "date": "2026-08-14",
            }
        ],
    },
}


def appel_web(requete="premier ministre du Canada 2026"):
    return {"function": {"name": "web_search", "arguments": {"query": requete}}}


def harnais(reponses, *, recherche=RECHERCHE, page=PAGE, historique=()):
    """Un LLM scripté : chaque élément est un texte ou une liste d'appels."""
    etat = {"i": 0}
    journal = {"executed": [], "rounds": [], "spoken": []}

    def llm(messages):
        journal["rounds"].append(list(messages))
        queue: asyncio.Queue = asyncio.Queue()
        scenario = reponses[min(etat["i"], len(reponses) - 1)]
        etat["i"] += 1
        if isinstance(scenario, list):
            queue.put_nowait(("tools", scenario))
        else:
            queue.put_nowait(scenario)
        queue.put_nowait(None)
        return queue

    def executor(name, args):
        journal["executed"].append((name, args))
        if name == "web_search":
            return recherche
        if name == "web_read":
            return page
        return {"ok": True, "content": "fait"}

    def tts(text):
        journal["spoken"].append(text)
        return b"\x01" * 64

    session = LocalVoiceSession(
        stt=lambda _a: "x",
        llm=llm,
        tts=tts,
        tool_executor=executor,
        enable_tools=True,
    )
    session._history.extend(historique)
    return session, journal


class TestLaGardeVocale:
    @pytest.mark.asyncio
    async def test_la_consigne_puis_la_page_du_poste_puis_la_note(self):
        session, journal = harnais(
            [[appel_web()], "Mark Carney [2], depuis mars 2025."]
        )
        await session._respond_to_text(PREMIER_MINISTRE)
        premier = journal["rounds"][0]
        assert (
            premier[-1]["role"] == "system" and "web_search" in premier[-1]["content"]
        ), "la consigne d'actualité se pose au tour courant, après la demande"
        noms = [n for n, _ in journal["executed"]]
        assert noms == ["web_search", "web_read"], (
            "la recherche, puis la page du poste lue par le code"
        )
        assert journal["executed"][0][1].get("recency") == "year", (
            "la fraîcheur est décidée par le code, comme au chat"
        )
        assert journal["executed"][1][1]["url"].endswith("Premier_ministre_du_Canada")
        second = journal["rounds"][1]
        outil = next(m for m in second if m["role"] == "tool")
        # Le modèle lit le résultat en JSON (la forme de la boucle vocale).
        lu = json.loads(outil["content"])["content"]
        assert "Page lue (web_read) :\n[2] Premier ministre du Canada" in lu, (
            "la page est jointe au résultat sous son numéro de source"
        )
        assert "Titulaire actuel | Mark Carney" in lu
        note = second[-1]
        assert note["role"] == "system" and "Mark Carney [2]" in note["content"], (
            "le modèle est prévenu avant de rédiger"
        )
        assert " ".join(journal["spoken"]) == (
            "Je vérifie en ligne. Mark Carney, depuis mars 2025."
        ), (
            "l'accusé pendant la recherche, puis la réponse — sans le « [2] » "
            "que Kokoro prononçait « deux » ; réponse vérifiée : rien à ajouter"
        )

    @pytest.mark.asyncio
    async def test_une_reponse_de_memoire_est_relancee_puis_dite_de_memoire(self):
        """La parole est sortie ; la relance suit, une fois. Si le modèle
        persiste sans chercher, la voix le dit après coup."""
        session, journal = harnais(
            ["Justin Trudeau, depuis 2015.", "Toujours Justin Trudeau."]
        )
        await session._respond_to_text(PREMIER_MINISTRE)
        sommation = journal["rounds"][1][-1]
        assert (
            sommation["role"] == "system"
            and "sans appeler web_search" in (sommation["content"])
        ), "une relance ferme, comme au chat — la réponse dite reste dans le fil"
        assert journal["rounds"][1][-2] == {
            "role": "assistant",
            "content": "Justin Trudeau, depuis 2015.",
        }
        assert " ".join(journal["spoken"]) == (
            f"Justin Trudeau, depuis 2015. Toujours Justin Trudeau. {AVEU_VOCAL}"
        ), "la voix ne peut pas retenir : elle dit après coup que rien n'a été vérifié"
        assert session._history[-1]["content"].endswith(AVEU_VOCAL), (
            "l'aveu fait partie de la réponse gardée en historique"
        )
        assert len(journal["rounds"]) == 2, "une seule relance, jamais une boucle"

    @pytest.mark.asyncio
    async def test_la_relance_mene_a_la_recherche(self):
        session, journal = harnais(
            [
                "Je vais vérifier ça en ligne.",
                [appel_web()],
                "Selon Wikipédia, Mark Carney.",
            ]
        )
        await session._respond_to_text(PREMIER_MINISTRE)
        assert [n for n, _ in journal["executed"]] == ["web_search", "web_read"]
        assert " ".join(journal["spoken"]) == (
            "Je vais vérifier ça en ligne. Selon Wikipédia, Mark Carney."
        ), "promesse, puis livraison — et rien à avouer"

    @pytest.mark.asyncio
    async def test_ce_qui_ne_recoit_pas_l_aveu(self):
        """Une question de précision, un aveu déjà dit, un fait lu à
        l'horloge : « je le dis de mémoire » n'y a pas sa place."""
        session, journal = harnais(["Tu veux dire au fédéral ou au Québec ?"] * 2)
        await session._respond_to_text(PREMIER_MINISTRE)
        assert AVEU_VOCAL not in " ".join(journal["spoken"])
        session, journal = harnais(["Je n'ai pas pu vérifier, désolé."] * 2)
        await session._respond_to_text(PREMIER_MINISTRE)
        assert " ".join(journal["spoken"]).count("mémoire") == 0, "pas de second aveu"
        session, journal = harnais(["Il est quinze heures."])
        await session._respond_to_text("Quelle heure est-il ?")
        assert " ".join(journal["spoken"]) == "Il est quinze heures.", (
            "l'horloge n'est pas une question d'actualité"
        )

    @pytest.mark.asyncio
    async def test_une_recherche_vide_est_dite_telle_quelle(self):
        vide = {"ok": True, "content": "No results found.", "metadata": {}}
        session, journal = harnais([[appel_web()], "Justin Trudeau."], recherche=vide)
        await session._respond_to_text(PREMIER_MINISTRE)
        assert journal["spoken"][-1] == AVEU_VOCAL_RECHERCHE
        assert [n for n, _ in journal["executed"]] == ["web_search"], (
            "rien à lire quand la recherche n'a rien rendu"
        )

    @pytest.mark.asyncio
    async def test_la_reponse_qui_contredit_les_sources_est_corrigee_a_voix_haute(self):
        session, journal = harnais([[appel_web()], "Justin Trudeau [3], depuis 2015."])
        await session._respond_to_text(PREMIER_MINISTRE)
        assert journal["spoken"][-1] == (
            "Attention : les sources désignent Mark Carney comme titulaire, "
            "pas Justin Trudeau."
        )

    @pytest.mark.asyncio
    async def test_verifie_ca_porte_sur_la_question_d_avant(self):
        session, journal = harnais(
            [[appel_web()], "Mark Carney [2]."],
            historique=[
                {"role": "user", "content": PREMIER_MINISTRE},
                {"role": "assistant", "content": "Justin Trudeau."},
            ],
        )
        await session._respond_to_text("vérifie ça")
        consigne = journal["rounds"][0][-1]
        assert consigne["role"] == "system"
        assert f"demandée pour : « {PREMIER_MINISTRE} »" in consigne["content"]
        assert [n for n, _ in journal["executed"]] == ["web_search", "web_read"]

    @pytest.mark.asyncio
    async def test_une_question_ordinaire_ou_personnelle_ne_change_rien(self):
        session, journal = harnais(["Trois tâches aujourd'hui."])
        await session._respond_to_text("qu'est-ce que j'ai comme tâches aujourd'hui ?")
        assert journal["rounds"][0][-1]["role"] == "user", "aucune consigne"
        assert journal["spoken"] == ["Trois tâches aujourd'hui."], "aucun aveu"
        session, journal = harnais(["Conscient de soi."])
        await session._respond_to_text("que veut dire self aware ?")
        assert journal["spoken"] == ["Conscient de soi."]

    @pytest.mark.asyncio
    async def test_la_lecture_automatique_est_annoncee_au_panneau(self):
        session, journal = harnais([[appel_web()], "Mark Carney [2]."])
        await session._respond_to_text(PREMIER_MINISTRE)
        evenements = []
        while not session._queue.empty():
            evenements.append(session._queue.get_nowait())
        outils = [e.tool_name for e in evenements if e.kind == "tool"]
        assert outils == ["web_search", "web_read"], "rien ne se fait en cachette (§5)"


class TestLesPiecesDuTour:
    def test_preparer_tour(self):
        assert preparer_tour("Qui est le pape ?", []).question == "Qui est le pape ?"
        assert preparer_tour("Écris un poème", []) is None
        assert preparer_tour("vérifie ça", []) is None, "rien avant : rien à vérifier"
        tour = preparer_tour(
            "vérifie ça",
            [
                {"role": "user", "content": "Qui est le pape ?"},
                {"role": "assistant", "content": "x"},
            ],
        )
        assert (
            tour is not None and tour.demande and tour.question == "Qui est le pape ?"
        )
        assert (
            preparer_tour(
                "vérifie ça",
                [{"role": "user", "content": "Quelles sont mes tâches ?"}],
            )
            is None
        ), "ce qui est personnel ne se vérifie pas sur le web"

    def test_absorber_resultat_ne_lit_qu_une_fois_et_qu_un_titulaire(self):
        tour = actualite_vocale.TourVocal(question=PREMIER_MINISTRE)
        lectures = []

        def lire(nom, args):
            lectures.append(args["url"])
            return PAGE

        actualite_vocale.absorber_resultat(
            tour, "web_search", {}, dict(RECHERCHE), lire
        )
        actualite_vocale.absorber_resultat(
            tour, "web_search", {}, dict(RECHERCHE), lire
        )
        assert lectures == ["https://fr.wikipedia.org/wiki/Premier_ministre_du_Canada"]
        assert [s["ref"] for s in tour.sources] == [1, 2, 3], (
            "la page lue garde le numéro [2] de la recherche ; la seconde "
            "recherche ne renumérote rien"
        )
        prix = actualite_vocale.TourVocal(question="Quel est le taux directeur ?")
        actualite_vocale.absorber_resultat(
            prix, "web_search", {}, dict(RECHERCHE), lire
        )
        assert lectures == [
            "https://fr.wikipedia.org/wiki/Premier_ministre_du_Canada"
        ], "un prix ne lit aucune page"

    def test_le_resultat_reste_du_json_lisible_par_le_modele(self):
        tour = actualite_vocale.TourVocal(question=PREMIER_MINISTRE)
        resultat = actualite_vocale.absorber_resultat(
            tour, "web_search", {}, dict(RECHERCHE), lambda n, a: PAGE
        )
        json.dumps(resultat, ensure_ascii=False)
        assert resultat["ok"] is True and "Page lue" in resultat["content"]
        assert "sources" not in resultat.get("metadata", {}), (
            "la liste structurée n'est pas recopiée au modèle : le texte est numéroté"
        )

    def test_la_page_deja_lue_ne_se_retelecharge_pas(self):
        tour = actualite_vocale.TourVocal(question=PREMIER_MINISTRE)
        actualite_vocale.absorber_resultat(
            tour, "web_search", {}, dict(RECHERCHE), lambda n, a: PAGE
        )
        url = "https://fr.wikipedia.org/wiki/Premier_ministre_du_Canada"
        deja = actualite_vocale.deja_lue(tour, "web_read", {"url": url})
        assert deja and "déjà lue" in deja["content"] and "numéro 2" in deja["content"]
        assert (
            actualite_vocale.deja_lue(tour, "web_read", {"url": "https://x.ca"}) is None
        )

    def test_l_epilogue_selon_ce_qui_a_ete_dit(self):
        from diapason.server.actualite import AVEU
        from diapason.speech.realtime.actualite_vocale import AVEU_VOCAL_REFUS, epilogue

        tour = actualite_vocale.TourVocal(question=PREMIER_MINISTRE)
        assert epilogue(tour, "") == AVEU, (
            "une réponse vide reçoit l'aveu qui se tient seul"
        )
        assert epilogue(tour, "Tu parles du fédéral ?") == ""
        assert epilogue(tour, "Justin Trudeau.") == AVEU_VOCAL
        assert epilogue(tour, "C'est Carney.") == AVEU_VOCAL, (
            "un nom hors tête de phrase"
        )
        assert epilogue(tour, "Je n'ai pas pu vérifier.") == ""
        tour.recherche_tentee = True
        tour.recherche_refusee = True
        assert epilogue(tour, "Justin Trudeau.") == AVEU_VOCAL_REFUS
        local = actualite_vocale.TourVocal(
            question=PREMIER_MINISTRE, outil_local_ok=True
        )
        assert epilogue(local, "Il est 15 h.") == "", "un fait lu à un outil local"

    def test_les_formes_dictees_sans_ponctuation(self):
        from diapason.speech.realtime.actualite_vocale import est_une_demande_vocale

        for texte in ("c'est vrai", "vraiment", "t'es sûr", "ah bon", "C'est vrai ça"):
            assert est_une_demande_vocale(texte), texte
        for texte in ("Confirme", "Vraiment content", "vérifie mes tâches"):
            assert not est_une_demande_vocale(texte), texte


class TestLaSpeculationVoitLaConsigne:
    def test_l_assemblage_du_tour_porte_la_consigne(self):
        """La réponse préparée pendant le silence est bâtie sur le MÊME
        assemblage que l'adoption : sans la consigne dedans, elle aurait été
        adoptée telle quelle — de mémoire (21/09/2026)."""
        session, _journal = harnais(["x"])
        messages = session._turn_messages(PREMIER_MINISTRE)
        assert (
            messages[-1]["role"] == "system" and "web_search" in messages[-1]["content"]
        )
        assert messages[-2] == {"role": "user", "content": PREMIER_MINISTRE}
        assert (
            session._turn_messages("que veut dire self aware ?")[-1]["role"] == "user"
        )

    def test_sans_outils_aucune_consigne(self):
        session, _journal = harnais(["x"])
        session._enable_tools = False
        assert session._turn_messages(PREMIER_MINISTRE)[-1]["role"] == "user"


def test_speakable_ne_prononce_ni_numero_ni_adresse():
    """Revue du 21/09 : « Mark Carney [2] » sortait « Mark Carney deux »."""
    from diapason.speech.realtime.local_voice import speakable

    assert (
        speakable("Mark Carney [2], depuis mars 2025.")
        == "Mark Carney, depuis mars 2025."
    )
    assert speakable("Selon Wikipédia [1][3]. Source: https://fr.wikipedia.org/x") == (
        "Selon Wikipédia."
    )
    assert speakable("Deux [2, 3] sources") == "Deux sources"
