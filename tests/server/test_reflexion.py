"""La réflexion à deux vitesses : routage, critique, replis.

Le contrat : les questions analytiques passent par un brouillon silencieux
puis une relecture diffusée ; tout échec du brouillon retombe sur le flux
ordinaire ; le vif reste vif.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from diapason.core.types import Role
from diapason.server.reflexion import (
    meriter_reflexion,
    messages_de_critique,
    modele_de_reflexion,
    repondre_en_reflechissant,
)


class TestMeriterReflexion:
    def test_les_tournures_analytiques_ouvrent_la_porte(self):
        assert meriter_reflexion("Compare Python et Rust pour mon projet")
        assert meriter_reflexion("Analyse les avantages et inconvénients de SQLite")
        assert meriter_reflexion("Aide-moi à décider entre ces deux parcours")
        assert meriter_reflexion("Quelle est la meilleure stratégie pour apprendre ?")

    def test_le_quotidien_reste_vif(self):
        assert not meriter_reflexion("Bonjour !")
        assert not meriter_reflexion("Merci beaucoup")
        assert not meriter_reflexion("Quelle heure est-il ?")
        assert not meriter_reflexion("Ouvre Safari")

    def test_un_paragraphe_interrogatif_merite_reflexion(self):
        long_texte = (
            "Je me demande comment organiser mon temps entre " * 8
        ) + "qu'en dis-tu ?"
        assert meriter_reflexion(long_texte)

    def test_un_paragraphe_sans_question_reste_vif(self):
        assert not meriter_reflexion("voici mon journal du jour " * 20)


class TestModele:
    def test_la_config_designe_le_grand_frere(self):
        config = MagicMock()
        config.reflexion.model = "qwen3:14b"
        assert modele_de_reflexion(config, "qwen3.5:9b") == "qwen3:14b"

    def test_vide_garde_le_modele_du_tour(self):
        config = MagicMock()
        config.reflexion.model = ""
        assert modele_de_reflexion(config, "qwen3.5:9b") == "qwen3.5:9b"


class TestCritique:
    def test_le_brouillon_et_lordre_terminent_la_conversation(self):
        from diapason.core.types import Message

        base = [Message(role=Role.USER, content="Compare A et B")]
        augmente = messages_de_critique(base, "Mon premier jet.")
        assert len(augmente) == 3
        assert augmente[1].role == Role.ASSISTANT
        assert augmente[1].content == "Mon premier jet."
        assert augmente[2].role == Role.USER
        assert "version finale" in augmente[2].content


def _collecter(iterateur):
    async def _run():
        return [t async for t in iterateur]

    return asyncio.run(_run())


def _moteur(brouillon="Premier jet.", jetons=("Version", " relue.")):
    engine = MagicMock()
    engine.generate.return_value = {"content": brouillon}

    async def stream(messages, **kwargs):
        stream.appels.append((list(messages), dict(kwargs)))
        for jeton in jetons:
            yield jeton

    stream.appels = []
    engine.stream = stream
    return engine


class TestRepondre:
    def test_brouillon_puis_relecture_en_flux(self):
        from diapason.core.types import Message

        engine = _moteur()
        base = [Message(role=Role.USER, content="Compare A et B")]
        jetons = _collecter(
            repondre_en_reflechissant(
                engine, "qwen3:14b", base, temperature=0.7, max_tokens=512
            )
        )
        assert jetons == ["Version", " relue."]
        # le brouillon a été demandé au grand frère, court et non diffusé
        assert engine.generate.call_args.kwargs["model"] == "qwen3:14b"
        assert engine.generate.call_args.kwargs["max_tokens"] <= 512
        # la relecture voit le brouillon dans la conversation
        messages_relus = engine.stream.appels[0][0]
        assert any(
            m.role == Role.ASSISTANT and m.content == "Premier jet."
            for m in messages_relus
        )

    def test_brouillon_en_panne_retombe_sur_le_flux_ordinaire(self):
        from diapason.core.types import Message

        engine = _moteur(jetons=("Réponse", " simple."))
        engine.generate.side_effect = RuntimeError("modèle absent")
        base = [Message(role=Role.USER, content="Compare A et B")]
        jetons = _collecter(
            repondre_en_reflechissant(
                engine,
                "fantome:99b",
                base,
                temperature=0.7,
                max_tokens=512,
                modele_de_secours="qwen3.5:9b",
            )
        )
        assert jetons == ["Réponse", " simple."]
        appel = engine.stream.appels[0]
        assert appel[1]["model"] == "qwen3.5:9b"  # le secours, pas le fantôme
        assert appel[0] == base  # la conversation nue, sans critique

    def test_brouillon_vide_vaut_panne(self):
        from diapason.core.types import Message

        engine = _moteur(brouillon="   ")
        base = [Message(role=Role.USER, content="Compare A et B")]
        jetons = _collecter(
            repondre_en_reflechissant(
                engine, "qwen3:14b", base, temperature=0.7, max_tokens=512
            )
        )
        assert jetons == ["Version", " relue."]
        assert engine.stream.appels[0][0] == base
