"""Les piles de photos d'un projet Succès.

Une pile est une catégorie (« Python », « Ottawa ») ; une photo appartient à
une pile, porte une légende et peut pointer vers une tâche du projet. Les
octets vivent sur disque, jamais dans SQLite : une base de quelques Mo par
photo aurait fini par ralentir chaque relève du téléphone, qui lit le même
fichier.

Les photos ne passent PAS par le journal d'opérations. Le client Dart
réimplémente l'enveloppe signée avec une liste de champs figée ; y glisser
des images serait exactement le genre d'ajout que `docs/succes-client-mobile.md`
interdit. Une photo est locale à ce Mac, comme le fichier qu'elle est.

Le serveur ne décode aucune image : il n'y a pas Pillow dans ce venv, et un
décodeur d'images est une surface d'attaque qu'on n'ouvre pas pour une
galerie personnelle. C'est le navigateur qui produit l'aperçu, la taille et
la teinte ; le serveur vérifie la signature du fichier et le range.
"""

from __future__ import annotations

import base64
import binascii
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Mapping

from diapason.succes.finances import SuccesFinancesStore
from diapason.succes.store import SuccesError, SuccesNotFound, now_ms

_PHOTOS_SCHEMA = """
CREATE TABLE IF NOT EXISTS succes_photo_piles (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    name TEXT NOT NULL,
    cover_photo_id TEXT NOT NULL DEFAULT '',
    order_index INTEGER NOT NULL DEFAULT 0,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    deleted_at_ms INTEGER
);
CREATE INDEX IF NOT EXISTS succes_photo_piles_project_idx
    ON succes_photo_piles(project_id, deleted_at_ms);
CREATE TABLE IF NOT EXISTS succes_photos (
    id TEXT PRIMARY KEY,
    pile_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    file_name TEXT NOT NULL,
    mime TEXT NOT NULL,
    bytes INTEGER NOT NULL,
    width INTEGER NOT NULL DEFAULT 0,
    height INTEGER NOT NULL DEFAULT 0,
    tint TEXT NOT NULL DEFAULT '',
    caption TEXT NOT NULL DEFAULT '',
    task_id TEXT NOT NULL DEFAULT '',
    position INTEGER NOT NULL DEFAULT 0,
    file_path TEXT NOT NULL,
    thumb_path TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    deleted_at_ms INTEGER
);
CREATE INDEX IF NOT EXISTS succes_photos_pile_idx
    ON succes_photos(pile_id, deleted_at_ms, created_at_ms);
CREATE INDEX IF NOT EXISTS succes_photos_task_idx
    ON succes_photos(project_id, task_id, deleted_at_ms);
"""

# 15 Mo : une photo d'iPhone convertie en JPEG par le navigateur pèse 2 à
# 4 Mo ; un PNG de capture d'écran Retina, 1 à 6 Mo. Le double du pire cas
# laisse passer tout ce qu'on a vu, et arrête un fichier qui n'est pas une
# photo (une vidéo renommée, un export brut).
MAX_PHOTO_BYTES = 15 * 1024 * 1024
# L'aperçu fait 480 px de côté au plus, en JPEG à 0,8 : entre 20 et 60 Ko.
# 512 Ko, c'est dix fois trop — un « aperçu » plus lourd est une photo entière
# qu'un client aurait rangée au mauvais endroit.
MAX_THUMB_BYTES = 512 * 1024
PILE_NAME_MAX = 80
CAPTION_MAX = 500
APERCUS_PAR_PILE = 3
# Un calque d'annotations : 200 formes, 100 Ko de JSON. Une capture annotée
# à la main en compte dix ; au-delà, ce n'est plus une annotation.
ANNOTATIONS_MAX = 200
ANNOTATIONS_OCTETS_MAX = 100 * 1024
TYPES_ANNOTATION = {"arrow", "rect", "ellipse", "text", "highlight", "pen"}
ROTATIONS = {0, 90, 180, 270}
# Le texte lu par l'OCR : borné pour qu'une affiche de 10 000 mots ne fasse
# pas gonfler chaque relève de la liste.
OCR_TEXTE_MAX = 20_000
# Un PDF exporté : 60 Mo, soit une pile de cent captures en JPEG.
EXPORT_OCTETS_MAX = 60 * 1024 * 1024
RECHERCHE_MAX = 200

_EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}


def mime_depuis_signature(data: bytes) -> str:
    """Le type réel du fichier, lu dans ses premiers octets.

    Le type annoncé par le client est une opinion ; la signature est un fait.
    Un `.jpg` qui commence par `<html` n'est pas une image et ne sera pas
    servi comme telle.
    """
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return ""


def decoder_base64(value: str, *, champ: str, maximum: int) -> bytes:
    """Décoder strictement : un caractère hors alphabet est une erreur."""
    brut = value.strip()
    if brut.startswith("data:"):
        # Un client peut envoyer l'URL de données telle quelle ; on ne garde
        # que la charge utile, le type vient de la signature de toute façon.
        brut = brut.partition(",")[2]
    # 4 caractères base64 → 3 octets : borner AVANT de décoder, sinon un
    # corps de 200 Mo est décodé en entier pour être refusé ensuite.
    if len(brut) > maximum * 4 // 3 + 4:
        raise SuccesError(f"{champ} dépasse {maximum // (1024 * 1024) or 1} Mo.")
    try:
        data = base64.b64decode(brut, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SuccesError(f"{champ} n'est pas un base64 valide.") from exc
    if not data:
        raise SuccesError(f"{champ} est vide.")
    if len(data) > maximum:
        raise SuccesError(f"{champ} dépasse {maximum // (1024 * 1024) or 1} Mo.")
    return data


def _teinte(value: Any) -> str:
    """Une couleur `#rrggbb` ou rien — jamais du texte libre dans un style."""
    text = str(value or "").strip().lower()
    if (
        len(text) == 7
        and text[0] == "#"
        and all(c in "0123456789abcdef" for c in text[1:])
    ):
        return text
    return ""


def _json_ou(texte: str, defaut: Any) -> Any:
    if not texte:
        return defaut
    try:
        return json.loads(texte)
    except ValueError:
        # Une colonne corrompue à la main ne doit pas casser toute la liste.
        return defaut


def _nombre_unitaire(value: Any, champ: str) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError) as exc:
        raise SuccesError(f"{champ} doit être un nombre entre 0 et 1.") from exc
    if not (0.0 <= n <= 1.0):
        raise SuccesError(f"{champ} doit être un nombre entre 0 et 1.")
    return round(n, 5)


def valider_cadre(value: Any) -> str:
    """Le cadre de recadrage, en fractions de l'image : `{x, y, w, h}`.

    Vide (``None``) = pas de recadrage. Un cadre plus petit que 2 % de
    l'image est une erreur de manipulation, pas une intention.
    """
    if value is None or value == "":
        return ""
    if not isinstance(value, Mapping):
        raise SuccesError("Le cadre doit être un objet {x, y, w, h}.")
    x = _nombre_unitaire(value.get("x"), "x")
    y = _nombre_unitaire(value.get("y"), "y")
    w = _nombre_unitaire(value.get("w"), "w")
    h = _nombre_unitaire(value.get("h"), "h")
    if w < 0.02 or h < 0.02 or x + w > 1.00001 or y + h > 1.00001:
        raise SuccesError("Le cadre doit rester dans l'image et faire au moins 2 %.")
    return json.dumps({"x": x, "y": y, "w": w, "h": h})


def valider_annotations(value: Any) -> str:
    """Le calque d'annotations : une liste de formes aux coordonnées en fractions."""
    if value is None:
        return ""
    if not isinstance(value, list):
        raise SuccesError("Les annotations doivent être une liste.")
    if len(value) > ANNOTATIONS_MAX:
        raise SuccesError(f"Au plus {ANNOTATIONS_MAX} annotations par photo.")
    propres: list[dict[str, Any]] = []
    for forme in value:
        if not isinstance(forme, Mapping):
            raise SuccesError("Chaque annotation doit être un objet.")
        genre = str(forme.get("type", ""))
        if genre not in TYPES_ANNOTATION:
            raise SuccesError(f"Type d'annotation inconnu : {genre or '(vide)'}.")
        propre: dict[str, Any] = {
            "id": str(forme.get("id") or uuid.uuid4())[:40],
            "type": genre,
            "color": _teinte(forme.get("color")) or "#ff3b30",
        }
        points = forme.get("points")
        if not isinstance(points, list) or len(points) < 1 or len(points) > 2000:
            raise SuccesError("Une annotation a besoin de points.")
        propre["points"] = [
            [_nombre_unitaire(p[0], "x"), _nombre_unitaire(p[1], "y")]
            for p in points
            if isinstance(p, (list, tuple)) and len(p) == 2
        ]
        if not propre["points"]:
            raise SuccesError("Une annotation a besoin de points.")
        if genre == "text":
            propre["text"] = str(forme.get("text") or "")[:300]
        largeur = forme.get("width", 3)
        try:
            propre["width"] = max(1, min(24, int(largeur)))
        except (TypeError, ValueError):
            propre["width"] = 3
        propres.append(propre)
    if not propres:
        return ""
    texte = json.dumps(propres, ensure_ascii=False, separators=(",", ":"))
    if len(texte.encode()) > ANNOTATIONS_OCTETS_MAX:
        raise SuccesError("Le calque d'annotations est trop lourd.")
    return texte


def _data_url(path: Path, mime: str) -> str:
    try:
        return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"
    except OSError:
        # L'aperçu a disparu du disque (nettoyage manuel, disque restauré).
        # Une pile sans image vaut mieux qu'une galerie qui ne s'ouvre plus.
        return ""


class SuccesPhotosStore(SuccesFinancesStore):
    """Piles et photos, rangées sous `<données>/succes-photos/<projet>/`."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        super().__init__(db_path)
        self.photos_dir = self.db_path.parent / "succes-photos"
        with self._connect() as conn:
            conn.executescript(_PHOTOS_SCHEMA)
            self._ensure_photo_columns(conn)
            conn.commit()

    @staticmethod
    def _ensure_photo_columns(conn: sqlite3.Connection) -> None:
        """Migration additive : `position`, ajoutée le 13 septembre 2026.

        Les photos s'ordonnaient par date seulement ; on peut maintenant les
        ranger à la main. Une base créée avant n'a pas la colonne, et
        `CREATE TABLE IF NOT EXISTS` ne l'ajoute pas.
        """
        colonnes = {
            row["name"] for row in conn.execute("PRAGMA table_info(succes_photos)")
        }
        if "position" not in colonnes:
            conn.execute(
                "ALTER TABLE succes_photos ADD COLUMN "
                "position INTEGER NOT NULL DEFAULT 0"
            )
        # Retouche non destructive, annotations et OCR — 13 septembre 2026.
        for nom, definition in (
            ("rotation", "INTEGER NOT NULL DEFAULT 0"),
            ("crop_json", "TEXT NOT NULL DEFAULT ''"),
            ("annotations_json", "TEXT NOT NULL DEFAULT ''"),
            ("ocr_text", "TEXT NOT NULL DEFAULT ''"),
        ):
            if nom not in colonnes:
                conn.execute(f"ALTER TABLE succes_photos ADD COLUMN {nom} {definition}")
        # L'index sur `position` ne peut se créer qu'APRÈS la colonne : mis
        # dans le schéma, il faisait échouer l'ouverture d'une base créée le
        # matin même — le test l'a attrapé avant la base de Carlito.
        conn.execute(
            "CREATE INDEX IF NOT EXISTS succes_photos_ordre_idx "
            "ON succes_photos(pile_id, deleted_at_ms, position, created_at_ms)"
        )

    # ── lecture ────────────────────────────────────────────────────────

    def _pile_row(self, conn: sqlite3.Connection, pile_id: str) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM succes_photo_piles WHERE id=? AND deleted_at_ms IS NULL",
            (pile_id,),
        ).fetchone()
        if row is None:
            raise SuccesNotFound("Cette pile n'existe pas ou a été supprimée.")
        return row

    def _photo_row(self, conn: sqlite3.Connection, photo_id: str) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM succes_photos WHERE id=? AND deleted_at_ms IS NULL",
            (photo_id,),
        ).fetchone()
        if row is None:
            raise SuccesNotFound("Cette photo n'existe pas ou a été supprimée.")
        return row

    def _exiger_projet(self, conn: sqlite3.Connection, project_id: str) -> None:
        if self._load_project(conn, project_id) is None:
            raise SuccesNotFound("Ce projet n'existe pas ou a été supprimé.")

    @staticmethod
    def _photo_dict(row: sqlite3.Row, *, thumb: bool) -> dict[str, Any]:
        photo = {
            "id": row["id"],
            "pileId": row["pile_id"],
            "projectId": row["project_id"],
            "fileName": row["file_name"],
            "mime": row["mime"],
            "bytes": int(row["bytes"]),
            "width": int(row["width"]),
            "height": int(row["height"]),
            "tint": row["tint"],
            "caption": row["caption"],
            "taskId": row["task_id"],
            "position": int(row["position"]),
            "rotation": int(row["rotation"]),
            "crop": _json_ou(row["crop_json"], None),
            "annotations": _json_ou(row["annotations_json"], []),
            "ocrText": row["ocr_text"],
            "createdAtMs": int(row["created_at_ms"]),
            "updatedAtMs": int(row["updated_at_ms"]),
        }
        if thumb:
            photo["thumb"] = _data_url(Path(row["thumb_path"]), "image/jpeg")
        return photo

    def _photos_de_pile(
        self, conn: sqlite3.Connection, pile_id: str, *, limite: int | None = None
    ) -> list[sqlite3.Row]:
        # La position d'abord — celle qu'on a rangée à la main — puis l'ordre
        # d'arrivée. Une photo ajoutée prend `max + 1` et se met À LA FIN :
        # demandé le 13 septembre 2026, « ça doit garder ma préférence et les
        # images récentes doivent s'ajouter à la fin ». Avant, la nouvelle
        # passait devant et décalait tout ce qu'on avait rangé.
        sql = (
            "SELECT * FROM succes_photos WHERE pile_id=? AND deleted_at_ms IS NULL "
            "ORDER BY position ASC, created_at_ms ASC, id ASC"
        )
        if limite is not None:
            sql += f" LIMIT {int(limite)}"
        return conn.execute(sql, (pile_id,)).fetchall()

    def _pile_dict(self, conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM succes_photos WHERE pile_id=? "
            "AND deleted_at_ms IS NULL",
            (row["id"],),
        ).fetchone()["n"]
        # La couverture d'abord, puis les premières de l'ordre : ce sont les trois
        # photos visibles sur la pile fermée.
        apercus: list[sqlite3.Row] = []
        cover_id = row["cover_photo_id"]
        if cover_id:
            cover = conn.execute(
                "SELECT * FROM succes_photos WHERE id=? AND pile_id=? "
                "AND deleted_at_ms IS NULL",
                (cover_id, row["id"]),
            ).fetchone()
            if cover is not None:
                apercus.append(cover)
            else:
                # La couverture a été supprimée : on retombe sur la plus
                # récente plutôt que d'afficher une pile vide.
                cover_id = ""
        for photo in self._photos_de_pile(conn, row["id"], limite=APERCUS_PAR_PILE + 1):
            if len(apercus) >= APERCUS_PAR_PILE:
                break
            if photo["id"] != cover_id:
                apercus.append(photo)
        return {
            "id": row["id"],
            "projectId": row["project_id"],
            "name": row["name"],
            "coverPhotoId": cover_id,
            "tint": apercus[0]["tint"] if apercus else "",
            "count": int(count),
            "apercus": [self._photo_dict(p, thumb=True) for p in apercus],
            "createdAtMs": int(row["created_at_ms"]),
            "updatedAtMs": int(row["updated_at_ms"]),
        }

    def list_photo_piles(self, project_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            self._exiger_projet(conn, project_id)
            rows = conn.execute(
                "SELECT * FROM succes_photo_piles WHERE project_id=? "
                "AND deleted_at_ms IS NULL ORDER BY order_index, created_at_ms",
                (project_id,),
            ).fetchall()
            piles = [self._pile_dict(conn, row) for row in rows]
            par_tache = {
                r["task_id"]: int(r["n"])
                for r in conn.execute(
                    "SELECT task_id, COUNT(*) AS n FROM succes_photos "
                    "WHERE project_id=? AND deleted_at_ms IS NULL AND task_id<>'' "
                    "GROUP BY task_id",
                    (project_id,),
                ).fetchall()
            }
        return {"piles": piles, "parTache": par_tache}

    def list_photos(self, pile_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            pile = self._pile_row(conn, pile_id)
            photos = [
                self._photo_dict(row, thumb=True)
                for row in self._photos_de_pile(conn, pile_id)
            ]
            return {"pile": self._pile_dict(conn, pile), "photos": photos}

    def photo_content(self, photo_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = self._photo_row(conn, photo_id)
        try:
            data = Path(row["file_path"]).read_bytes()
        except OSError as exc:
            raise SuccesNotFound(
                "Le fichier de cette photo n'est plus sur le disque."
            ) from exc
        return {
            "id": row["id"],
            "mime": row["mime"],
            "fileName": row["file_name"],
            "dataBase64": base64.b64encode(data).decode(),
        }

    # ── piles ──────────────────────────────────────────────────────────

    @staticmethod
    def _nom_de_pile(value: Any) -> str:
        name = " ".join(str(value or "").split())
        if not name:
            raise SuccesError("Une pile a besoin d'un nom.")
        if len(name) > PILE_NAME_MAX:
            raise SuccesError(
                f"Le nom d'une pile fait au plus {PILE_NAME_MAX} caractères."
            )
        return name

    def create_photo_pile(self, project_id: str, name: Any) -> dict[str, Any]:
        clean = self._nom_de_pile(name)
        stamp = now_ms()
        with self._transaction() as conn:
            self._exiger_projet(conn, project_id)
            # Deux piles « Python » dans le même projet, c'est une photo qu'on
            # ne retrouve plus. Le doublon se refuse sans tenir compte de la
            # casse, comme on le chercherait.
            doublon = conn.execute(
                "SELECT 1 FROM succes_photo_piles WHERE project_id=? "
                "AND deleted_at_ms IS NULL AND lower(name)=lower(?)",
                (project_id, clean),
            ).fetchone()
            if doublon:
                raise SuccesError(f"Une pile « {clean} » existe déjà dans ce projet.")
            rang = conn.execute(
                "SELECT COALESCE(MAX(order_index), -1) + 1 AS r "
                "FROM succes_photo_piles WHERE project_id=? AND deleted_at_ms IS NULL",
                (project_id,),
            ).fetchone()["r"]
            pile_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO succes_photo_piles "
                "(id, project_id, name, order_index, created_at_ms, updated_at_ms) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (pile_id, project_id, clean, int(rang), stamp, stamp),
            )
            return self._pile_dict(conn, self._pile_row(conn, pile_id))

    def update_photo_pile(
        self, pile_id: str, data: Mapping[str, Any]
    ) -> dict[str, Any]:
        stamp = now_ms()
        with self._transaction() as conn:
            pile = self._pile_row(conn, pile_id)
            fields: dict[str, Any] = {}
            if "name" in data:
                clean = self._nom_de_pile(data["name"])
                doublon = conn.execute(
                    "SELECT 1 FROM succes_photo_piles WHERE project_id=? AND id<>? "
                    "AND deleted_at_ms IS NULL AND lower(name)=lower(?)",
                    (pile["project_id"], pile_id, clean),
                ).fetchone()
                if doublon:
                    raise SuccesError(
                        f"Une pile « {clean} » existe déjà dans ce projet."
                    )
                fields["name"] = clean
            if "coverPhotoId" in data:
                cover = str(data["coverPhotoId"] or "")
                if cover:
                    photo = self._photo_row(conn, cover)
                    if photo["pile_id"] != pile_id:
                        raise SuccesError(
                            "La couverture doit venir de la pile elle-même."
                        )
                fields["cover_photo_id"] = cover
            if fields:
                fields["updated_at_ms"] = stamp
                assignments = ", ".join(f"{k}=?" for k in fields)
                conn.execute(
                    f"UPDATE succes_photo_piles SET {assignments} WHERE id=?",
                    (*fields.values(), pile_id),
                )
            return self._pile_dict(conn, self._pile_row(conn, pile_id))

    def delete_photo_pile(self, pile_id: str) -> int:
        """Supprimer la pile ET ses photos, fichiers compris. Rend le nombre."""
        stamp = now_ms()
        chemins: list[Path] = []
        with self._transaction() as conn:
            self._pile_row(conn, pile_id)
            rows = self._photos_de_pile(conn, pile_id)
            for row in rows:
                chemins.extend((Path(row["file_path"]), Path(row["thumb_path"])))
            conn.execute(
                "UPDATE succes_photos SET deleted_at_ms=?, updated_at_ms=? "
                "WHERE pile_id=? AND deleted_at_ms IS NULL",
                (stamp, stamp, pile_id),
            )
            conn.execute(
                "UPDATE succes_photo_piles SET deleted_at_ms=?, updated_at_ms=? "
                "WHERE id=?",
                (stamp, stamp, pile_id),
            )
        self._effacer(chemins)
        return len(rows)

    # ── photos ─────────────────────────────────────────────────────────

    def _valider_tache(
        self, conn: sqlite3.Connection, project_id: str, task_id: Any
    ) -> str:
        tid = str(task_id or "").strip()
        if not tid:
            return ""
        row = conn.execute(
            "SELECT project_id FROM succes_tasks WHERE id=? AND deleted_at_ms IS NULL",
            (tid,),
        ).fetchone()
        if row is None or row["project_id"] != project_id:
            raise SuccesError("Cette tâche n'appartient pas au projet de la photo.")
        return tid

    @staticmethod
    def _legende(value: Any) -> str:
        caption = str(value or "").strip()
        if len(caption) > CAPTION_MAX:
            raise SuccesError(f"Une légende fait au plus {CAPTION_MAX} caractères.")
        return caption

    def add_photo(self, pile_id: str, data: Mapping[str, Any]) -> dict[str, Any]:
        contenu = decoder_base64(
            str(data.get("dataBase64", "")), champ="La photo", maximum=MAX_PHOTO_BYTES
        )
        mime = mime_depuis_signature(contenu)
        if not mime:
            raise SuccesError(
                "Ce fichier n'est pas une image reconnue (JPEG, PNG, WebP ou GIF)."
            )
        apercu = decoder_base64(
            str(data.get("thumbBase64", "")), champ="L'aperçu", maximum=MAX_THUMB_BYTES
        )
        if mime_depuis_signature(apercu) != "image/jpeg":
            raise SuccesError("L'aperçu doit être un JPEG.")
        width = max(0, int(data.get("width") or 0))
        height = max(0, int(data.get("height") or 0))
        caption = self._legende(data.get("caption"))
        tint = _teinte(data.get("tint"))
        # Le nom sert à l'export et à l'affichage ; il ne touche jamais au
        # chemin sur disque, qui est l'identifiant. Un `../` dans un nom de
        # fichier n'a donc nulle part où aller.
        file_name = " ".join(str(data.get("fileName") or "photo").split())[:160]
        stamp = now_ms()
        photo_id = str(uuid.uuid4())
        with self._transaction() as conn:
            pile = self._pile_row(conn, pile_id)
            project_id = pile["project_id"]
            task_id = self._valider_tache(conn, project_id, data.get("taskId"))
            dossier = self.photos_dir / project_id
            dossier.mkdir(parents=True, exist_ok=True)
            file_path = dossier / f"{photo_id}.{_EXTENSIONS[mime]}"
            thumb_path = dossier / f"{photo_id}.apercu.jpg"
            # Les fichiers d'abord : si le disque refuse, la transaction
            # n'est pas validée et aucune ligne ne pointe vers le vide.
            file_path.write_bytes(contenu)
            thumb_path.write_bytes(apercu)
            position = conn.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM succes_photos "
                "WHERE pile_id=? AND deleted_at_ms IS NULL",
                (pile_id,),
            ).fetchone()["p"]
            conn.execute(
                "INSERT INTO succes_photos (id, pile_id, project_id, file_name, mime, "
                "bytes, width, height, tint, caption, task_id, position, file_path, "
                "thumb_path, created_at_ms, updated_at_ms) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    photo_id,
                    pile_id,
                    project_id,
                    file_name,
                    mime,
                    len(contenu),
                    width,
                    height,
                    tint,
                    caption,
                    task_id,
                    int(position),
                    str(file_path),
                    str(thumb_path),
                    stamp,
                    stamp,
                ),
            )
            conn.execute(
                "UPDATE succes_photo_piles SET updated_at_ms=? WHERE id=?",
                (stamp, pile_id),
            )
            return self._photo_dict(self._photo_row(conn, photo_id), thumb=True)

    def update_photo(self, photo_id: str, data: Mapping[str, Any]) -> dict[str, Any]:
        stamp = now_ms()
        with self._transaction() as conn:
            photo = self._photo_row(conn, photo_id)
            fields: dict[str, Any] = {}
            if "caption" in data:
                fields["caption"] = self._legende(data["caption"])
            if "taskId" in data:
                fields["task_id"] = self._valider_tache(
                    conn, photo["project_id"], data["taskId"]
                )
            if "rotation" in data:
                try:
                    rotation = int(data["rotation"]) % 360
                except (TypeError, ValueError) as exc:
                    raise SuccesError("La rotation vaut 0, 90, 180 ou 270.") from exc
                if rotation not in ROTATIONS:
                    raise SuccesError("La rotation vaut 0, 90, 180 ou 270.")
                fields["rotation"] = rotation
            if "crop" in data:
                fields["crop_json"] = valider_cadre(data["crop"])
            if "annotations" in data:
                fields["annotations_json"] = valider_annotations(data["annotations"])
            if data.get("thumbBase64"):
                # L'aperçu suit la retouche : le client le redessine et
                # l'envoie ; l'original, lui, ne bouge jamais.
                apercu = decoder_base64(
                    str(data["thumbBase64"]), champ="L'aperçu", maximum=MAX_THUMB_BYTES
                )
                if mime_depuis_signature(apercu) != "image/jpeg":
                    raise SuccesError("L'aperçu doit être un JPEG.")
                Path(photo["thumb_path"]).write_bytes(apercu)
                fields["updated_at_ms"] = stamp
            if "pileId" in data:
                cible = self._pile_row(conn, str(data["pileId"]))
                if cible["project_id"] != photo["project_id"]:
                    raise SuccesError("Une photo ne change pas de projet.")
                fields["pile_id"] = cible["id"]
                if cible["id"] != photo["pile_id"]:
                    # Si elle était la couverture de son ancienne pile, celle-ci
                    # retombe sur sa photo la plus récente.
                    conn.execute(
                        "UPDATE succes_photo_piles SET cover_photo_id='' "
                        "WHERE id=? AND cover_photo_id=?",
                        (photo["pile_id"], photo_id),
                    )
            if fields:
                fields["updated_at_ms"] = stamp
                assignments = ", ".join(f"{k}=?" for k in fields)
                conn.execute(
                    f"UPDATE succes_photos SET {assignments} WHERE id=?",
                    (*fields.values(), photo_id),
                )
            return self._photo_dict(self._photo_row(conn, photo_id), thumb=True)

    def reorder_photos(
        self, pile_id: str, photo_ids: list[str]
    ) -> list[dict[str, Any]]:
        """Ranger les photos de la pile dans l'ordre donné, complet ou non.

        Les identifiants absents de la liste gardent leur ordre relatif et
        passent après. Un identifiant d'une autre pile est une erreur : on
        ne déplace pas une photo en la « rangeant ».
        """
        stamp = now_ms()
        with self._transaction() as conn:
            self._pile_row(conn, pile_id)
            actuelles = [row["id"] for row in self._photos_de_pile(conn, pile_id)]
            connues = set(actuelles)
            vus: set[str] = set()
            ordre: list[str] = []
            for pid in photo_ids:
                pid = str(pid)
                if pid not in connues:
                    raise SuccesError("Cette photo n'est pas dans la pile.")
                if pid in vus:
                    continue
                vus.add(pid)
                ordre.append(pid)
            ordre.extend(pid for pid in actuelles if pid not in vus)
            for index, pid in enumerate(ordre):
                conn.execute(
                    "UPDATE succes_photos SET position=?, updated_at_ms=? WHERE id=?",
                    (index, stamp, pid),
                )
            conn.execute(
                "UPDATE succes_photo_piles SET updated_at_ms=? WHERE id=?",
                (stamp, pile_id),
            )
            return [
                self._photo_dict(row, thumb=False)
                for row in self._photos_de_pile(conn, pile_id)
            ]

    def set_photo_ocr(self, photo_id: str, texte: str) -> dict[str, Any]:
        propre = " ".join(str(texte or "").split())[:OCR_TEXTE_MAX]
        stamp = now_ms()
        with self._transaction() as conn:
            self._photo_row(conn, photo_id)
            conn.execute(
                "UPDATE succes_photos SET ocr_text=?, updated_at_ms=? WHERE id=?",
                (propre, stamp, photo_id),
            )
            return self._photo_dict(self._photo_row(conn, photo_id), thumb=True)

    def search_photos(self, project_id: str, query: str) -> list[dict[str, Any]]:
        """Les photos dont la légende, le nom ou le texte lu contient `query`."""
        mots = [m for m in " ".join(str(query or "").split()).lower().split(" ") if m]
        if not mots:
            return []
        with self._connect() as conn:
            self._exiger_projet(conn, project_id)
            # Chaque mot doit apparaître quelque part ; l'ordre n'importe pas.
            conditions = " AND ".join(
                "(instr(lower(caption), ?) > 0 OR instr(lower(file_name), ?) > 0 "
                "OR instr(lower(ocr_text), ?) > 0)"
                for _ in mots
            )
            params: list[Any] = []
            for mot in mots:
                params.extend((mot, mot, mot))
            rows = conn.execute(
                "SELECT ph.*, pi.name AS pile_name FROM succes_photos ph "
                "JOIN succes_photo_piles pi ON pi.id = ph.pile_id "
                "WHERE ph.project_id=? AND ph.deleted_at_ms IS NULL "
                f"AND pi.deleted_at_ms IS NULL AND {conditions} "
                "ORDER BY pi.order_index, ph.position, ph.created_at_ms DESC "
                f"LIMIT {RECHERCHE_MAX}",
                (project_id, *params),
            ).fetchall()
            return [
                {**self._photo_dict(row, thumb=True), "pileName": row["pile_name"]}
                for row in rows
            ]

    @staticmethod
    def write_export(chemin: Any, data_base64: str) -> dict[str, Any]:
        """Écrire un export (PDF) là où l'utilisateur l'a demandé.

        Le chemin vient du dialogue « Enregistrer sous » de l'app ; on refuse
        tout de même ce qui sort du dossier personnel, et tout ce qui n'est
        pas un `.pdf` : une route qui écrit n'importe où est une route qui
        écrira un jour dans `~/Library`.
        """
        cible = Path(str(chemin or "")).expanduser()
        if not cible.is_absolute() or cible.suffix.lower() != ".pdf":
            raise SuccesError("L'export doit être un fichier .pdf à un chemin complet.")
        maison = Path.home().resolve()
        try:
            resolu = cible.parent.resolve(strict=True)
        except OSError as exc:
            raise SuccesError("Ce dossier n'existe pas.") from exc
        if maison != resolu and maison not in resolu.parents:
            raise SuccesError("L'export ne s'écrit que dans ton dossier personnel.")
        data = decoder_base64(
            data_base64, champ="Le fichier", maximum=EXPORT_OCTETS_MAX
        )
        if data[:5] != b"%PDF-":
            raise SuccesError("Ce fichier n'est pas un PDF.")
        (resolu / cible.name).write_bytes(data)
        return {"path": str(resolu / cible.name), "bytes": len(data)}

    def delete_photo(self, photo_id: str) -> None:
        stamp = now_ms()
        with self._transaction() as conn:
            photo = self._photo_row(conn, photo_id)
            conn.execute(
                "UPDATE succes_photos SET deleted_at_ms=?, updated_at_ms=? WHERE id=?",
                (stamp, stamp, photo_id),
            )
            conn.execute(
                "UPDATE succes_photo_piles SET cover_photo_id='', updated_at_ms=? "
                "WHERE id=? AND cover_photo_id=?",
                (stamp, photo["pile_id"], photo_id),
            )
            chemins = [Path(photo["file_path"]), Path(photo["thumb_path"])]
        self._effacer(chemins)

    @staticmethod
    def _effacer(chemins: list[Path]) -> None:
        for chemin in chemins:
            try:
                chemin.unlink()
            except FileNotFoundError:
                continue
            except OSError:
                # Un fichier verrouillé ne doit pas faire échouer une
                # suppression déjà validée en base : la ligne est partie,
                # l'orphelin sur disque est un détail de nettoyage.
                continue

    # ── cascade ────────────────────────────────────────────────────────

    def delete_project(self, project_id: str, *, op_id: str | None = None) -> None:
        super().delete_project(project_id, op_id=op_id)
        # Les lignes suivent le projet ; les fichiers restent sur le disque.
        # Un projet supprimé par erreur se recrée, ses photos ne se
        # reprennent pas — on ne détruit pas des images sur une soft-delete.
        stamp = now_ms()
        with self._transaction() as conn:
            conn.execute(
                "UPDATE succes_photos SET deleted_at_ms=?, updated_at_ms=? "
                "WHERE project_id=? AND deleted_at_ms IS NULL",
                (stamp, stamp, project_id),
            )
            conn.execute(
                "UPDATE succes_photo_piles SET deleted_at_ms=?, updated_at_ms=? "
                "WHERE project_id=? AND deleted_at_ms IS NULL",
                (stamp, stamp, project_id),
            )


__all__ = [
    "ANNOTATIONS_MAX",
    "APERCUS_PAR_PILE",
    "CAPTION_MAX",
    "MAX_PHOTO_BYTES",
    "MAX_THUMB_BYTES",
    "PILE_NAME_MAX",
    "SuccesPhotosStore",
    "decoder_base64",
    "mime_depuis_signature",
    "valider_annotations",
    "valider_cadre",
]
