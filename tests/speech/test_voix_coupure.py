"""La voix se coupe seule — §78, phase 4 du plan mobile (26/09/2026).

Jusqu'ici, /v1/voice/live n'avait aucune coupure : une orbe oubliée, un
onglet caché, un téléphone mis en poche gardaient le micro armé et Whisper à
l'écoute jusqu'à ce que quelqu'un ferme la page. La coupure vit dans le pont
(``speech/realtime/bridge.py``), côté serveur : un client ancien, planté ou
hostile ne peut pas l'ignorer.

Les limites sont abaissées à quelques dixièmes de seconde par test ; les
vraies valeurs sont figées à part, avec leur raison.
"""

from __future__ import annotations

import asyncio
import base64
import time

import pytest

from diapason.speech.realtime.base import SessionEvent
from diapason.speech.realtime.bridge import (
    BATTEMENT_S,
    DUREE_MAX_S,
    MOTIF_DUREE,
    MOTIF_SILENCE,
    SILENCE_MAX_S,
    VoiceLiveBridge,
)

_SILENCE = 0.3
_DUREE = 5.0
# Au-delà, le test échoue au lieu de pendre : une coupure qui ne vient
# jamais ne doit pas bloquer la suite.
_DELAI_DU_TEST_S = 4.0


class _Client:
    """Le WebSocket vu par le pont : ce qu'il reçoit, ce qu'il envoie."""

    def __init__(self) -> None:
        self.entrantes: asyncio.Queue = asyncio.Queue()
        self.envoyes: list[dict] = []
        self.fermeture: tuple[int, str | None] | None = None

    async def receive_json(self) -> dict:
        from fastapi import WebSocketDisconnect

        message = await self.entrantes.get()
        if message is None:
            raise WebSocketDisconnect(1000)
        return message

    async def send_json(self, donnees: dict) -> None:
        self.envoyes.append(donnees)

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        self.fermeture = (code, reason)
        self.entrantes.put_nowait(None)


class _Session:
    provider_id = "local"
    input_sample_rate = 16000
    output_sample_rate = 24000

    def __init__(self, *, connexion_bloquee: bool = False) -> None:
        self.file: asyncio.Queue = asyncio.Queue()
        self.audio_recu = 0
        self.fermee = False
        self._connexion_bloquee = connexion_bloquee

    async def connect(self) -> None:
        if self._connexion_bloquee:
            await asyncio.Event().wait()
        await self.file.put(SessionEvent(kind="ready"))

    async def events(self):
        while True:
            event = await self.file.get()
            if event is None:
                return
            yield event

    async def send_audio(self, _pcm16: bytes) -> None:
        self.audio_recu += 1

    async def send_text(self, _texte: str) -> None:
        return None

    async def interrupt(self) -> None:
        return None

    async def close(self) -> None:
        if self.fermee:
            return
        self.fermee = True
        await self.file.put(SessionEvent(kind="closed"))
        await self.file.put(None)


def _trame_de_micro() -> dict:
    return {
        "type": "audio",
        "data": base64.b64encode(b"\x00\x00" * 320).decode(),
        "sample_rate": 16000,
    }


async def _micro_continu(client: _Client, arret: asyncio.Event) -> None:
    """Ce que fait le vrai client : une trame toutes les 20 ms, silence ou non."""
    while not arret.is_set():
        client.entrantes.put_nowait(_trame_de_micro())
        await asyncio.sleep(0.02)


async def _mener(pont: VoiceLiveBridge, *pendant) -> float:
    debut = time.monotonic()
    arret = asyncio.Event()
    taches = [asyncio.ensure_future(p(arret)) for p in pendant]
    try:
        await asyncio.wait_for(pont.run(), _DELAI_DU_TEST_S)
    finally:
        arret.set()
        for tache in taches:
            tache.cancel()
    return time.monotonic() - debut


def _pont(client, session, **limites) -> VoiceLiveBridge:
    limites.setdefault("silence_max_s", _SILENCE)
    limites.setdefault("duree_max_s", _DUREE)
    return VoiceLiveBridge(client, session, **limites)


class TestLeSilenceCoupe:
    @pytest.mark.asyncio
    async def test_un_micro_qui_n_entend_personne_est_coupe(self):
        """§78 : sans cette garde, le micro restait armé indéfiniment. Les
        trames du micro arrivent en continu — elles ne prouvent pas que
        quelqu'un parle et ne doivent pas tenir la session ouverte."""
        client, session = _Client(), _Session()
        pont = _pont(client, session)
        duree = await _mener(pont, lambda a: _micro_continu(client, a))

        assert session.audio_recu > 5, "le micro n'a jamais atteint la session"
        assert client.envoyes[-1] == {"type": "closed", "reason": MOTIF_SILENCE}, (
            "le client doit apprendre POURQUOI la voix s'est tue"
        )
        assert client.fermeture == (1000, MOTIF_SILENCE), client.fermeture
        assert session.fermee, "la session du fournisseur a survécu à la coupure"
        assert _SILENCE <= duree < _SILENCE + 1.0, f"coupée en {duree:.2f} s"

    @pytest.mark.asyncio
    async def test_un_client_muet_comme_un_telephone_perdu_est_coupe(self):
        """Un WebSocket perdu sans fermeture (téléphone hors réseau) ne
        parle plus : il tombe sous la même règle."""
        client, session = _Client(), _Session()
        duree = await _mener(_pont(client, session))
        assert client.envoyes[-1]["reason"] == MOTIF_SILENCE
        assert duree < _SILENCE + 1.0, f"coupée en {duree:.2f} s"

    @pytest.mark.asyncio
    async def test_les_partiels_de_l_utilisateur_ne_retiennent_pas_la_session(self):
        """La transcription locale produit des partiels sur la télévision,
        avant de juger que personne ne s'adressait à nous. Les compter
        garderait le micro ouvert tant que la télé parle."""
        client, session = _Client(), _Session()

        async def television(arret: asyncio.Event) -> None:
            while not arret.is_set():
                await session.file.put(
                    SessionEvent(kind="transcript", role="user", text="…", replace=True)
                )
                await asyncio.sleep(0.05)

        duree = await _mener(_pont(client, session), television)
        assert client.envoyes[-1] == {"type": "closed", "reason": MOTIF_SILENCE}
        assert duree < _SILENCE + 1.0, f"coupée en {duree:.2f} s"

    @pytest.mark.asyncio
    async def test_une_phrase_finale_repousse_la_coupure(self):
        client, session = _Client(), _Session()

        async def parler(_arret: asyncio.Event) -> None:
            await asyncio.sleep(0.2)
            await session.file.put(
                SessionEvent(kind="transcript", role="user", text="Oui", final=True)
            )

        duree = await _mener(_pont(client, session), parler)
        assert duree >= 0.2 + _SILENCE, (
            f"coupée en {duree:.2f} s : la phrase finale n'a pas compté"
        )
        assert client.envoyes[-1]["reason"] == MOTIF_SILENCE

    @pytest.mark.asyncio
    async def test_la_voix_de_l_assistant_compte_jusqu_a_la_fin_de_sa_lecture(self):
        """La synthèse devance la lecture : une réponse d'une seconde part en
        quelques millisecondes. Compter l'envoi au lieu de la lecture
        entamerait le silence accordé à l'utilisateur pendant qu'il écoute."""
        client, session = _Client(), _Session()
        une_seconde = base64.b64encode(b"\x00\x00" * 24000).decode()

        async def repondre(_arret: asyncio.Event) -> None:
            await session.file.put(
                SessionEvent(kind="audio", audio_b64=une_seconde, sample_rate=24000)
            )

        duree = await _mener(_pont(client, session), repondre)
        assert duree >= 1.0 + _SILENCE - 0.05, (
            f"coupée en {duree:.2f} s, pendant que la réponse se lisait encore"
        )

    @pytest.mark.asyncio
    async def test_un_texte_tape_compte_comme_une_parole(self):
        client, session = _Client(), _Session()

        async def taper(_arret: asyncio.Event) -> None:
            await asyncio.sleep(0.2)
            client.entrantes.put_nowait({"type": "text", "text": "bonjour"})

        duree = await _mener(_pont(client, session), taper)
        assert duree >= 0.2 + _SILENCE, f"coupée en {duree:.2f} s"

    @pytest.mark.asyncio
    async def test_une_interruption_compte_comme_une_parole(self):
        """Couper la parole à l'assistant, c'est parler. 26/09/2026,
        contre-épreuve : ``_entendu()`` retiré avant ``interrupt()``, tous
        les tests restaient verts."""
        client, session = _Client(), _Session()

        async def interrompre(_arret: asyncio.Event) -> None:
            await asyncio.sleep(0.2)
            client.entrantes.put_nowait({"type": "interrupt"})

        duree = await _mener(_pont(client, session), interrompre)
        assert duree >= 0.2 + _SILENCE, (
            f"coupée en {duree:.2f} s : l'interruption n'a pas compté"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "evenement",
        [
            SessionEvent(kind="tool", tool_name="vie_tasks", tool_ok=True),
            SessionEvent(kind="verification", verification={"verdict": "ok"}),
            SessionEvent(kind="interrupted"),
        ],
        ids=["outil", "verification", "interrompue"],
    )
    async def test_ce_que_fait_l_assistant_sans_parler_compte_aussi(
        self, evenement: SessionEvent
    ):
        """Un outil long ou une vérification : l'assistant TRAVAILLE, sans un
        son. 26/09/2026, contre-épreuve : ``_noter`` réduit à « ready »
        laissait tout vert — la voix aurait été coupée pendant qu'elle
        cherchait la réponse."""
        client, session = _Client(), _Session()

        async def travailler(_arret: asyncio.Event) -> None:
            await asyncio.sleep(0.2)
            await session.file.put(evenement)

        duree = await _mener(_pont(client, session), travailler)
        assert duree >= 0.2 + _SILENCE, (
            f"coupée en {duree:.2f} s : « {evenement.kind} » n'a pas compté"
        )


class TestLaDureeCoupe:
    @pytest.mark.asyncio
    async def test_une_conversation_sans_fin_est_coupee_a_la_duree_maximale(self):
        """Une parole toutes les 100 ms ne laisse jamais le silence expirer :
        seule la durée maximale arrête la session."""
        client, session = _Client(), _Session()

        async def bavarder(arret: asyncio.Event) -> None:
            while not arret.is_set():
                client.entrantes.put_nowait({"type": "text", "text": "encore"})
                await asyncio.sleep(0.1)

        duree = await _mener(
            _pont(client, session, silence_max_s=0.5, duree_max_s=0.8), bavarder
        )
        assert client.envoyes[-1] == {"type": "closed", "reason": MOTIF_DUREE}
        assert client.fermeture == (1000, MOTIF_DUREE)
        assert 0.8 <= duree < 1.8, f"coupée en {duree:.2f} s"

    @pytest.mark.asyncio
    async def test_un_chauffage_qui_ne_rend_jamais_la_main_est_coupe(self):
        """La garde court PENDANT la mise en route : sans cela, un Kokoro
        bloqué laissait le micro du client ouvert sans limite, puisque rien
        d'autre ne tournait encore."""
        client, session = _Client(), _Session(connexion_bloquee=True)
        duree = await _mener(_pont(client, session))
        assert client.envoyes == [{"type": "closed", "reason": MOTIF_SILENCE}]
        assert session.fermee
        assert duree < _SILENCE + 1.0, f"coupée en {duree:.2f} s"


class TestLeBattement:
    """Le micro du téléphone ne sait rien de la coupure du Mac quand le
    réseau est tombé : ni la trame « closed » ni la fermeture ne lui
    arrivent, et son TCP retransmet jusqu'à quinze minutes (26/09/2026,
    contre-épreuve). Le serveur bat ; le client coupe son micro quand les
    battements cessent (``coupureCliente``, frontend/src/lib/voiceLive.ts)."""

    @pytest.mark.asyncio
    async def test_un_silence_porte_des_battements_et_la_fermeture_reste_derniere(
        self,
    ):
        client, session = _Client(), _Session()
        await _mener(_pont(client, session, silence_max_s=0.5, battement_s=0.1))
        types = [m["type"] for m in client.envoyes]
        assert types[0] == "ready", "un battement ne précède jamais « ready »"
        assert types.count("alive") >= 3, (
            f"un silence d'une demi-seconde doit porter des battements : {types}"
        )
        assert client.envoyes[-1] == {"type": "closed", "reason": MOTIF_SILENCE}, (
            "la trame « closed » doit rester la dernière reçue"
        )

    @pytest.mark.asyncio
    async def test_un_battement_ne_repousse_pas_la_coupure(self):
        """Le battement est la voix du SERVEUR, pas une parole : compté, il
        garderait le micro ouvert pour toujours."""
        client, session = _Client(), _Session()
        duree = await _mener(_pont(client, session, battement_s=0.05))
        assert client.envoyes[-1]["reason"] == MOTIF_SILENCE
        assert duree < _SILENCE + 1.0, f"coupée en {duree:.2f} s"

    @pytest.mark.asyncio
    async def test_un_chauffage_bloque_ne_bat_pas(self):
        """Pas de battement avant « ready » : le client n'arme sa garde qu'au
        premier, et un serveur plus ancien, qui ne bat pas, n'est jamais
        pris pour un mort."""
        client, session = _Client(), _Session(connexion_bloquee=True)
        await _mener(_pont(client, session, battement_s=0.05))
        assert client.envoyes == [{"type": "closed", "reason": MOTIF_SILENCE}]

    def test_le_battement_laisse_trois_chances_avant_la_garde_du_client(self):
        """Le client coupe après 45 s sans trame : trois battements manqués.
        La valeur du client est tenue contre celle-ci par voiceLive.test.ts."""
        assert BATTEMENT_S == 15.0
        assert BATTEMENT_S * 3 <= 45.0


class TestLesVraiesLimites:
    def test_le_silence_laisse_le_temps_d_appeler_diapason_par_son_nom(self):
        """La conversation se désengage après ADDRESS_WINDOW_S et attend son
        nom : couper au même instant rendrait ce rappel impossible."""
        from diapason.speech.realtime.local_voice import ADDRESS_WINDOW_S

        assert SILENCE_MAX_S >= ADDRESS_WINDOW_S + 30, (
            "la voix se couperait à l'instant où elle se désengage"
        )

    def test_le_silence_couvre_l_attente_de_la_cloche(self):
        """Un tour qui attend l'approbation reste muet 45 s au plus."""
        from diapason.speech.realtime.tools import VOICE_APPROVAL_WAIT_S

        assert SILENCE_MAX_S > VOICE_APPROVAL_WAIT_S + 30, (
            "une approbation lente couperait la voix avant la réponse"
        )

    def test_la_duree_maximale_est_celle_du_mode_gestes(self):
        """§78 et §83 : ni la caméra ni le micro ne tiennent une heure par
        accident."""
        from diapason.server.gestes_routes import _DUREE_MAX_S

        assert DUREE_MAX_S == _DUREE_MAX_S == 600.0
        assert SILENCE_MAX_S < DUREE_MAX_S
