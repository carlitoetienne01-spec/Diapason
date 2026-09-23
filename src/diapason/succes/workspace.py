"""Projects, habits and notes for the native Succès workspace.

The phase-two entities use the same local-first operation log as tasks.  They
stay on the Mac, keep tombstones for later replication, and materialize data
that phase one deliberately preserved inside archived Life OS snapshots.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping

from diapason.succes import reseau as reseau_module
from diapason.succes.dates import normalize_time
from diapason.succes.project_kits import (
    get_project_kit,
    normalize_structure,
)
from diapason.succes.store import (
    SuccesError,
    SuccesNoteConflict,
    SuccesNotFound,
    SuccesStore,
    _clean_text,
    _safe_timestamp,
    _validate_iso_date,
    now_ms,
)
from diapason.succes.structures import (
    decode_structure_config,
    encode_structure_config,
    normalize_structure_config,
    stages_of,
)

HABIT_FREQUENCIES = frozenset({"daily", "weekly", "monthly"})
_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

_WORKSPACE_SCHEMA = """
CREATE TABLE IF NOT EXISTS succes_habits (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    icon TEXT NOT NULL DEFAULT '',
    color TEXT NOT NULL DEFAULT '#6366f1',
    frequency TEXT NOT NULL DEFAULT 'daily',
    created_date TEXT NOT NULL,
    start_date TEXT NOT NULL DEFAULT '',
    end_date TEXT NOT NULL DEFAULT '',
    weekly_days_json TEXT NOT NULL DEFAULT '[]',
    month_week_slots_json TEXT NOT NULL DEFAULT '[]',
    month_week_day INTEGER NOT NULL DEFAULT 1,
    reminder_time TEXT NOT NULL DEFAULT '',
    updated_at_ms INTEGER NOT NULL,
    deleted_at_ms INTEGER
);
CREATE INDEX IF NOT EXISTS succes_habits_active_idx
    ON succes_habits(deleted_at_ms, updated_at_ms);
CREATE TABLE IF NOT EXISTS succes_habit_logs (
    habit_id TEXT NOT NULL REFERENCES succes_habits(id),
    log_date TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,
    updated_at_ms INTEGER NOT NULL,
    PRIMARY KEY(habit_id, log_date)
);
CREATE INDEX IF NOT EXISTS succes_habit_logs_date_idx
    ON succes_habit_logs(log_date, done);
CREATE TABLE IF NOT EXISTS succes_notes (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    deleted_at_ms INTEGER,
    page_format TEXT NOT NULL DEFAULT 'a4',
    page_size TEXT NOT NULL DEFAULT 'a4',
    page_orientation TEXT NOT NULL DEFAULT 'portrait',
    page_margins TEXT NOT NULL DEFAULT 'normales',
    page_background TEXT NOT NULL DEFAULT 'default',
    font_family TEXT NOT NULL DEFAULT 'Special Elite',
    doc_lang TEXT NOT NULL DEFAULT 'fr',
    color TEXT NOT NULL DEFAULT '#6366f1',
    reading_mark INTEGER NOT NULL DEFAULT 0,
    category TEXT NOT NULL DEFAULT '',
    project_id TEXT NOT NULL DEFAULT '',
    order_index INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS succes_notes_active_idx
    ON succes_notes(deleted_at_ms, updated_at_ms DESC);
CREATE TABLE IF NOT EXISTS succes_note_categories (
    name TEXT PRIMARY KEY,
    order_index INTEGER NOT NULL DEFAULT 0,
    updated_at_ms INTEGER NOT NULL DEFAULT 0
);
PRAGMA user_version = 3;
"""

NOTE_PAGE_FORMATS = frozenset(
    {"a4", "letter", "a5", "wide", "narrow", "full", "reading"}
)
# Les trois axes de « Mise en page » de Word, que la liste ci-dessus
# mélangeait : « A4 » est un papier, « Marges minimales » un réglage de
# marges, « A4 paysage » une orientation. On ne pouvait donc ni mettre une A5
# en paysage, ni savoir sur quel papier « marges minimales » s'appliquait.
NOTE_PAGE_SIZES = frozenset({"a4", "letter", "legal", "a5", "executive"})
NOTE_PAGE_ORIENTATIONS = frozenset({"portrait", "paysage"})
NOTE_PAGE_MARGINS = frozenset({"normales", "etroites", "moderees", "larges"})

# Comment se relit une note écrite avant la séparation. Deux des sept valeurs
# n'existaient chez Word sous aucune forme — « A5 » portait 15 mm de marges et
# « Lecture » 32 mm — et deviennent le préréglage le plus proche.
_FORMAT_HERITE: dict[str, tuple[str, str, str]] = {
    "a4": ("a4", "portrait", "normales"),
    "letter": ("letter", "portrait", "normales"),
    "a5": ("a5", "portrait", "normales"),
    "wide": ("a4", "paysage", "normales"),
    "narrow": ("executive", "portrait", "moderees"),
    "full": ("a4", "portrait", "etroites"),
    "reading": ("a4", "portrait", "larges"),
}


def _axes_de_page(row: Any, keys: Any) -> dict[str, str]:
    """Les quatre champs de mise en page d'une note.

    Les colonnes disent la vérité : la migration les a remplies depuis la
    valeur héritée. La décomposition ne sert plus qu'au cas où le schéma est
    plus ancien que ce code — une base ouverte par une version antérieure,
    ou un enregistrement venu de la synchronisation.
    """
    herite = str(row["page_format"] if "page_format" in keys else "a4")
    taille, sens, marges = _FORMAT_HERITE.get(herite, _FORMAT_HERITE["a4"])
    if "page_size" in keys and row["page_size"]:
        taille = str(row["page_size"])
    if "page_orientation" in keys and row["page_orientation"]:
        sens = str(row["page_orientation"])
    if "page_margins" in keys and row["page_margins"]:
        marges = str(row["page_margins"])
    return {
        "pageFormat": herite,
        "pageSize": taille,
        "pageOrientation": sens,
        "pageMargins": marges,
    }


# 29 août 2026 : 100 000 caractères refusaient un guide riche (HTML de
# mise en forme + gouttières de pagination). Ce n'est pas un plafond
# métier — c'est une garde-fou. Un million laisse un manuel entier.
NOTE_CONTENT_MAX = 1_000_000
NOTE_PAGE_BACKGROUNDS = frozenset({"default", "lined", "grid", "sepia", "dark"})
NOTE_DOC_LANGS = frozenset({"fr", "ht"})
NOTE_FONTS = frozenset(
    {
        "Press Start 2P",
        "VT323",
        "Special Elite",
        "Inter",
        "Poppins",
        "Roboto",
        "Lato",
        "Open Sans",
        "Merriweather",
        "Montserrat",
        "Source Serif 4",
        "Nunito",
        "Playfair Display",
    }
)


def _color(value: Any) -> str:
    raw = str(value or "#6366f1").strip()
    if not _COLOR_RE.fullmatch(raw):
        raise SuccesError("La couleur doit être au format hexadécimal #RRGGBB.")
    return raw.lower()


def _weekly_days(value: Any) -> list[int]:
    source = value if isinstance(value, list) else []
    days = sorted({int(item) for item in source if str(item).isdigit()})
    if any(day < 0 or day > 6 for day in days):
        raise SuccesError("Les jours hebdomadaires doivent être compris entre 0 et 6.")
    return days


def _month_slots(value: Any) -> list[int | str]:
    source = value if isinstance(value, list) else []
    slots: list[int | str] = []
    for item in source:
        if str(item) == "last":
            slots.append("last")
        elif str(item).isdigit() and 1 <= int(item) <= 4:
            slots.append(int(item))
        else:
            raise SuccesError(
                "Les occurrences mensuelles doivent être 1, 2, 3, 4 ou last."
            )
    return list(dict.fromkeys(slots))


def _sunday_weekday(value: date) -> int:
    return (value.weekday() + 1) % 7


def _is_last_weekday(value: date) -> bool:
    return (value + timedelta(days=7)).month != value.month


class SuccesWorkspaceStore(SuccesStore):
    """Task store extended with the remaining phase-two workspace entities."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        super().__init__(db_path)
        with self._connect() as conn:
            conn.executescript(_WORKSPACE_SCHEMA)
            self._ensure_note_columns(conn)
            self._ensure_habit_columns(conn)
            conn.commit()
        self.materialize_archived_snapshots()

    @staticmethod
    def _ensure_note_columns(conn: sqlite3.Connection) -> None:
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(succes_notes)").fetchall()
        }
        additions = (
            ("page_format", "TEXT NOT NULL DEFAULT 'a4'"),
            # 30 août 2026 : les trois axes de « Mise en page » de Word, que
            # `page_format` mélangeait. Les notes déjà écrites sont REMPLIES
            # depuis leur valeur héritée juste après l'ajout — voir plus bas.
            ("page_size", "TEXT NOT NULL DEFAULT 'a4'"),
            ("page_orientation", "TEXT NOT NULL DEFAULT 'portrait'"),
            ("page_margins", "TEXT NOT NULL DEFAULT 'normales'"),
            ("page_background", "TEXT NOT NULL DEFAULT 'default'"),
            ("font_family", "TEXT NOT NULL DEFAULT 'Special Elite'"),
            ("doc_lang", "TEXT NOT NULL DEFAULT 'fr'"),
            ("color", "TEXT NOT NULL DEFAULT '#6366f1'"),
            # 30 août 2026 : la page où l'on s'est arrêté de lire. Zéro veut
            # dire « aucun marqueur », et c'est un défaut honnête — une note
            # jamais lue n'a pas de page 1 marquée, elle n'a rien.
            ("reading_mark", "INTEGER NOT NULL DEFAULT 0"),
            # 15 septembre 2026 : le classement demandé par Carlito. Vide veut
            # dire « sans catégorie » / « sans projet » — jamais NULL, pour
            # que l'égalité SQL reste simple.
            ("category", "TEXT NOT NULL DEFAULT ''"),
            ("project_id", "TEXT NOT NULL DEFAULT ''"),
            # 15 septembre 2026 : l'ordre manuel demandé par Carlito, le
            # patron des tâches (order_index, camelCase `order` sur le fil).
            # DEFAULT 0 met les notes existantes ex æquo ; le mode « Mon
            # ordre » les départage par updatedAtMs tant qu'aucun glisser
            # n'a réécrit un rang.
            ("order_index", "INTEGER NOT NULL DEFAULT 0"),
        )
        neuves = [name for name, _ in additions if name not in columns]
        for name, declaration in additions:
            if name not in columns:
                conn.execute(
                    f"ALTER TABLE succes_notes ADD COLUMN {name} {declaration}"
                )
        if "page_size" in neuves and "page_format" in columns:
            # REMPLIR, et non déduire à la lecture. `ALTER TABLE` donne à
            # chaque note existante le défaut des colonnes neuves, ce qui rend
            # « jamais renseigné » indiscernable de « choisi exprès » : une
            # note héritée « A4 paysage » qu'on remettrait ensuite en portrait
            # serait éternellement rendue en paysage par une lecture qui
            # préfère la valeur non-défaut. Une seule écriture, ici, et les
            # colonnes deviennent la vérité.
            for herite, (taille, sens, marges) in _FORMAT_HERITE.items():
                conn.execute(
                    """UPDATE succes_notes
                       SET page_size=?, page_orientation=?, page_margins=?
                       WHERE page_format=?""",
                    (taille, sens, marges, herite),
                )

    @staticmethod
    def _ensure_habit_columns(conn: sqlite3.Connection) -> None:
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(succes_habits)").fetchall()
        }
        if "reminder_time" not in columns:
            conn.execute(
                "ALTER TABLE succes_habits ADD COLUMN reminder_time TEXT NOT NULL "
                "DEFAULT ''"
            )

    def _replayed_entity(
        self,
        conn: sqlite3.Connection,
        op_id: str | None,
        request: Mapping[str, Any],
        loader: Callable[[sqlite3.Connection, str], dict[str, Any] | None],
    ) -> dict[str, Any] | None:
        if not op_id:
            return None
        row = conn.execute(
            "SELECT request_json,payload_json FROM succes_operations WHERE op_id=?",
            (op_id,),
        ).fetchone()
        if row is None:
            return None
        if row["request_json"] != self._canonical_json(request):
            raise SuccesError(
                "Cet identifiant d'opération a déjà été utilisé "
                "avec d'autres paramètres."
            )
        payload = json.loads(row["payload_json"])
        entity_id = str(payload.get("id") or "") if isinstance(payload, dict) else ""
        return loader(conn, entity_id) if entity_id else payload

    # Projects ---------------------------------------------------------

    @staticmethod
    def _project_dict(
        row: sqlite3.Row, task_total: int, task_done: int
    ) -> dict[str, Any]:
        keys = row.keys()
        return {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "color": row["color"],
            "icon": row["icon"],
            "startDate": row["start_date"],
            "endDate": row["end_date"],
            "structure": row["structure"] if "structure" in keys else "flat",
            "structureConfig": decode_structure_config(
                row["structure_config"] if "structure_config" in keys else ""
            ),
            "createdAt": row["created_date"],
            "updatedAtMs": row["updated_at_ms"],
            "deletedAtMs": row["deleted_at_ms"],
            "order": int(row["order_index"]) if "order_index" in keys else 0,
            "taskTotal": task_total,
            "taskCompleted": task_done,
        }

    def _load_project(
        self, conn: sqlite3.Connection, project_id: str
    ) -> dict[str, Any] | None:
        row = conn.execute(
            "SELECT * FROM succes_projects WHERE id=? AND deleted_at_ms IS NULL",
            (project_id,),
        ).fetchone()
        if row is None:
            return None
        counts = conn.execute(
            """SELECT COUNT(*) total, COALESCE(SUM(done),0) completed
               FROM succes_tasks WHERE project_id=? AND deleted_at_ms IS NULL""",
            (project_id,),
        ).fetchone()
        return self._project_dict(row, int(counts["total"]), int(counts["completed"]))

    def get_project(self, project_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            project = self._load_project(conn, project_id)
        if project is None:
            raise SuccesNotFound("Ce projet n'existe pas ou a été supprimé.")
        return project

    def list_projects(self, *, search: str = "") -> list[dict[str, Any]]:
        query = "%" + search.strip().lower() + "%"
        with self._connect() as conn:
            ids = [
                row["id"]
                for row in conn.execute(
                    """SELECT id FROM succes_projects
                       WHERE deleted_at_ms IS NULL AND lower(name) LIKE ?
                       ORDER BY order_index ASC, updated_at_ms DESC""",
                    (query,),
                ).fetchall()
            ]
            return [
                item
                for project_id in ids
                if (item := self._load_project(conn, project_id))
            ]

    def create_project(
        self, data: Mapping[str, Any], *, op_id: str | None = None
    ) -> dict[str, Any]:
        name = _clean_text(
            data.get("name"), field="Le nom du projet", maximum=200, required=True
        )
        description = _clean_text(
            data.get("description"), field="La description", maximum=4000
        )
        start_date = _validate_iso_date(
            str(data.get("startDate") or ""), "La date de début"
        )
        end_date = _validate_iso_date(str(data.get("endDate") or ""), "La date de fin")
        if start_date and end_date and end_date < start_date:
            raise SuccesError("La date de fin doit suivre la date de début.")
        kit_id = str(data.get("kitId") or "").strip()
        kit = get_project_kit(kit_id) if kit_id else None
        demande = data.get("structure")
        if kit is not None and str(demande or "flat").strip().lower() == "flat":
            # Le gabarit connaît sa forme : un kit de pipeline crée un
            # pipeline, pas un arbre. Un choix explicite d'une autre forme
            # arborescente reste respecté.
            demande = kit.get("structure") or "tree"
        structure = normalize_structure(demande, kit_id=kit_id)
        # Le gabarit nourrit l'ENTRÉE, il ne rattrape pas la sortie : pour un
        # pipeline, une entrée vide se normalise déjà en étapes par défaut,
        # et un repli d'après-coup ne se déclencherait donc jamais.
        config_entree = data.get("structureConfig")
        if kit is not None and not config_entree:
            config_entree = kit.get("structureConfig")
        structure_config = normalize_structure_config(structure, config_entree)
        request = {
            "action": "create_project",
            "name": name,
            "description": description,
            "color": _color(data.get("color")),
            "icon": _clean_text(data.get("icon"), field="L'icône", maximum=16),
            "startDate": start_date,
            "endDate": end_date,
            "structure": structure,
            "structureConfig": structure_config,
            "kitId": kit_id,
        }
        project_id = str(data.get("id") or uuid.uuid4())
        timestamp = _safe_timestamp(data.get("updatedAtMs"))
        with self._transaction() as conn:
            replay = self._replayed_entity(conn, op_id, request, self._load_project)
            if replay is not None:
                return replay
            conn.execute(
                """INSERT INTO succes_projects
                   (id,name,description,color,icon,start_date,end_date,created_date,
                    updated_at_ms,deleted_at_ms,structure,structure_config,order_index)
                   VALUES (?,?,?,?,?,?,?,?,?,NULL,?,?,?)""",
                (
                    project_id,
                    name,
                    description,
                    request["color"],
                    request["icon"],
                    start_date,
                    end_date,
                    str(data.get("createdAt") or date.today().isoformat()),
                    timestamp,
                    structure,
                    encode_structure_config(structure_config),
                    self._prochain_ordre_projet(conn),
                ),
            )
            project = self._load_project(conn, project_id)
            assert project is not None
            self._record_op(
                conn,
                entity="projects",
                entity_id=project_id,
                kind="upsert",
                payload=project,
                request=request,
                timestamp_ms=timestamp,
                op_id=op_id,
            )
        if kit_id:
            self._materialize_project_kit(project_id, kit_id)
            project = self.get_project(project_id)
        return project

    def _materialize_project_kit(self, project_id: str, kit_id: str) -> None:
        kit = get_project_kit(kit_id)

        def walk(nodes: list[dict[str, Any]], parent_task_id: str) -> None:
            for order, node in enumerate(nodes):
                title = _clean_text(
                    node.get("title"), field="Le titre", maximum=200, required=True
                )
                notes = _clean_text(node.get("notes"), field="Les notes", maximum=2000)
                task = self.create_task(
                    {
                        "title": title,
                        "notes": notes,
                        "projectId": project_id,
                        "parentTaskId": parent_task_id,
                        "order": order,
                        "priority": "medium",
                        # Un kit de pipeline place ses cartes, un kit de cycle
                        # donne leur cadence. Absents, ces champs sont inertes.
                        "stage": str(node.get("stage") or ""),
                        "cadence": node.get("cadence"),
                    }
                )
                children = node.get("children")
                if isinstance(children, list) and children:
                    walk(children, task["id"])

        walk(kit.get("nodes") or [], "")

    # ── Le réseau : des synapses « from débloque to » ─────────────────────

    def _edge_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "projectId": row["project_id"],
            "fromTaskId": row["from_task_id"],
            "toTaskId": row["to_task_id"],
            "updatedAtMs": row["updated_at_ms"],
        }

    def list_task_edges(self, project_id: str) -> list[dict[str, Any]]:
        self.get_project(project_id)  # 404 franc plutôt qu'une liste vide menteuse
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM succes_task_edges WHERE project_id=? "
                "ORDER BY from_task_id, to_task_id",
                (project_id,),
            ).fetchall()
        return [self._edge_dict(row) for row in rows]

    def _assert_task_in_project(
        self, conn: sqlite3.Connection, task_id: str, project_id: str, *, role: str
    ) -> None:
        row = conn.execute(
            "SELECT project_id FROM succes_tasks WHERE id=? AND deleted_at_ms IS NULL",
            (task_id,),
        ).fetchone()
        if row is None:
            raise SuccesNotFound(f"La tâche {role} n'existe pas ou a été supprimée.")
        if str(row["project_id"]) != project_id:
            raise SuccesError(f"La tâche {role} n'appartient pas à ce projet.")

    def create_task_edge(
        self,
        project_id: str,
        from_task_id: str,
        to_task_id: str,
        *,
        op_id: str | None = None,
    ) -> dict[str, Any]:
        """Relier deux tâches : « from débloque to ».

        Le graphe doit rester sans boucle. Avec un cycle, « que puis-je faire
        maintenant ? » n'a plus de réponse — chaque tâche attend l'autre — et
        c'est précisément la question que la forme réseau existe pour poser.
        On refuse donc l'arête qui fermerait une boucle, en le disant.
        """
        de, vers = str(from_task_id or "").strip(), str(to_task_id or "").strip()
        if not de or not vers:
            raise SuccesError("Une arête relie deux tâches : les deux sont requises.")
        if de == vers:
            raise SuccesError("Une tâche ne peut pas se débloquer elle-même.")
        request = {
            "action": "create_edge",
            "projectId": project_id,
            "fromTaskId": de,
            "toTaskId": vers,
        }
        ts = now_ms()
        with self._transaction() as conn:
            if self._load_project(conn, project_id) is None:
                raise SuccesNotFound("Ce projet n'existe pas ou a été supprimé.")
            self._assert_task_in_project(conn, de, project_id, role="amont")
            self._assert_task_in_project(conn, vers, project_id, role="aval")
            # Une boucle se formerait si « de » est déjà atteignable depuis
            # « vers » en suivant les arêtes existantes.
            atteints = {vers}
            frontiere = [vers]
            while frontiere:
                courant = frontiere.pop()
                for row in conn.execute(
                    "SELECT to_task_id FROM succes_task_edges "
                    "WHERE project_id=? AND from_task_id=?",
                    (project_id, courant),
                ).fetchall():
                    suivant = row["to_task_id"]
                    if suivant == de:
                        raise SuccesError(
                            "Cette arête fermerait une boucle : chaque tâche "
                            "attendrait l'autre, et rien ne serait jamais "
                            "faisable."
                        )
                    if suivant not in atteints:
                        atteints.add(suivant)
                        frontiere.append(suivant)
            existante = conn.execute(
                "SELECT updated_at_ms FROM succes_task_edges "
                "WHERE from_task_id=? AND to_task_id=?",
                (de, vers),
            ).fetchone()
            if existante is not None:
                # Rien n'a changé : ne pas enregistrer d'op. Un double-clic
                # gonflait le journal que le pair rejoue et rafraîchissait
                # updatedAtMs comme si l'arête venait de naître.
                return {
                    "projectId": project_id,
                    "fromTaskId": de,
                    "toTaskId": vers,
                    "updatedAtMs": int(existante["updated_at_ms"]),
                }
            conn.execute(
                "INSERT INTO succes_task_edges "
                "(project_id, from_task_id, to_task_id, updated_at_ms) "
                "VALUES (?,?,?,?)",
                (project_id, de, vers, ts),
            )
            edge = {
                "projectId": project_id,
                "fromTaskId": de,
                "toTaskId": vers,
                "updatedAtMs": ts,
            }
            self._record_op(
                conn,
                entity="task_edges",
                entity_id=f"{de}->{vers}",
                kind="upsert",
                payload=edge,
                request=request,
                timestamp_ms=ts,
                op_id=op_id,
            )
        return edge

    def delete_task_edge(
        self,
        project_id: str,
        from_task_id: str,
        to_task_id: str,
        *,
        op_id: str | None = None,
    ) -> None:
        de, vers = str(from_task_id or "").strip(), str(to_task_id or "").strip()
        request = {
            "action": "delete_edge",
            "projectId": project_id,
            "fromTaskId": de,
            "toTaskId": vers,
        }
        ts = now_ms()
        with self._transaction() as conn:
            cursor = conn.execute(
                "DELETE FROM succes_task_edges "
                "WHERE project_id=? AND from_task_id=? AND to_task_id=?",
                (project_id, de, vers),
            )
            if cursor.rowcount == 0:
                raise SuccesNotFound("Cette arête n'existe pas.")
            self._record_op(
                conn,
                entity="task_edges",
                entity_id=f"{de}->{vers}",
                kind="delete",
                payload={"projectId": project_id, "fromTaskId": de, "toTaskId": vers},
                request=request,
                timestamp_ms=ts,
                op_id=op_id,
            )

    # ── Les branches : ce qu'une tâche attend, ce qu'elle débloque ────────
    #
    # Chantier réseau du 18 septembre 2026. Le serveur savait refuser une
    # boucle mais ne calculait rien de dérivé : la voix ne pouvait ni dire
    # « qu'est-ce que je peux faire dans AgriCulture ? » ni « relie le budget
    # au tracteur » — la souris était l'unique chemin, ce que le §82 refuse.
    # Le raisonnement vit dans `succes/reseau.py`, miroir de `reseau.ts`.

    def list_project_tasks(self, project_id: str) -> list[dict[str, Any]]:
        """Les tâches vivantes d'un projet, sous-tâches comprises.

        `list_tasks` n'a jamais filtré par projet : l'outil vocal aurait
        résolu « budget » parmi les quatre-vingt-cinq tâches de toutes les
        listes, et relié deux tâches de projets différents.
        """
        self.get_project(project_id)
        with self._connect() as conn:
            ids = [
                row["id"]
                for row in conn.execute(
                    "SELECT id FROM succes_tasks WHERE project_id=? "
                    "AND deleted_at_ms IS NULL ORDER BY order_index, updated_at_ms",
                    (project_id,),
                ).fetchall()
            ]
            return [task for tid in ids if (task := self._load_task(conn, tid))]

    def _reseau(self, project_id: str) -> reseau_module.Reseau:
        return reseau_module.construire_reseau(
            self.list_project_tasks(project_id), self.list_task_edges(project_id)
        )

    @staticmethod
    def _resume_tache(reseau: reseau_module.Reseau, tid: str) -> dict[str, Any]:
        tache = reseau.par_id[tid]
        return {
            "id": tid,
            "title": tache["title"],
            "done": bool(tache.get("done")),
            "status": reseau_module.statut_de(reseau, tid),
        }

    def branches_de(self, project_id: str, task_id: str) -> dict[str, Any]:
        """Les branches d'une tâche : amont, aval, la chaîne entière, ce que
        la terminer ouvre. Les champs sont ceux du fil (camelCase anglais)."""
        reseau = self._reseau(project_id)
        tid = str(task_id or "").strip()
        if tid not in reseau.par_id:
            raise SuccesNotFound(
                "Cette tâche n'existe pas dans ce projet ou a été supprimée."
            )
        amont = reseau_module.voisines_ordonnees(reseau, tid, "amont")
        aval = reseau_module.voisines_ordonnees(reseau, tid, "aval")
        return {
            "task": self._resume_tache(reseau, tid),
            "status": reseau_module.statut_de(reseau, tid),
            "upstream": [self._resume_tache(reseau, i) for i in amont],
            "downstream": [self._resume_tache(reseau, i) for i in aval],
            "upstreamAll": [
                {**self._resume_tache(reseau, i), "depth": p}
                for i, p in reseau_module.chaine(reseau, tid, "amont")
            ],
            "downstreamAll": [
                {**self._resume_tache(reseau, i), "depth": p}
                for i, p in reseau_module.chaine(reseau, tid, "aval")
            ],
            "missing": [
                self._resume_tache(reseau, i)
                for i in amont
                if not bool(reseau.par_id[i].get("done"))
            ],
            "unlocks": [
                self._resume_tache(reseau, i)
                for i in reseau_module.ce_que_debloque(reseau, tid)
            ],
            "impact": reseau_module.impact(reseau, tid),
        }

    def prochaines_actions(self, project_id: str) -> list[dict[str, Any]]:
        """Les faisables maintenant, celles qui libèrent le plus d'abord."""
        reseau = self._reseau(project_id)
        return [
            {
                **self._resume_tache(reseau, tid),
                "impact": reseau_module.impact(reseau, tid),
                "unlocks": [
                    self._resume_tache(reseau, i)
                    for i in reseau_module.ce_que_debloque(reseau, tid)
                ],
            }
            for tid in reseau_module.faisables(reseau)
        ]

    # ── Le cycle : chaque nouveau tour régénère les tâches ────────────────

    def reset_cycle(
        self, project_id: str, *, op_id: str | None = None
    ) -> dict[str, Any]:
        """Décoche toutes les tâches du projet : un tour recommence.

        Explicite, jamais automatique : une régénération déclenchée par une
        simple lecture serait un GET qui écrit, et l'utilisateur verrait ses
        coches disparaître sans geste de sa part.
        """
        project = self.get_project(project_id)
        if project.get("structure") != "cycle":
            raise SuccesError("Seul un projet en cycle recommence un tour.")
        request = {"action": "reset_cycle", "projectId": project_id}
        ts = now_ms()
        rouvertes = 0
        with self._transaction() as conn:
            # Rejouer un tour ne doit pas en refaire un : sans ce garde, un
            # client qui renvoie son op après une coupure décoche une seconde
            # fois un travail entre-temps refait.
            if op_id:
                deja = conn.execute(
                    "SELECT 1 FROM succes_operations WHERE op_id LIKE ? LIMIT 1",
                    (f"{op_id}:%",),
                ).fetchone()
                if deja is not None:
                    return {
                        "project": self._load_project(conn, project_id),
                        "reopened": 0,
                    }
            ids = [
                row["id"]
                for row in conn.execute(
                    "SELECT id FROM succes_tasks "
                    "WHERE project_id=? AND deleted_at_ms IS NULL AND done=1",
                    (project_id,),
                ).fetchall()
            ]
            for task_id in ids:
                conn.execute(
                    "UPDATE succes_tasks SET done=0, completed_date='', "
                    "updated_at_ms=? WHERE id=?",
                    (ts, task_id),
                )
                # Les sous-tâches suivent. Sans cela, elles restaient cochées :
                # au premier geste sur l'une d'elles, le recalcul voyait tout
                # l'arbre fait et re-cochait la tâche — le tour « recommencé »
                # s'achevait tout seul, sans que rien n'ait été fait.
                conn.execute(
                    "UPDATE succes_subtasks SET done=0, updated_at_ms=? "
                    "WHERE task_id=? AND deleted_at_ms IS NULL",
                    (ts, task_id),
                )
                task = self._load_task(conn, task_id)
                assert task is not None
                # Une opération PAR tâche : la synchronisation rejoue des
                # tâches, pas des gestes de projet.
                self._record_op(
                    conn,
                    entity="tasks",
                    entity_id=task_id,
                    kind="upsert",
                    payload=task,
                    request=request,
                    timestamp_ms=ts,
                    op_id=f"{op_id}:{task_id}" if op_id else None,
                )
                rouvertes += 1
        return {"project": self.get_project(project_id), "reopened": rouvertes}

    def update_project(
        self,
        project_id: str,
        patch: Mapping[str, Any],
        *,
        op_id: str | None = None,
    ) -> dict[str, Any]:
        current = self.get_project(project_id)
        merged = {**current, **patch, "id": project_id}
        name = _clean_text(
            merged.get("name"), field="Le nom du projet", maximum=200, required=True
        )
        description = _clean_text(
            merged.get("description"), field="La description", maximum=4000
        )
        start_date = _validate_iso_date(
            str(merged.get("startDate") or ""), "La date de début"
        )
        end_date = _validate_iso_date(
            str(merged.get("endDate") or ""), "La date de fin"
        )
        if start_date and end_date and end_date < start_date:
            raise SuccesError("La date de fin doit suivre la date de début.")
        structure = normalize_structure(merged.get("structure"))
        structure_config = normalize_structure_config(
            structure, merged.get("structureConfig")
        )
        request = {
            "action": "update_project",
            "projectId": project_id,
            "patch": dict(patch),
        }
        timestamp = now_ms()
        with self._transaction() as conn:
            replay = self._replayed_entity(conn, op_id, request, self._load_project)
            if replay is not None:
                return replay
            if self._load_project(conn, project_id) is None:
                raise SuccesNotFound("Ce projet n'existe pas ou a été supprimé.")
            conn.execute(
                """UPDATE succes_projects SET name=?,description=?,color=?,icon=?,
                   start_date=?,end_date=?,structure=?,structure_config=?,
                   updated_at_ms=? WHERE id=?""",
                (
                    name,
                    description,
                    _color(merged.get("color")),
                    _clean_text(merged.get("icon"), field="L'icône", maximum=16),
                    start_date,
                    end_date,
                    structure,
                    encode_structure_config(structure_config),
                    timestamp,
                    project_id,
                ),
            )
            # Les tâches suivent la forme du projet. Sans ça, changer les
            # étapes d'un pipeline — ou le sortir de cette forme — laissait des
            # tâches portant une étape que le projet ne connaît plus : la vue
            # les rangeait en première colonne pendant que la base disait autre
            # chose, et réaffirmer sa propre étape courante était REFUSÉ. Le
            # serveur interdisait une étape fantôme à l'écriture d'une tâche
            # tout en en fabriquant lui-même ici.
            etapes_valides = stages_of(structure, structure_config)
            if etapes_valides:
                marques = ",".join("?" * len(etapes_valides))
                egarees = conn.execute(
                    f"""SELECT id FROM succes_tasks WHERE project_id=?
                        AND deleted_at_ms IS NULL AND stage NOT IN ({marques})""",
                    (project_id, *etapes_valides),
                ).fetchall()
                repli = etapes_valides[0]
            else:
                egarees = conn.execute(
                    "SELECT id FROM succes_tasks WHERE project_id=? "
                    "AND deleted_at_ms IS NULL AND stage != ''",
                    (project_id,),
                ).fetchall()
                repli = ""
            for ligne in egarees:
                conn.execute(
                    "UPDATE succes_tasks SET stage=?, updated_at_ms=? WHERE id=?",
                    (repli, timestamp, ligne["id"]),
                )
                tache = self._load_task(conn, ligne["id"])
                if tache is not None:
                    # Une op par tâche : le pair doit voir le rangement, sinon
                    # il garderait des étapes que son propre projet ignore.
                    self._record_op(
                        conn,
                        entity="tasks",
                        entity_id=ligne["id"],
                        kind="upsert",
                        payload=tache,
                        request={"action": "restage", "projectId": project_id},
                        timestamp_ms=timestamp,
                        op_id=f"{op_id}:restage:{ligne['id']}" if op_id else None,
                    )

            project = self._load_project(conn, project_id)
            assert project is not None
            self._record_op(
                conn,
                entity="projects",
                entity_id=project_id,
                kind="upsert",
                payload=project,
                request=request,
                timestamp_ms=timestamp,
                op_id=op_id,
            )
            return project

    @staticmethod
    def _prochain_ordre_projet(conn: sqlite3.Connection) -> int:
        row = conn.execute(
            "SELECT COALESCE(MAX(order_index), -1) + 1 AS n FROM succes_projects"
        ).fetchone()
        return int(row["n"])

    def reorder_projects(self, ids: list[str]) -> list[dict[str, Any]]:
        """Fixe l'ordre manuel des projets : order_index = rang dans `ids`.
        Seuls les projets dont le rang change sont réécrits et journalisés,
        pour que le maillage voie le nouvel ordre sans inonder la relève."""
        propres: list[str] = []
        for project_id in ids:
            pid = str(project_id or "").strip()
            if pid and pid not in propres:
                propres.append(pid)
        timestamp = now_ms()
        changes: list[dict[str, Any]] = []
        with self._transaction() as conn:
            rang = 0
            for project_id in propres:
                row = conn.execute(
                    "SELECT order_index FROM succes_projects"
                    " WHERE id=? AND deleted_at_ms IS NULL",
                    (project_id,),
                ).fetchone()
                if row is None:
                    continue
                index = rang
                rang += 1
                if int(row["order_index"]) == index:
                    continue
                conn.execute(
                    "UPDATE succes_projects SET order_index=?,updated_at_ms=?"
                    " WHERE id=?",
                    (index, timestamp, project_id),
                )
                project = self._load_project(conn, project_id)
                if project is not None:
                    self._record_op(
                        conn,
                        entity="projects",
                        entity_id=project_id,
                        kind="upsert",
                        payload=project,
                        request={"action": "reorder_project", "order": index},
                        timestamp_ms=timestamp,
                    )
                    changes.append(project)
        return changes

    def delete_project(self, project_id: str, *, op_id: str | None = None) -> None:
        timestamp = now_ms()
        request = {"action": "delete_project", "projectId": project_id}
        with self._transaction() as conn:
            # La garde d'idempotence AVANT de charger le projet. Elle était
            # après : ``get_project`` levait « ce projet n'existe pas ou a été
            # supprimé » et la garde n'était jamais atteinte. Un pair qui
            # renvoie son op après une coupure réseau recevait donc une erreur
            # là où il attendait un non-événement — et cessait de synchroniser.
            if (
                op_id
                and conn.execute(
                    "SELECT 1 FROM succes_operations WHERE op_id=?", (op_id,)
                ).fetchone()
            ):
                return
            project = self._load_project(conn, project_id)
            if project is None:
                raise SuccesNotFound("Ce projet n'existe pas ou a été supprimé.")
            conn.execute(
                "UPDATE succes_projects SET deleted_at_ms=?,updated_at_ms=? WHERE id=?",
                (timestamp, timestamp, project_id),
            )
            # Les notes rattachées redeviennent « sans projet » — supprimer un
            # projet ne supprime jamais une note, et une pastille vers un
            # projet mort serait un mensonge. Chaque note libérée est
            # journalisée : la synchronisation doit la voir changer.
            liberees = [
                row["id"]
                for row in conn.execute(
                    """SELECT id FROM succes_notes
                       WHERE deleted_at_ms IS NULL AND project_id=?""",
                    (project_id,),
                )
            ]
            for note_id in liberees:
                conn.execute(
                    """UPDATE succes_notes SET project_id='',updated_at_ms=?
                       WHERE id=?""",
                    (timestamp, note_id),
                )
                note = self._load_note(conn, note_id)
                if note is not None:
                    self._record_op(
                        conn,
                        entity="notes",
                        entity_id=note_id,
                        kind="upsert",
                        payload=note,
                        request={
                            "action": "detach_note_project",
                            "projectId": project_id,
                        },
                        timestamp_ms=timestamp,
                    )
            self._record_op(
                conn,
                entity="projects",
                entity_id=project_id,
                kind="delete",
                payload={**project, "deletedAtMs": timestamp},
                request=request,
                timestamp_ms=timestamp,
                op_id=op_id,
            )
            # Le projet emporte ses tâches. Il ne les emportait pas : constaté
            # le 22 août 2026 sur l'installation de Carlito, soixante-quinze
            # tâches survivaient à seize projets supprimés et s'entassaient
            # dans « sans date ». Elles n'étaient plus rattachées à rien de
            # visible, donc impossibles à retrouver par leur projet — et
            # impossibles à supprimer autrement qu'une par une.
            #
            # Une op par tâche, et non une seule pour le projet : le téléphone
            # applique les suppressions entité par entité, et un pair qui ne
            # reçoit que la mort du projet garde toutes les tâches.
            survivantes = conn.execute(
                "SELECT id FROM succes_tasks "
                "WHERE project_id=? AND deleted_at_ms IS NULL",
                (project_id,),
            ).fetchall()
            for rang, ligne in enumerate(survivantes):
                task_id = ligne["id"]
                conn.execute(
                    "UPDATE succes_tasks SET deleted_at_ms=?,updated_at_ms=? "
                    "WHERE id=?",
                    (timestamp, timestamp, task_id),
                )
                aretes = self._emporter_les_dependances(conn, task_id, timestamp)
                self._record_op(
                    conn,
                    entity="tasks",
                    entity_id=task_id,
                    kind="delete",
                    payload={"id": task_id, "deletedAtMs": timestamp},
                    request={
                        "action": "delete_tasks_of_project",
                        "projectId": project_id,
                        "taskId": task_id,
                    },
                    timestamp_ms=timestamp,
                    # Dérivé de l'op du projet : rejouer la suppression après
                    # une coupure ne doit pas produire une seconde salve d'ops.
                    op_id=f"{op_id}:task:{rang}" if op_id else None,
                )
                for arete in aretes:
                    de, vers = arete["from_task_id"], arete["to_task_id"]
                    self._record_op(
                        conn,
                        entity="task_edges",
                        entity_id=f"{de}->{vers}",
                        kind="delete",
                        payload={"fromTaskId": de, "toTaskId": vers},
                        request={
                            "action": "delete_edges_of_task",
                            "taskId": task_id,
                        },
                        timestamp_ms=timestamp,
                        op_id=(
                            f"{op_id}:task:{rang}:edge:{de}:{vers}" if op_id else None
                        ),
                    )

    # Habits -----------------------------------------------------------

    @staticmethod
    def _habit_base(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "icon": row["icon"],
            "color": row["color"],
            "frequency": row["frequency"],
            "createdAt": row["created_date"],
            "startDate": row["start_date"],
            "endDate": row["end_date"],
            "weeklyDays": json.loads(row["weekly_days_json"]),
            "monthWeekSlots": json.loads(row["month_week_slots_json"]),
            "monthWeekDay": row["month_week_day"],
            "reminderTime": row["reminder_time"]
            if "reminder_time" in row.keys()
            else "",
            "updatedAtMs": row["updated_at_ms"],
            "deletedAtMs": row["deleted_at_ms"],
        }

    def _load_habit(
        self, conn: sqlite3.Connection, habit_id: str
    ) -> dict[str, Any] | None:
        row = conn.execute(
            "SELECT * FROM succes_habits WHERE id=? AND deleted_at_ms IS NULL",
            (habit_id,),
        ).fetchone()
        return self._habit_base(row) if row is not None else None

    @staticmethod
    def _habit_due(habit: Mapping[str, Any], on_date: date) -> bool:
        iso = on_date.isoformat()
        if habit.get("startDate") and iso < str(habit["startDate"]):
            return False
        if habit.get("endDate") and iso > str(habit["endDate"]):
            return False
        frequency = str(habit.get("frequency") or "daily")
        if frequency == "daily":
            return True
        weekday = _sunday_weekday(on_date)
        if frequency == "weekly":
            days = habit.get("weeklyDays") or []
            return not days or weekday in days
        slots = habit.get("monthWeekSlots") or []
        if weekday != int(habit.get("monthWeekDay") or 1) or not slots:
            return False
        occurrence = ((on_date.day - 1) // 7) + 1
        return occurrence in slots or ("last" in slots and _is_last_weekday(on_date))

    def _habit_done(self, conn: sqlite3.Connection, habit_id: str, iso: str) -> bool:
        row = conn.execute(
            "SELECT done FROM succes_habit_logs WHERE habit_id=? AND log_date=?",
            (habit_id, iso),
        ).fetchone()
        return bool(row and row["done"])

    def _habit_streak(
        self, conn: sqlite3.Connection, habit: Mapping[str, Any], on_date: date
    ) -> int:
        """Jours dus consécutifs déjà tenus, en remontant depuis *on_date*.

        Le jour COURANT ne rompt pas la série tant qu'il n'est pas écoulé.
        Auparavant, une habitude due aujourd'hui et pas encore cochée cassait
        la boucle au premier tour : quarante jours d'affilée s'affichaient
        « 0 » chaque matin, jusqu'à ce qu'on coche la case. C'est-à-dire
        précisément au moment où la série a le plus de valeur pour celui qui
        la regarde — et l'effacer là décourage l'usage même de l'outil.

        Une fois cochée, la journée compte normalement ; le lendemain, elle
        n'est plus le jour courant et rompt la série si elle est restée vide.
        """
        streak = 0
        cursor = on_date
        for _ in range(366):
            if self._habit_due(habit, cursor):
                done = self._habit_done(conn, str(habit["id"]), cursor.isoformat())
                if not done:
                    # Le jour en cours n'est pas encore manqué : il est en
                    # cours. On l'enjambe sans le compter — la série montre ce
                    # qui est acquis, pas ce qui est promis.
                    if cursor != on_date:
                        break
                else:
                    streak += 1
            cursor -= timedelta(days=1)
        return streak

    def get_habit(self, habit_id: str, *, on_date: str | None = None) -> dict[str, Any]:
        iso = _validate_iso_date(on_date or date.today().isoformat())
        target = date.fromisoformat(iso)
        with self._connect() as conn:
            habit = self._load_habit(conn, habit_id)
            if habit is None:
                raise SuccesNotFound("Cette habitude n'existe pas ou a été supprimée.")
            habit["due"] = self._habit_due(habit, target)
            habit["done"] = self._habit_done(conn, habit_id, iso)
            habit["streak"] = self._habit_streak(conn, habit, target)
            habit["date"] = iso
            return habit

    def list_habits(self, *, on_date: str | None = None) -> list[dict[str, Any]]:
        iso = _validate_iso_date(on_date or date.today().isoformat())
        target = date.fromisoformat(iso)
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM succes_habits WHERE deleted_at_ms IS NULL
                   ORDER BY updated_at_ms DESC"""
            ).fetchall()
            habits: list[dict[str, Any]] = []
            for row in rows:
                habit = self._habit_base(row)
                habit["due"] = self._habit_due(habit, target)
                habit["done"] = self._habit_done(conn, str(habit["id"]), iso)
                habit["streak"] = self._habit_streak(conn, habit, target)
                habit["date"] = iso
                habits.append(habit)
            return habits

    def _validated_habit(self, data: Mapping[str, Any]) -> dict[str, Any]:
        frequency = str(data.get("frequency") or "daily").lower()
        if frequency not in HABIT_FREQUENCIES:
            raise SuccesError("La fréquence doit être daily, weekly ou monthly.")
        days = _weekly_days(data.get("weeklyDays"))
        slots = _month_slots(data.get("monthWeekSlots"))
        if frequency == "weekly" and not days:
            raise SuccesError(
                "Choisissez au moins un jour pour l'habitude hebdomadaire."
            )
        if frequency == "monthly" and not slots:
            raise SuccesError("Choisissez au moins une occurrence mensuelle.")
        month_day = int(data.get("monthWeekDay") or 1)
        if month_day < 0 or month_day > 6:
            raise SuccesError("Le jour mensuel doit être compris entre 0 et 6.")
        start = _validate_iso_date(str(data.get("startDate") or ""), "La date de début")
        end = _validate_iso_date(str(data.get("endDate") or ""), "La date de fin")
        if start and end and end < start:
            raise SuccesError("La date de fin doit suivre la date de début.")
        try:
            reminder = normalize_time(str(data.get("reminderTime") or ""))
        except ValueError as exc:
            raise SuccesError(str(exc)) from exc
        return {
            "name": _clean_text(
                data.get("name"),
                field="Le nom de l'habitude",
                maximum=200,
                required=True,
            ),
            "icon": _clean_text(data.get("icon"), field="L'icône", maximum=16),
            "color": _color(data.get("color")),
            "frequency": frequency,
            "startDate": start or date.today().isoformat(),
            "endDate": end,
            "weeklyDays": days if frequency == "weekly" else [],
            "monthWeekSlots": slots if frequency == "monthly" else [],
            "monthWeekDay": month_day,
            "reminderTime": reminder,
        }

    def create_habit(
        self, data: Mapping[str, Any], *, op_id: str | None = None
    ) -> dict[str, Any]:
        clean = self._validated_habit(data)
        request = {"action": "create_habit", **clean}
        habit_id = str(data.get("id") or uuid.uuid4())
        timestamp = _safe_timestamp(data.get("updatedAtMs"))
        with self._transaction() as conn:
            replay = self._replayed_entity(conn, op_id, request, self._load_habit)
            if replay is not None:
                return replay
            conn.execute(
                """INSERT INTO succes_habits
                   (id,name,icon,color,frequency,created_date,start_date,end_date,
                    weekly_days_json,month_week_slots_json,month_week_day,
                    reminder_time,updated_at_ms,deleted_at_ms)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)""",
                (
                    habit_id,
                    clean["name"],
                    clean["icon"],
                    clean["color"],
                    clean["frequency"],
                    str(data.get("createdAt") or date.today().isoformat()),
                    clean["startDate"],
                    clean["endDate"],
                    json.dumps(clean["weeklyDays"]),
                    json.dumps(clean["monthWeekSlots"]),
                    clean["monthWeekDay"],
                    clean["reminderTime"],
                    timestamp,
                ),
            )
            habit = self._load_habit(conn, habit_id)
            assert habit is not None
            self._record_op(
                conn,
                entity="habits",
                entity_id=habit_id,
                kind="upsert",
                payload=habit,
                request=request,
                timestamp_ms=timestamp,
                op_id=op_id,
            )
        return self.get_habit(habit_id)

    def update_habit(
        self, habit_id: str, patch: Mapping[str, Any], *, op_id: str | None = None
    ) -> dict[str, Any]:
        current = self.get_habit(habit_id)
        clean = self._validated_habit({**current, **patch})
        request = {"action": "update_habit", "habitId": habit_id, "patch": dict(patch)}
        timestamp = now_ms()
        with self._transaction() as conn:
            replay = self._replayed_entity(conn, op_id, request, self._load_habit)
            if replay is not None:
                return self.get_habit(habit_id)
            if self._load_habit(conn, habit_id) is None:
                raise SuccesNotFound("Cette habitude n'existe pas ou a été supprimée.")
            conn.execute(
                """UPDATE succes_habits SET name=?,icon=?,color=?,frequency=?,
                   start_date=?,end_date=?,weekly_days_json=?,month_week_slots_json=?,
                   month_week_day=?,reminder_time=?,updated_at_ms=? WHERE id=?""",
                (
                    clean["name"],
                    clean["icon"],
                    clean["color"],
                    clean["frequency"],
                    clean["startDate"],
                    clean["endDate"],
                    json.dumps(clean["weeklyDays"]),
                    json.dumps(clean["monthWeekSlots"]),
                    clean["monthWeekDay"],
                    clean["reminderTime"],
                    timestamp,
                    habit_id,
                ),
            )
            habit = self._load_habit(conn, habit_id)
            assert habit is not None
            self._record_op(
                conn,
                entity="habits",
                entity_id=habit_id,
                kind="upsert",
                payload=habit,
                request=request,
                timestamp_ms=timestamp,
                op_id=op_id,
            )
        return self.get_habit(habit_id)

    def list_habit_logs(
        self,
        *,
        from_date: str,
        to_date: str,
        habit_id: str | None = None,
    ) -> dict[str, bool]:
        """Return done=true logs keyed as ``habitId_YYYY-MM-DD`` for a date span."""
        start = _validate_iso_date(from_date, "La date de début")
        end = _validate_iso_date(to_date, "La date de fin")
        if not start or not end:
            raise SuccesError("Indiquez une plage de dates complète.")
        if end < start:
            raise SuccesError("La date de fin doit suivre la date de début.")
        # Bound the window so a bad client cannot pull the entire history at once.
        if (date.fromisoformat(end) - date.fromisoformat(start)).days > 400:
            raise SuccesError("La plage de suivi ne peut pas dépasser 400 jours.")
        query = """SELECT habit_id, log_date FROM succes_habit_logs
                   WHERE done=1 AND log_date>=? AND log_date<=?"""
        params: list[Any] = [start, end]
        if habit_id:
            query += " AND habit_id=?"
            params.append(habit_id)
        with self._connect() as conn:
            if habit_id and self._load_habit(conn, habit_id) is None:
                raise SuccesNotFound("Cette habitude n'existe pas ou a été supprimée.")
            rows = conn.execute(query, params).fetchall()
        return {f"{row['habit_id']}_{row['log_date']}": True for row in rows}

    def set_habit_done(
        self,
        habit_id: str,
        log_date: str,
        done: bool,
        *,
        op_id: str | None = None,
    ) -> dict[str, Any]:
        self.get_habit(habit_id, on_date=log_date)
        iso = _validate_iso_date(log_date)
        request = {
            "action": "set_habit_done",
            "habitId": habit_id,
            "date": iso,
            "done": bool(done),
        }
        timestamp = now_ms()
        with self._transaction() as conn:
            if op_id:
                row = conn.execute(
                    "SELECT request_json FROM succes_operations WHERE op_id=?", (op_id,)
                ).fetchone()
                if row:
                    if row["request_json"] != self._canonical_json(request):
                        raise SuccesError(
                            "Cet identifiant d'opération a déjà été utilisé "
                            "avec d'autres paramètres."
                        )
                    return self.get_habit(habit_id, on_date=iso)
            conn.execute(
                """INSERT INTO succes_habit_logs(habit_id,log_date,done,updated_at_ms)
                   VALUES (?,?,?,?) ON CONFLICT(habit_id,log_date) DO UPDATE SET
                   done=excluded.done,updated_at_ms=excluded.updated_at_ms""",
                (habit_id, iso, int(done), timestamp),
            )
            payload = {"id": f"{habit_id}_{iso}", **request, "updatedAtMs": timestamp}
            self._record_op(
                conn,
                entity="habit_logs",
                entity_id=payload["id"],
                kind="habitlog_set",
                payload=payload,
                request=request,
                timestamp_ms=timestamp,
                op_id=op_id,
            )
        return self.get_habit(habit_id, on_date=iso)

    def delete_habit(self, habit_id: str, *, op_id: str | None = None) -> None:
        habit = self.get_habit(habit_id)
        timestamp = now_ms()
        request = {"action": "delete_habit", "habitId": habit_id}
        with self._transaction() as conn:
            if (
                op_id
                and conn.execute(
                    "SELECT 1 FROM succes_operations WHERE op_id=?", (op_id,)
                ).fetchone()
            ):
                return
            conn.execute(
                "UPDATE succes_habits SET deleted_at_ms=?,updated_at_ms=? WHERE id=?",
                (timestamp, timestamp, habit_id),
            )
            self._record_op(
                conn,
                entity="habits",
                entity_id=habit_id,
                kind="delete",
                payload={**habit, "deletedAtMs": timestamp},
                request=request,
                timestamp_ms=timestamp,
                op_id=op_id,
            )

    # Notes ------------------------------------------------------------

    @staticmethod
    def _note_dict(row: sqlite3.Row) -> dict[str, Any]:
        keys = set(row.keys())
        return {
            "id": row["id"],
            "title": row["title"],
            "content": row["content"],
            "contentHash": hashlib.sha256(row["content"].encode()).hexdigest(),
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
            "updatedAtMs": row["updated_at_ms"],
            "deletedAtMs": row["deleted_at_ms"],
            **_axes_de_page(row, keys),
            "pageBackground": (
                row["page_background"] if "page_background" in keys else "default"
            ),
            "fontFamily": (
                row["font_family"] if "font_family" in keys else "Special Elite"
            ),
            "docLang": row["doc_lang"] if "doc_lang" in keys else "fr",
            "color": row["color"] if "color" in keys else "#6366f1",
            "readingMark": (
                int(row["reading_mark"] or 0) if "reading_mark" in keys else 0
            ),
            "category": row["category"] if "category" in keys else "",
            "projectId": row["project_id"] if "project_id" in keys else "",
            "order": int(row["order_index"]) if "order_index" in keys else 0,
        }

    def _load_note(
        self, conn: sqlite3.Connection, note_id: str
    ) -> dict[str, Any] | None:
        row = conn.execute(
            "SELECT * FROM succes_notes WHERE id=? AND deleted_at_ms IS NULL",
            (note_id,),
        ).fetchone()
        return self._note_dict(row) if row is not None else None

    def get_note(self, note_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            note = self._load_note(conn, note_id)
        if note is None:
            raise SuccesNotFound("Cette note n'existe pas ou a été supprimée.")
        return note

    def list_notes(self, *, search: str = "") -> list[dict[str, Any]]:
        query = "%" + search.strip().lower() + "%"
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM succes_notes WHERE deleted_at_ms IS NULL
                   AND (lower(title) LIKE ? OR lower(content) LIKE ?)
                   ORDER BY order_index ASC, updated_at_ms DESC""",
                (query, query),
            ).fetchall()
        return [self._note_dict(row) for row in rows]

    @staticmethod
    def _note_meta(data: Mapping[str, Any]) -> dict[str, str]:
        page_format = str(data.get("pageFormat") or "a4").strip().lower()
        if page_format not in NOTE_PAGE_FORMATS:
            raise SuccesError("Le format de page de la note est invalide.")
        # Le défaut des trois axes vient de la valeur HÉRITÉE, pas d'une
        # constante : un appelant qui n'envoie que `pageFormat: "wide"` — le
        # client mobile, la synchronisation, une note importée — doit obtenir
        # A4 paysage, et non A4 portrait parce que « portrait » se trouve être
        # le défaut de la colonne.
        taille_h, sens_h, marges_h = _FORMAT_HERITE.get(
            page_format, _FORMAT_HERITE["a4"]
        )
        page_size = str(data.get("pageSize") or taille_h).strip().lower()
        if page_size not in NOTE_PAGE_SIZES:
            raise SuccesError("La taille de papier de la note est invalide.")
        page_orientation = str(data.get("pageOrientation") or sens_h).strip().lower()
        if page_orientation not in NOTE_PAGE_ORIENTATIONS:
            raise SuccesError("L'orientation de la note est invalide.")
        page_margins = str(data.get("pageMargins") or marges_h).strip().lower()
        if page_margins not in NOTE_PAGE_MARGINS:
            raise SuccesError("Les marges de la note sont invalides.")
        page_background = str(data.get("pageBackground") or "default").strip().lower()
        if page_background not in NOTE_PAGE_BACKGROUNDS:
            raise SuccesError("Le fond de page de la note est invalide.")
        font_family = str(data.get("fontFamily") or "Special Elite").strip()
        if font_family not in NOTE_FONTS:
            raise SuccesError("La police de la note est invalide.")
        doc_lang = str(data.get("docLang") or "fr").strip().lower()
        if doc_lang not in NOTE_DOC_LANGS:
            raise SuccesError("La langue du document doit être fr ou ht.")
        # La page marquée. Bornée à zéro : un marqueur négatif ou illisible
        # vaut « pas de marqueur », il ne vaut pas une exception — on ne perd
        # pas une note parce que sa page marquée est absurde. Le plafond, lui,
        # ne peut pas être appliqué ici : le nombre de pages dépend du format
        # d'affichage et de la police, que le serveur ne rend pas.
        try:
            reading_mark = max(0, int(data.get("readingMark") or 0))
        except (TypeError, ValueError):
            reading_mark = 0
        category = _clean_text(
            data.get("category") or "", field="La catégorie", maximum=60
        )
        project_id = str(data.get("projectId") or "").strip()
        return {
            "pageFormat": page_format,
            "pageSize": page_size,
            "pageOrientation": page_orientation,
            "pageMargins": page_margins,
            "pageBackground": page_background,
            "fontFamily": font_family,
            "docLang": doc_lang,
            "color": _color(data.get("color")),
            "readingMark": reading_mark,
            "category": category,
            "projectId": project_id,
        }

    @classmethod
    def _note_fields(cls, data: Mapping[str, Any]) -> tuple[str, str, dict[str, str]]:
        title = _clean_text(
            data.get("title"), field="Le titre de la note", maximum=200, required=True
        )
        content = str(data.get("content") or "")
        if len(content) > NOTE_CONTENT_MAX:
            raise SuccesError(
                "Le contenu de la note ne peut pas dépasser "
                f"{NOTE_CONTENT_MAX:,} caractères.".replace(",", " ")
            )
        return title, content, cls._note_meta(data)

    def create_note(
        self, data: Mapping[str, Any], *, op_id: str | None = None
    ) -> dict[str, Any]:
        title, content, meta = self._note_fields(data)
        request = {
            "action": "create_note",
            "title": title,
            "content": content,
            **meta,
        }
        note_id = str(data.get("id") or uuid.uuid4())
        timestamp = _safe_timestamp(data.get("updatedAtMs"))
        iso_time = str(data.get("updatedAt") or date.today().isoformat())
        with self._transaction() as conn:
            replay = self._replayed_entity(conn, op_id, request, self._load_note)
            if replay is not None:
                return replay
            conn.execute(
                """INSERT INTO succes_notes
                   (id,title,content,created_at,updated_at,updated_at_ms,deleted_at_ms,
                    page_format,page_size,page_orientation,page_margins,
                    page_background,font_family,doc_lang,color,reading_mark,
                    category,project_id,order_index)
                   VALUES (?,?,?,?,?,?,NULL,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    note_id,
                    title,
                    content,
                    str(data.get("createdAt") or date.today().isoformat()),
                    iso_time,
                    timestamp,
                    meta["pageFormat"],
                    meta["pageSize"],
                    meta["pageOrientation"],
                    meta["pageMargins"],
                    meta["pageBackground"],
                    meta["fontFamily"],
                    meta["docLang"],
                    meta["color"],
                    meta["readingMark"],
                    meta["category"],
                    meta["projectId"],
                    self._prochain_ordre_note(conn),
                ),
            )
            pid = meta["projectId"]
            if pid and self._load_project(conn, pid) is None:
                raise SuccesError("Ce projet n'existe pas ou a été supprimé.")
            note = self._load_note(conn, note_id)
            assert note is not None
            self._record_op(
                conn,
                entity="notes",
                entity_id=note_id,
                kind="upsert",
                payload=note,
                request=request,
                timestamp_ms=timestamp,
                op_id=op_id,
            )
            return note

    def update_note(
        self, note_id: str, patch: Mapping[str, Any], *, op_id: str | None = None
    ) -> dict[str, Any]:
        request = {"action": "update_note", "noteId": note_id, "patch": dict(patch)}
        timestamp = now_ms()
        iso_time = date.today().isoformat()
        with self._transaction() as conn:
            replay = self._replayed_entity(conn, op_id, request, self._load_note)
            if replay is not None:
                return replay
            current = self._load_note(conn, note_id)
            if current is None:
                raise SuccesNotFound("Cette note n'existe pas ou a été supprimée.")
            # 23/09/2026 : lire avant BEGIN IMMEDIATE perdait aussi les champs
            # non modifiés. L'ajout d'un visuel et les sauvegardes concurrentes
            # doivent décider sur le même contenu que celui qu'ils écrivent.
            if (
                "content" in patch
                and patch.get("expectedContentHash") is not None
                and patch["expectedContentHash"] != current["contentHash"]
            ):
                raise SuccesNoteConflict(
                    "Cette note a été modifiée dans une autre fenêtre. "
                    "Ton brouillon est conservé ; enregistre-le comme copie."
                )
            valeurs = {**current, **patch}
            if "appendContent" in patch:
                if "content" in patch:
                    raise SuccesError("Choisis l'ajout ou le remplacement du contenu.")
                valeurs["content"] = current["content"] + str(patch["appendContent"])
            title, content, meta = self._note_fields(valeurs)
            conn.execute(
                """UPDATE succes_notes SET title=?,content=?,updated_at=?,
                   updated_at_ms=?,page_format=?,page_size=?,page_orientation=?,
                   page_margins=?,page_background=?,font_family=?,
                   doc_lang=?,color=?,reading_mark=?,category=?,project_id=?
                   WHERE id=?""",
                (
                    title,
                    content,
                    iso_time,
                    timestamp,
                    meta["pageFormat"],
                    meta["pageSize"],
                    meta["pageOrientation"],
                    meta["pageMargins"],
                    meta["pageBackground"],
                    meta["fontFamily"],
                    meta["docLang"],
                    meta["color"],
                    meta["readingMark"],
                    meta["category"],
                    meta["projectId"],
                    note_id,
                ),
            )
            pid = meta["projectId"]
            if pid and self._load_project(conn, pid) is None:
                raise SuccesError("Ce projet n'existe pas ou a été supprimé.")
            note = self._load_note(conn, note_id)
            assert note is not None
            self._record_op(
                conn,
                entity="notes",
                entity_id=note_id,
                kind="upsert",
                payload=note,
                request=request,
                timestamp_ms=timestamp,
                op_id=op_id,
            )
            return note

    @staticmethod
    def _prochain_ordre_note(conn: sqlite3.Connection) -> int:
        """Le rang de la prochaine note : à la FIN. Les tombes comptent, pour
        qu'un pair qui resynchronise une note supprimée ne retombe pas sur un
        rang déjà pris (le patron des tâches, pas celui des photos)."""
        row = conn.execute(
            "SELECT COALESCE(MAX(order_index), -1) + 1 AS n FROM succes_notes"
        ).fetchone()
        return int(row["n"])

    def reorder_notes(self, ids: list[str]) -> list[dict[str, Any]]:
        """Fixe l'ordre manuel des notes citées : order_index = leur rang dans
        `ids`. Seules les notes DONT le rang change sont réécrites et
        journalisées — un glisser parmi dix ne doit pas inonder le journal de
        relève (§5). Une note absente garde son rang ; un id inconnu est ignoré
        en silence (la liste vient du réseau, elle n'est pas de confiance)."""
        propres: list[str] = []
        for note_id in ids:
            nid = str(note_id or "").strip()
            if nid and nid not in propres:
                propres.append(nid)
        timestamp = now_ms()
        changees: list[dict[str, Any]] = []
        with self._transaction() as conn:
            # Un id inconnu ne consomme PAS de rang : il ne pousserait pas les
            # notes réelles d'un cran. Le rang ne compte que les existantes.
            rang = 0
            for note_id in propres:
                row = conn.execute(
                    "SELECT order_index FROM succes_notes"
                    " WHERE id=? AND deleted_at_ms IS NULL",
                    (note_id,),
                ).fetchone()
                if row is None:
                    continue
                index = rang
                rang += 1
                if int(row["order_index"]) == index:
                    continue
                conn.execute(
                    "UPDATE succes_notes SET order_index=?,updated_at_ms=? WHERE id=?",
                    (index, timestamp, note_id),
                )
                note = self._load_note(conn, note_id)
                if note is not None:
                    self._record_op(
                        conn,
                        entity="notes",
                        entity_id=note_id,
                        kind="upsert",
                        payload=note,
                        request={"action": "reorder_note", "order": index},
                        timestamp_ms=timestamp,
                    )
                    changees.append(note)
        return changees

    def list_note_categories(self) -> list[str]:
        """Les catégories vivantes, dans l'ordre choisi par l'utilisateur.

        Une catégorie EXISTE tant qu'une note vivante la porte — il n'y a pas
        d'état séparé à entretenir, donc pas d'orphelines. La table ne garde
        que l'ORDRE ; ses lignes mortes sont élaguées au passage, et une
        catégorie apparue depuis (note importée, synchronisée) se range à la
        fin, par ordre alphabétique.
        """
        with self._transaction() as conn:
            vivantes = {
                str(row["category"])
                for row in conn.execute(
                    """SELECT DISTINCT category FROM succes_notes
                       WHERE deleted_at_ms IS NULL AND category != ''"""
                )
            }
            ordonnees = [
                str(row["name"])
                for row in conn.execute(
                    "SELECT name FROM succes_note_categories ORDER BY order_index"
                )
            ]
            for morte in [n for n in ordonnees if n not in vivantes]:
                conn.execute(
                    "DELETE FROM succes_note_categories WHERE name=?", (morte,)
                )
            gardees = [n for n in ordonnees if n in vivantes]
            return gardees + sorted(vivantes - set(gardees))

    def order_note_categories(self, names: list[str]) -> list[str]:
        """Mémorise l'ordre des sections — celui du glisser de Carlito."""
        propres: list[str] = []
        for name in names:
            nom = _clean_text(name, field="La catégorie", maximum=60)
            if nom and nom not in propres:
                propres.append(nom)
        timestamp = now_ms()
        with self._transaction() as conn:
            for index, nom in enumerate(propres):
                conn.execute(
                    """INSERT INTO succes_note_categories
                       (name,order_index,updated_at_ms)
                       VALUES (?,?,?)
                       ON CONFLICT(name) DO UPDATE
                       SET order_index=excluded.order_index,
                           updated_at_ms=excluded.updated_at_ms""",
                    (nom, index, timestamp),
                )
        return self.list_note_categories()

    def rename_note_category(self, ancien: str, nouveau: str) -> int:
        """Renomme (ou dissout, si `nouveau` est vide) une catégorie entière.

        Chaque note touchée est journalisée une à une : la synchronisation ne
        connaît que des notes, pas des catégories.
        """
        ancien_nom = _clean_text(ancien, field="La catégorie", maximum=60)
        nouveau_nom = _clean_text(nouveau or "", field="La catégorie", maximum=60)
        if not ancien_nom:
            raise SuccesError("La catégorie à renommer est obligatoire.")
        timestamp = now_ms()
        with self._transaction() as conn:
            notes = [
                row["id"]
                for row in conn.execute(
                    """SELECT id FROM succes_notes
                       WHERE deleted_at_ms IS NULL AND category=?""",
                    (ancien_nom,),
                )
            ]
            for note_id in notes:
                conn.execute(
                    """UPDATE succes_notes SET category=?,updated_at_ms=?
                       WHERE id=?""",
                    (nouveau_nom, timestamp, note_id),
                )
                note = self._load_note(conn, note_id)
                if note is not None:
                    self._record_op(
                        conn,
                        entity="notes",
                        entity_id=note_id,
                        kind="upsert",
                        payload=note,
                        request={
                            "action": "rename_note_category",
                            "from": ancien_nom,
                            "to": nouveau_nom,
                        },
                        timestamp_ms=timestamp,
                    )
            # L'ordre suit le nom ; une dissolution retire la ligne.
            if nouveau_nom:
                conn.execute(
                    """UPDATE OR REPLACE succes_note_categories SET name=?
                       WHERE name=?""",
                    (nouveau_nom, ancien_nom),
                )
            else:
                conn.execute(
                    "DELETE FROM succes_note_categories WHERE name=?", (ancien_nom,)
                )
        return len(notes)

    def delete_note(self, note_id: str, *, op_id: str | None = None) -> None:
        note = self.get_note(note_id)
        timestamp = now_ms()
        request = {"action": "delete_note", "noteId": note_id}
        with self._transaction() as conn:
            if (
                op_id
                and conn.execute(
                    "SELECT 1 FROM succes_operations WHERE op_id=?", (op_id,)
                ).fetchone()
            ):
                return
            conn.execute(
                "UPDATE succes_notes SET deleted_at_ms=?,updated_at_ms=? WHERE id=?",
                (timestamp, timestamp, note_id),
            )
            self._record_op(
                conn,
                entity="notes",
                entity_id=note_id,
                kind="delete",
                payload={**note, "deletedAtMs": timestamp},
                request=request,
                timestamp_ms=timestamp,
                op_id=op_id,
            )

    # Dashboard and migration ----------------------------------------

    def dashboard(self, *, on_date: str | None = None) -> dict[str, Any]:
        iso = _validate_iso_date(on_date or date.today().isoformat())
        tasks = self.list_tasks(scheduled_date=iso, include_done=True)
        habits = self.list_habits(on_date=iso)
        due = [habit for habit in habits if habit["due"]]
        return {
            "date": iso,
            "tasks": {
                "total": len(tasks),
                "completed": sum(bool(task["done"]) for task in tasks),
            },
            "habits": {
                "due": len(due),
                "completed": sum(bool(habit["done"]) for habit in due),
            },
            "projects": len(self.list_projects()),
            "notes": len(self.list_notes()),
        }

    def materialize_archived_snapshots(self) -> None:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT snapshot_json FROM succes_imports ORDER BY imported_at_ms"
            ).fetchall()
        for row in rows:
            try:
                snapshot = json.loads(row["snapshot_json"])
            except (TypeError, json.JSONDecodeError):
                continue
            self._materialize_workspace_snapshot(snapshot)

    def import_legacy_snapshot(
        self, snapshot: Mapping[str, Any], *, source: str = "Life OS PHP/Flutter"
    ) -> dict[str, Any]:
        summary = super().import_legacy_snapshot(snapshot, source=source)
        workspace = self._materialize_workspace_snapshot(snapshot)
        return {**summary, **workspace}

    def _materialize_workspace_snapshot(
        self, snapshot: Mapping[str, Any]
    ) -> dict[str, int]:
        state = (
            snapshot.get("state")
            if isinstance(snapshot.get("state"), Mapping)
            else snapshot
        )
        if not isinstance(state, Mapping):
            return {"habitsImported": 0, "notesImported": 0, "habitLogsImported": 0}
        summary = {"habitsImported": 0, "notesImported": 0, "habitLogsImported": 0}
        with self._transaction() as conn:
            for raw in (
                state.get("habits", []) if isinstance(state.get("habits"), list) else []
            ):
                if not isinstance(raw, Mapping):
                    continue
                habit_id = str(raw.get("id") or "").strip()
                if not habit_id or not str(raw.get("name") or "").strip():
                    continue
                timestamp = _safe_timestamp(raw.get("updatedAtMs"), fallback=0)
                current = conn.execute(
                    "SELECT updated_at_ms FROM succes_habits WHERE id=?", (habit_id,)
                ).fetchone()
                if current and current["updated_at_ms"] >= timestamp:
                    continue
                try:
                    clean = self._validated_habit(raw)
                except SuccesError:
                    continue
                conn.execute(
                    """INSERT INTO succes_habits
                       (id,name,icon,color,frequency,created_date,start_date,end_date,
                        weekly_days_json,month_week_slots_json,month_week_day,
                        reminder_time,updated_at_ms,deleted_at_ms)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)
                       ON CONFLICT(id) DO UPDATE SET name=excluded.name,
                       icon=excluded.icon,color=excluded.color,frequency=excluded.frequency,
                       created_date=excluded.created_date,start_date=excluded.start_date,
                       end_date=excluded.end_date,weekly_days_json=excluded.weekly_days_json,
                       month_week_slots_json=excluded.month_week_slots_json,
                       month_week_day=excluded.month_week_day,
                       reminder_time=excluded.reminder_time,
                       updated_at_ms=excluded.updated_at_ms,deleted_at_ms=NULL""",
                    (
                        habit_id,
                        clean["name"],
                        clean["icon"],
                        clean["color"],
                        clean["frequency"],
                        str(raw.get("createdAt") or clean["startDate"]),
                        clean["startDate"],
                        clean["endDate"],
                        json.dumps(clean["weeklyDays"]),
                        json.dumps(clean["monthWeekSlots"]),
                        clean["monthWeekDay"],
                        clean["reminderTime"],
                        timestamp,
                    ),
                )
                summary["habitsImported"] += 1
            for raw in (
                state.get("notes", []) if isinstance(state.get("notes"), list) else []
            ):
                if not isinstance(raw, Mapping):
                    continue
                note_id = str(raw.get("id") or "").strip()
                if not note_id or not str(raw.get("title") or "").strip():
                    continue
                timestamp = _safe_timestamp(raw.get("updatedAtMs"), fallback=0)
                current = conn.execute(
                    "SELECT updated_at_ms FROM succes_notes WHERE id=?", (note_id,)
                ).fetchone()
                if current and current["updated_at_ms"] >= timestamp:
                    continue
                try:
                    title, content, meta = self._note_fields(raw)
                except SuccesError:
                    continue
                conn.execute(
                    """INSERT INTO succes_notes
                       (id,title,content,created_at,updated_at,updated_at_ms,deleted_at_ms,
                        page_format,page_size,page_orientation,page_margins,
                        page_background,font_family,doc_lang,color,reading_mark)
                       VALUES (?,?,?,?,?,?,NULL,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(id) DO UPDATE SET
                       title=excluded.title,content=excluded.content,
                       created_at=excluded.created_at,updated_at=excluded.updated_at,
                       updated_at_ms=excluded.updated_at_ms,deleted_at_ms=NULL,
                       page_format=excluded.page_format,
                       page_size=excluded.page_size,
                       page_orientation=excluded.page_orientation,
                       page_margins=excluded.page_margins,
                       page_background=excluded.page_background,
                       font_family=excluded.font_family,doc_lang=excluded.doc_lang,
                       color=excluded.color,reading_mark=excluded.reading_mark""",
                    (
                        note_id,
                        title,
                        content,
                        str(raw.get("createdAt") or ""),
                        str(raw.get("updatedAt") or ""),
                        timestamp,
                        meta["pageFormat"],
                        meta["pageSize"],
                        meta["pageOrientation"],
                        meta["pageMargins"],
                        meta["pageBackground"],
                        meta["fontFamily"],
                        meta["docLang"],
                        meta["color"],
                        meta["readingMark"],
                    ),
                )
                summary["notesImported"] += 1
            logs = (
                state.get("habitLogs")
                if isinstance(state.get("habitLogs"), Mapping)
                else {}
            )
            logs_at = (
                state.get("habitLogsAt")
                if isinstance(state.get("habitLogsAt"), Mapping)
                else {}
            )
            for key, value in logs_at.items():
                raw_key = str(key)
                habit_id, separator, iso = raw_key.rpartition("_")
                if not separator or not habit_id:
                    continue
                try:
                    _validate_iso_date(iso)
                except SuccesError:
                    continue
                if not conn.execute(
                    "SELECT 1 FROM succes_habits WHERE id=? AND deleted_at_ms IS NULL",
                    (habit_id,),
                ).fetchone():
                    continue
                timestamp = _safe_timestamp(value, fallback=0)
                current = conn.execute(
                    """SELECT updated_at_ms FROM succes_habit_logs
                       WHERE habit_id=? AND log_date=?""",
                    (habit_id, iso),
                ).fetchone()
                if current and current["updated_at_ms"] >= timestamp:
                    continue
                conn.execute(
                    """INSERT INTO succes_habit_logs
                       (habit_id,log_date,done,updated_at_ms)
                       VALUES (?,?,?,?) ON CONFLICT(habit_id,log_date) DO UPDATE SET
                       done=excluded.done,updated_at_ms=excluded.updated_at_ms""",
                    (habit_id, iso, int(bool(logs.get(key))), timestamp),
                )
                summary["habitLogsImported"] += 1
        return summary


__all__ = [
    "HABIT_FREQUENCIES",
    "NOTE_DOC_LANGS",
    "NOTE_FONTS",
    "NOTE_PAGE_BACKGROUNDS",
    "NOTE_PAGE_FORMATS",
    "SuccesWorkspaceStore",
]
