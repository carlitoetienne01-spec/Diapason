"""Un seul ouvrier Orion au repos, sans séance ni accès au microphone."""

from __future__ import annotations

import asyncio
from weakref import WeakKeyDictionary

# 27/09/2026 : rouvrir immédiatement coûtait encore 3,4–3,6 s, car Orion
# mourait à chaque fermeture. Deux minutes couvrent une courte pause, puis
# rendent sa mémoire au Mac ; aucune synthèse ne tourne pendant ce repos.
REPOS_MAX_S = 120.0


async def arreter_processus(processus: asyncio.subprocess.Process) -> None:
    if processus.returncode is None:
        try:
            processus.kill()
        except ProcessLookupError:
            pass
    await processus.wait()


class ReserveOrion:
    def __init__(self) -> None:
        self._libre: tuple[str, asyncio.subprocess.Process] | None = None
        self._expiration: asyncio.TimerHandle | None = None
        self._arrets: set[asyncio.Task] = set()

    def prendre(self, voix: str) -> asyncio.subprocess.Process | None:
        libre, self._libre = self._libre, None
        if self._expiration is not None:
            self._expiration.cancel()
            self._expiration = None
        if libre is None:
            return None
        timbre, processus = libre
        if timbre == voix and processus.returncode is None:
            return processus
        self._arreter_plus_tard(processus)
        return None

    async def garder(self, voix: str, processus: asyncio.subprocess.Process) -> None:
        if self._libre is not None or processus.returncode is not None:
            await arreter_processus(processus)
            return
        self._libre = (voix, processus)
        self._expiration = asyncio.get_running_loop().call_later(
            REPOS_MAX_S, self._expirer
        )

    def _arreter_plus_tard(self, processus: asyncio.subprocess.Process) -> None:
        tache = asyncio.create_task(arreter_processus(processus))
        self._arrets.add(tache)
        tache.add_done_callback(self._arrets.discard)

    def _expirer(self) -> None:
        libre, self._libre = self._libre, None
        self._expiration = None
        if libre is not None:
            self._arreter_plus_tard(libre[1])

    async def fermer(self) -> None:
        if self._expiration is not None:
            self._expiration.cancel()
        self._expirer()
        if self._arrets:
            await asyncio.gather(*self._arrets)


# Les processus asyncio appartiennent à leur boucle. Les serveurs de test
# n'empruntent jamais les tubes d'un autre serveur ou d'une boucle fermée.
_RESERVES: WeakKeyDictionary[asyncio.AbstractEventLoop, ReserveOrion] = (
    WeakKeyDictionary()
)


def reserve_orion() -> ReserveOrion:
    boucle = asyncio.get_running_loop()
    if boucle not in _RESERVES:
        _RESERVES[boucle] = ReserveOrion()
    return _RESERVES[boucle]


async def fermer_reserve_orion() -> None:
    reserve = _RESERVES.pop(asyncio.get_running_loop(), None)
    if reserve is not None:
        await reserve.fermer()
