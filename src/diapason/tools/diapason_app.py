"""Les actions métier de l'application, avec les mêmes modèles et magasins.

27/09/2026 : les outils exposaient cinq actions des finances alors que
l'interface gérait aussi budgets, objectifs et abonnements. Un catalogue
fermé réutilise les handlers réels ; aucun chemin HTTP arbitraire, SQL ou
réglage de sécurité n'est accepté. Les schémas détaillés se consultent à la
demande sans changer la trousse et son préfixe en cache.
"""

from __future__ import annotations

import asyncio
import copy
import inspect
import json
import re
from functools import lru_cache
from typing import Any, get_type_hints

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, ValidationError, create_model

from diapason.core.registry import ToolRegistry
from diapason.core.types import ToolResult
from diapason.tools._stubs import BaseTool, ToolSpec
from diapason.tools.navigation_app import PAGES, naviguer
from diapason.vie.store import VieError

# Liste positive : une route ajoutée au serveur n'accorde pas un pouvoir au
# modèle. Les suppressions passent par un outil distinct et sa cloche.
OPERATIONS = {
    "tasks": "get_task create_task update_task set_task_done reschedule_task "
    "reschedule_task_series create_subtask set_subtask_done",
    "projects": "list_projects list_project_kits list_project_structures "
    "list_task_edges create_task_edge delete_task_edge reset_project_cycle "
    "create_project update_project reorder_projects",
    "habits": "list_habits list_habit_logs create_habit update_habit set_habit_done",
    "notes": "list_note_categories order_note_categories rename_note_category "
    "reorder_notes note_summaries get_note list_notes create_note update_note",
    "planner": "planner planner_pastilles dashboard list_templates create_template "
    "update_template materialize_templates list_quotes create_quote year_review",
    "finances": "list_accounts create_account update_account list_categories "
    "create_category list_transactions create_transaction list_subscriptions "
    "create_subscription update_subscription materialize_subscriptions "
    "list_budgets upsert_budget list_goals create_goal update_goal finance_overview "
    "import_csv",
}
SUPPRESSIONS = {
    "tasks": "delete_task delete_subtask",
    "projects": "delete_project",
    "habits": "delete_habit",
    "notes": "delete_note",
    "planner": "delete_template delete_quote",
    "finances": "delete_account delete_category delete_transaction "
    "delete_subscription delete_budget delete_goal",
}


def _noms(suppression: bool = False) -> dict[str, str]:
    groupes = SUPPRESSIONS if suppression else OPERATIONS
    return {nom: domaine for domaine, noms in groupes.items() for nom in noms.split()}


def _camel(nom: str) -> str:
    return re.sub(r"_([a-z])", lambda m: m[1].upper(), nom)


@lru_cache(maxsize=128)
def _operation(nom: str) -> tuple[Any, type[BaseModel], dict[str, str]]:
    from diapason.vie.routes import router

    if nom not in _noms() and nom not in _noms(True):
        raise ValueError("Cette opération n'appartient pas au catalogue Diapason.")
    routes = [r for r in router.routes if r.endpoint.__name__ == nom]
    if len(routes) != 1:
        raise ValueError("L'opération demandée n'est pas disponible.")
    fonction = routes[0].endpoint
    types = get_type_hints(fonction, include_extras=True)
    champs, liens = {}, {}
    for cle, parametre in inspect.signature(fonction).parameters.items():
        public = _camel(cle)
        liens[public] = cle
        defaut = (
            ...
            if parametre.default is inspect.Parameter.empty
            else copy.copy(parametre.default)
        )
        champs[public] = (types[cle], defaut)
    modele = create_model(
        "Arguments_" + nom, __config__=ConfigDict(extra="forbid"), **champs
    )
    return fonction, modele, liens


def decrire_operation(nom: str) -> dict[str, Any]:
    _, modele, _ = _operation(nom)
    return {
        "operation": nom,
        "tool": "diapason_app_delete" if nom in _noms(True) else "diapason_app",
        "parameters": modele.model_json_schema(),
    }


def executer_operation(nom: str, params: dict[str, Any], *, suppression: bool) -> Any:
    if nom not in _noms(suppression):
        raise ValueError(
            "Opération non autorisée par cet outil ; consulter le catalogue."
        )
    fonction, modele, liens = _operation(nom)
    entree = dict(params)
    if suppression:
        entree["body"] = {**(entree.get("body") or {}), "confirmed": True}
    # Les modèles historiques du HTTP ignorent parfois les champs inconnus.
    # Ici, ignorer « montant » au lieu de « amount » ferait une fausse édition.
    for public, champ in modele.model_fields.items():
        annotation = champ.annotation
        valeur = entree.get(public)
        if (
            isinstance(annotation, type)
            and issubclass(annotation, BaseModel)
            and isinstance(valeur, dict)
        ):
            inconnus = set(valeur) - set(annotation.model_fields)
            if inconnus:
                raise ValueError("Champs inconnus : " + ", ".join(sorted(inconnus)))
    arguments = modele.model_validate(entree)
    transmis = {cle: getattr(arguments, public) for public, cle in liens.items()}
    if inspect.iscoroutinefunction(fonction):
        # ToolExecutor est exécuté dans un fil : les anciennes routes async
        # des finances ne bloquent donc pas la boucle du chat/de la voix.
        resultat = asyncio.run(fonction(**transmis))
    else:
        resultat = fonction(**transmis)
    if nom == "list_budgets":
        from diapason.vie.finances import _year_month

        # Une liste vide en septembre ne dit rien du budget d'octobre.
        resultat = {"yearMonth": _year_month(transmis.get("yearMonth")), **resultat}
    return resultat


@ToolRegistry.register("diapason_app")
class DiapasonAppTool(BaseTool):
    """Catalogue et opérations internes ; les données restent dans Diapason."""

    tool_id = "diapason_app"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description=(
                "Read/create/edit inside Diapason: notes, tasks, projects, habits, "
                "planner and full finances (accounts, transactions, budgets, goals, "
                "subscriptions). Use operation='catalogue' with domain, then "
                "operation='describe' with name for exact parameter schema, then "
                "operation=<name>, params=<arguments>. For example upsert_budget, "
                "create_goal, update_subscription, update_note. params uses body "
                "for record fields and camelCase IDs alongside body: "
                "upsert_budget params={body:{scope:'global',"
                "yearMonth:'2026-10',limit:650}}; "
                "update_note params={noteId:'<returned ID>',"
                "body:{appendContent:'...'}}. "
                "Money is CAD. Read before edits, "
                "upsert_budget creates OR updates that same scope/month. "
                "list_budgets params={yearMonth:'YYYY-MM'} reads that month; "
                "if omitted it reads the current month only. "
                "reuse returned IDs, then verify the result. Financial operations "
                "edit the local ledger only, never move money at a bank. "
                "For task counts/ranges use vie_tasks. "
                "Deletions use diapason_app_delete. Use operation='navigate' and "
                "params={'page': <page from catalogue>} to show an app screen. "
                "Use operation='current_view' to read the currently displayed page."
            ),
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": [
                            "catalogue",
                            "describe",
                            "navigate",
                            "current_view",
                            *sorted(_noms()),
                        ],
                    },
                    "domain": {"type": "string", "enum": list(OPERATIONS)},
                    "name": {
                        "type": "string",
                        "enum": sorted([*_noms(), *_noms(True)]),
                        "description": "Exact operation to describe.",
                    },
                    "params": {
                        "type": "object",
                        "description": "Arguments from describe; body holds edits.",
                    },
                },
                "required": ["operation"],
            },
            category="vie",
            metadata={"risk": "routine_write", "reversible": True},
        )

    def execute(self, **params: Any) -> ToolResult:
        return self._executer(params, suppression=False)

    def _executer(self, params: dict[str, Any], *, suppression: bool) -> ToolResult:
        try:
            operation = str(params.get("operation") or "")
            inconnus = set(params) - {"operation", "domain", "name", "params"}
            if inconnus:
                raise ValueError(
                    "Les arguments de l'opération vont dans params, pas à la racine : "
                    + ", ".join(sorted(inconnus))
                )
            if operation == "catalogue" and not suppression:
                domaine = params.get("domain")
                if domaine is not None and domaine not in OPERATIONS:
                    raise ValueError("Domaine inconnu.")
                donnees = {
                    "pages": PAGES,
                    "catalogue": [
                        {
                            "domain": groupe,
                            "operations": noms.split(),
                            "deleteOperations": SUPPRESSIONS.get(groupe, "").split(),
                        }
                        for groupe, noms in OPERATIONS.items()
                        if domaine is None or groupe == domaine
                    ],
                }
            elif operation == "describe" and not suppression:
                donnees = decrire_operation(str(params.get("name") or ""))
            elif operation == "navigate" and not suppression:
                donnees = naviguer(str((params.get("params") or {}).get("page") or ""))
            elif operation == "current_view" and not suppression:
                from diapason.server.contexte_routes import lire_la_vue

                donnees = lire_la_vue()
            else:
                donnees = executer_operation(
                    operation, params.get("params") or {}, suppression=suppression
                )
            return ToolResult(
                tool_name=self.tool_id,
                success=True,
                content=json.dumps(donnees, ensure_ascii=False, default=str),
                metadata={"operation": operation, "persistence": "local"},
            )
        except (ValueError, TypeError, VieError, HTTPException) as exc:
            if isinstance(exc, HTTPException):
                erreur = exc.detail
            elif isinstance(exc, ValidationError):
                erreur = exc.errors(include_input=False, include_url=False)
            else:
                erreur = str(exc)
            reprise = {"error": erreur}
            if operation in _noms(suppression) and isinstance(
                exc, (ValueError, TypeError)
            ):
                # 27/09/2026 : après « body manquant », le modèle essayait
                # d'autres noms inventés. Le schéma réel rend la reprise utile.
                reprise["expectedParameters"] = decrire_operation(operation)[
                    "parameters"
                ]
            return ToolResult(
                tool_name=self.tool_id,
                success=False,
                content="Échec de l’opération : "
                + json.dumps(reprise, ensure_ascii=False, default=str),
                metadata={"operation": operation},
            )


@ToolRegistry.register("diapason_app_delete")
class DiapasonAppDeleteTool(DiapasonAppTool):
    """Suppression nommée, avec l'approbation commune à l'application."""

    tool_id = "diapason_app_delete"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description=(
                "Delete a named item INSIDE Diapason after approval. Get the exact "
                "ID by reading and the parameters via diapason_app describe. "
                "Never infer an ID."
            ),
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "operation": {"type": "string", "enum": sorted(_noms(True))},
                    "params": {"type": "object"},
                },
                "required": ["operation", "params"],
            },
            category="vie",
            requires_confirmation=True,
            metadata={"risk": "impactful", "reversible": False},
        )

    def execute(self, **params: Any) -> ToolResult:
        return self._executer(params, suppression=True)
