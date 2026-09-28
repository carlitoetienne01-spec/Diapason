"""La voix masculine locale, lue dans un processus MLX isolé."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import platform
import time
from pathlib import Path
from typing import AsyncIterator

from diapason.core.paths import get_config_dir
from diapason.speech.realtime.reserve_orion import arreter_processus, reserve_orion

VOIX_MASCULINE = "qwen3-b"
VOIX_EXPRESSIVES = (VOIX_MASCULINE,)
logger = logging.getLogger(__name__)


def dossier_moteur() -> Path:
    return get_config_dir() / "voices" / "qwen3"


def moteur_installe() -> bool:
    dossier = dossier_moteur()
    return (
        platform.system() == "Darwin"
        and platform.machine() == "arm64"
        and (dossier / "runtime/bin/python").is_file()
        and (dossier / "model/config.json").is_file()
        and (dossier / "model/model.safetensors").is_file()
        and (dossier / "model/speech_tokenizer/model.safetensors").is_file()
        and (dossier / "installed.json").is_file()
    )


def voix_disponibles() -> list[str]:
    return list(VOIX_EXPRESSIVES) if moteur_installe() else []


def voix_configuree(repli: str = "") -> str:
    # 27/09/2026 : Carlito retire A et la voix classique. Une ancienne
    # configuration, ou une fenêtre restée ouverte, ne doit pas les rétablir.
    return VOIX_MASCULINE


def normaliser_voix(voix: str) -> str:
    if voix in ("", "qwen3-a", "ff_siwis", VOIX_MASCULINE):
        return VOIX_MASCULINE
    raise ValueError("Cette voix n’est pas disponible dans Parler.")


class VoixExpressive:
    """Une séance possède seule son ouvrier ; annuler détruit le calcul."""

    # L'ouvrier publie des préfixes du décodeur complet, avec une réserve
    # mesurée. Le serveur ne doit pas les retenir jusqu'à la fin de phrase.
    lecture_anticipee = True

    def __init__(self, voix: str, *, conserver_au_repos: bool = False) -> None:
        if voix not in VOIX_EXPRESSIVES:
            raise ValueError("Voix expressive inconnue")
        self.voix = voix
        self._processus: asyncio.subprocess.Process | None = None
        self._verrou = asyncio.Lock()
        self._fermee = False
        self._pretee = False
        self._conserver_au_repos = conserver_au_repos

    async def _lire(self) -> dict:
        assert self._processus is not None and self._processus.stdout is not None
        # 90 s couvrent le premier chargement Metal sur une machine occupée ;
        # une panne ne doit pas laisser le micro attendre indéfiniment.
        ligne = await asyncio.wait_for(self._processus.stdout.readline(), 90)
        if not ligne:
            raise RuntimeError("Le moteur vocal local s’est arrêté.")
        trame = json.loads(ligne)
        if not isinstance(trame, dict):
            raise RuntimeError("Réponse du moteur vocal invalide.")
        if trame.get("type") == "error":
            raise RuntimeError("La synthèse vocale locale a échoué.")
        return trame

    async def _demarrer(self) -> None:
        if self._fermee:
            raise RuntimeError("La session vocale est fermée.")
        if self._processus is not None and self._processus.returncode is None:
            return
        self._pretee = False
        if self._conserver_au_repos:
            self._processus = reserve_orion().prendre(self.voix)
            if self._processus is not None:
                self._pretee = True
                return
        if not moteur_installe():
            raise RuntimeError("Cette voix n’est pas installée sur ce Mac.")
        dossier = dossier_moteur()
        env = {
            **os.environ,
            "HF_HUB_OFFLINE": "1",
            "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
        }
        self._processus = await asyncio.create_subprocess_exec(
            str(dossier / "runtime/bin/python"),
            "-u",
            str(Path(__file__).with_name("ouvrier_voix.py")),
            str(dossier / "model"),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=env,
            limit=256 * 1024,
        )
        if self._fermee:
            await self.annuler()
            raise RuntimeError("La session vocale est fermée.")
        if (await self._lire()).get("type") != "ready":
            raise RuntimeError("Le moteur vocal n’est pas prêt.")

    async def preparer(self) -> None:
        debut = time.monotonic()
        repris = False
        try:
            async with self._verrou:
                await self._demarrer()
                if self._pretee:
                    # Un PID vivant ne prouve pas que l'ouvrier répond encore.
                    # La sonde ne synthétise rien ; deux secondes bornent un
                    # tube bloqué avant de repartir sur un ouvrier neuf.
                    try:
                        async with asyncio.timeout(2):
                            assert self._processus is not None
                            assert self._processus.stdin is not None
                            self._processus.stdin.write(b'{"type":"ping"}\n')
                            await self._processus.stdin.drain()
                            if (await self._lire()).get("type") != "ready":
                                raise RuntimeError("Orion ne répond plus.")
                        repris = True
                    except (OSError, RuntimeError, ValueError, TimeoutError):
                        await self.annuler()
            if not repris:
                await self._prechauffer()
                self._pretee = True
        except BaseException:
            await self.annuler()
            raise
        logger.info(
            "local voice timing: stage=orion_warm reused=%d ms=%.0f",
            repris,
            (time.monotonic() - debut) * 1000,
        )

    async def _prechauffer(self) -> None:
        # 27/09/2026 : « Bonjour » n'atteint pas les 16 codes du premier
        # préfixe. Il ne préparait donc pas ce chemin avant l'écoute.
        # Cette phrase n'est jamais jouée ni ajoutée à la conversation.
        async for _ in self.morceaux(
            "Cette voix est prête pour une conversation claire et naturelle."
        ):
            pass

    async def morceaux(self, texte: str) -> AsyncIterator[bytes]:
        async with self._verrou:
            fini = False
            try:
                await self._demarrer()
                assert self._processus is not None and self._processus.stdin is not None
                requete = json.dumps(
                    {"voice": self.voix, "text": texte}, ensure_ascii=False
                )
                self._processus.stdin.write((requete + "\n").encode())
                await self._processus.stdin.drain()
                # 120 s bornent une phrase, même si le moteur produit une
                # répétition infinie. Le délai tue sa suite et ne déclare
                # jamais la phrase entière réussie après un préfixe joué.
                async with asyncio.timeout(120):
                    while True:
                        trame = await self._lire()
                        if trame.get("type") == "done":
                            fini = True
                            return
                        if (
                            trame.get("type") != "audio"
                            or trame.get("sampleRate") != 24000
                        ):
                            raise RuntimeError("Format audio local invalide.")
                        mesures = trame.get("timing") or {}
                        if mesures:
                            logger.info(
                                "local voice timing: stage=orion_prefix "
                                "mode=%s ms=%d next_ms=%d prepare_ms=%d "
                                "first_code_ms=%d decode_ms=%d",
                                "prefix"
                                if mesures.get("mode") == "prefix"
                                else "complete",
                                int(mesures.get("prefixMs", 0)),
                                int(mesures.get("nextMs", 0)),
                                int(mesures.get("prepareMs", 0)),
                                int(mesures.get("firstCodeMs", 0)),
                                int(mesures.get("decodeMs", 0)),
                            )
                        pcm = base64.b64decode(trame.get("data", ""), validate=True)
                        if not pcm or len(pcm) % 2 or len(pcm) > 192000:
                            raise RuntimeError("Morceau audio local invalide.")
                        yield pcm
            finally:
                # En fermeture anticipée/erreur, aucune fin de phrase ancienne
                # ne doit devenir le début de la prochaine requête.
                if not fini:
                    await self.annuler()

    async def annuler(self) -> None:
        self._pretee = False
        processus, self._processus = self._processus, None
        if processus is not None:
            await arreter_processus(processus)

    async def fermer(self) -> None:
        self._fermee = True
        if (
            self._conserver_au_repos
            and self._pretee
            and not self._verrou.locked()
            and self._processus is not None
        ):
            processus, self._processus = self._processus, None
            self._pretee = False
            await reserve_orion().garder(self.voix, processus)
            return
        await self.annuler()
