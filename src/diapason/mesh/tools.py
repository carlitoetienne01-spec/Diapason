"""What may be asked of a device remotely — and nothing else.

Spec §21 forbids a universal tool. That is not a style preference: an
assistant that can call ``remote.execute(action, params)`` has, in practice,
been handed the other device's shell, and every permission check upstream
becomes decoration. The prohibition is enforced structurally here —

* every tool declares its parameters by name, with a type;
* unknown parameters are refused, never forwarded;
* no parameter may be named ``action``, ``command``, ``method``, ``code``,
  ``script`` or ``sql`` — the shapes a passthrough always takes;
* a tool with no declared parameters accepts no arguments at all.

A test (``test_no_universal_tool``) re-checks these on the whole registry, so
adding a fourteenth tool cannot quietly reintroduce the thirteenth's escape
hatch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

__all__ = [
    "RemoteToolSpec",
    "REMOTE_TOOLS",
    "get_remote_tool",
    "list_remote_tools",
    "FORBIDDEN_PARAMETER_NAMES",
]

# Parameter names that betray a passthrough. A tool wanting one of these is
# not a narrow tool; it is a shell wearing a costume.
FORBIDDEN_PARAMETER_NAMES = frozenset(
    {
        "action",
        "command",
        "method",
        "code",
        "script",
        "sql",
        "query",
        "exec",
        "eval",
        "path",
        "url",
        "shell",
    }
)

_ALLOWED_TYPES = {"string", "integer", "boolean"}


@dataclass(frozen=True)
class RemoteToolSpec:
    """One narrow, explicitly-shaped remote capability."""

    name: str
    description: str
    capability: str
    #: name -> {"type": str, "required": bool, "enum": tuple[str, ...], "max": int}
    parameters: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    #: Impactful tools may not run without an explicit confirmation (spec §35).
    requires_confirmation: bool = False
    #: What to do when the target is unreachable (spec §44).
    offline_policy: str = "QUEUE_UNTIL_EXPIRATION"

    def validate(self, arguments: Mapping[str, Any]) -> None:
        """Refuse anything the tool did not explicitly ask for."""
        from diapason.mesh.commands import CommandRejected

        if not isinstance(arguments, Mapping):
            raise CommandRejected("DENIED", "Les arguments sont illisibles.")

        unknown = set(arguments) - set(self.parameters)
        if unknown:
            raise CommandRejected(
                "DENIED",
                f"Paramètre non reconnu pour « {self.name} » : "
                f"{', '.join(sorted(unknown))}.",
            )

        for key, rule in self.parameters.items():
            if key not in arguments:
                if rule.get("required"):
                    raise CommandRejected(
                        "DENIED", f"Le paramètre « {key} » est obligatoire."
                    )
                continue
            value = arguments[key]
            expected = rule.get("type", "string")
            if expected == "string":
                if not isinstance(value, str):
                    raise CommandRejected(
                        "DENIED", f"Le paramètre « {key} » doit être du texte."
                    )
                if len(value) > int(rule.get("max", 500)):
                    raise CommandRejected(
                        "DENIED", f"Le paramètre « {key} » est trop long."
                    )
            elif expected == "integer" and not isinstance(value, int):
                raise CommandRejected(
                    "DENIED", f"Le paramètre « {key} » doit être un nombre."
                )
            elif expected == "boolean" and not isinstance(value, bool):
                raise CommandRejected(
                    "DENIED", f"Le paramètre « {key} » doit être vrai ou faux."
                )
            choices = rule.get("enum")
            if choices and value not in choices:
                raise CommandRejected(
                    "DENIED",
                    f"Valeur non autorisée pour « {key} ».",
                )


# The catalogue. Deliberately small: each entry is a verb someone can picture,
# not a category that could grow to mean anything.
REMOTE_TOOLS: dict[str, RemoteToolSpec] = {
    "app.navigate": RemoteToolSpec(
        name="app.navigate",
        description="Ouvrir un écran de Succès sur l'appareil cible.",
        capability="app.navigate",
        parameters={
            # A route, not a URL: the target resolves it against its own
            # router, so nothing outside the app can be addressed.
            "route": {"type": "string", "required": True, "max": 300},
        },
        offline_policy="REQUIRE_ONLINE",
    ),
    "app.show_resource": RemoteToolSpec(
        name="app.show_resource",
        description="Afficher une tâche, un projet ou une note précise.",
        capability="app.show_resource",
        parameters={
            "resourceType": {
                "type": "string",
                "required": True,
                "enum": ("task", "project", "note", "habit"),
            },
            "resourceId": {"type": "string", "required": True, "max": 120},
        },
        offline_policy="QUEUE_UNTIL_EXPIRATION",
    ),
    "desktop.open": RemoteToolSpec(
        name="desktop.open",
        description=(
            "Ouvrir une application, une adresse, un fichier ou une "
            "recherche sur l'ORDINATEUR cible."
        ),
        capability="desktop.open",
        parameters={
            # Volontairement non contrainte : le propriétaire a choisi la
            # portée ouverte en connaissance de cause. La cible est passée
            # telle quelle à open_anything, qui porte déjà ses garde-fous —
            # un second jeu de règles ici finirait par diverger du premier.
            "target": {"type": "string", "required": True, "max": 500},
            "kind": {
                "type": "string",
                "required": False,
                "enum": ("auto", "app", "url", "search", "file"),
            },
        },
        # Ouvrir quelque chose des heures plus tard, sur une machine dont on
        # ne sait plus ce qu'elle affiche, serait une surprise, pas un
        # service.
        offline_policy="REQUIRE_ONLINE",
        # Le SEUL verbe du catalogue qui sorte de l'application pour piloter
        # le bureau, et le seul à portée ouverte. Il exige donc que
        # l'émetteur atteste avoir obtenu l'accord de l'utilisateur : le
        # récepteur refuse une enveloppe qui ne le porte pas (contrôle 10 de
        # verify_command). Avant le 25 août 2026, aucun outil ne déclarait
        # cette exigence — le contrôle existait sans jamais s'exercer, et un
        # relecteur y voyait une garantie qui n'en était pas une.
        requires_confirmation=True,
    ),
    "app.open": RemoteToolSpec(
        name="app.open",
        description="Mettre Succès au premier plan sur l'appareil cible.",
        capability="app.open",
        parameters={},
        offline_policy="REQUIRE_ONLINE",
    ),
    "notifications.show": RemoteToolSpec(
        name="notifications.show",
        description="Afficher une notification sur l'appareil cible.",
        capability="notifications.show",
        parameters={
            "title": {"type": "string", "required": True, "max": 120},
            "body": {"type": "string", "required": False, "max": 400},
        },
        # A notification is the one thing worth keeping for a sleeping phone.
        offline_policy="QUEUE_UNTIL_EXPIRATION",
    ),
}


def get_remote_tool(name: str) -> RemoteToolSpec | None:
    return REMOTE_TOOLS.get(str(name or ""))


def list_remote_tools() -> list[dict[str, Any]]:
    """The catalogue, as the assistant's tool router should advertise it."""
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "capability": spec.capability,
            "parameters": {
                key: dict(rule) for key, rule in sorted(spec.parameters.items())
            },
            "requiresConfirmation": spec.requires_confirmation,
            "offlinePolicy": spec.offline_policy,
        }
        for spec in sorted(REMOTE_TOOLS.values(), key=lambda s: s.name)
    ]
