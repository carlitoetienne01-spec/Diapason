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


def harnais(
    reponses, *, recherche=RECHERCHE, page=PAGE, historique=(), max_tool_steps=12
):
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
        max_tool_steps=max_tool_steps,
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
        """Sur un sujet que la table des pages officielles ne couvre pas :
        22/09, cette épreuve portait sur le premier ministre du Canada, qui a
        depuis sa page officielle — une recherche vide y trouve désormais sa
        réponse, et l'aveu qu'on vérifiait ici ne s'y dit plus."""
        vide = {"ok": True, "content": "No results found.", "metadata": {}}
        session, journal = harnais(
            [[appel_web()], "Le Canadien a gagné."], recherche=vide
        )
        await session._respond_to_text("Qui a gagné le match hier soir ?")
        assert journal["spoken"][-1] == AVEU_VOCAL_RECHERCHE
        assert [n for n, _ in journal["executed"]] == ["web_search"], (
            "rien à lire quand la recherche n'a rien rendu"
        )

    @pytest.mark.asyncio
    async def test_une_recherche_vide_n_avoue_plus_quand_la_page_officielle_repond(
        self,
    ):
        """C'est le cas où la page officielle vaut le plus (22/09) : ddgs est
        intermittent, et une recherche à blanc laissait la voix avouer alors
        que pm.gc.ca répondait. Avouer là serait un faux aveu — aussi faux
        qu'un faux SUCCESS (§100)."""
        vide = {"ok": True, "content": "No results found.", "metadata": {}}
        session, journal = harnais([[appel_web()], "Mark Carney [1]."], recherche=vide)
        await session._respond_to_text(PREMIER_MINISTRE)
        lus = [a.get("url") for n, a in journal["executed"] if n == "web_read"]
        assert lus == ["https://www.pm.gc.ca/fr"], (
            "la page officielle est lue même sans un seul résultat de recherche"
        )
        assert AVEU_VOCAL_RECHERCHE not in journal["spoken"]

    @pytest.mark.asyncio
    async def test_une_seule_lecture_automatique_par_tour(self):
        """Ollama tourne à un créneau : deux allers au réseau pour un seul
        fait se paient en silence. La page du poste passe d'abord — elle
        porte la date d'entrée en fonction que le titre de pm.gc.ca n'a
        pas."""
        session, journal = harnais([[appel_web()], "Mark Carney [3], depuis 2025."])
        await session._respond_to_text(PREMIER_MINISTRE)
        lus = [a.get("url") for n, a in journal["executed"] if n == "web_read"]
        assert len(lus) == 1, f"deux lectures pour une question : {lus}"
        assert "wikipedia" in lus[0], "la page du poste, pas la page officielle"

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


class TestLaPastilleDuPanneauVocal:
    """22/09/2026. Jusqu'ici : « pas de badge dans le panneau vocal, l'épilogue
    en tient lieu. » Il n'en tenait pas lieu — l'épilogue ne parle que lorsqu'il
    a quelque chose à avouer, donc son silence disait à la fois « vérifié en
    ligne » et « personne n'a rien vérifié » (§5)."""

    @staticmethod
    def niveaux(session):
        sortie = []
        while not session._queue.empty():
            e = session._queue.get_nowait()
            if e.kind == "verification":
                sortie.append(e.verification)
        return sortie

    @pytest.mark.asyncio
    async def test_une_reponse_cherchee_et_lue_est_vérifiée(self):
        session, _ = harnais([[appel_web()], "Mark Carney, depuis mars 2025."])
        await session._respond_to_text(PREMIER_MINISTRE)
        assert self.niveaux(session) == [{"level": "verified", "searchTried": True}]

    @pytest.mark.asyncio
    async def test_une_reponse_sans_crochets_reste_verifiee(self):
        """La consigne vocale INTERDIT les « [1] » — Kokoro prononçait « Mark
        Carney deux ». Déléguer au niveau du chat, qui déclasse toute réponse
        sans citation, aurait mis « Partiellement vérifié » sous chaque bonne
        réponse vocale."""
        session, journal = harnais(
            [[appel_web()], "C'est Mark Carney, selon Wikipédia, depuis mars 2025."]
        )
        await session._respond_to_text(PREMIER_MINISTRE)
        assert "[" not in " ".join(journal["spoken"]), "rien à prononcer entre crochets"
        assert self.niveaux(session) == [{"level": "verified", "searchTried": True}]

    @pytest.mark.asyncio
    async def test_sans_recherche_la_pastille_dit_de_memoire(self):
        session, _ = harnais(["Mark Carney."] * 3)
        await session._respond_to_text(PREMIER_MINISTRE)
        (niveau,) = self.niveaux(session)
        assert niveau["level"] == "memory"

    @pytest.mark.asyncio
    async def test_une_recherche_vide_dit_de_memoire_et_qu_on_a_cherche(self):
        vide = {"ok": True, "content": "No results found.", "metadata": {}}
        session, _ = harnais([[appel_web()], "Le Canadien a gagné."], recherche=vide)
        await session._respond_to_text("Qui a gagné le match hier soir ?")
        assert self.niveaux(session) == [{"level": "memory", "searchTried": True}]

    @pytest.mark.asyncio
    async def test_un_desaccord_avec_les_sources_n_est_pas_verifie(self):
        """Le cas où un badge vert serait un faux SUCCESS (§100) : la voix
        avertit déjà à l'oral, la pastille ne doit pas dire le contraire."""
        session, journal = harnais([[appel_web()], "Justin Trudeau, depuis 2015."])
        await session._respond_to_text(PREMIER_MINISTRE)
        assert "Mark Carney" in journal["spoken"][-1], "l'avertissement est prononcé"
        (niveau,) = self.niveaux(session)
        assert niveau["level"] == "partial", "la pastille ne contredit pas la voix"

    @pytest.mark.asyncio
    async def test_la_pastille_juge_la_reponse_et_non_l_aveu(self):
        """`_speak_sentence` ajoute l'épilogue à ce qui a été dit : juger le
        tout reviendrait à juger le verdict au lieu de la réponse."""
        session, journal = harnais([[appel_web()], "Mark Carney, depuis mars 2025."])
        await session._respond_to_text(PREMIER_MINISTRE)
        assert journal["spoken"][-1] == "Mark Carney, depuis mars 2025.", (
            "rien n'est ajouté après une réponse vérifiée"
        )
        assert self.niveaux(session)[0]["level"] == "verified"

    @pytest.mark.asyncio
    async def test_rien_hors_d_une_question_d_actualite(self):
        """Une pastille sur « écris-moi un poème » ne voudrait rien dire."""
        session, _ = harnais(["Les feuilles tombent."])
        await session._respond_to_text("Écris-moi un haïku.")
        assert self.niveaux(session) == []


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
        prix = actualite_vocale.TourVocal(question="Quel est le prix du bitcoin ?")
        actualite_vocale.absorber_resultat(
            prix, "web_search", {}, dict(RECHERCHE), lire
        )
        assert lectures == [
            "https://fr.wikipedia.org/wiki/Premier_ministre_du_Canada"
        ], "un prix ne lit aucune page"

    def test_la_page_officielle_est_lue_meme_sans_resultat_de_recherche(self):
        """P6 à la voix : la prévision d'Environnement Canada pour la ville de
        la config, jointe au résultat, datée du jour et dite officielle."""
        from datetime import date

        tour = actualite_vocale.TourVocal(
            question="Quel temps fait-il ce soir ?", ville="Ottawa"
        )
        lectures = []

        def lire(nom, args):
            lectures.append(args)
            return {
                "ok": True,
                "content": (
                    "[1] Ottawa, ON - Prévision — meteo.gc.ca · modifié 2026-09-03\n"
                    f"Source: {args['url']}\nCe soir et cette nuit\n3°C\n"
                    "Partiellement nuageux\n"
                ),
                "metadata": {
                    "sources": [
                        {
                            "ref": 1,
                            "title": "Ottawa",
                            "url": args["url"],
                            "date": "2026-09-03",
                        }
                    ]
                },
            }

        vide = {"ok": True, "content": "No results found.", "metadata": {}}
        resultat = actualite_vocale.absorber_resultat(
            tour, "web_search", {}, vide, lire
        )
        assert lectures[0]["url"] == (
            "https://meteo.gc.ca/fr/location/index.html?coords=45.421,-75.697"
        )
        assert tour.verification_faite and tour.officielle_lue
        assert tour.sources == [
            {
                "ref": 1,
                "title": "Ottawa — Prévision 7 jours, Environnement Canada",
                "url": "https://meteo.gc.ca/fr/location/index.html?coords=45.421,-75.697",
                "date": date.today().isoformat(),
                "sender": "meteo.gc.ca",
                "official": True,
            }
        ]
        assert "Source officielle, lue par le code" in resultat["content"]
        assert "source officielle · consultée le" in resultat["content"]
        assert "Ce soir et cette nuit" in resultat["content"]
        assert actualite_vocale.epilogue(tour, "Ce soir, trois degrés.") == "", (
            "la page officielle vaut vérification : rien à avouer"
        )
        actualite_vocale.absorber_resultat(tour, "web_search", {}, vide, lire)
        assert len(lectures) == 1, "une seule lecture par tour"

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


class TestLaLectureSurNonReponseALaVoix:
    """Banc du 21/09 : « je n'ai pas trouvé le vainqueur » après une
    recherche — nhl.com était dans les résultats et le 9b n'y allait pas.
    Le code lit la source la plus prometteuse, puis le modèle reprend."""

    RECHERCHE_HOCKEY = {
        "ok": True,
        "content": (
            "[1] Le Devoir : contrats prolongés — ledevoir.com · 2026-09-19\n"
            "Source: https://ledevoir.com/a\nExtrait: …\n\n"
            "[2] 2026 Stanley Cup Final: Game 6 recap — nhl.com · 2026-06-20\n"
            "Source: https://www.nhl.com/news/x\nExtrait: …"
        ),
        "metadata": {
            "sources": [
                {
                    "ref": 1,
                    "title": "Le Devoir : contrats prolongés",
                    "url": "https://ledevoir.com/a",
                    "date": "2026-09-19",
                },
                {
                    "ref": 2,
                    "title": "2026 Stanley Cup Final: Game 6 recap",
                    "url": "https://www.nhl.com/news/x",
                    "date": "2026-06-20",
                },
            ]
        },
    }
    PAGE_NHL = {
        "ok": True,
        "content": (
            "[1] 2026 Stanley Cup Final: Game 6 recap — nhl.com · publié 2026-06-20\n"
            "Source: https://www.nhl.com/news/x\n"
            "Début : The Florida Panthers won the 2026 Stanley Cup.\n"
        ),
        "metadata": {
            "sources": [
                {
                    "ref": 1,
                    "title": "2026 Stanley Cup Final",
                    "url": "https://www.nhl.com/news/x",
                    "date": "2026-06-20",
                }
            ]
        },
    }

    @pytest.mark.asyncio
    async def test_le_code_lit_puis_le_modele_reprend_une_fois(self):
        from diapason.speech.realtime.actualite_vocale import CONSIGNE_PAGE_LUE_VOCALE

        session, journal = harnais(
            [
                [appel_web("gagnant Coupe Stanley 2026")],
                "Je n'ai pas trouvé le vainqueur dans les résultats.",
                "Selon la LNH, les Panthers de la Floride ont gagné la Coupe Stanley.",
            ],
            recherche=self.RECHERCHE_HOCKEY,
            page=self.PAGE_NHL,
        )
        await session._respond_to_text("Qui a gagné la Coupe Stanley en 2026 ?")
        assert [n for n, _ in journal["executed"]] == ["web_search", "web_read"], (
            "pas de page du poste pour un vainqueur ; la lecture vient de la "
            "non-réponse"
        )
        assert journal["executed"][1][1]["url"] == "https://www.nhl.com/news/x"
        reprise = journal["rounds"][2]
        assert reprise[-2] == {
            "role": "assistant",
            "content": "Je n'ai pas trouvé le vainqueur dans les résultats.",
        }, "la passe prononcée reste dans le fil — sans l'accusé, qui n'affirme rien"
        assert reprise[-1]["role"] == "system"
        assert "Florida Panthers won the 2026 Stanley Cup" in reprise[-1]["content"]
        assert reprise[-1]["content"].endswith(
            CONSIGNE_PAGE_LUE_VOCALE.format(
                titre="2026 Stanley Cup Final: Game 6 recap"
            )
        )
        assert " ".join(journal["spoken"]) == (
            "Je vérifie en ligne. Je n'ai pas trouvé le vainqueur dans les résultats. "
            "Je lis la source. "
            "Selon la LNH, les Panthers de la Floride ont gagné la Coupe Stanley."
        ), "l'aveu reste, « Je lis la source. » couvre le silence, la réponse suit"
        assert len(journal["rounds"]) == 3, "une lecture, une reprise, pas de boucle"

    @pytest.mark.asyncio
    async def test_sans_source_prometteuse_une_autre_requete(self):
        from diapason.speech.realtime.actualite_vocale import (
            CONSIGNE_AUTRE_REQUETE_VOCALE,
        )

        session, journal = harnais(
            [
                [appel_web("gagnant Coupe Stanley 2026")],
                "Je n'ai pas trouvé le vainqueur dans les résultats.",
                "Toujours rien.",
            ]
        )
        await session._respond_to_text("Qui a gagné la Coupe Stanley en 2026 ?")
        assert [n for n, _ in journal["executed"]] == ["web_search"], (
            "les titres (Carney, Trudeau) ne reprennent aucun mot de la question"
        )
        assert journal["rounds"][2][-1] == {
            "role": "system",
            "content": CONSIGNE_AUTRE_REQUETE_VOCALE,
        }
        assert "Je lis la source." not in journal["spoken"], (
            "rien à lire : l'accusé de lecture n'est pas prononcé (revue du 21/09)"
        )

    @pytest.mark.asyncio
    async def test_sans_budget_ni_accuse_ni_lecture(self):
        """Revue du 21/09 (22 h) : la recherche avait consommé le seul pas ;
        « Je lis la source. » était prononcé, la lecture refusée pour budget,
        et plus rien."""
        session, journal = harnais(
            [
                [appel_web("gagnant Coupe Stanley 2026")],
                "Je n'ai pas trouvé le vainqueur dans les résultats.",
                "Toujours rien.",
            ],
            recherche=self.RECHERCHE_HOCKEY,
            page=self.PAGE_NHL,
            max_tool_steps=1,
        )
        await session._respond_to_text("Qui a gagné la Coupe Stanley en 2026 ?")
        assert [n for n, _ in journal["executed"]] == ["web_search"]
        assert "Je lis la source." not in journal["spoken"]
        assert "Je n'ai pas pu lire la source." not in journal["spoken"]
        assert len(journal["rounds"]) == 2, "sans budget, l'aveu reste le dernier mot"

    @pytest.mark.asyncio
    async def test_la_page_refuse_et_plus_de_budget_l_accuse_est_corrige(self):
        """Annoncé « Je lis la source. », la page refuse (403), le budget ne
        permet plus de chercher : le silence disait que ça avait marché."""
        session, journal = harnais(
            [
                [appel_web("gagnant Coupe Stanley 2026")],
                "Je n'ai pas trouvé le vainqueur dans les résultats.",
                "Toujours rien.",
            ],
            recherche=self.RECHERCHE_HOCKEY,
            page={"ok": False, "error": "Lecture impossible : HTTP 403"},
            max_tool_steps=2,
        )
        await session._respond_to_text("Qui a gagné la Coupe Stanley en 2026 ?")
        assert [n for n, _ in journal["executed"]] == ["web_search", "web_read"], (
            "un seul essai : le second n'a plus de budget"
        )
        assert journal["spoken"][-2:] == [
            "Je lis la source.",
            "Je n'ai pas pu lire la source.",
        ]
        assert len(journal["rounds"]) == 2


class TestLaRelanceVocaleJugeLaDernierePasse:
    @pytest.mark.asyncio
    async def test_un_aveu_avant_la_recherche_ne_fait_pas_relire(self):
        """Revue du 21/09 : « je n'ai pas pu vérifier de mémoire, je cherche »
        dit avant la recherche faisait relire une page après la bonne réponse,
        et la répéter."""
        session, journal = harnais(
            [
                "Je n'ai pas trouvé, je cherche.",
                [appel_web()],
                "Selon Wikipédia, Mark Carney.",
            ]
        )
        await session._respond_to_text(PREMIER_MINISTRE)
        assert [n for n, _ in journal["executed"]] == ["web_search", "web_read"], (
            "la page du poste seulement — aucune lecture sur non-réponse"
        )
        assert " ".join(journal["spoken"]).count("Mark Carney") == 1
        assert len(journal["rounds"]) == 3

    def test_deux_essais_puis_rien_sans_budget(self):
        from diapason.speech.realtime import actualite_vocale as av

        tour = av.TourVocal(question="Qui a gagné la Coupe Stanley en 2026 ?")
        tour.verification_faite = True
        tour.sources = [
            {
                "ref": 1,
                "title": "Coupe Stanley 2026 : le bilan",
                "url": "https://a.ca/x",
            },
            {
                "ref": 2,
                "title": "2026 Stanley Cup Final",
                "url": "https://www.nhl.com/y",
            },
            {"ref": 3, "title": "Stanley Cup 2026 recap", "url": "https://z.ca/w"},
        ]
        tentees = []

        def lire(nom, args):
            tentees.append(args["url"])
            return {"ok": False, "error": "Lecture impossible : HTTP 403"}

        budget = {"restant": 3}

        def peut_chercher():
            return budget["restant"] > 0

        reprise = av.relance_apres_non_reponse(
            tour, "Je n'ai rien trouvé.", lire, peut_chercher
        )
        assert tentees == ["https://a.ca/x", "https://www.nhl.com/y"], "deux essais"
        assert reprise[-1]["content"] == av.CONSIGNE_AUTRE_REQUETE_VOCALE
        assert tour.pages_lues == set(), "une page refusée n'est pas « déjà lue »"
        # Le budget se demande APRÈS les lectures (revue du 21/09, 22 h) : un
        # booléen pris avant promettait une recherche impayable.
        tour3 = av.TourVocal(question=tour.question, verification_faite=True)
        tour3.sources = list(tour.sources)
        budget["restant"] = 1

        def lire_et_payer(nom, args):
            budget["restant"] -= 1
            return {"ok": False, "error": "Lecture impossible : HTTP 403"}

        assert (
            av.relance_apres_non_reponse(
                tour3, "Je n'ai rien trouvé.", lire_et_payer, peut_chercher
            )
            is None
        ), "la lecture a pris le dernier pas : pas de consigne « appelle web_search »"
        tour2 = av.TourVocal(question=tour.question, verification_faite=True)
        assert (
            av.relance_apres_non_reponse(tour2, "Je n'ai rien trouvé.", None, False)
            is None
        ), "sans budget pour chercher, l'aveu reste tel quel"


class TestLEpilogueJugeLaDernierePasse:
    @pytest.mark.asyncio
    async def test_un_de_memoire_avant_la_recherche_ne_tait_pas_le_desaccord(self):
        """Revue du 21/09 (22 h) : « De mémoire, c'est Justin Trudeau. » dit
        avant la recherche, puis « Justin Trudeau, depuis 2015. » après elle,
        les sources désignant Mark Carney — et pas un mot (§100)."""
        session, journal = harnais(
            [
                "De mémoire, c'est Justin Trudeau.",
                [appel_web()],
                "Justin Trudeau, depuis 2015.",
            ]
        )
        await session._respond_to_text(PREMIER_MINISTRE)
        assert journal["spoken"][-1].startswith(
            "Attention : les sources désignent Mark Carney"
        ), "le désaccord se juge sur la dernière passe, pas sur l'aveu d'avant"


class TestLaSuiteHeriteDuSujetALaVoix:
    @pytest.mark.asyncio
    async def test_ce_pays_recoit_le_rappel_de_l_echange_precedent(self):
        """21/09 (23 h) : « Raconte-moi l'histoire de ce pays » après Haïti
        recevait « de quel pays tu parles ? » au chat ; la voix assemble le
        même rappel (server/suite.py), dans la spéculation comme à l'adoption."""
        session, journal = harnais(
            ["Haïti est devenue indépendante en 1804."],
            historique=[
                {"role": "user", "content": "Qui est le président actuel d'Haïti ?"},
                {
                    "role": "assistant",
                    "content": "Il n'y a pas de président élu ; Alix Didier Fils-Aimé "
                    "dirige le gouvernement intérimaire.",
                },
            ],
        )
        await session._respond_to_text("Raconte-moi l'histoire de ce pays")
        premier = journal["rounds"][0]
        rappels = [
            m
            for m in premier
            if m["role"] == "system"
            and "La demande renvoie à ce qui précède" in m["content"]
        ]
        assert len(rappels) == 1
        assert "Fils-Aimé" in rappels[0]["content"]
        assert premier.index(rappels[0]) > premier.index(
            {"role": "user", "content": "Raconte-moi l'histoire de ce pays"}
        ), "après la demande"
