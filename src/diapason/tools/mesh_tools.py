"""The assistant's door to the other devices.

Spec §22 and §33. Two tools, deliberately: one that only looks, one that
acts. Splitting them means the model can answer « quels appareils sont
allumés ? » without ever entering the code path that sends something.

``mesh_devices`` is read-only and always safe.
``mesh_send`` routes one catalogued remote tool to one resolved device, and
carries the risk metadata that makes the approval system treat it as an
outward action — because it is one: it changes what appears on a screen the
user may not be standing in front of.

What this file refuses to do is as important as what it does. It never
takes a device id from the model when a phrase would do, it never invents a
tool name, and it never reports a queued command as done: the status and
the sentence come straight from the dispatcher, which is the only component
that knows the truth.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from diapason.core.registry import ToolRegistry
from diapason.core.types import ToolResult
from diapason.mesh.registry import DeviceRegistry, MeshError
from diapason.mesh.resolver import describe_devices, resolve_device
from diapason.tools._stubs import BaseTool, ToolSpec

if TYPE_CHECKING:
    from diapason.mesh.queue import CommandQueue

# Statuses that mean the user's intent actually reached the other device.
# Everything else is a refusal or a delay, and must not be phrased as success.
_DONE = {"SUCCESS"}


def _result(name: str, success: bool, content: str, metadata: dict[str, Any]):
    return ToolResult(
        tool_name=name, success=success, content=content, metadata=metadata
    )


def _fleet(registry: DeviceRegistry) -> list[dict[str, Any]]:
    return registry.list_devices(include_revoked=False)


@ToolRegistry.register("mesh_devices")
class MeshDevicesTool(BaseTool):
    """Look at the fleet. Never sends anything, so it needs no approval."""

    tool_id = "mesh_devices"
    is_local = True

    def __init__(self, registry: DeviceRegistry | None = None) -> None:
        self._registry = registry

    @property
    def registry(self) -> DeviceRegistry:
        if self._registry is None:
            self._registry = DeviceRegistry()
        return self._registry

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="mesh_devices",
            description=(
                "List the user's other paired devices (name, kind, whether they are "
                "awake, what they can do), or work out which device a phrase like "
                "« mon PC » or « ma tablette » refers to. Read-only. Call this "
                "before mesh_send when the target is described in words."
            ),
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "device_phrase": {
                        "type": "string",
                        "description": (
                            "How the user named the device, verbatim — "
                            "« sur mon PC du bureau », « ma tablette ». "
                            "Omit to list every paired device."
                        ),
                    }
                },
            },
            category="mesh",
            metadata={"risk": "read_only", "reversible": True},
        )

    def execute(self, **params: Any) -> ToolResult:
        from diapason.mesh.identity import device_identity

        phrase = str(params.get("device_phrase") or "").strip()
        devices = _fleet(self.registry)

        if not phrase:
            listed = describe_devices(
                [d for d in devices if d.get("trustLevel") == "TRUSTED"]
            )
            return _result(
                "mesh_devices",
                True,
                f"{len(listed)} appareil(s) appairé(s)."
                if listed
                else "Aucun autre appareil n'est appairé.",
                {"devices": listed, "persistence": "unchanged"},
            )

        outcome = resolve_device(
            phrase, devices, local_device_id=device_identity().device_id
        )
        return _result(
            "mesh_devices",
            outcome["status"] in {"RESOLVED", "LOCAL"},
            outcome["message"],
            {
                "status": outcome["status"],
                "deviceId": (outcome.get("device") or {}).get("deviceId"),
                "candidates": outcome["candidates"],
                "persistence": "unchanged",
            },
        )


@ToolRegistry.register("mesh_send")
class MeshSendTool(BaseTool):
    """Send one catalogued action to one other device."""

    tool_id = "mesh_send"
    is_local = True

    def __init__(
        self,
        registry: DeviceRegistry | None = None,
        queue: "CommandQueue | None" = None,
    ) -> None:
        self._registry = registry
        self._queue = queue

    @property
    def registry(self) -> DeviceRegistry:
        if self._registry is None:
            self._registry = DeviceRegistry()
        return self._registry

    @property
    def queue(self) -> "CommandQueue":
        from diapason.mesh.queue import CommandQueue

        if self._queue is None:
            self._queue = CommandQueue()
        return self._queue

    @property
    def spec(self) -> ToolSpec:
        from diapason.mesh.tools import list_remote_tools

        catalogue = list_remote_tools()
        names = [t["name"] for t in catalogue]
        return ToolSpec(
            name="mesh_send",
            description=(
                "Ask one of the user's other paired devices to do something: open a "
                "screen, show a task or project, bring the app forward, or display a "
                "notification. Resolve the target with mesh_devices first when the "
                "user described it in words. Only these actions exist — there is no "
                "way to run arbitrary code on another device."
            ),
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "device_id": {
                        "type": "string",
                        "description": "Target device id, as returned by mesh_devices.",
                    },
                    "device_phrase": {
                        "type": "string",
                        "description": (
                            "Alternative to device_id: how the user named the "
                            "device. Refused if it matches several devices."
                        ),
                    },
                    "action": {
                        "type": "string",
                        "enum": names,
                        "description": _catalogue_hint(catalogue),
                    },
                    "arguments": {
                        "type": "object",
                        "description": (
                            "Arguments for the action, exactly as its parameters "
                            "require. Unknown keys are rejected."
                        ),
                    },
                },
                "required": ["action"],
            },
            category="mesh",
            metadata={"risk": "outward_action", "reversible": True},
        )

    def execute(self, **params: Any) -> ToolResult:
        from diapason.mesh.dispatch import dispatch_command
        from diapason.mesh.identity import device_identity
        from diapason.mesh.tools import get_remote_tool

        action = str(params.get("action") or "").strip()
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return _result(
                "mesh_send", False, "Les arguments doivent être un objet.", {}
            )
        # Checked before the device is resolved, so an impossible action is
        # named as such instead of blaming the fleet for it.
        if get_remote_tool(action) is None:
            return _result(
                "mesh_send",
                False,
                f"L'action « {action} » n'existe pas : un appareil distant ne "
                "peut qu'ouvrir un écran, afficher un élément, passer au "
                "premier plan ou montrer une notification.",
                {"status": "UNSUPPORTED", "persistence": "unchanged"},
            )

        try:
            target = self._target(params, device_identity().device_id)
        except _Unresolved as exc:
            return _result("mesh_send", False, exc.message, exc.metadata)
        except MeshError as exc:
            return _result("mesh_send", False, str(exc), {})

        outcome = dispatch_command(
            target_device_id=target,
            tool=action,
            arguments=arguments,
            registry=self.registry,
            queue=self.queue,
        )
        # The dispatcher owns the truth about what happened; this tool only
        # relays it. Success is narrow on purpose (spec §57).
        return _result(
            "mesh_send",
            outcome["status"] in _DONE,
            outcome["userSafeMessage"],
            {
                "status": outcome["status"],
                "commandId": outcome.get("commandId"),
                "targetDeviceId": target,
                "persistence": "remote",
            },
        )

    def _target(self, params: dict[str, Any], local_id: str) -> str:
        explicit = str(params.get("device_id") or "").strip()
        if explicit:
            return explicit

        phrase = str(params.get("device_phrase") or "").strip()
        outcome = resolve_device(
            phrase, _fleet(self.registry), local_device_id=local_id
        )
        if outcome["status"] == "RESOLVED":
            return str(outcome["device"]["deviceId"])
        if outcome["status"] == "LOCAL":
            raise _Unresolved(
                "Cette action concerne cet appareil-ci : faites-la directement, "
                "sans passer par un autre appareil.",
                {"status": "LOCAL"},
            )
        # AMBIGUOUS and UNKNOWN both end the same way: ask, never guess.
        raise _Unresolved(
            outcome["message"],
            {"status": outcome["status"], "candidates": outcome["candidates"]},
        )


class _Unresolved(Exception):
    """No single device was meant — the assistant must ask before acting."""

    def __init__(self, message: str, metadata: dict[str, Any]) -> None:
        super().__init__(message)
        self.message = message
        self.metadata = {**metadata, "persistence": "unchanged"}


def _catalogue_hint(catalogue: list[dict[str, Any]]) -> str:
    """Describe each remote action inline, so the model never has to guess a
    parameter name — guessing is what the structural guard rejects."""
    lines = []
    for tool in catalogue:
        keys = ", ".join(tool.get("parameters", {}).keys()) or "aucun paramètre"
        lines.append(f"{tool['name']} ({keys}) — {tool.get('description', '')}")
    return " | ".join(lines)
