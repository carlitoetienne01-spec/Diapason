"""Une seule inférence STT, y compris après l'annulation de son attente."""

from __future__ import annotations

import asyncio
import itertools
import logging
import time
from typing import Callable

logger = logging.getLogger(__name__)


class TranscriptionSerie:
    """Le tour final attend le calcul actif, pas une mêlée de partiels."""

    def __init__(
        self,
        transcrire: Callable[[bytes], str],
        *,
        partiel: Callable[[bytes], str] | None = None,
    ) -> None:
        self._transcrire = transcrire
        self._partiel = partiel or transcrire
        self._condition = asyncio.Condition()
        self._attente: list[tuple[int, int]] = []
        self._rangs = itertools.count()
        self._actif = False

    async def __call__(self, audio: bytes, *, etape: str = "final") -> str:
        demande = time.monotonic()
        # 27/09/2026 : la file FIFO faisait passer les sous-titres anciens
        # avant une phrase complète. Le calcul DÉJÀ actif finit réellement ;
        # seuls ceux qui attendent se réordonnent (final, spéculation, partiel).
        ticket = (
            {"final": 0, "speculative": 1, "partial": 2}.get(etape, 0),
            next(self._rangs),
        )
        async with self._condition:
            self._attente.append(ticket)
            try:
                await self._condition.wait_for(
                    lambda: not self._actif and min(self._attente) == ticket
                )
                self._actif = True
            finally:
                self._attente.remove(ticket)
                self._condition.notify_all()

        # 27/09/2026 : annuler to_thread n'arrête pas Whisper. Les partiels
        # abandonnés continuaient sur le CPU pendant le calcul final. Le
        # verrou reste pris jusqu'à la FIN réelle, sans bloquer le micro.
        def transcrire() -> str:
            debut = time.monotonic()
            try:
                fonction = self._partiel if etape == "partial" else self._transcrire
                return fonction(audio)
            finally:
                # 27/09/2026 : 6,41 s « STT » dans l'app contre environ
                # 1 s par calcul isolé. Le total masquait l'attente d'un
                # partiel ; mesurer sa FIN native, même après annulation.
                # Aucun texte ni enregistrement de parole au journal.
                logger.info(
                    "local voice timing: stage=stt_compute kind=%s "
                    "queue_ms=%.0f compute_ms=%.0f audio_bytes=%d",
                    etape,
                    (debut - demande) * 1000,
                    (time.monotonic() - debut) * 1000,
                    len(audio),
                )

        calcul = asyncio.create_task(asyncio.to_thread(transcrire))
        try:
            return await asyncio.shield(calcul)
        finally:
            if calcul.done():
                await self._liberer(calcul)
            else:
                calcul.add_done_callback(
                    lambda fini: asyncio.create_task(self._liberer(fini))
                )

    async def _liberer(self, calcul: asyncio.Task[str]) -> None:
        if not calcul.cancelled():
            calcul.exception()  # une erreur après abandon est tout de même lue
        async with self._condition:
            self._actif = False
            self._condition.notify_all()
