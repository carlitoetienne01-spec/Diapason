"""What a device may be asked to do — and who decides.

The rule this module exists to enforce (spec §6, acceptance TEST I): a
device DECLARES its capabilities, the server GRANTS them. A declaration is
information, never authorisation. A compromised or lying agent that claims
``automation.approved.run`` on an iPhone must not receive it, because the
platform cannot honour it and no amount of insistence changes that.

So every capability passes through two gates:

1. ``PLATFORM_CAPABILITIES`` — what the operating system can actually do.
   This is the honest matrix of spec §26, written once, server-side.
2. the device's own declaration — what this build actually implements, which
   is always a SUBSET of what its platform allows.

Effective = intersection. Never the union, never the claim alone.
"""

from __future__ import annotations

from typing import Iterable

__all__ = [
    "ALL_CAPABILITIES",
    "PLATFORM_CAPABILITIES",
    "effective_capabilities",
    "is_known_capability",
    "platform_allows",
]

# The vocabulary. Narrow, explicit verbs — spec §21 forbids a universal one,
# so there is deliberately no `automation.run_anything` here.
ALL_CAPABILITIES: frozenset[str] = frozenset(
    {
        # data
        "tasks.read",
        "tasks.write",
        "projects.read",
        "projects.write",
        "planning.read",
        "planning.write",
        "notes.read",
        "notes.write",
        "habits.read",
        "habits.write",
        # surface
        "app.open",
        "app.navigate",
        "app.show_resource",
        "notifications.show",
        # input / output
        "voice.input",
        "voice.output",
        "local_ai.available",
        # host
        "filesystem.workspace.read",
        "filesystem.workspace.write",
        "automation.approved.run",
    }
)

_DATA = frozenset(
    {
        "tasks.read",
        "tasks.write",
        "projects.read",
        "projects.write",
        "planning.read",
        "planning.write",
        "notes.read",
        "notes.write",
        "habits.read",
        "habits.write",
    }
)

_SURFACE = frozenset({"app.open", "app.navigate", "app.show_resource"})

# Per-platform ceiling. What each OS genuinely permits an app to do — not
# what we wish it did. iOS gets deep links and notifications; it does not get
# OS automation or arbitrary filesystem access, and pretending otherwise
# would only produce commands that fail on the device (spec §27).
PLATFORM_CAPABILITIES: dict[str, frozenset[str]] = {
    "MACOS": ALL_CAPABILITIES,
    "WINDOWS": ALL_CAPABILITIES,
    "LINUX": ALL_CAPABILITIES,
    # Mobile: navigation and notifications yes, host automation no.
    "IOS": _DATA | _SURFACE | {"notifications.show", "voice.input", "voice.output"},
    "IPADOS": _DATA | _SURFACE | {"notifications.show", "voice.input", "voice.output"},
    "ANDROID": _DATA
    | _SURFACE
    | {
        "notifications.show",
        "voice.input",
        "voice.output",
        # Android permits a foreground service to hold a workspace directory
        # it owns; still sandboxed, still user-granted.
        "filesystem.workspace.read",
    },
    # A browser tab is a client, not a system agent (spec §31). Notifications
    # depend on the browser and are therefore not granted by default.
    "WEB": _DATA | _SURFACE,
    # An unrecognised platform gets the safe floor: read-only data.
    "UNKNOWN": frozenset({c for c in _DATA if c.endswith(".read")}),
}


def is_known_capability(capability: str) -> bool:
    return capability in ALL_CAPABILITIES


def platform_allows(platform: str, capability: str) -> bool:
    ceiling = PLATFORM_CAPABILITIES.get(
        (platform or "").upper(), PLATFORM_CAPABILITIES["UNKNOWN"]
    )
    return capability in ceiling


def effective_capabilities(
    platform: str, declared: Iterable[str] | None
) -> tuple[str, ...]:
    """The capabilities a device actually gets, sorted and deduplicated.

    Unknown verbs are dropped rather than rejected: a newer client that
    declares a capability this server has never heard of should keep working
    for everything else it declared, not fail wholesale.
    """
    ceiling = PLATFORM_CAPABILITIES.get(
        (platform or "").upper(), PLATFORM_CAPABILITIES["UNKNOWN"]
    )
    claimed = {str(c).strip() for c in (declared or []) if str(c).strip()}
    return tuple(sorted(claimed & ceiling))
