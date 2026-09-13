"""Les routes des piles de photos d'un projet Succès.

Les corps voyagent en JSON base64, jamais en multipart : la fenêtre Tauri
(WKWebView) échoue sur un `Blob` ou un `ArrayBuffer` avec un « Load failed »
opaque — piège déjà payé, consigné dans CLAUDE.md.

Les routes qui lisent ou écrivent des fichiers sont des `def` synchrones,
que Starlette exécute dans un fil. En `async def`, un `write_bytes` de 10 Mo
s'exécuterait sur la boucle d'événements et figerait le WebSocket vocal le
temps de l'écriture.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from diapason.succes.corps import DeleteBody
from diapason.succes.photos import (
    CAPTION_MAX,
    MAX_PHOTO_BYTES,
    MAX_THUMB_BYTES,
    PILE_NAME_MAX,
    SuccesPhotosStore,
)
from diapason.succes.store import SuccesError

logger = logging.getLogger(__name__)

# Les modèles vivent au niveau du module — voir `corps.py` pour la raison :
# une classe locale à la fonction d'enregistrement casse `/openapi.json`.


class PileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=PILE_NAME_MAX)


class PilePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=PILE_NAME_MAX)
    coverPhotoId: str | None = Field(default=None, max_length=80)


class PhotoCreate(BaseModel):
    fileName: str = Field(default="photo", max_length=160)
    # Base64 de la photo ; 4/3 de la taille décodée, plus la marge du remplissage.
    dataBase64: str = Field(min_length=4, max_length=MAX_PHOTO_BYTES * 4 // 3 + 4)
    # L'aperçu JPEG produit par le navigateur (≤ 480 px de côté).
    thumbBase64: str = Field(min_length=4, max_length=MAX_THUMB_BYTES * 4 // 3 + 4)
    width: int = Field(default=0, ge=0, le=100_000)
    height: int = Field(default=0, ge=0, le=100_000)
    tint: str = Field(default="", max_length=7)
    caption: str = Field(default="", max_length=CAPTION_MAX)
    taskId: str = Field(default="", max_length=80)


class PhotoOrder(BaseModel):
    photoIds: list[str] = Field(min_length=1, max_length=5000)


class PhotoPatch(BaseModel):
    caption: str | None = Field(default=None, max_length=CAPTION_MAX)
    taskId: str | None = Field(default=None, max_length=80)
    pileId: str | None = Field(default=None, min_length=1, max_length=80)
    rotation: int | None = None
    # `crop: {}` ou `null` explicite efface le cadre ; absent = inchangé.
    # Pydantic confond « absent » et « None » avec `exclude_none` : on passe
    # par un drapeau à part.
    crop: dict[str, Any] | None = None
    effacerCadre: bool = False
    annotations: list[dict[str, Any]] | None = None
    thumbBase64: str | None = Field(
        default=None, min_length=4, max_length=MAX_THUMB_BYTES * 4 // 3 + 4
    )


class ExportBody(BaseModel):
    path: str = Field(min_length=5, max_length=1000)
    dataBase64: str = Field(min_length=8, max_length=60 * 1024 * 1024 * 4 // 3 + 4)


def register_photos_routes(router: APIRouter, *, get_store, domain_error) -> None:
    """Poser les routes des photos sur le routeur de Succès."""

    def _photos() -> SuccesPhotosStore:
        store = get_store()
        if not isinstance(store, SuccesPhotosStore):
            raise HTTPException(
                status_code=503, detail="Le module Photos n'est pas disponible."
            )
        return store

    def _confirmer(body: DeleteBody, message: str) -> None:
        if not body.confirmed:
            raise HTTPException(
                status_code=409,
                detail={"code": "confirmation_required", "message": message},
            )

    @router.get("/projects/{project_id}/photo-piles")
    def list_photo_piles(project_id: str) -> dict[str, Any]:
        try:
            return {**_photos().list_photo_piles(project_id), "persistence": "local"}
        except SuccesError as exc:
            raise domain_error(exc) from exc

    @router.post("/projects/{project_id}/photo-piles", status_code=201)
    def create_photo_pile(project_id: str, body: PileCreate) -> dict[str, Any]:
        try:
            pile = _photos().create_photo_pile(project_id, body.name)
        except SuccesError as exc:
            raise domain_error(exc) from exc
        return {"pile": pile, "persistence": "local"}

    @router.patch("/photo-piles/{pile_id}")
    def update_photo_pile(pile_id: str, body: PilePatch) -> dict[str, Any]:
        try:
            pile = _photos().update_photo_pile(
                pile_id, body.model_dump(exclude_none=True)
            )
        except SuccesError as exc:
            raise domain_error(exc) from exc
        return {"pile": pile, "persistence": "local"}

    @router.delete("/photo-piles/{pile_id}")
    def delete_photo_pile(pile_id: str, body: DeleteBody) -> dict[str, Any]:
        _confirmer(body, "Confirmez la suppression de cette pile et de ses photos.")
        try:
            count = _photos().delete_photo_pile(pile_id)
        except SuccesError as exc:
            raise domain_error(exc) from exc
        return {"deleted": True, "id": pile_id, "photos": count, "persistence": "local"}

    @router.get("/photo-piles/{pile_id}/photos")
    def list_photos(pile_id: str) -> dict[str, Any]:
        try:
            return {**_photos().list_photos(pile_id), "persistence": "local"}
        except SuccesError as exc:
            raise domain_error(exc) from exc

    @router.post("/photo-piles/{pile_id}/photos", status_code=201)
    def add_photo(pile_id: str, body: PhotoCreate) -> dict[str, Any]:
        try:
            photo = _photos().add_photo(pile_id, body.model_dump())
        except SuccesError as exc:
            raise domain_error(exc) from exc
        return {"photo": photo, "persistence": "local"}

    @router.put("/photo-piles/{pile_id}/ordre")
    def reorder_photos(pile_id: str, body: PhotoOrder) -> dict[str, Any]:
        try:
            photos = _photos().reorder_photos(pile_id, body.photoIds)
        except SuccesError as exc:
            raise domain_error(exc) from exc
        return {"photos": photos, "persistence": "local"}

    @router.get("/photos/{photo_id}/contenu")
    def photo_content(photo_id: str) -> dict[str, Any]:
        try:
            return _photos().photo_content(photo_id)
        except SuccesError as exc:
            raise domain_error(exc) from exc

    @router.patch("/photos/{photo_id}")
    def update_photo(photo_id: str, body: PhotoPatch) -> dict[str, Any]:
        data = body.model_dump(exclude_none=True, exclude={"effacerCadre"})
        if body.effacerCadre:
            data["crop"] = None
        try:
            photo = _photos().update_photo(photo_id, data)
        except SuccesError as exc:
            raise domain_error(exc) from exc
        return {"photo": photo, "persistence": "local"}

    @router.post("/photos/{photo_id}/ocr")
    def ocr_photo(photo_id: str) -> dict[str, Any]:
        """Lire le texte de la photo avec Vision (macOS), et le garder."""
        from diapason.desktop.ocr import ocr_available, recognize_text

        if not ocr_available():
            raise HTTPException(
                status_code=503,
                detail="La lecture de texte (Vision) n'est pas disponible ici.",
            )
        try:
            contenu = _photos().photo_content(photo_id)
        except SuccesError as exc:
            raise domain_error(exc) from exc
        magasin = _photos()
        with magasin._connect() as conn:
            row = magasin._photo_row(conn, photo_id)
        try:
            lignes = recognize_text(row["file_path"])
        except Exception as exc:  # noqa: BLE001 — Vision parle en NSError
            logger.warning("OCR impossible sur %s : %s", contenu["fileName"], exc)
            raise HTTPException(
                status_code=502, detail="La lecture de texte a échoué sur cette photo."
            ) from exc
        texte = "\n".join(ligne["text"] for ligne in lignes)
        try:
            photo = magasin.set_photo_ocr(photo_id, texte)
        except SuccesError as exc:
            raise domain_error(exc) from exc
        return {"photo": photo, "lignes": len(lignes), "persistence": "local"}

    @router.get("/projects/{project_id}/photos/recherche")
    def search_photos(project_id: str, q: str = "") -> dict[str, Any]:
        try:
            photos = _photos().search_photos(project_id, q)
        except SuccesError as exc:
            raise domain_error(exc) from exc
        return {"photos": photos, "count": len(photos)}

    @router.post("/photos/exporter")
    def export_file(body: ExportBody) -> dict[str, Any]:
        try:
            return {
                **_photos().write_export(body.path, body.dataBase64),
                "persistence": "local",
            }
        except SuccesError as exc:
            raise domain_error(exc) from exc

    @router.delete("/photos/{photo_id}")
    def delete_photo(photo_id: str, body: DeleteBody) -> dict[str, Any]:
        _confirmer(body, "Confirmez la suppression de cette photo.")
        try:
            _photos().delete_photo(photo_id)
        except SuccesError as exc:
            raise domain_error(exc) from exc
        return {"deleted": True, "id": photo_id, "persistence": "local"}


__all__ = ["register_photos_routes"]
