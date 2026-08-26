"""ABC for tool implementations and the ToolExecutor dispatch engine.

Follows the same registry pattern as ``engine/_stubs.py`` and ``memory/_stubs.py``.
Each tool is registered via ``@ToolRegistry.register("name")`` and implements
``BaseTool`` with a ``spec`` property and ``execute()`` method.
"""

from __future__ import annotations

import functools
import json
import logging
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from diapason.core.events import EventBus, EventType
from diapason.core.types import ToolCall, ToolResult

logger = logging.getLogger(__name__)

_CONFIRMATION_CAPABILITIES = frozenset(
    {
        "file:write",
        "code:execute",
        "channel:send",
        "schedule:create",
        "system:admin",
    }
)
# Envoyer quelque chose hors de cette machine, sur un choix du modèle.
# `mesh_send` y manquait : il déclarait `requires_confirmation=False` tout en
# portant `metadata={"risk": "outward_action"}` — une étiquette qu'AUCUN code
# d'approbation ne lit. La cloche ne sonnait donc pour lui nulle part, et un
# second outil invoquait cette protection inexistante pour justifier la
# sienne (constaté le 26 août 2026). Il n'est pas exposé à la voix, donc la
# confirmation y trouve toujours un interlocuteur.
_MUTATING_NETWORK_TOOLS = frozenset(
    {"browser_click", "browser_type", "mail_send", "messages_send", "mesh_send"}
)

# ---------------------------------------------------------------------------
# ToolSpec — metadata describing a tool's interface
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ToolSpec:
    """Declarative description of a tool's interface and characteristics."""

    name: str
    description: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    category: str = ""
    cost_estimate: float = 0.0
    latency_estimate: float = 0.0
    requires_confirmation: bool = False
    timeout_seconds: float = 30.0
    required_capabilities: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# BaseTool ABC
# ---------------------------------------------------------------------------


class BaseTool(ABC):
    """Base class for all tool implementations.

    Subclasses must be registered via
    ``@ToolRegistry.register("name")`` to become discoverable.
    """

    tool_id: str
    is_local: bool = True

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Install the local-only guard on every tool subclass.

        A guard written inside ``BaseTool.execute`` would never run: the
        method is abstract, so subclasses replace it outright. Wrapping it at
        subclass-definition time is what makes the contract structural instead
        of a convention someone has to remember.

        It also covers what a guard on the dispatcher cannot. ``ToolExecutor``
        is already bypassed today by ``server/api_routes.py``,
        ``agents/hybrid/_base.py`` and ``desktop/welcome_runner.py``, which
        call ``Tool().execute(...)`` directly — a class-level wrapper catches
        all three, and every future one.

        Subclasses that do not define their own ``execute`` inherit the
        already-wrapped parent version, so the guard is never applied twice.
        """
        super().__init_subclass__(**kwargs)
        execute = cls.__dict__.get("execute")
        if execute is None or getattr(execute, "_local_only_guarded", False):
            return
        if getattr(execute, "__isabstractmethod__", False):
            return

        @functools.wraps(execute)
        def _guarded_execute(self: "BaseTool", **params: Any) -> ToolResult:
            if not getattr(self, "is_local", True):
                from diapason.core.local_mode import REFUSAL_HINT, local_only

                if local_only():
                    name = getattr(self, "tool_id", "") or cls.__name__
                    logger.info(
                        "local-mode: refused tool %r — it is declared remote", name
                    )
                    return ToolResult(
                        tool_name=name,
                        content=f"Tool {name!r} needs the network. {REFUSAL_HINT}",
                        success=False,
                        metadata={"nothing_left_the_machine": True},
                    )
            return execute(self, **params)

        _guarded_execute._local_only_guarded = True  # type: ignore[attr-defined]
        cls.execute = _guarded_execute  # type: ignore[method-assign]

    @property
    @abstractmethod
    def spec(self) -> ToolSpec:
        """Return the tool specification."""

    @abstractmethod
    def execute(self, **params: Any) -> ToolResult:
        """Execute the tool with the given parameters."""

    def to_openai_function(self) -> Dict[str, Any]:
        """Convert to OpenAI function-calling format."""
        from diapason.tools.description_loader import (
            get_tool_description_override,
        )

        s = self.spec
        desc = get_tool_description_override(s.name) or s.description
        return {
            "type": "function",
            "function": {
                "name": s.name,
                "description": desc,
                "parameters": s.parameters,
            },
        }


# ---------------------------------------------------------------------------
# ToolExecutor — dispatch engine for tool calls
# ---------------------------------------------------------------------------


class ToolExecutor:
    """Dispatch tool calls to registered tools with event bus integration.

    Parameters
    ----------
    tools:
        List of tool instances to make available.
    bus:
        Optional event bus for publishing ``TOOL_CALL_START``/``TOOL_CALL_END``.
    """

    def __init__(
        self,
        tools: List[BaseTool],
        bus: Optional[EventBus] = None,
        *,
        interactive: bool = False,
        confirm_callback: Optional[Callable[[str], bool]] = None,
        default_timeout: float = 30.0,
        capability_policy: Optional[Any] = None,
        agent_id: str = "",
        boundary_guard: Optional[Any] = None,
        rate_limiter: Optional[Any] = None,
        autoload_capability_policy: bool = True,
    ) -> None:
        self._tools: Dict[str, BaseTool] = {t.spec.name: t for t in tools}
        self._bus = bus
        self._interactive = interactive
        self._confirm_callback = confirm_callback
        self._default_timeout = default_timeout
        self._capability_policy = capability_policy
        self._agent_id = agent_id
        self._boundary_guard = boundary_guard
        self._rate_limiter = rate_limiter
        self._autoload_capability_policy = autoload_capability_policy
        self._load_default_security_controls()
        self._grant_selected_tools_when_unmanaged()

    def _load_default_security_controls(self) -> None:
        """Enforce configured controls even at legacy construction sites.

        Several subsystems historically instantiated ``ToolExecutor``
        directly.  Loading missing controls here makes security structural:
        forgetting to use a higher-level factory cannot silently disable it.
        Explicitly supplied controls are always preserved.
        """
        try:
            from diapason.core.config import load_config

            config = load_config()
            if not config.security.enabled:
                return
            if self._boundary_guard is None:
                from diapason.security.boundary import BoundaryGuard

                self._boundary_guard = BoundaryGuard(
                    mode=config.security.mode,
                    bus=self._bus,
                )
            if (
                self._capability_policy is None
                and self._autoload_capability_policy
                and config.security.capabilities.enabled
            ):
                from diapason.security.capabilities import CapabilityPolicy

                self._capability_policy = CapabilityPolicy(
                    policy_path=config.security.capabilities.policy_path or None,
                    default_deny=config.security.capabilities.default_deny,
                )
            if self._rate_limiter is None:
                from diapason.security.rate_limiter import RateLimitConfig, RateLimiter

                self._rate_limiter = RateLimiter(
                    RateLimitConfig(
                        requests_per_minute=config.security.rate_limit_rpm,
                        burst_size=config.security.rate_limit_burst,
                        enabled=config.security.rate_limit_enabled,
                    )
                )
        except Exception as exc:
            raise RuntimeError(
                "Could not initialize mandatory tool security controls"
            ) from exc

    @staticmethod
    def _required_capabilities(tool: BaseTool) -> list[str]:
        """Resolve both declared and conservative built-in capabilities."""
        from diapason.security.capabilities import DEFAULT_TOOL_CAPABILITIES

        capabilities = list(tool.spec.required_capabilities)
        for capability in DEFAULT_TOOL_CAPABILITIES.get(tool.spec.name, []):
            value = getattr(capability, "value", capability)
            if value not in capabilities:
                capabilities.append(value)
        # Any tool that can make data leave the device must at minimum be
        # authorized for network access, even if its metadata is incomplete.
        if not getattr(tool, "is_local", True) and "network:fetch" not in capabilities:
            capabilities.append("network:fetch")
        return capabilities

    @staticmethod
    def _requires_confirmation(
        tool: BaseTool,
        params: Dict[str, Any],
        capabilities: list[str],
    ) -> bool:
        """Return whether a call can mutate local or external state."""
        if tool.spec.requires_confirmation:
            return True
        if _CONFIRMATION_CAPABILITIES.intersection(capabilities):
            return True
        if tool.spec.name in _MUTATING_NETWORK_TOOLS:
            return True
        if tool.spec.name == "http_request":
            return str(params.get("method", "GET")).upper() not in {"GET", "HEAD"}
        return False

    def _grant_selected_tools_when_unmanaged(self) -> None:
        """Create a least-privilege policy for an explicitly selected tool set.

        A deny-by-default policy without a policy file must remain usable on a
        fresh installation.  The executor therefore grants only the declared
        capabilities of tools that the caller already selected, scoped to
        each exact tool name.  An administrator-provided policy is never
        modified.
        """
        policy = self._capability_policy
        if (
            policy is None
            or not getattr(policy, "default_deny", False)
            or getattr(policy, "has_explicit_policy", False)
        ):
            return
        for tool in self._tools.values():
            for capability in self._required_capabilities(tool):
                policy.grant(self._agent_id, capability, tool.spec.name)

    def execute(self, tool_call: ToolCall) -> ToolResult:
        """Parse arguments, dispatch to tool, measure latency, emit events."""
        tool = self._tools.get(tool_call.name)
        if tool is None:
            return ToolResult(
                tool_name=tool_call.name,
                content=f"Unknown tool: {tool_call.name}",
                success=False,
            )

        if self._rate_limiter is not None:
            key = f"{self._agent_id or 'anonymous'}:{tool_call.name}"
            allowed, wait_seconds = self._rate_limiter.check(key)
            if not allowed:
                if self._bus:
                    self._bus.publish(
                        EventType.SECURITY_BLOCK,
                        {
                            "source": "tool_rate_limiter",
                            "tool": tool_call.name,
                            "agent_id": self._agent_id,
                            "retry_after": wait_seconds,
                        },
                    )
                return ToolResult(
                    tool_name=tool_call.name,
                    content=(
                        f"Rate limit exceeded for tool '{tool_call.name}'. "
                        f"Retry after {wait_seconds:.1f}s."
                    ),
                    success=False,
                    metadata={"retry_after": wait_seconds},
                )

        # Parse arguments
        try:
            params = json.loads(tool_call.arguments) if tool_call.arguments else {}
        except json.JSONDecodeError as exc:
            return ToolResult(
                tool_name=tool_call.name,
                content=f"Invalid arguments JSON: {exc}",
                success=False,
            )

        # Boundary guard: scan external tool arguments
        if self._boundary_guard is not None and not getattr(tool, "is_local", True):
            try:
                tool_call = self._boundary_guard.check_outbound(tool_call)
                # Re-parse arguments after potential redaction
                params = json.loads(tool_call.arguments) if tool_call.arguments else {}
            except Exception as exc:
                return ToolResult(
                    tool_name=tool_call.name,
                    content=f"Security block: {exc}",
                    success=False,
                )

        # RBAC capability check. Built-ins receive conservative fallback
        # capabilities so incomplete metadata cannot bypass authorization.
        required_capabilities = self._required_capabilities(tool)
        if required_capabilities and self._capability_policy is None:
            return ToolResult(
                tool_name=tool_call.name,
                content="Security block: capability policy is unavailable.",
                success=False,
            )
        if self._capability_policy and required_capabilities:
            for cap in required_capabilities:
                if not self._capability_policy.check(
                    self._agent_id,
                    cap,
                    tool_call.name,
                ):
                    if self._bus:
                        self._bus.publish(
                            EventType.CAPABILITY_DENIED,
                            {
                                "agent_id": self._agent_id,
                                "capability": cap,
                                "tool": tool_call.name,
                            },
                        )
                    return ToolResult(
                        tool_name=tool_call.name,
                        content=(
                            f"Capability '{cap}' denied for"
                            f" agent '{self._agent_id}'"
                            f" on tool '{tool_call.name}'."
                        ),
                        success=False,
                    )

        # Taint checking (sink policy)
        taint_set = params.get("_taint") if isinstance(params, dict) else None
        if taint_set is not None:
            try:
                from diapason.security.taint import TaintSet, check_taint

                if isinstance(taint_set, TaintSet):
                    violation = check_taint(tool_call.name, taint_set)
                    if violation:
                        if self._bus:
                            self._bus.publish(
                                EventType.TAINT_VIOLATION,
                                {
                                    "tool": tool_call.name,
                                    "violation": violation,
                                },
                            )
                        return ToolResult(
                            tool_name=tool_call.name,
                            content=f"Taint violation: {violation}",
                            success=False,
                        )
            except ImportError:
                pass
            # Remove internal taint key before passing to tool
            if isinstance(params, dict):
                params.pop("_taint", None)

        # Confirmation check for sensitive tools
        if self._requires_confirmation(tool, params, required_capabilities):
            if not self._interactive or self._confirm_callback is None:
                return ToolResult(
                    tool_name=tool_call.name,
                    content=(
                        f"Tool '{tool_call.name}' requires"
                        " confirmation but no confirmation"
                        " callback is available."
                    ),
                    success=False,
                )
            prompt_args = json.dumps(params, default=str)
            if self._boundary_guard is not None:
                prompt_args = self._boundary_guard.redact_for_storage(prompt_args)
            prompt = (
                f"Allow execution of tool '{tool_call.name}' with args {prompt_args}?"
            )
            if not self._confirm_callback(prompt):
                return ToolResult(
                    tool_name=tool_call.name,
                    content=f"Tool '{tool_call.name}' execution denied by user.",
                    success=False,
                )

        # Emit start event. ``agent`` carries the managed-agent UUID so the
        # AgentExecutor's trace subscriber (which filters by agent_id) can
        # actually match this event — without it, every tool call is silently
        # dropped from traces.
        if self._bus:
            event_arguments: Any = params
            if self._boundary_guard is not None:
                serialized = json.dumps(params, default=str)
                sanitized = self._boundary_guard.redact_for_storage(serialized)
                try:
                    event_arguments = json.loads(sanitized)
                except json.JSONDecodeError:
                    event_arguments = {"redacted": True}
            self._bus.publish(
                EventType.TOOL_CALL_START,
                {
                    "tool": tool_call.name,
                    "arguments": event_arguments,
                    "agent": self._agent_id,
                },
            )

        # Execute with timeout
        timeout = tool.spec.timeout_seconds or self._default_timeout
        t0 = time.time()
        finished = threading.Event()
        outcome: dict[str, Any] = {}

        def _invoke() -> None:
            try:
                outcome["result"] = tool.execute(**params)
            except BaseException as exc:  # contained and handled on caller thread
                outcome["error"] = exc
            finally:
                finished.set()

        worker = threading.Thread(
            target=_invoke,
            name=f"diapason-tool-{tool_call.name}",
            daemon=True,
        )
        worker.start()
        if not finished.wait(timeout=timeout):
            if self._bus:
                self._bus.publish(
                    EventType.TOOL_TIMEOUT,
                    {"tool": tool_call.name, "timeout": timeout},
                )
            result = ToolResult(
                tool_name=tool_call.name,
                content=(f"Tool '{tool_call.name}' timed out after {timeout:.0f}s."),
                success=False,
            )
        elif "error" in outcome:
            exc = outcome["error"]
            result = ToolResult(
                tool_name=tool_call.name,
                content=f"Tool execution error: {exc}",
                success=False,
            )
        else:
            result = outcome["result"]
        latency = time.time() - t0
        result.latency_seconds = latency
        # Never attach raw arguments to a result: results are commonly stored
        # in traces and may otherwise turn telemetry into a secret store.
        if self._boundary_guard is not None:
            serialized = json.dumps(params, default=str)
            sanitized = self._boundary_guard.redact_for_storage(serialized)
            try:
                result.metadata["arguments"] = json.loads(sanitized)
            except json.JSONDecodeError:
                result.metadata["arguments"] = {"redacted": True}

        # Auto-detect taints in results
        if result.success:
            try:
                from diapason.security.taint import auto_detect_taint

                detected = auto_detect_taint(result.content)
                if detected and detected.labels:
                    result.metadata["_taint"] = detected
            except ImportError:
                pass

        # Emit end event
        if self._bus:
            result_text = str(result.content)[:10240] if result.content else ""
            if self._boundary_guard is not None:
                result_text = self._boundary_guard.redact_for_storage(result_text)
            # Pass through ToolResult.metadata so downstream consumers
            # (TraceCollector → TraceStep.metadata → SkillOptimizer) can
            # see skill-tagged invocations.  Filter to JSON-serializable
            # values only — internal objects like TaintSet (added by the
            # taint auto-detect above) must not leak to event subscribers
            # since the trace store will JSON-serialize them later.
            event_metadata = self._json_safe_metadata(result.metadata)
            event_metadata.pop("arguments", None)
            self._bus.publish(
                EventType.TOOL_CALL_END,
                {
                    "tool": tool_call.name,
                    "success": result.success,
                    "latency": latency,
                    "result": result_text,
                    "metadata": event_metadata,
                    "agent": self._agent_id,
                },
            )

        return result

    @staticmethod
    def _json_safe_metadata(metadata: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Return a copy of *metadata* containing only JSON-serializable values.

        ``ToolExecutor`` annotates ``ToolResult.metadata`` with internal
        objects (currently ``_taint: TaintSet``).  Those are useful for
        in-process security checks but cannot be serialized when the
        ``TraceCollector`` writes ``TraceStep.metadata`` to JSON in the
        SQLite trace store.  This helper drops any keys whose value is
        not JSON-safe — silently, since the missing data is not
        load-bearing for downstream consumers.
        """
        if not metadata:
            return {}

        import json

        safe: Dict[str, Any] = {}
        for key, value in metadata.items():
            if not isinstance(key, str):
                continue
            try:
                json.dumps(value)
            except (TypeError, ValueError):
                # Skip non-serializable values (e.g. TaintSet)
                continue
            safe[key] = value
        return safe

    def available_tools(self) -> List[ToolSpec]:
        """Return specs for all available tools."""
        return [t.spec for t in self._tools.values()]

    def get_openai_tools(self) -> List[Dict[str, Any]]:
        """Return tools in OpenAI function-calling format."""
        return [t.to_openai_function() for t in self._tools.values()]


def build_tool_descriptions(
    tools: List[BaseTool],
    *,
    include_category: bool = True,
    include_cost: bool = False,
) -> str:
    """Build rich text descriptions from a list of tools.

    This is the single source of truth for all text-based agents that need
    to describe available tools in their system prompts.

    Parameters
    ----------
    tools:
        List of tool instances.
    include_category:
        Whether to include the ``Category:`` line.
    include_cost:
        Whether to include ``Cost estimate:`` and ``Latency estimate:`` lines.

    Returns
    -------
    str
        Formatted multi-tool description, or ``"No tools available."`` if
        *tools* is empty.
    """
    if not tools:
        return "No tools available."

    from diapason.tools.description_loader import (
        get_tool_description_override,
    )

    sections: list[str] = []
    for t in tools:
        s = t.spec
        desc = get_tool_description_override(s.name) or s.description
        lines = [f"### {s.name}", desc]

        if include_category and s.category:
            lines.append(f"Category: {s.category}")

        if include_cost:
            if s.cost_estimate:
                lines.append(f"Cost estimate: ${s.cost_estimate:.4f}")
            if s.latency_estimate:
                lines.append(f"Latency estimate: {s.latency_estimate:.1f}s")

        # Parameter descriptions
        props = s.parameters.get("properties", {})
        required = set(s.parameters.get("required", []))
        if props:
            lines.append("Parameters:")
            for pname, pinfo in props.items():
                ptype = pinfo.get("type", "any")
                req_mark = ", required" if pname in required else ""
                desc = pinfo.get("description", "")
                if desc:
                    lines.append(f"  - {pname} ({ptype}{req_mark}): {desc}")
                else:
                    lines.append(f"  - {pname} ({ptype}{req_mark})")

        sections.append("\n".join(lines))

    return "\n\n".join(sections)


__all__ = ["BaseTool", "ToolExecutor", "ToolSpec", "build_tool_descriptions"]
