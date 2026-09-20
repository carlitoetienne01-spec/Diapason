"""§5/§100 : quantité livrée, arrêt réel et aucune réussite inventée."""

import asyncio

import pytest

from diapason.core.types import Message, Role
from diapason.engine._stubs import StreamChunk
from diapason.server.reponses_longues import (
    budget_quantite,
    compter_entrees,
    consigne_quantite,
    prolonger_flux,
    quantite_demandee,
    quantite_du_tour,
)


class Moteur:
    def __init__(self, tours):
        self.tours = tours
        self.appels = []

    async def stream_full(self, messages, **kwargs):
        self.appels.append((list(messages), kwargs))
        for morceau in self.tours[len(self.appels) - 1]:
            yield morceau


def demande(texte="Donne-moi 400 verbes"):
    return [Message(role=Role.USER, content=texte)]


async def collecter(moteur, messages=None, **kwargs):
    return [
        m
        async for m in prolonger_flux(
            moteur, messages or demande(), model="local", max_tokens=24576, **kwargs
        )
    ]


class TestQuantite:
    """§5 : la longueur du prompt ne mesure pas celle du résultat attendu."""

    @pytest.mark.parametrize(
        "texte",
        [
            "Donne moi la liste complète sous forme de tableau des 400 et les temps",
            "Je veux les 400 prends ton temps pour me les donner",
            "Generate 400 examples",
            "Donne-moi 400 verbes irréguliers",
        ],
    )
    def test_la_demande_de_carlito_recoit_un_budget_long(self, texte):
        assert quantite_demandee(texte) == 400, "la quantité doit être reconnue"
        assert budget_quantite(texte) == 13824, "400 lignes ne sont pas triviales"

    @pytest.mark.parametrize(
        "texte",
        [
            "Combien font 400 * 5 ?",
            "Donne-moi le calendrier de 2026",
            "Donne moi 400 euros",
            "Merci",
            "Pourquoi 400 verbes ?",
        ],
    )
    def test_un_nombre_n_est_pas_une_quantite_a_generer(self, texte):
        assert budget_quantite(texte) == 0, "ne pas relancer une réponse ordinaire"

    def test_borne_le_budget_et_n_herite_pas_d_une_ancienne_demande(self):
        assert budget_quantite("Donne-moi 999999 exemples") == 24576
        messages = [
            *demande(),
            Message(role=Role.ASSISTANT, content="400 verbes"),
            Message(role=Role.USER, content="Merci"),
        ]
        assert quantite_du_tour(messages) is None
        assert "ne fabrique" in consigne_quantite(400).lower()

    def test_renumeroter_le_meme_verbe_ne_le_rend_pas_distinct(self):
        texte = "| N° | Verbe | Passé |\n|---|---|---|\n|1|go|went|\n|2|Go|went|"
        assert compter_entrees(texte) == 1, "la clé est le verbe, pas le numéro"
        assert compter_entrees("1. Un\n2. Deux\n3. Un") == 2
        assert compter_entrees("Je ne connais pas de liste fiable.") is None
        assert compter_entrees("```\n" + texte + "\n```") is None


class TestReprise:
    """§100 : seules des interruptions observées justifient les reprises."""

    @pytest.mark.asyncio
    async def test_reprend_une_coupure_dans_le_meme_message(self):
        moteur = Moteur(
            [
                [StreamChunk(content="inter"), StreamChunk(finish_reason="length")],
                [StreamChunk(content="rompu"), StreamChunk(finish_reason="stop")],
            ]
        )
        sortie = await collecter(moteur)
        assert "".join(m.content or "" for m in sortie) == "interrompu"
        assert len(moteur.appels) == 2
        assert moteur.appels[1][0][-2].content == "inter"
        assert moteur.appels[0][1]["max_tokens"] == 8192

    @pytest.mark.asyncio
    async def test_complete_une_liste_numerotee_trop_courte(self):
        debut = "\n".join(f"{i}. Entrée {i}" for i in range(1, 26))
        fin = "\n".join(f"{i}. Entrée {i}" for i in range(26, 51))
        moteur = Moteur(
            [
                [StreamChunk(content=debut), StreamChunk(finish_reason="stop")],
                [StreamChunk(content=fin), StreamChunk(finish_reason="stop")],
            ]
        )
        sortie = await collecter(moteur, demande("Donne-moi 50 exemples"))
        texte = "".join(m.content or "" for m in sortie)
        assert compter_entrees(texte) == 50
        assert "Réponse partielle" not in texte

    @pytest.mark.asyncio
    async def test_trois_coupures_signalent_un_resultat_partiel(self):
        moteur = Moteur(
            [[StreamChunk(content="x"), StreamChunk(finish_reason="length")]] * 3
        )
        sortie = await collecter(moteur)
        assert len(moteur.appels) == 3, "jamais de boucle sans fin"
        assert "Réponse partielle" in "".join(m.content or "" for m in sortie)
        assert sortie[-1].finish_reason == "length"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("raison", ["stop", "content_filter", None])
    async def test_ne_relance_pas_un_arret_normal_ou_de_securite(self, raison):
        moteur = Moteur(
            [
                [
                    StreamChunk(content="Impossible de vérifier cette liste."),
                    StreamChunk(finish_reason=raison),
                ]
            ]
        )
        await collecter(moteur)
        assert len(moteur.appels) == 1

    @pytest.mark.asyncio
    async def test_un_outil_est_transmis_sans_etre_rejoue(self):
        appels = [{"index": 0, "function": {"name": "test", "arguments": "{}"}}]
        moteur = Moteur(
            [[StreamChunk(tool_calls=appels), StreamChunk(finish_reason="length")]]
        )
        sortie = await collecter(moteur, tools=[{"name": "test"}])
        assert any(m.tool_calls == appels for m in sortie)
        assert len(moteur.appels) == 1

    @pytest.mark.asyncio
    async def test_la_reprise_de_texte_n_a_plus_d_outils(self):
        moteur = Moteur(
            [
                [StreamChunk(content="A"), StreamChunk(finish_reason="length")],
                [StreamChunk(content="B"), StreamChunk(finish_reason="stop")],
            ]
        )
        await collecter(moteur, tools=[{"name": "test"}])
        assert "tools" in moteur.appels[0][1]
        assert "tools" not in moteur.appels[1][1]

    @pytest.mark.asyncio
    async def test_une_petite_demande_conserve_son_flux_et_son_budget(self):
        original = StreamChunk(
            content="Bonjour", finish_reason="stop", usage={"completion_tokens": 1}
        )
        moteur = Moteur([[original]])
        sortie = await collecter(moteur, demande("Donne-moi 3 exemples"))
        assert sortie == [original]
        assert moteur.appels[0][1]["max_tokens"] == 24576

    @pytest.mark.asyncio
    async def test_annuler_ne_lance_jamais_une_reprise(self):
        class Annule:
            appels = 0

            async def stream_full(self, *args, **kwargs):
                self.appels += 1
                yield StreamChunk(content="début")
                raise asyncio.CancelledError

        moteur = Annule()
        with pytest.raises(asyncio.CancelledError):
            await collecter(moteur)
        assert moteur.appels == 1


@pytest.mark.parametrize("outille", [False, True])
def test_le_chat_livre_400_lignes_dans_un_seul_flux(monkeypatch, outille):
    """§5 : le vrai endpoint relie budget, consigne et reprise, avec/sans outils."""
    import json

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from diapason.core.config import DiapasonConfig
    from diapason.server import routes

    entete = "| N° | Infinitif | Passé |\n|---|---|---|\n"
    debut = (
        entete + "\n".join(f"|{i}|entrée{i}|forme{i}|" for i in range(1, 101)) + "\n"
    )
    fin = "\n".join(f"|{i}|entrée{i}|forme{i}|" for i in range(101, 401))
    moteur = Moteur(
        [
            [StreamChunk(content=debut), StreamChunk(finish_reason="length")],
            [StreamChunk(content=fin), StreamChunk(finish_reason="stop")],
        ]
    )

    class Outil:
        def to_openai_function(self):
            return {
                "type": "function",
                "function": {"name": "factice", "parameters": {}},
            }

    monkeypatch.setattr(
        routes, "_chat_tooling", lambda *args: ([Outil()], None) if outille else None
    )
    monkeypatch.setattr("diapason.desktop.etat_bureau.etat_du_bureau", lambda: None)
    app = FastAPI()
    app.state.engine = moteur
    app.state.config = DiapasonConfig()
    app.include_router(routes.router)
    with TestClient(app) as client:
        reponse = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-local",
                "stream": True,
                "max_tokens": 4096,
                "messages": [{"role": "user", "content": "Donne-moi 400 verbes"}],
            },
        )
    assert reponse.status_code == 200
    evenements = [
        json.loads(ligne[6:])
        for ligne in reponse.text.splitlines()
        if ligne.startswith("data: ") and ligne != "data: [DONE]"
    ]
    contenu = "".join(
        e["choices"][0]["delta"].get("content") or ""
        for e in evenements
        if e.get("choices")
    )
    assert compter_entrees(contenu) == 400, (
        "les deux générations forment une seule réponse"
    )
    assert reponse.text.count("[DONE]") == 1
    assert len({e["id"] for e in evenements if "id" in e}) == 1
    assert evenements[-1]["complexity"]["suggested_max_tokens"] == 13824
    assert len(moteur.appels) == 2
    assert any(
        "400 éléments" in (m.content or "")
        for m in moteur.appels[0][0]
        if m.role == Role.SYSTEM
    )
    assert moteur.appels[1][1]["max_tokens"] == 5632
    assert "Réponse partielle" not in contenu


@pytest.mark.asyncio
async def test_un_arret_precoce_ne_consomme_pas_tout_le_budget():
    """§5 : la place inutilisée doit servir à compléter une tranche trop courte."""
    entete = "| N° | Entrée |\n|---|---|\n"
    debut = entete + "\n".join(f"|{i}|entrée{i}|" for i in range(1, 26))
    fin = "\n".join(f"|{i}|entrée{i}|" for i in range(26, 51))
    moteur = Moteur(
        [
            [
                StreamChunk(content=debut),
                StreamChunk(finish_reason="stop", usage={"completion_tokens": 700}),
            ],
            [
                StreamChunk(content=fin),
                StreamChunk(finish_reason="stop", usage={"completion_tokens": 600}),
            ],
        ]
    )
    sortie = [
        m
        async for m in prolonger_flux(
            moteur, demande("Donne-moi 50 exemples"), model="local", max_tokens=4096
        )
    ]
    texte = "".join(m.content or "" for m in sortie)
    assert compter_entrees(texte) == 50
    assert "|25|entrée25|\n|26|entrée26|" in texte, "pas de trou au milieu du tableau"
    assert moteur.appels[1][1]["max_tokens"] == 3396
    assert "Réponse partielle" not in texte


class TestRefusDeVolume:
    """§5 : un refus rédigé avant toute ligne n'est pas une coupure de jetons."""

    REFUS = (
        "Je ne peux pas générer une liste de **400 verbes** avec **tous leurs temps** "
        "dans un seul message. Cela dépasserait largement les limites techniques "
        "d'une réponse unique. Cependant, je peux proposer 50 verbes."
    )

    def test_reconnait_le_refus_reel_sans_confondre_les_limites_factuelles(self):
        from diapason.server.reponses_longues import refus_de_volume

        assert refus_de_volume(self.REFUS)
        assert not refus_de_volume("Je ne peux pas vérifier 400 verbes distincts.")
        assert not refus_de_volume(
            "Je ne peux pas fournir ces données confidentielles ; limites techniques."
        )
        assert not refus_de_volume(
            "Je ne peux pas contourner les règles de sécurité, "
            "même avec des limites techniques."
        )
        assert not refus_de_volume("> " + self.REFUS), "une citation n’est pas un refus"
        assert not refus_de_volume("Voici le tableau, malgré les limites techniques.")

    @pytest.mark.asyncio
    async def test_revise_le_refus_avant_affichage_et_garde_la_demande(self):
        moteur = Moteur(
            [
                [
                    StreamChunk(content=self.REFUS[:30]),
                    StreamChunk(content=self.REFUS[30:]),
                    StreamChunk(finish_reason="stop", usage={"completion_tokens": 110}),
                ],
                [
                    StreamChunk(
                        content="La prémisse nécessite une vérification des sources."
                    ),
                    StreamChunk(finish_reason="stop"),
                ],
            ]
        )
        messages = demande()
        sortie = await collecter(moteur, messages)
        texte = "".join(m.content or "" for m in sortie)
        assert "limites techniques" not in texte, "le brouillon refusé ne doit pas fuir"
        assert "vérification" in texte, "une réserve factuelle reste autorisée"
        assert len(moteur.appels) == 2
        assert moteur.appels[1][0][-1].content == messages[-1].content
        assert moteur.appels[1][0][-2].role == Role.SYSTEM
        assert "brouillon" in moteur.appels[1][0][-2].content
        assert len(messages) == 1, "l’historique persistant n’est pas réécrit"

    @pytest.mark.asyncio
    async def test_ne_reessaie_qu_une_fois_si_le_modele_persiste(self):
        tour = [StreamChunk(content=self.REFUS), StreamChunk(finish_reason="stop")]
        moteur = Moteur([tour, tour])
        sortie = await collecter(moteur)
        assert len(moteur.appels) == 2
        assert "".join(m.content or "" for m in sortie) == self.REFUS

    @pytest.mark.asyncio
    async def test_un_filtrage_de_securite_n_est_jamais_reessaye(self):
        moteur = Moteur(
            [
                [
                    StreamChunk(content=self.REFUS),
                    StreamChunk(finish_reason="content_filter"),
                ]
            ]
        )
        sortie = await collecter(moteur)
        assert len(moteur.appels) == 1
        assert "".join(m.content or "" for m in sortie) == self.REFUS

    @pytest.mark.asyncio
    async def test_un_appel_d_outil_passe_sans_reexecution(self):
        appels = [{"index": 0, "function": {"name": "test", "arguments": "{}"}}]
        moteur = Moteur(
            [
                [
                    StreamChunk(content=self.REFUS),
                    StreamChunk(tool_calls=appels),
                    StreamChunk(finish_reason="tool_calls"),
                ]
            ]
        )
        sortie = await collecter(moteur)
        assert len(moteur.appels) == 1
        assert sum(bool(m.tool_calls) for m in sortie) == 1
        assert "".join(m.content or "" for m in sortie) == self.REFUS

    @pytest.mark.asyncio
    async def test_ne_retient_pas_une_longue_reponse_entiere(self):
        from diapason.server.reponses_longues import AMORCE_MAX_CARACTERES

        premier = "A" * AMORCE_MAX_CARACTERES
        moteur = Moteur(
            [
                [
                    StreamChunk(content=premier),
                    StreamChunk(content="fin"),
                    StreamChunk(finish_reason="stop"),
                ]
            ]
        )
        flux = prolonger_flux(moteur, demande(), model="local", max_tokens=8192)
        assert (await anext(flux)).content == premier
        assert (await anext(flux)).content == "fin"
        await flux.aclose()
