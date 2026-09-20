"""§5/§100 : un flux réel, sans secret partiel ni appel d'outil prématuré."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from diapason.core.events import EventBus, EventType
from diapason.engine._stubs import StreamChunk
from diapason.security._stubs import BaseScanner
from diapason.security.guardrails import GuardrailsEngine, SecurityBlockError
from diapason.security.scanner import PIIScanner, SecretScanner
from diapason.security.types import RedactionMode, ScanFinding, ScanResult, ThreatLevel

pytestmark = pytest.mark.asyncio

# Un exemplaire par motif : un nouveau scanner/motif exige de revoir les
# frontières du flux ; une simple marge de 128 caractères ne suffit pas.
SECRETS = {
    "openai_key": "sk-" + "a" * 401,
    "anthropic_key": "sk-ant-" + "b" * 402,
    "aws_access_key": "AKIA" + "A" * 16,
    "github_token": "github_pat_" + "c" * 403,
    "password_assignment": "password" + " \n" * 90 + '= \n"' + "début\n" * 90 + '"',
    "db_connection_string": "postgres://" + "x" * 20 + "x\x1c" * 250,
    "private_key": "-----BEGIN RSA PRIVATE KEY-----",
    "slack_token": "xoxb-" + "d" * 405,
    "stripe_key": "sk_live_" + "e" * 406,
    "generic_api_key": "auth_token"
    + " \n" * 90
    + ":"
    + " " * 180
    + "'"
    + "f\n" * 200
    + "'",
}
PII = {
    "email": "g" * 450 + "@" + "h" * 300 + ".example",
    "us_ssn": "123-45-6789",
    "credit_card_visa": "4111 1111 1111 1111",
    "credit_card_mastercard": "5555-5555-5555-4444",
    "credit_card_amex": "3782 822463 10005",
    "us_phone": "+1 (202) 555-0199",
    "ipv4_public": "8.8.4.4",
}
AVANT = "Une introduction française, claire et sans donnée confidentielle. " * 8
APRES = "\nLa suite du texte reste présente et conserve exactement ses accents. " * 6


class Moteur:
    def __init__(self, morceaux):
        self.morceaux = morceaux
        self.ferme = False
        self.termine = False
        self.options = None

    async def stream_full(self, messages, **kwargs):
        self.options = kwargs
        try:
            for morceau in self.morceaux:
                yield morceau
            self.termine = True
        finally:
            self.ferme = True

    async def stream(self, messages, **kwargs):
        try:
            for morceau in self.morceaux:
                if morceau.content is not None:
                    yield morceau.content
            self.termine = True
        finally:
            self.ferme = True


def scanners(python):
    objets = [SecretScanner(), PIIScanner()]
    if python:
        for objet in objets:
            objet._rust_impl = None
    else:
        if any(objet._rust_impl is None for objet in objets):
            pytest.skip("accélérateur Rust absent ; le repli Python reste testé")
    return objets


async def recevoir(engine, riche):
    if riche:
        return [
            chunk.content or "" async for chunk in engine.stream_full([], model="test")
        ]
    return [texte async for texte in engine.stream([], model="test")]


class TestFrontieresDuFlux:
    """§5 : un secret découpé ne devient pas une série de morceaux publics."""

    async def test_chaque_motif_possede_un_cas_de_frontiere(self):
        assert set(SECRETS) == set(SecretScanner.PATTERNS), (
            "revoir la frontière du nouveau motif"
        )
        assert set(PII) == set(PIIScanner.PATTERNS), (
            "revoir la frontière du nouveau motif"
        )

    @pytest.mark.parametrize("python", [False, True], ids=["rust", "python"])
    @pytest.mark.parametrize("riche", [True, False], ids=["riche", "texte"])
    @pytest.mark.parametrize("taille", [1, 17, 173])
    @pytest.mark.parametrize(
        "secret", [*SECRETS.values(), *PII.values()], ids=[*SECRETS, *PII]
    )
    async def test_aucun_fragment_ne_fuit_et_la_suite_est_identique(
        self, python, riche, taille, secret
    ):
        texte = AVANT + secret + APRES
        bus = EventBus(record_history=True)
        engine = GuardrailsEngine(
            Moteur(
                [
                    StreamChunk(content=texte[i : i + taille])
                    for i in range(0, len(texte), taille)
                ]
            ),
            scanners=scanners(python),
            scan_input=False,
            bus=bus,
        )
        attendu = engine._redact_text(texte)
        assert attendu != texte, "le scanner doit reconnaître le secret de l'essai"
        sortie = await recevoir(engine, riche)
        assert "".join(sortie) == attendu, (
            "aucun préfixe sensible, doublon ou texte perdu"
        )
        assert len(sortie) > 1, "l'introduction doit avoir été diffusée progressivement"
        alerts = [e for e in bus.history if e.event_type == EventType.SECURITY_ALERT]
        assert len(alerts) == 1, "une seule alerte par réponse, pas une par fragment"

    @pytest.mark.parametrize("riche", [True, False])
    async def test_la_prose_avec_un_mot_password_n_est_pas_masquee(self, riche):
        texte = AVANT + "password est un mot anglais. api_key aussi. " + APRES
        morceaux = [
            StreamChunk(content=texte[i : i + 7]) for i in range(0, len(texte), 7)
        ]
        sortie = await recevoir(GuardrailsEngine(Moteur(morceaux)), riche)
        assert "".join(sortie) == texte, (
            "un mot isolé n'est pas une affectation secrète"
        )


class TestDiffusion:
    """§100 : recevoir avant la fin doit être prouvé, pas déduit du nom stream."""

    @pytest.mark.parametrize("riche", [True, False])
    async def test_le_debut_arrive_avant_que_la_generation_finisse(self, riche):
        moteur = Moteur([StreamChunk(content=AVANT), StreamChunk(content=APRES)])
        engine = GuardrailsEngine(moteur)
        flux = (
            engine.stream_full([], model="test")
            if riche
            else engine.stream([], model="test")
        )
        premier = await anext(flux)
        texte = premier.content if riche else premier
        assert texte and AVANT.startswith(texte), "recevoir du vrai texte avant la fin"
        assert not moteur.termine, "le fournisseur ne doit pas avoir fini sa réponse"
        await flux.aclose()
        assert moteur.ferme, (
            "fermer le lecteur doit fermer immédiatement le fournisseur"
        )

    async def test_desactiver_le_scan_n_impose_plus_un_tampon_entier(self):
        morceaux = [StreamChunk(content="court"), StreamChunk(finish_reason="stop")]
        moteur = Moteur(morceaux)
        flux = GuardrailsEngine(moteur, scan_output=False).stream_full([], model="test")
        assert await anext(flux) is morceaux[0], "transmission immédiate et inchangée"
        assert not moteur.termine, "pas d'attente de fin avec scan désactivé"
        await flux.aclose()
        assert moteur.ferme

    async def test_les_metadonnees_et_fragments_outils_sont_emis_une_seule_fois(self):
        morceaux = [
            StreamChunk(content=AVANT),
            StreamChunk(
                content=" avant l'outil ",
                tool_calls=[
                    {"index": 0, "function": {"name": "lire", "arguments": "{"}}
                ],
            ),
            StreamChunk(tool_calls=[{"index": 0, "function": {"arguments": "}"}}]),
            StreamChunk(
                content=APRES,
                finish_reason="tool_calls",
                usage={"completion_tokens": 42},
                content_blocks=[{"type": "text", "text": "résultat"}],
                tool_results=[{"id": "r"}],
            ),
        ]
        moteur = Moteur(morceaux)
        flux = GuardrailsEngine(moteur).stream_full(
            [], model="test", tools=[{"type": "function"}]
        )
        sortie = []
        async for morceau in flux:
            if morceau.tool_calls or morceau.finish_reason or morceau.usage:
                assert moteur.termine, "aucune métadonnée avant le contrôle final"
            sortie.append(morceau)
        assert "".join(m.content or "" for m in sortie) == "".join(
            m.content or "" for m in morceaux
        )
        for champ in (
            "tool_calls",
            "finish_reason",
            "usage",
            "content_blocks",
            "tool_results",
        ):
            assert [
                getattr(m, champ) for m in sortie if getattr(m, champ) is not None
            ] == [
                getattr(m, champ) for m in morceaux if getattr(m, champ) is not None
            ], champ
        assert moteur.options["tools"] == [{"type": "function"}], (
            "les options survivent au contrôle"
        )

    async def test_une_redaction_garde_aussi_le_terminal_et_les_outils(self):
        fin = StreamChunk(
            content=SECRETS["openai_key"],
            tool_calls=[{"index": 0}],
            finish_reason="stop",
            usage={"completion_tokens": 10},
        )
        moteur = Moteur([StreamChunk(content=AVANT), fin])
        sortie = [
            m async for m in GuardrailsEngine(moteur).stream_full([], model="test")
        ]
        assert sortie[-1] == replace(fin, content=None), (
            "métadonnées conservées une fois"
        )
        assert "sk-" not in "".join(m.content or "" for m in sortie)

    @pytest.mark.parametrize("riche", [True, False])
    async def test_block_ne_diffuse_rien_meme_si_le_secret_arrive_a_la_fin(self, riche):
        moteur = Moteur(
            [
                StreamChunk(content=AVANT),
                StreamChunk(content=PII["email"]),
            ]
        )
        engine = GuardrailsEngine(moteur, mode=RedactionMode.BLOCK)
        sortie = []
        with pytest.raises(SecurityBlockError):
            if riche:
                async for morceau in engine.stream_full([], model="test"):
                    sortie.append(morceau)
            else:
                async for morceau in engine.stream([], model="test"):
                    sortie.append(morceau)
        assert sortie == [], "BLOCK est atomique : aucun texte ni outil partiel"
        assert moteur.ferme

    async def test_warn_garde_le_contenu_et_signale_le_secret(self):
        texte = AVANT + PII["email"]
        bus = EventBus(record_history=True)
        engine = GuardrailsEngine(
            Moteur([StreamChunk(content=texte)]), mode=RedactionMode.WARN, bus=bus
        )
        assert "".join(await recevoir(engine, True)) == texte, "WARN n'est pas REDACT"
        assert len(bus.history) == 1 and bus.history[0].data["mode"] == "warn"

    async def test_scanner_personnalise_reste_entierement_bufferise(self):
        class ScannerLibre(BaseScanner):
            scanner_id = "libre"

            def scan(self, text):
                return ScanResult(
                    [ScanFinding("libre", text, ThreatLevel.HIGH, 0, len(text))]
                )

            def redact(self, text):
                return "[MASQUÉ]"

        moteur = Moteur([StreamChunk(content=AVANT), StreamChunk(content=APRES)])
        flux = GuardrailsEngine(moteur, scanners=[ScannerLibre()]).stream_full(
            [], model="test"
        )
        assert (await anext(flux)).content == "[MASQUÉ]", (
            "aucune hypothèse sur les scanners inconnus"
        )
        assert moteur.termine, "la règle personnalisée doit voir tout le contenu"
        await flux.aclose()

    @pytest.mark.parametrize("riche", [True, False])
    async def test_annuler_pendant_la_retenue_libere_le_fournisseur(self, riche):
        attend = asyncio.Event()
        ferme = asyncio.Event()

        class Lent(Moteur):
            async def stream_full(self, messages, **kwargs):
                try:
                    yield StreamChunk(content="court")
                    attend.set()
                    await asyncio.Event().wait()
                finally:
                    ferme.set()

            async def stream(self, messages, **kwargs):
                source = self.stream_full(messages, **kwargs)
                try:
                    async for chunk in source:
                        yield chunk.content
                finally:
                    await source.aclose()

        engine = GuardrailsEngine(Lent([]))
        flux = (
            engine.stream_full([], model="test")
            if riche
            else engine.stream([], model="test")
        )
        lecture = asyncio.create_task(anext(flux))
        await asyncio.wait_for(attend.wait(), 1)
        lecture.cancel()
        with pytest.raises(asyncio.CancelledError):
            await lecture
        assert ferme.is_set(), (
            "annuler ne doit pas laisser une génération occuper le modèle"
        )
