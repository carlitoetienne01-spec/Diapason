"""Outils des tests de synchronisation et de pièces (étape 5 du §6).

Les blobs viennent du VRAI client (``diapason.compte.enveloppe``) : si le
serveur refusait la forme de ce que le client scelle — Padmé, plancher,
en-tête —, ces tests le verraient. Le serveur, lui, n'ouvre rien : une DEK
tirée au hasard suffit.
"""

from __future__ import annotations

import os
from typing import Any

from diapason.compte import enveloppe as env
from diapason_comptes.validation import b64url
from tests.diapason_comptes._outils import Inscrit, Service


def nouvel_id() -> str:
    """``objectId`` ou ``pieceId`` : 16 o en base64url, 22 caractères."""
    return b64url(os.urandom(16))


def blob_objet(
    inscrit: Inscrit,
    object_id: str,
    rev: int,
    *,
    key_epoch: int = 1,
    incarnation: int = 1,
    clair: bytes | None = None,
) -> bytes:
    return env.sceller_objet(
        os.urandom(32),
        clair if clair is not None else b'{"v":1,"data":{}}',
        account_id=inscrit.account_id,
        incarnation=incarnation,
        object_id=object_id,
        rev=rev,
        key_epoch=key_epoch,
    )


def blob_piece(
    inscrit: Inscrit, piece_id: str, *, key_epoch: int = 1, taille: int = 100
) -> bytes:
    return env.sceller_piece(
        os.urandom(32),
        os.urandom(taille),
        account_id=inscrit.account_id,
        incarnation=1,
        piece_id=piece_id,
        key_epoch=key_epoch,
    )


def element(object_id: str, base_rev: int, blob: bytes) -> dict[str, Any]:
    return {"objectId": object_id, "baseRev": base_rev, "blob": b64url(blob)}


def pousser(
    service: Service,
    inscrit: Inscrit,
    items: list[dict[str, Any]],
    *,
    incarnation: int = 1,
    key_epoch: int = 1,
    client=None,
):
    return (client or service.client).post(
        "/api/v1/sync/push",
        json={"incarnation": incarnation, "keyEpoch": key_epoch, "items": items},
        headers=inscrit.bearer,
    )


def pousser_un(
    service: Service,
    inscrit: Inscrit,
    object_id: str,
    base_rev: int,
    *,
    key_epoch: int = 1,
    incarnation: int = 1,
) -> dict[str, Any]:
    """Pousse un objet neuf scellé en ``rev = baseRev + 1`` ; rend son issue."""
    blob = blob_objet(
        inscrit, object_id, base_rev + 1, key_epoch=key_epoch, incarnation=incarnation
    )
    r = pousser(
        service,
        inscrit,
        [element(object_id, base_rev, blob)],
        key_epoch=key_epoch,
        incarnation=incarnation,
    )
    assert r.status_code == 200, r.text
    return r.json()["results"][0]


def tirer(service: Service, inscrit: Inscrit, since: int = 0, limit: int | None = None):
    parametres = f"?since={since}" + ("" if limit is None else f"&limit={limit}")
    return service.get("/sync/changes" + parametres, headers=inscrit.bearer)


def reclamer(service: Service, inscrit: Inscrit, ids: list[str], as_of: int):
    return service.post(
        "/pieces/missing",
        {"asOfSeq": as_of, "pieceIds": ids},
        headers=inscrit.bearer,
    )


def deposer(service: Service, inscrit: Inscrit, piece_id: str, blob: bytes):
    return service.client.put(
        f"/api/v1/pieces/{piece_id}",
        content=blob,
        headers={**inscrit.bearer, "Content-Type": "application/octet-stream"},
    )


def marquer(service: Service, inscrit: Inscrit, piece_id: str, as_of: int):
    return service.client.request(
        "DELETE",
        f"/api/v1/pieces/{piece_id}",
        json={"asOfSeq": as_of},
        headers=inscrit.bearer,
    )


def server_seq(service: Service, inscrit: Inscrit) -> int:
    r = tirer(service, inscrit, since=0, limit=1)
    assert r.status_code == 200, r.text
    return r.json()["meta"]["serverSeq"]


def octets_du_compte(service: Service, inscrit: Inscrit) -> int:
    r = service.get("/account", headers=inscrit.bearer)
    assert r.status_code == 200, r.text
    return r.json()["usedBytes"]
