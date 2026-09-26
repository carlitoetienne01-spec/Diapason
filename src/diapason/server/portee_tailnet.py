"""Ce que le téléphone a le droit d'atteindre par le tailnet — route par route.

26/09/2026, phase 2 du plan mobile (étape 3). La passerelle du socket 8002
(``server/passerelle_tailnet.py``) enveloppe l'application ENTIÈRE : sans
ce tableau, tout ce que la loopback sait faire deviendrait joignable depuis
le téléphone dès que ``tailscale serve`` le relaie — y compris ce qu'une
autre session ajoutera demain sans penser au téléphone.

Trois classes, et une règle qui les gouverne : **une liste d'autorisation,
pas une liste de refus**.

* ``ouverte`` — sans session : ``/health``, les neuf portes du maillage (qui
  portent déjà une créance plus forte que la clé : signature, invitation ou
  jeton de transfert) et les deux portes qui ouvrent une session.
* ``session`` — le cookie d'appareil est exigé.
* ``refusee`` — 403, avec une phrase qui dit pourquoi.

Ouverte et session ne s'accordent qu'à une clé EXACTE (« MÉTHODE /gabarit »
de la route, tel que Starlette le déclare). Seul le REFUS s'accorde aussi
par famille de préfixe : refuser large ne coûte qu'un 403, autoriser large
exposerait la prochaine route de la famille sans que personne l'ait décidé.
Une route qu'aucune règle ne nomme est refusée — et
``tests/contract/tailnet_portee.json`` fait échouer la suite tant qu'elle
n'est pas classée ici.
"""

from __future__ import annotations

from typing import Iterable

__all__ = [
    "OUVERTE",
    "SESSION",
    "REFUSEE",
    "ROUTES_DE_LA_PASSERELLE",
    "classer",
    "motif_du_refus",
    "cle_de_route",
    "portee_de_l_app",
]

OUVERTE = "ouverte"
SESSION = "session"
REFUSEE = "refusee"

# Les deux portes que la passerelle sert ELLE-MÊME, sans les demander à
# l'application : elles n'ont de sens que sur ce socket, et montées dans
# l'app principale elles seraient une route de plus sur la loopback.
ROUTES_DE_LA_PASSERELLE = (
    "POST /v1/appareil/session",
    "POST /v1/appareil/ouvrir",
)


def _lignes(bloc: str, prefixe: str = "") -> frozenset[str]:
    """« GET /chemin » par ligne ; *prefixe* s'insère devant le chemin."""
    cles = set()
    for ligne in bloc.strip().splitlines():
        methode, _, chemin = ligne.strip().partition(" ")
        if methode:
            cles.add(f"{methode} {prefixe}{chemin}")
    return frozenset(cles)


def _portes_du_maillage() -> frozenset[str]:
    # Lues dans app.py plutôt que recopiées : les neuf portes du LAN sont
    # UNE vérité, et une copie ici aurait divergé à la première porte
    # ajoutée. Toutes sont des POST ; une porte en GET ajoutée demain ne
    # correspondrait à aucune clé d'ici, donc serait refusée — le sens sûr.
    from diapason.server.app import _PORTES_LAN

    return frozenset(f"POST {chemin}" for chemin in _PORTES_LAN)


# ── ouvertes ─────────────────────────────────────────────────────────────
#
# /health sert de sonde à la coquille (phase 3, étape 7) : sans réponse,
# elle affiche « Mac injoignable » au lieu d'un bundle en cache qui
# échouerait action par action.
_OUVERTES = frozenset({"GET /health", *ROUTES_DE_LA_PASSERELLE}) | _portes_du_maillage()

# ── session ──────────────────────────────────────────────────────────────
#
# Le domaine vie, sauf sa synchronisation (plus bas). Écrit route par
# route, et c'est voulu : une route de vie ajoutée demain reste fermée au
# téléphone tant qu'on ne l'a pas écrite ici.
_VIE = _lignes(
    """
    DELETE /finances/accounts/{account_id}
    DELETE /finances/budgets/{budget_id}
    DELETE /finances/categories/{category_id}
    DELETE /finances/goals/{goal_id}
    DELETE /finances/subscriptions/{sub_id}
    DELETE /finances/transactions/{txn_id}
    DELETE /habits/{habit_id}
    DELETE /notes/{note_id}
    DELETE /photo-piles/{pile_id}
    DELETE /photos/{photo_id}
    DELETE /projects/{project_id}
    DELETE /projects/{project_id}/edges/{from_task_id}/{to_task_id}
    DELETE /quotes/{quote_id}
    DELETE /tasks/{task_id}
    DELETE /tasks/{task_id}/subtasks/{subtask_id}
    DELETE /templates/{template_id}
    GET /dashboard
    GET /export
    GET /finances/accounts
    GET /finances/budgets
    GET /finances/categories
    GET /finances/goals
    GET /finances/overview
    GET /finances/subscriptions
    GET /finances/transactions
    GET /habits
    GET /habits/logs
    GET /notes
    GET /notes/categories
    GET /notes/resumes
    GET /notes/{note_id}
    GET /photo-piles/{pile_id}/photos
    GET /photos/{photo_id}/contenu
    GET /planner
    GET /planner/pastilles
    GET /project-kits
    GET /project-structures
    GET /projects
    GET /projects/{project_id}/edges
    GET /projects/{project_id}/photo-piles
    GET /projects/{project_id}/photos/recherche
    GET /quotes
    GET /tasks
    GET /tasks/{task_id}
    GET /templates
    GET /year-review
    PATCH /finances/accounts/{account_id}
    PATCH /finances/goals/{goal_id}
    PATCH /finances/subscriptions/{sub_id}
    PATCH /habits/{habit_id}
    PATCH /notes/{note_id}
    PATCH /photo-piles/{pile_id}
    PATCH /photos/{photo_id}
    PATCH /projects/{project_id}
    PATCH /tasks/{task_id}
    PATCH /templates/{template_id}
    POST /finances/accounts
    POST /finances/budgets
    POST /finances/categories
    POST /finances/goals
    POST /finances/import/csv
    POST /finances/subscriptions
    POST /finances/subscriptions/materialize
    POST /finances/transactions
    POST /habits
    POST /habits/{habit_id}/log
    POST /import/legacy
    POST /notes
    POST /notes/categories/renommer
    POST /photo-piles/{pile_id}/photos
    POST /photos/exporter
    POST /photos/{photo_id}/ocr
    POST /projects
    POST /projects/{project_id}/cycle/reset
    POST /projects/{project_id}/edges
    POST /projects/{project_id}/photo-piles
    POST /quotes
    POST /tasks
    POST /tasks/{task_id}/done
    POST /tasks/{task_id}/reschedule
    POST /tasks/{task_id}/reschedule-series
    POST /tasks/{task_id}/subtasks
    POST /tasks/{task_id}/subtasks/{subtask_id}/done
    POST /templates
    POST /templates/materialize
    PUT /notes/categories/ordre
    PUT /notes/ordre
    PUT /photo-piles/{pile_id}/ordre
    PUT /projects/ordre
    """,
    prefixe="/v1/vie",
)

# Le reste de ce que le bundle fait dans une WebView : la Discussion, ses
# conversations et ses pièces jointes, les approbations (décidé le
# 25/09/2026 : le téléphone PEUT approuver), les modèles, les agents, la
# mémoire, les tableaux de bord. ``GET /{full_path:path}`` et ``MOUNT
# /assets`` sont le bundle lui-même : ils n'existent que quand
# ``server/static`` est construit, et sans eux la WebView n'a rien à
# afficher.
_PRODUIT = _lignes(
    """
    GET /{full_path:path}
    MOUNT /assets
    GET /api/digest
    GET /api/digest/audio
    POST /api/digest/generate
    GET /api/digest/history
    GET /api/digest/schedule
    POST /api/digest/schedule
    POST /api/research
    GET /comparison
    GET /dashboard
    GET /v1/agents
    POST /v1/agents
    GET /v1/agents/errors
    WS /v1/agents/events
    GET /v1/agents/health
    DELETE /v1/agents/{agent_id}
    POST /v1/agents/{agent_id}/message
    GET /v1/analytics/identity
    GET /v1/approvals/pending
    POST /v1/approvals/{action_id}/approve
    POST /v1/approvals/{action_id}/deny
    GET /v1/budget
    GET /v1/channels
    GET /v1/channels/status
    POST /v1/chat/completions
    POST /v1/chat/documents
    WS /v1/chat/stream
    GET /v1/config
    GET /v1/connectors
    POST /v1/connectors/upload/ingest
    POST /v1/connectors/upload/ingest/files
    GET /v1/connectors/{connector_id}
    GET /v1/connectors/{connector_id}/sync
    GET /v1/conversations
    DELETE /v1/conversations/{conversation_id}
    PUT /v1/conversations/{conversation_id}
    GET /v1/dictation/dictionary
    POST /v1/dictation/dictionary
    POST /v1/dictation/dictionary/learn
    POST /v1/dictation/finalize
    POST /v1/dictation/polish
    POST /v1/feedback
    GET /v1/feedback/stats
    GET /v1/info
    GET /v1/learning/policy
    GET /v1/learning/stats
    GET /v1/managed-agents
    POST /v1/managed-agents
    DELETE /v1/managed-agents/{agent_id}
    GET /v1/managed-agents/{agent_id}
    PATCH /v1/managed-agents/{agent_id}
    GET /v1/managed-agents/{agent_id}/learning
    POST /v1/managed-agents/{agent_id}/learning/run
    GET /v1/managed-agents/{agent_id}/messages
    POST /v1/managed-agents/{agent_id}/messages
    POST /v1/managed-agents/{agent_id}/pause
    POST /v1/managed-agents/{agent_id}/recover
    POST /v1/managed-agents/{agent_id}/resume
    POST /v1/managed-agents/{agent_id}/run
    GET /v1/managed-agents/{agent_id}/state
    GET /v1/managed-agents/{agent_id}/tasks
    POST /v1/managed-agents/{agent_id}/tasks
    DELETE /v1/managed-agents/{agent_id}/tasks/{task_id}
    GET /v1/managed-agents/{agent_id}/tasks/{task_id}
    PATCH /v1/managed-agents/{agent_id}/tasks/{task_id}
    GET /v1/managed-agents/{agent_id}/traces
    GET /v1/managed-agents/{agent_id}/traces/{trace_id}
    GET /v1/memory/config
    POST /v1/memory/index
    POST /v1/memory/search
    GET /v1/memory/stats
    POST /v1/memory/store
    GET /v1/models
    POST /v1/models/prewarm
    GET /v1/optimize/runs
    GET /v1/optimize/runs/{run_id}
    GET /v1/recommended-model
    GET /v1/savings
    GET /v1/sessions
    GET /v1/sessions/{session_id}
    GET /v1/skills
    POST /v1/speech/transcribe
    GET /v1/speech/health
    GET /v1/telemetry/energy
    GET /v1/telemetry/stats
    GET /v1/templates
    POST /v1/templates/{template_id}/instantiate
    GET /v1/tools
    GET /v1/traces
    GET /v1/traces/{trace_id}
    GET /v1/visuals/inkscape
    POST /v1/visuals/inkscape
    POST /v1/visuals/matplotlib
    """
)

_SESSIONS = _VIE | _PRODUIT

# ── refusées ─────────────────────────────────────────────────────────────

_MOTIF_MAILLAGE = (
    "Le plan de contrôle du maillage reste sur le Mac : appairer, envoyer "
    "une commande ou révoquer se fait depuis sa page Appareils."
)
_MOTIF_COMPTE = "Le compte chiffré se gère depuis le Mac."
_MOTIF_GESTES = "Le mode gestes ne se pilote que depuis le Mac."
_MOTIF_ACTIONS = (
    "Les actions sur le Mac ne se commandent pas encore depuis le téléphone "
    "(phase 6 du plan mobile)."
)
_MOTIF_VOIX = (
    "La voix n'est pas encore ouverte au téléphone : elle attend sa coupure "
    "automatique (phase 4 du plan mobile, §78)."
)
_MOTIF_REGLAGES = "Ce réglage du Mac ne se modifie que depuis le Mac."
_MOTIF_SECRETS = "Les clés et les secrets ne quittent pas le Mac."
_MOTIF_ADMIN = "Cette opération d'administration se lance depuis le Mac."
_MOTIF_ALIAS = (
    "L'ancien préfixe /v1/succes n'est pas servi au téléphone : il appelle /v1/vie."
)
_MOTIF_SYNCHRO = "La synchronisation entre deux Diapason se règle depuis le Mac."
_MOTIF_ECRAN = "L'écran du Mac ne se lit ni ne se partage depuis le téléphone."
_MOTIF_DECLENCHEURS = "Les déclencheurs du Mac (mot d'éveil) restent au Mac."
_MOTIF_ENUMERATION = (
    "La description de l'API et les compteurs du serveur ne se lisent que sur le Mac."
)
_MOTIF_WEBHOOKS = "Les webhooks arrivent d'Internet, jamais par le tailnet."
_MOTIF_ENVOI = (
    "Envoyer un message par les canaux du Mac ne se commande pas depuis le téléphone."
)

_REFUSEES: dict[str, str] = {
    "POST /v1/config/set": _MOTIF_REGLAGES,
    "PUT /v1/budget/limits": _MOTIF_REGLAGES,
    "POST /v1/skills": _MOTIF_REGLAGES,
    "DELETE /v1/skills/{skill_name}": _MOTIF_REGLAGES,
    "POST /v1/connectors/{connector_id}/connect": _MOTIF_SECRETS,
    "POST /v1/connectors/{connector_id}/disconnect": _MOTIF_REGLAGES,
    "GET /v1/connectors/{connector_id}/oauth/start": _MOTIF_SECRETS,
    "GET /v1/connectors/{connector_id}/oauth/callback": _MOTIF_SECRETS,
    "POST /v1/connectors/{connector_id}/sync": _MOTIF_ADMIN,
    "POST /v1/cloud/reload": _MOTIF_SECRETS,
    "GET /v1/tools/{tool_name}/credentials/status": _MOTIF_SECRETS,
    "POST /v1/tools/{tool_name}/credentials": _MOTIF_SECRETS,
    "DELETE /v1/tools/{tool_name}/credentials/{key}": _MOTIF_SECRETS,
    "GET /v1/managed-agents/{agent_id}/channels": _MOTIF_SECRETS,
    "POST /v1/managed-agents/{agent_id}/channels": _MOTIF_SECRETS,
    "DELETE /v1/managed-agents/{agent_id}/channels/{binding_id}": _MOTIF_SECRETS,
    "POST /v1/channels/send": _MOTIF_ENVOI,
    "POST /v1/models/pull": _MOTIF_ADMIN,
    "DELETE /v1/models/{model_name:path}": _MOTIF_ADMIN,
    "POST /v1/telemetry/reset": _MOTIF_ADMIN,
    "POST /v1/optimize/runs": _MOTIF_ADMIN,
    "GET /v1/security/scan": _MOTIF_ADMIN,
}

# Refuser par famille : c'est le seul sens où un préfixe est sûr. Le
# préfixe porte sur le GABARIT de la route, jamais sur le chemin reçu.
_FAMILLES_REFUSEES: tuple[tuple[str, str], ...] = (
    ("/v1/succes/", _MOTIF_ALIAS),
    ("/v1/vie/sync/", _MOTIF_SYNCHRO),
    ("/v1/mesh/", _MOTIF_MAILLAGE),
    ("/v1/account/", _MOTIF_COMPTE),
    ("/v1/gestures/", _MOTIF_GESTES),
    ("/v1/actions/", _MOTIF_ACTIONS),
    ("/v1/context/", _MOTIF_ECRAN),
    ("/v1/screen_share/", _MOTIF_ECRAN),
    ("/v1/triggers/", _MOTIF_DECLENCHEURS),
    ("/v1/voice/", _MOTIF_VOIX),
    ("/v1/channels/sendblue/", _MOTIF_SECRETS),
    ("/webhooks/", _MOTIF_WEBHOOKS),
    ("/docs", _MOTIF_ENUMERATION),
    ("/redoc", _MOTIF_ENUMERATION),
    ("/openapi.json", _MOTIF_ENUMERATION),
    ("/metrics", _MOTIF_ENUMERATION),
)

_MOTIF_NON_CLASSEE = (
    "Cette route n'a pas été ouverte au téléphone : elle reste fermée tant "
    "qu'on n'a pas décidé qu'elle le soit."
)


def _chemin_de(cle: str) -> str:
    return cle.partition(" ")[2]


def classer(cle: str) -> str | None:
    """La classe de *cle*, ou None quand aucune règle ne la nomme.

    L'ordre compte : les clés exactes d'abord (une porte du maillage est
    ouverte même si la famille /v1/mesh/ est refusée), puis les familles de
    refus. None se traite comme un refus — c'est la liste d'autorisation.
    """
    if cle in _OUVERTES:
        return OUVERTE
    if cle in _SESSIONS:
        return SESSION
    if cle in _REFUSEES:
        return REFUSEE
    chemin = _chemin_de(cle)
    for prefixe, _motif in _FAMILLES_REFUSEES:
        if chemin.startswith(prefixe):
            return REFUSEE
    return None


def motif_du_refus(cle: str) -> str:
    """La phrase rendue au téléphone pour une route qu'il ne peut atteindre."""
    if cle in _REFUSEES:
        return _REFUSEES[cle]
    chemin = _chemin_de(cle)
    for prefixe, motif in _FAMILLES_REFUSEES:
        if chemin.startswith(prefixe):
            return motif
    return _MOTIF_NON_CLASSEE


def cle_de_route(route, methode: str = "", *, websocket: bool = False) -> str:  # noqa: ANN001
    """« MÉTHODE /gabarit » pour une route Starlette.

    ``WS`` pour une route WebSocket, ``MOUNT`` pour un montage (le bundle
    statique). HEAD se classe comme GET : Starlette sert l'un par l'autre,
    et une classe différente pour les deux ferait d'un HEAD une porte
    dérobée vers une route GET refusée — ou l'inverse.
    """
    from starlette.routing import Mount, WebSocketRoute

    chemin = getattr(route, "path", "")
    if websocket:
        # Un montage n'a rien à faire d'une poignée de main WebSocket : la
        # clé « WS /assets » n'est classée nulle part, donc refusée.
        return f"WS {chemin}"
    if isinstance(route, WebSocketRoute) or type(route).__name__.endswith(
        "WebSocketRoute"
    ):
        return f"WS {chemin}"
    if isinstance(route, Mount):
        return f"MOUNT {chemin}"
    methode = (methode or "GET").upper()
    if methode == "HEAD":
        methode = "GET"
    return f"{methode} {chemin}"


def _cles_declarees(routes: Iterable) -> list[str]:  # noqa: ANN001
    """Toutes les clés qu'un ensemble de routes Starlette déclare."""
    from starlette.routing import Mount

    cles: set[str] = set()
    for route in routes:
        methodes = getattr(route, "methods", None)
        if isinstance(route, Mount) or methodes is None:
            cles.add(cle_de_route(route))
            continue
        for methode in methodes:
            if methode.upper() == "HEAD":
                continue
            cles.add(cle_de_route(route, methode))
    return sorted(cles)


def portee_de_l_app(app) -> dict[str, str | None]:  # noqa: ANN001
    """Chaque route de *app*, plus les portes de la passerelle, et sa classe.

    Ce que ``tests/contract/tailnet_portee.json`` fige, et ce que
    ``scripts/gen_tailnet_portee.py`` régénère. Une valeur None est une
    route que personne n'a classée : le test de contrat la refuse.
    """
    cles = set(_cles_declarees(app.router.routes)) | set(ROUTES_DE_LA_PASSERELLE)
    return {cle: classer(cle) for cle in sorted(cles)}


def cles_autorisees() -> frozenset[str]:
    """Les clés exactes ouvertes ou sous session — pour le test des restes."""
    return _OUVERTES | _SESSIONS
