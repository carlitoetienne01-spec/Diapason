"""Le chat en flux exécute-t-il vraiment les outils que le modèle réclame ?

Constaté le 22 août 2026 : ``/v1/chat/completions`` avec ``stream: true`` et
sans ``tools`` — exactement ce qu'envoie l'application de bureau — était routé
vers le moteur nu. L'agent était contourné, et les 98 outils enregistrés avec
lui. Diapason décrivait un agenda qu'il ne pouvait pas lire.

Ces tests tiennent la boucle par ses deux bouts : le flux doit rester un flux
(jeton par jeton, pas un bloc à la fin) ET les outils doivent s'exécuter.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from diapason.core.types import Role, ToolResult
from diapason.engine._stubs import StreamChunk
from diapason.server.agentic_stream import (
    MAX_TOOL_RESULT_CHARS,
    stream_with_tools,
)


class MoteurFactice:
    """Rejoue des tours préprogrammés et retient ce qu'on lui a envoyé."""

    def __init__(self, tours: list[list[StreamChunk]]) -> None:
        self._tours = tours
        self.appels: list[dict] = []

    async def stream_full(self, messages, **kwargs):
        self.appels.append({"messages": list(messages), "kwargs": dict(kwargs)})
        index = min(len(self.appels) - 1, len(self._tours) - 1)
        for morceau in self._tours[index]:
            yield morceau


class OutilFactice:
    def __init__(self, nom: str) -> None:
        self._nom = nom

    def to_openai_function(self) -> dict:
        return {
            "type": "function",
            "function": {"name": self._nom, "description": "", "parameters": {}},
        }


class ExecuteurFactice:
    def __init__(self, reponse: str = "résultat", *, leve=None) -> None:
        self._reponse = reponse
        self._leve = leve
        self.recus: list = []

    def execute(self, tool_call):
        self.recus.append(tool_call)
        if self._leve is not None:
            raise self._leve
        return ToolResult(tool_name=tool_call.name, content=self._reponse, success=True)


def _appel(nom: str, arguments: str = "{}", index: int = 0) -> dict:
    return {
        "index": index,
        "id": f"call_{index}",
        "type": "function",
        "function": {"name": nom, "arguments": arguments},
    }


def _collecter(moteur, executeur, outils=("horloge",), **kw) -> list:
    async def run():
        return [
            e
            async for e in stream_with_tools(
                moteur,
                "modele-de-test",
                [],
                tools=[OutilFactice(n) for n in outils],
                executor=executeur,
                **kw,
            )
        ]

    return asyncio.run(run())


def test_sans_outil_le_flux_passe_inchange():
    """Le cas courant ne doit rien coûter : les jetons sortent tels quels."""
    moteur = MoteurFactice([[StreamChunk(content="Bon"), StreamChunk(content="jour")]])
    evts = _collecter(moteur, ExecuteurFactice())
    assert [e.kind for e in evts] == ["token", "token"]
    assert "".join(e.data for e in evts) == "Bonjour"
    assert len(moteur.appels) == 1, "un seul aller-retour quand aucun outil n'est voulu"


def test_les_jetons_sortent_un_par_un():
    """La régression à craindre : un pont qui attend la fin puis découpe."""
    moteur = MoteurFactice(
        [[StreamChunk(content=m) for m in ("a", "b", "c", "d")]],
    )
    evts = _collecter(moteur, ExecuteurFactice())
    assert [e.data for e in evts] == ["a", "b", "c", "d"]


def test_l_outil_reclame_est_execute_et_son_resultat_revient_au_modele():
    moteur = MoteurFactice(
        [
            [StreamChunk(tool_calls=[_appel("horloge")])],
            [StreamChunk(content="Il est midi.")],
        ]
    )
    executeur = ExecuteurFactice("12:00")
    evts = _collecter(moteur, executeur)

    assert [e.kind for e in evts] == ["tool_start", "tool_end", "token"]
    assert executeur.recus[0].name == "horloge"

    # Le second tour doit PORTER le résultat, sinon le modèle rappelle l'outil.
    second = moteur.appels[1]["messages"]
    assert second[-1].role is Role.TOOL
    assert second[-1].content == "12:00"
    # …précédé de l'intention du modèle, sans quoi le message d'outil est orphelin.
    assert second[-2].role is Role.ASSISTANT
    assert second[-2].tool_calls[0].name == "horloge"


def test_les_evenements_portent_ce_que_l_interface_affiche():
    """Chat/InputArea.tsx lit tool/arguments puis tool/success/latency/result."""
    moteur = MoteurFactice(
        [
            [StreamChunk(tool_calls=[_appel("horloge", '{"z":"Montréal"}')])],
            [StreamChunk(content="fini")],
        ]
    )
    evts = _collecter(moteur, ExecuteurFactice("12:00"))
    debut = next(e for e in evts if e.kind == "tool_start")
    fin = next(e for e in evts if e.kind == "tool_end")
    assert debut.data["tool"] == "horloge"
    assert json.loads(debut.data["arguments"]) == {"z": "Montréal"}
    assert fin.data["tool"] == "horloge"
    assert fin.data["success"] is True
    assert isinstance(fin.data["latency"], float)
    assert fin.data["result"] == "12:00"


def test_le_dernier_tour_se_fait_sans_outils():
    """Sinon un modèle qui boucle rendrait le silence — l'utilisateur veut une phrase."""
    moteur = MoteurFactice([[StreamChunk(tool_calls=[_appel("horloge")])]])
    _collecter(moteur, ExecuteurFactice(), max_tool_turns=2)

    assert len(moteur.appels) == 3
    assert "tools" in moteur.appels[0]["kwargs"]
    assert "tools" in moteur.appels[1]["kwargs"]
    assert "tools" not in moteur.appels[2]["kwargs"], (
        "le tour de trop doit réclamer une réponse, pas un nouvel appel"
    )


def test_un_appel_identique_repete_est_court_circuite():
    """Un 9b qui tourne en rond ne doit pas refaire le travail indéfiniment."""
    moteur = MoteurFactice(
        [
            [StreamChunk(tool_calls=[_appel("horloge")])],
            [StreamChunk(tool_calls=[_appel("horloge")])],
            [StreamChunk(content="Il est midi.")],
        ]
    )
    executeur = ExecuteurFactice("12:00")
    _collecter(moteur, executeur, max_tool_turns=3)
    assert len(executeur.recus) == 1, "le second appel identique n'est pas rejoué"


def test_un_outil_qui_leve_n_interrompt_pas_le_flux():
    moteur = MoteurFactice(
        [
            [StreamChunk(tool_calls=[_appel("horloge")])],
            [StreamChunk(content="Je n'ai pas pu lire l'heure.")],
        ]
    )
    evts = _collecter(moteur, ExecuteurFactice(leve=RuntimeError("cassé")))
    fin = next(e for e in evts if e.kind == "tool_end")
    assert fin.data["success"] is False
    assert "".join(e.data for e in evts if e.kind == "token")


def test_un_resultat_enorme_est_tronque_en_le_disant():
    """Un pavé noie le contexte d'un 9b ; le tronquer en silence le ferait mentir."""
    moteur = MoteurFactice(
        [
            [StreamChunk(tool_calls=[_appel("horloge")])],
            [StreamChunk(content="fini")],
        ]
    )
    executeur = ExecuteurFactice("x" * (MAX_TOOL_RESULT_CHARS + 500))
    _collecter(moteur, executeur)
    envoye = moteur.appels[1]["messages"][-1].content
    assert len(envoye) < MAX_TOOL_RESULT_CHARS + 200
    assert "tronqués" in envoye


def test_les_fragments_openai_sont_recomposes():
    """Ollama envoie d'un bloc ; les moteurs compatibles OpenAI fragmentent."""
    moteur = MoteurFactice(
        [
            [
                StreamChunk(
                    tool_calls=[
                        {
                            "index": 0,
                            "id": "c1",
                            "function": {"name": "hor", "arguments": '{"z":'},
                        }
                    ]
                ),
                StreamChunk(
                    tool_calls=[
                        {"index": 0, "function": {"name": "loge", "arguments": '"MTL"}'}}
                    ]
                ),
            ],
            [StreamChunk(content="fini")],
        ]
    )
    executeur = ExecuteurFactice()
    _collecter(moteur, executeur, outils=("horloge",))
    assert executeur.recus[0].name == "horloge"
    assert json.loads(executeur.recus[0].arguments) == {"z": "MTL"}


@pytest.mark.parametrize("tours", [0, 1])
def test_max_tool_turns_est_respecte(tours):
    moteur = MoteurFactice([[StreamChunk(tool_calls=[_appel("horloge")])]])
    executeur = ExecuteurFactice()
    _collecter(moteur, executeur, max_tool_turns=tours)
    assert len(executeur.recus) == tours


class TestObservation:
    """Ce que le MODÈLE lit d'un résultat d'outil.

    ``succes_tasks(action="list")`` rend ``content = "85 tâche(s) trouvée(s)."``
    et met les tâches dans ``metadata``. Le modèle ne recevait que la phrase :
    il appelait le bon outil, obtenait les quatre-vingt-cinq tâches, et n'en
    voyait que le nombre. Les outils Succès étaient inutiles même branchés.
    """

    def test_les_donnees_de_metadata_rejoignent_le_modele(self):
        from diapason.server.agentic_stream import observation

        r = ToolResult(
            tool_name="succes_tasks",
            content="85 tâche(s) trouvée(s).",
            metadata={"tasks": [{"title": "Appeler le dentiste", "done": False}]},
        )
        vu = observation(r)
        assert "85 tâche(s) trouvée(s)." in vu
        assert "Appeler le dentiste" in vu, "sans ça le modèle ne sait pas LESQUELLES"

    def test_le_contenu_seul_suffit_quand_il_n_y_a_rien_de_plus(self):
        from diapason.server.agentic_stream import observation

        r = ToolResult(tool_name="current_time", content="samedi 22 août, 20:13")
        assert observation(r) == "samedi 22 août, 20:13"

    def test_les_cles_techniques_ne_polluent_pas(self):
        from diapason.server.agentic_stream import observation

        r = ToolResult(
            tool_name="succes_tasks",
            content="fait",
            metadata={"persistence": "sqlite", "when": "today"},
        )
        assert observation(r) == "fait"

    def test_une_liste_trop_longue_dit_ce_qu_elle_cache(self):
        """Tronquer en silence ferait répondre « tu as douze tâches »."""
        from diapason.server.agentic_stream import observation

        r = ToolResult(
            tool_name="succes_tasks",
            content="200 tâche(s).",
            metadata={"tasks": [{"t": i} for i in range(200)]},
        )
        vu = observation(r)
        assert "de plus, non montrés" in vu
        assert len(vu) < 4000

    def test_les_champs_vides_sont_jetes_mais_pas_les_zeros(self):
        from diapason.server.agentic_stream import observation

        r = ToolResult(
            tool_name="succes_tasks",
            content="",
            metadata={
                "tasks": [
                    {
                        "titre": "Ranger",
                        "notes": "",
                        "emoji": "",
                        "done": False,
                        "reports": 0,
                    }
                ]
            },
        )
        vu = observation(r)
        assert "notes" not in vu and "emoji" not in vu
        assert '"done": false' in vu, "false porte l'information « pas encore faite »"
        assert '"reports": 0' in vu

    def test_une_metadata_non_serialisable_ne_casse_rien(self):
        from diapason.server.agentic_stream import observation

        r = ToolResult(
            tool_name="x", content="ok", metadata={"objet": object(), "n": 1}
        )
        vu = observation(r)
        assert vu.startswith("ok")


def test_le_modele_recoit_l_observation_complete_pas_le_seul_contenu():
    """Le bout par lequel le défaut se voyait : ce qui repart dans le fil."""
    moteur = MoteurFactice(
        [
            [StreamChunk(tool_calls=[_appel("taches")])],
            [StreamChunk(content="Tu as une tâche.")],
        ]
    )

    class ExecuteurRiche:
        def execute(self, tool_call):
            return ToolResult(
                tool_name=tool_call.name,
                content="1 tâche(s) trouvée(s).",
                metadata={"tasks": [{"title": "Appeler le dentiste"}]},
            )

    _collecter(moteur, ExecuteurRiche(), outils=("taches",))
    renvoye = moteur.appels[1]["messages"][-1].content
    assert "Appeler le dentiste" in renvoye


class TestSeparateur:
    """Le texte d'avant l'outil ne doit pas se coller à celui d'après.

    Constaté à l'écran : « Je vais consulter tes tâches d'aujourd'hui.Tu as une
    tâche aujourd'hui ». Deux tours distincts, recollés sans respiration, parce
    que la boucle émettait les jetons du second à la suite du premier.
    """

    def test_deux_tours_qui_ecrivent_sont_separes(self):
        moteur = MoteurFactice(
            [
                [
                    StreamChunk(content="Je regarde tes tâches."),
                    StreamChunk(tool_calls=[_appel("taches")]),
                ],
                [StreamChunk(content="Tu as une tâche.")],
            ]
        )
        evts = _collecter(moteur, ExecuteurFactice("1 tâche"), outils=("taches",))
        texte = "".join(e.data for e in evts if e.kind == "token")
        assert texte == "Je regarde tes tâches.\n\nTu as une tâche."

    def test_pas_de_separateur_quand_le_premier_tour_est_muet(self):
        """Le cas courant : l'outil part sans préambule. Pas de saut en tête."""
        moteur = MoteurFactice(
            [
                [StreamChunk(tool_calls=[_appel("taches")])],
                [StreamChunk(content="Tu as une tâche.")],
            ]
        )
        evts = _collecter(moteur, ExecuteurFactice("1 tâche"), outils=("taches",))
        texte = "".join(e.data for e in evts if e.kind == "token")
        assert texte == "Tu as une tâche."

    def test_un_seul_tour_n_est_jamais_separe(self):
        moteur = MoteurFactice([[StreamChunk(content="Bon"), StreamChunk(content="soir")]])
        evts = _collecter(moteur, ExecuteurFactice())
        assert "".join(e.data for e in evts if e.kind == "token") == "Bonsoir"

    def test_un_tour_qui_n_emet_que_du_blanc_ne_declenche_pas_le_separateur(self):
        moteur = MoteurFactice(
            [
                [StreamChunk(content="   "), StreamChunk(tool_calls=[_appel("taches")])],
                [StreamChunk(content="Tu as une tâche.")],
            ]
        )
        evts = _collecter(moteur, ExecuteurFactice("1 tâche"), outils=("taches",))
        texte = "".join(e.data for e in evts if e.kind == "token")
        assert texte == "   Tu as une tâche.", "un blanc n'est pas du texte écrit"


class TestTemperatureDesToursOutilles:
    """Décider d'appeler un outil n'est pas un acte créatif.

    Mesuré sur qwen3.5:9b : à 0,7 le modèle répondait « Je vais regarder tes
    tâches pour aujourd'hui. » et s'arrêtait là une fois sur dix — une promesse
    sans suite, que rien ne signale comme un échec. À 0,3 et en dessous, dix
    sur dix.
    """

    def test_un_tour_porteur_d_outils_est_refroidi(self):
        from diapason.server.agentic_stream import TOOL_TURN_TEMPERATURE

        moteur = MoteurFactice([[StreamChunk(content="fini")]])
        _collecter(moteur, ExecuteurFactice(), temperature=0.9)
        assert moteur.appels[0]["kwargs"]["temperature"] == TOOL_TURN_TEMPERATURE

    def test_le_dernier_tour_garde_la_temperature_demandee(self):
        """Sans outils à choisir, c'est la prose qui se joue : on rend la main."""
        moteur = MoteurFactice([[StreamChunk(tool_calls=[_appel("horloge")])]])
        _collecter(moteur, ExecuteurFactice(), temperature=0.9, max_tool_turns=1)
        assert "tools" in moteur.appels[0]["kwargs"]
        assert "tools" not in moteur.appels[1]["kwargs"]
        assert moteur.appels[1]["kwargs"]["temperature"] == 0.9

    def test_une_temperature_deja_basse_n_est_jamais_rechauffee(self):
        moteur = MoteurFactice([[StreamChunk(content="fini")]])
        _collecter(moteur, ExecuteurFactice(), temperature=0.05)
        assert moteur.appels[0]["kwargs"]["temperature"] == 0.05
