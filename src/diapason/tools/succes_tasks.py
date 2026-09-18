"""Closed, typed Succès task tools available to DIA."""

from __future__ import annotations

from typing import Any, Mapping

from diapason.core.registry import ToolRegistry
from diapason.core.types import ToolResult
from diapason.succes.dates import normalize_time, resolve_date_expression
from diapason.succes.reseau import cle_titre
from diapason.succes.store import SuccesError, SuccesStore
from diapason.succes.workspace import SuccesWorkspaceStore
from diapason.tools._stubs import BaseTool, ToolSpec

_STATUT_FR = {"done": "faite", "feasible": "faisable maintenant", "blocked": "bloquée"}


def _citer(titres: list[str]) -> str:
    """« A », « A » et « B », « A », « B » et « C » — comme `citer` de reseau.ts."""
    guillemets = [f"« {t} »" for t in titres]
    if len(guillemets) <= 1:
        return "".join(guillemets)
    return ", ".join(guillemets[:-1]) + " et " + guillemets[-1]


@ToolRegistry.register("succes_tasks")
class SuccesTasksTool(BaseTool):
    """Routine, reversible task operations. Deletion is intentionally absent."""

    tool_id = "succes_tasks"
    is_local = True

    def __init__(self, store: SuccesStore | None = None) -> None:
        # Le magasin complet par défaut (18 sept. 2026) : les arêtes du
        # réseau y vivent, et `SuccesWorkspaceStore` est un `SuccesStore` —
        # tout ce qui marchait marche encore.
        self._store = store or SuccesWorkspaceStore()

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="succes_tasks",
            description=(
                "Manage the user's private Succès tasks on this Mac. Supports listing, "
                "creating, completing/reopening, rescheduling, and adding or toggling "
                "subtasks. Never claims remote sync. Deletion and bulk changes "
                "are not allowed. "
                # Le réseau (18 sept. 2026) : sans ces quatre actions, la
                # souris était l'unique chemin pour relier deux tâches ou
                # savoir ce qu'une tâche attend (§82).
                "Network projects: `link` (from_task unlocks to_task), `unlink`, "
                "`branches` (what a task waits for and what it unlocks) and "
                "`next_actions` (what can be done now, most unlocking first). "
                "These take `project` (name) or `project_id`, and tasks by exact "
                "ID or by title; an ambiguous title is refused with the candidates "
                "— ask the user which one, never guess. "
                # Sans cette phrase, un modèle 9b appelle list sans date et
                # reçoit les quatre-vingt-cinq tâches d'un coup — dont il ne
                # voit qu'un extrait, et sur lequel il répond de travers. La
                # question posée est presque toujours datée (« aujourd'hui »,
                # « demain », « cette semaine ») : le dire ici coûte une ligne
                # et change la réponse.
                "When listing, ALWAYS pass `date` if the question is about a "
                "day — 'aujourd'hui', 'demain', '2026-08-22'. Listing without a "
                "date returns every task ever created, which is rarely what was "
                "asked."
            ),
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "list",
                            "create",
                            "complete",
                            "reopen",
                            "reschedule",
                            "add_subtask",
                            "toggle_subtask",
                            "link",
                            "unlink",
                            "branches",
                            "next_actions",
                        ],
                    },
                    "task_id": {"type": "string"},
                    "project_id": {
                        "type": "string",
                        "description": "Exact project ID (network actions).",
                    },
                    "project": {
                        "type": "string",
                        "maxLength": 120,
                        "description": "Project name, e.g. AgriCulture (network).",
                    },
                    "task": {
                        "type": "string",
                        "maxLength": 200,
                        "description": "Task ID or title, for `branches`.",
                    },
                    "from_task": {
                        "type": "string",
                        "maxLength": 200,
                        "description": "ID or title of the task that unlocks to_task.",
                    },
                    "to_task": {
                        "type": "string",
                        "maxLength": 200,
                        "description": "ID or title of the task that waits.",
                    },
                    "title": {"type": "string", "maxLength": 200},
                    "date": {
                        "type": "string",
                        "description": "Exact or spoken date, e.g. 2026-08-14, demain.",
                    },
                    "time": {"type": "string", "description": "Optional HH:mm."},
                    "priority": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "urgent"],
                    },
                    "notes": {"type": "string", "maxLength": 2000},
                    "subtask_id": {"type": "string"},
                    "subtask_title": {"type": "string", "maxLength": 200},
                    "parent_id": {"type": "string"},
                    "done": {"type": "boolean"},
                },
                "required": ["action"],
            },
            category="succes",
            metadata={"risk": "routine_write", "reversible": True},
        )

    def execute(self, **params: Any) -> ToolResult:
        action = str(params.get("action") or "")
        try:
            if action == "list":
                scheduled = self._resolve_optional_date(params.get("date"))
                tasks = self._store.list_tasks(
                    scheduled_date=scheduled,
                    include_done=bool(params.get("done", True)),
                )
                return self._ok(
                    f"{len(tasks)} tâche(s) trouvée(s).",
                    {"tasks": tasks, "persistence": "local"},
                )
            if action == "create":
                title = str(params.get("title") or "").strip()
                if not title:
                    return self._fail("Le titre de la tâche est obligatoire.")
                scheduled = self._resolve_optional_date(params.get("date"))
                task = self._store.create_task(
                    {
                        "title": title,
                        "date": scheduled or "",
                        "time": normalize_time(str(params.get("time") or "")),
                        "priority": params.get("priority") or "medium",
                        "notes": params.get("notes") or "",
                    }
                )
                return self._ok(
                    f"Tâche créée : {task['title']}",
                    {"task": task, "persistence": "local"},
                )
            if action in {"link", "unlink", "branches", "next_actions"}:
                return self._reseau(action, params)
            task_id = str(params.get("task_id") or "").strip()
            if not task_id:
                return self._fail("L'identifiant exact de la tâche est obligatoire.")
            if action in {"complete", "reopen"}:
                task = self._store.set_task_done(task_id, action == "complete")
                verb = "terminée" if task["done"] else "rouverte"
                return self._ok(
                    f"Tâche {verb} : {task['title']}",
                    {"task": task, "persistence": "local"},
                )
            if action == "reschedule":
                scheduled = self._resolve_required_date(params.get("date"))
                task = self._store.reschedule_task(task_id, scheduled)
                warning = (
                    " Cette tâche a été reportée au moins quatre fois; "
                    "proposez de la découper."
                    if task["postponedCount"] >= 4
                    else ""
                )
                return self._ok(
                    f"Tâche reportée au {scheduled}.{warning}",
                    {"task": task, "persistence": "local"},
                )
            if action == "add_subtask":
                title = str(params.get("subtask_title") or "").strip()
                if not title:
                    return self._fail("Le titre de la sous-tâche est obligatoire.")
                task = self._store.add_subtask(
                    task_id, title, parent_id=str(params.get("parent_id") or "") or None
                )
                return self._ok(
                    f"Sous-tâche ajoutée à {task['title']}.",
                    {"task": task, "persistence": "local"},
                )
            if action == "toggle_subtask":
                subtask_id = str(params.get("subtask_id") or "").strip()
                if not subtask_id:
                    return self._fail(
                        "L'identifiant exact de la sous-tâche est obligatoire."
                    )
                task = self._store.set_subtask_done(
                    task_id, subtask_id, bool(params.get("done", True))
                )
                return self._ok(
                    f"Sous-tâche mise à jour dans {task['title']}.",
                    {"task": task, "persistence": "local"},
                )
            return self._fail(f"Action Succès inconnue : {action}")
        except (SuccesError, ValueError) as exc:
            return self._fail(str(exc))

    # ── Le réseau à la voix (18 sept. 2026) ────────────────────────────────

    def _workspace(self) -> SuccesWorkspaceStore:
        if not isinstance(self._store, SuccesWorkspaceStore):
            raise SuccesError(
                "Le module Succès complet n'est pas initialisé : le réseau est "
                "hors de portée."
            )
        return self._store

    def _resoudre_projet(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """Un id exact, sinon un nom : deux projets qui correspondent → on
        demande (§34), jamais le premier venu."""
        store = self._workspace()
        project_id = str(params.get("project_id") or "").strip()
        if project_id:
            return store.get_project(project_id)
        nom = str(params.get("project") or "").strip()
        if not nom:
            raise SuccesError("Le projet est obligatoire : son nom ou son identifiant.")
        candidats = store.list_projects(search=nom)
        exacts = [p for p in candidats if cle_titre(p["name"]) == cle_titre(nom)]
        if len(exacts) == 1:
            return exacts[0]
        if not candidats:
            raise SuccesError(f"Aucun projet ne s'appelle « {nom} ».")
        if len(candidats) > 1:
            raise SuccesError(
                f"Plusieurs projets correspondent à « {nom} » : "
                + _citer([p["name"] for p in candidats])
                + ". Demandez à l'utilisateur lequel."
            )
        return candidats[0]

    @staticmethod
    def _resoudre_tache(
        taches: list[dict[str, Any]], valeur: Any, *, role: str
    ) -> dict[str, Any]:
        """Un id exact d'abord, sinon un titre : entier avant fragment, et
        deux titres qui correspondent encore → on demande (§34). « contrat »
        désigne à la fois « Discuter du contrat… » et « Contrat | Paiement… »
        dans AgriCulture : deviner relierait la mauvaise."""
        texte = str(valeur or "").strip()
        if not texte:
            raise SuccesError(f"La tâche {role} est obligatoire : son titre ou son id.")
        for tache in taches:
            if tache["id"] == texte:
                return tache
        cle = cle_titre(texte)
        exacts = [t for t in taches if cle_titre(str(t["title"])) == cle]
        if len(exacts) == 1:
            return exacts[0]
        partiels = exacts or [t for t in taches if cle in cle_titre(str(t["title"]))]
        if not partiels:
            raise SuccesError(
                f"Aucune tâche de ce projet ne s'appelle « {texte} » ({role})."
            )
        if len(partiels) > 1:
            raise SuccesError(
                f"Plusieurs tâches correspondent à « {texte} » ({role}) : "
                + _citer([str(t["title"]) for t in partiels])
                + ". Demandez à l'utilisateur laquelle."
            )
        return partiels[0]

    def _reseau(self, action: str, params: Mapping[str, Any]) -> ToolResult:
        store = self._workspace()
        projet = self._resoudre_projet(params)
        pid = projet["id"]
        if action == "next_actions":
            actions = store.prochaines_actions(pid)
            if not actions:
                return self._ok(
                    f"Rien n'est faisable maintenant dans « {projet['name']} » : "
                    "tout est fait, ou tout attend.",
                    {"projectId": pid, "nextActions": [], "persistence": "local"},
                )
            lignes = []
            for a in actions:
                suite = (
                    f" (débloque {_citer([u['title'] for u in a['unlocks']])})"
                    if a["unlocks"]
                    else ""
                )
                lignes.append(f"« {a['title']} »{suite}")
            return self._ok(
                f"Faisable maintenant dans « {projet['name']} », la plus utile "
                f"d'abord : {' ; '.join(lignes)}.",
                {"projectId": pid, "nextActions": actions, "persistence": "local"},
            )
        taches = store.list_project_tasks(pid)
        if action == "branches":
            tache = self._resoudre_tache(taches, params.get("task"), role="demandée")
            branches = store.branches_de(pid, tache["id"])
            statut = _STATUT_FR[branches["status"]]
            phrase = f"« {tache['title']} » est {statut}."
            if branches["missing"]:
                phrase += (
                    " Attend " + _citer([t["title"] for t in branches["missing"]]) + "."
                )
            elif branches["upstream"]:
                phrase += " Ses attentes sont toutes faites."
            else:
                phrase += " Rien à attendre."
            if branches["downstream"]:
                phrase += (
                    " Débloque "
                    + _citer([t["title"] for t in branches["downstream"]])
                    + "."
                )
                if branches["unlocks"] and branches["status"] != "done":
                    phrase += (
                        " La terminer ouvre "
                        + _citer([t["title"] for t in branches["unlocks"]])
                        + "."
                    )
                if branches["impact"] >= 2:
                    phrase += f" {branches['impact']} tâches ouvertes en aval."
            else:
                phrase += " Ne débloque rien."
            return self._ok(
                phrase, {**branches, "projectId": pid, "persistence": "local"}
            )
        de = self._resoudre_tache(taches, params.get("from_task"), role="qui débloque")
        vers = self._resoudre_tache(taches, params.get("to_task"), role="qui attend")
        if action == "unlink":
            store.delete_task_edge(pid, de["id"], vers["id"])
            restantes = store.list_task_edges(pid)
            if any(
                e["fromTaskId"] == de["id"] and e["toTaskId"] == vers["id"]
                for e in restantes
            ):
                return self._fail(
                    f"Le lien « {de['title']} » → « {vers['title']} » est encore là "
                    "après la suppression."
                )
            return self._ok(
                f"Lien supprimé : « {de['title']} » ne débloque plus "
                f"« {vers['title']} ».",
                {
                    "projectId": pid,
                    "fromTaskId": de["id"],
                    "toTaskId": vers["id"],
                    "persistence": "local",
                },
            )
        # `link`. La boucle est refusée par `create_task_edge` avec sa phrase,
        # relayée mot pour mot par `except SuccesError` ; un lien qui existait
        # déjà est rendu tel quel par le serveur sans nouvelle op, et on le dit.
        existait = any(
            e["fromTaskId"] == de["id"] and e["toTaskId"] == vers["id"]
            for e in store.list_task_edges(pid)
        )
        arete = store.create_task_edge(pid, de["id"], vers["id"])
        # La phrase cite l'arête RENVOYÉE, jamais la demande (§100).
        par_id = {t["id"]: t for t in taches}
        source = par_id.get(arete["fromTaskId"], de)
        cible = par_id.get(arete["toTaskId"], vers)
        branches = store.branches_de(pid, arete["toTaskId"])
        etat = _STATUT_FR[branches["status"]]
        prefixe = "Ce lien existait déjà" if existait else "Lien créé"
        return self._ok(
            f"{prefixe} : « {source['title']} » débloque « {cible['title']} ». "
            f"« {cible['title']} » est maintenant {etat}.",
            {
                "edge": arete,
                "alreadyExisted": existait,
                "target": branches["task"],
                "persistence": "local",
            },
        )

    @staticmethod
    def _resolve_required_date(value: Any) -> str:
        resolution = resolve_date_expression(str(value or ""))
        if resolution.status == "ambiguous":
            raise SuccesError(
                "Cette date est ambiguë. Demandez à l'utilisateur de choisir entre "
                + " et ".join(resolution.options)
                + "."
            )
        if resolution.status != "exact" or not resolution.value:
            raise SuccesError(
                "Je n'ai pas reconnu cette date. Demandez une date précise."
            )
        return resolution.value

    @classmethod
    def _resolve_optional_date(cls, value: Any) -> str | None:
        if not str(value or "").strip():
            return None
        return cls._resolve_required_date(value)

    def _ok(self, content: str, metadata: dict[str, Any]) -> ToolResult:
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=content,
            metadata=metadata,
        )

    def _fail(self, content: str) -> ToolResult:
        return ToolResult(
            tool_name=self.spec.name,
            success=False,
            content=content,
            metadata={"persistence": "unchanged"},
        )


@ToolRegistry.register("succes_delete_task")
class SuccesDeleteTaskTool(BaseTool):
    """Single-task deletion, always routed through Diapason approval."""

    tool_id = "succes_delete_task"
    is_local = True

    def __init__(self, store: SuccesStore | None = None) -> None:
        self._store = store or SuccesStore()

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="succes_delete_task",
            description=(
                "Delete exactly one private Succès task by its exact ID. This is a "
                "sensitive action and must wait for the user's approval. Never infer "
                "an ID and never use it for bulk deletion."
            ),
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "Exact task ID returned by succes_tasks list.",
                    }
                },
                "required": ["task_id"],
            },
            category="succes",
            requires_confirmation=True,
            metadata={"risk": "impactful", "reversible": False},
        )

    def execute(self, **params: Any) -> ToolResult:
        task_id = str(params.get("task_id") or "").strip()
        if not task_id:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content="L'identifiant exact de la tâche est obligatoire.",
                metadata={"persistence": "unchanged"},
            )
        try:
            task = self._store.get_task(task_id)
            self._store.delete_task(task_id)
        except SuccesError as exc:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content=str(exc),
                metadata={"persistence": "unchanged"},
            )
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=f"Tâche supprimée : {task['title']}",
            metadata={"deletedId": task_id, "persistence": "local"},
        )


__all__ = ["SuccesDeleteTaskTool", "SuccesTasksTool"]
