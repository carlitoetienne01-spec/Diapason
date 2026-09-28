"""Bridge browser WebSocket clients to a provider realtime session."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Optional

from diapason.speech.realtime.base import RealtimeVoiceSession, SessionEvent
from diapason.speech.realtime.pcm import b64_to_pcm16, resample_pcm16

logger = logging.getLogger(__name__)

# §78 — rien ne guette en permanence. Jusqu'au 26/09/2026, /v1/voice/live
# n'avait AUCUNE coupure : une orbe oubliée ouverte, un onglet caché, un
# téléphone mis en poche gardaient le micro armé et Whisper à l'écoute
# jusqu'à ce que quelqu'un ferme la page. La coupure vit ICI, côté serveur,
# parce qu'une coupure décidée par le client est décorative (CLAUDE.md §5) :
# un client ancien, planté ou hostile ne l'appliquerait pas.
#
# Deux minutes sans PAROLE. La parole, c'est une phrase finale de
# l'utilisateur, une phrase ou un son de l'assistant (jusqu'à la fin de sa
# lecture), un outil, une interruption, un texte tapé — jamais une trame de
# micro : le client en envoie en continu, silence compris, et elles ne
# prouvent pas que quelqu'un parle. Jamais non plus un partiel de
# l'utilisateur : la transcription locale en produit sur la télévision,
# avant de juger que personne ne s'adressait à nous. Pourquoi 120 et pas 90
# comme les gestes : la conversation locale se désengage après 90 s
# (ADDRESS_WINDOW_S) et attend alors qu'on l'appelle par son nom ; 120 lui
# laisse 30 s pour qu'on le fasse, au lieu de couper à l'instant même où
# elle se désengage. Et 120 couvre un tour qui attend la cloche : 45 s
# d'approbation (VOICE_APPROVAL_WAIT_S) sans un mot, plus la réponse.
# Un WebSocket perdu sans fermeture (téléphone hors réseau, en poche) ne
# parle plus : la SÉANCE du Mac tombe sous cette même règle, en 120 s au
# plus. Le MICRO du téléphone, lui, n'en sait rien (26/09/2026,
# contre-épreuve) : la trame « closed » et la fermeture n'atteignent pas un
# téléphone hors réseau, et son TCP retransmet jusqu'à quinze minutes. D'où
# le battement ci-dessous, que le client surveille (`coupureCliente`,
# frontend/src/lib/voiceLive.ts).
SILENCE_MAX_S = 120.0
# Le battement : `{"type": "alive"}` toutes les quinze secondes, pour que le
# client sache le Mac encore là pendant un silence où rien d'autre ne
# passe. Le client coupe son micro après 45 s sans aucune trame (trois
# battements manqués : un creux de réseau de trente secondes ne coupe
# rien). Plus court, et le fil porterait du bruit pour rien ; plus long, et
# le micro d'un téléphone perdu resterait ouvert d'autant. Le premier part
# après quinze secondes, pas avant « ready » : un client ne le voit
# qu'une fois la séance montée, et n'arme sa garde qu'à ce moment-là — un
# serveur plus ancien, qui ne bat pas, n'est jamais pris pour un mort.
BATTEMENT_S = 15.0
# Dix minutes au plus, quoi qu'il se dise : le même plafond que le mode
# gestes (_DUREE_MAX_S, gestes_routes.py). Une réponse orale tient en une à
# trois phrases, ~15 s avec la question : dix minutes, c'est une quarantaine
# d'échanges. Réarmer coûte un toucher, et Whisper et Kokoro restent chargés
# (_SHARED, local_voice.py) : la reprise est immédiate.
DUREE_MAX_S = 600.0

# Les motifs de fermeture, sur le fil (anglais camelCase, CLAUDE.md §3) :
# le client les lit pour dire POURQUOI la voix s'est tue, au lieu d'un
# retour muet à l'état « inactif » qu'on prendrait pour une panne.
MOTIF_SILENCE = "inactivity"
MOTIF_DUREE = "maxDuration"


def event_to_client_json(event: SessionEvent) -> dict[str, Any]:
    """Serialize a :class:`SessionEvent` for the browser protocol."""
    if event.kind == "ready":
        return {
            "type": "ready",
            **(
                {"conversationOnly": True} if event.detail == "conversationOnly" else {}
            ),
        }
    if event.kind == "status":
        return {"type": "status", "stage": event.detail}
    if event.kind == "audio":
        return {
            "type": "audio",
            "data": event.audio_b64,
            "sample_rate": event.sample_rate,
        }
    if event.kind == "transcript":
        return {
            "type": "transcript",
            "role": event.role,
            "text": event.text,
            "final": event.final,
            "replace": event.replace,
        }
    if event.kind == "interrupted":
        return {"type": "interrupted"}
    if event.kind == "tool":
        return {
            "type": "tool",
            "name": event.tool_name,
            "ok": event.tool_ok,
            "detail": event.detail,
            # Clés anglaises camelCase, comme au chat : le client les lit avec
            # le même `resumeDeRecherche`.
            **(event.tool_details or {}),
        }
    if event.kind == "verification":
        # Les clés restent celles du chat : le client les lit avec le même
        # `lireVerification`, qui ne connaît que l'anglais camelCase.
        return {"type": "verification", **(event.verification or {})}
    if event.kind == "error":
        return {"type": "error", "detail": event.detail or "unknown error"}
    if event.kind in ("closing", "closed"):
        return {
            "type": event.kind,
            **({"reason": "farewell"} if event.detail == "farewell" else {}),
        }
    return {"type": "error", "detail": f"unknown event {event.kind}"}


class VoiceLiveBridge:
    """Pump audio/control messages between a FastAPI WebSocket and a provider."""

    def __init__(
        self,
        client_ws: Any,
        session: RealtimeVoiceSession,
        *,
        client_input_rate: int = 16000,
        silence_max_s: Optional[float] = None,
        duree_max_s: Optional[float] = None,
        horloge: Callable[[], float] = time.monotonic,
        battement_s: Optional[float] = None,
    ) -> None:
        self._client = client_ws
        self._session = session
        self._client_input_rate = client_input_rate
        self._tasks: list[asyncio.Task[Any]] = []
        # Lus à la construction, pas à la définition : un test abaisse les
        # constantes du module, la route n'en passe aucune.
        self._silence_max_s = (
            SILENCE_MAX_S if silence_max_s is None else float(silence_max_s)
        )
        self._duree_max_s = DUREE_MAX_S if duree_max_s is None else float(duree_max_s)
        self._battement_s = BATTEMENT_S if battement_s is None else float(battement_s)
        self._horloge = horloge
        self._debut = horloge()
        # L'instant jusqu'où quelqu'un parle — dans le FUTUR tant que la
        # voix de l'assistant se lit encore chez le client.
        self._parole_jusqua = self._debut
        self.motif_de_fermeture: Optional[str] = None

    # -- la coupure (§78) ------------------------------------------------

    def _entendu(self) -> None:
        self._parole_jusqua = max(self._parole_jusqua, self._horloge())

    def _entendu_audio(self, event: SessionEvent) -> None:
        # La synthèse devance la lecture : le dernier morceau part souvent
        # bien avant que le client ait fini de le jouer. Compter la durée
        # JOUÉE, sinon une longue réponse entamerait le silence accordé à
        # l'utilisateur pendant qu'il l'écoute encore.
        octets = len(event.audio_b64 or "") * 3 // 4
        taux = int(event.sample_rate or 24000) or 24000
        duree_s = octets / 2 / taux
        self._parole_jusqua = max(self._parole_jusqua, self._horloge()) + duree_s

    def _noter(self, event: SessionEvent) -> None:
        if event.kind == "audio":
            self._entendu_audio(event)
        elif event.kind == "transcript":
            if event.role != "user" or event.final:
                self._entendu()
        elif event.kind in ("ready", "tool", "interrupted", "verification"):
            self._entendu()

    async def _garder(self) -> str:
        """Rend le motif de la coupure quand une limite est franchie."""
        while True:
            maintenant = self._horloge()
            fin_duree = self._debut + self._duree_max_s
            fin_silence = self._parole_jusqua + self._silence_max_s
            if maintenant >= fin_duree:
                return MOTIF_DUREE
            if maintenant >= fin_silence:
                return MOTIF_SILENCE
            await asyncio.sleep(max(0.01, min(fin_duree, fin_silence) - maintenant))

    async def _battre(self) -> None:
        """Dit au client, à intervalle fixe, que le Mac est encore là."""
        while True:
            await asyncio.sleep(self._battement_s)
            try:
                await self._client.send_json({"type": "alive"})
            except Exception:  # noqa: BLE001 - le client est parti : la garde tranchera
                return

    async def _couper(self, motif: str) -> None:
        self.motif_de_fermeture = motif
        logger.info("voice live: session closed by the server (%s)", motif)
        try:
            await self._client.send_json({"type": "closed", "reason": motif})
        except Exception:  # noqa: BLE001 - le client est peut-être déjà parti
            pass
        try:
            # 1000 : une fin normale, voulue — pas une erreur à réessayer.
            await self._client.close(code=1000, reason=motif)
        except Exception:  # noqa: BLE001
            pass

    async def run(self) -> None:
        garde = asyncio.create_task(self._garder())
        try:
            # La garde court PENDANT la mise en route : un chauffage qui ne
            # rend jamais la main (Kokoro bloqué, Ollama muet) laissait le
            # micro du client ouvert sans limite, puisque rien d'autre ne
            # tournait encore.
            connexion = asyncio.create_task(self._session.connect())
            faites, _ = await asyncio.wait(
                {garde, connexion}, return_when=asyncio.FIRST_COMPLETED
            )
            if connexion not in faites:
                connexion.cancel()
                await self._couper(garde.result())
                return
            connexion.result()
            battement = asyncio.create_task(self._battre())
            forward = asyncio.create_task(self._forward_provider_events())
            receive = asyncio.create_task(self._receive_client_messages())
            self._tasks = [forward, receive, garde]
            done, pending = await asyncio.wait(
                self._tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )
            # Le battement se tait AVANT la trame « closed » : elle doit
            # rester la dernière chose que le client reçoit.
            battement.cancel()
            for task in pending:
                task.cancel()
            if garde in done:
                await self._couper(garde.result())
            elif self.motif_de_fermeture == "farewell":
                # Le client a déjà reçu closed après le dernier son. La
                # connexion peut tomber sans couper sa lecture finale.
                await self._client.close(code=1000, reason="farewell")
            for task in done:
                if task is garde:
                    continue
                exc = task.exception()
                if exc is not None and not isinstance(exc, asyncio.CancelledError):
                    logger.debug("voice live bridge task error: %s", exc, exc_info=exc)
        finally:
            if not garde.done():
                garde.cancel()
            await self._session.close()

    async def _forward_provider_events(self) -> None:
        async for event in self._session.events():
            self._noter(event)
            if event.kind == "closed" and event.detail == "farewell":
                self.motif_de_fermeture = "farewell"
            await self._client.send_json(event_to_client_json(event))
            if event.kind in ("closed", "error"):
                break

    async def _receive_client_messages(self) -> None:
        from fastapi import WebSocketDisconnect

        try:
            while True:
                data = await self._client.receive_json()
                await self._handle_client_message(data)
        except WebSocketDisconnect:
            return
        except Exception:
            logger.debug("client receive ended", exc_info=True)
            return

    async def _handle_client_message(self, data: dict[str, Any]) -> None:
        msg_type = (data.get("type") or "").lower()
        if msg_type == "audio":
            b64 = data.get("data") or ""
            if not b64:
                return
            pcm = b64_to_pcm16(b64)
            rate = int(data.get("sample_rate") or self._client_input_rate)
            if rate != self._session.input_sample_rate:
                pcm = resample_pcm16(pcm, rate, self._session.input_sample_rate)
            await self._session.send_audio(pcm)
        elif msg_type == "text":
            self._entendu()
            await self._session.send_text(str(data.get("text") or ""))
        elif msg_type == "interrupt":
            self._entendu()
            await self._session.interrupt()
        elif msg_type == "stop":
            await self._session.close()
            return
        # "start" is handled by the route before the bridge is created


__all__ = [
    "BATTEMENT_S",
    "DUREE_MAX_S",
    "MOTIF_DUREE",
    "MOTIF_SILENCE",
    "SILENCE_MAX_S",
    "VoiceLiveBridge",
    "event_to_client_json",
]
