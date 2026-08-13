"""Persistent Python REPL tool — maintains state across calls within a session.

Unlike ``CodeInterpreterTool`` (which runs each snippet in a fresh subprocess),
this tool keeps variables, functions, and imports alive across invocations
within the same session.
"""

from __future__ import annotations

import io
import multiprocessing
import threading
import time
import uuid
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from diapason.core.registry import ToolRegistry
from diapason.core.types import ToolResult
from diapason.tools._stubs import BaseTool, ToolSpec

# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------

# Layer 1: Pattern blocklist
_BLOCKED_PATTERNS = [
    "os.system",
    "os.popen",
    "subprocess",
    "shutil.rmtree",
    "__import__",
    "open(",
    "ctypes",
    "socket",
    "http.client",
    "urllib",
]

# Layer 2: Restricted builtins — remove dangerous ones
_REMOVED_BUILTINS = {
    "open",
    "exec",
    "eval",
    "compile",
    "__import__",
    "breakpoint",
    "exit",
    "quit",
    "input",
}

# Layer 3: Safe import allowlist
_SAFE_IMPORT_MODULES = frozenset(
    {
        "math",
        "cmath",
        "decimal",
        "fractions",
        "random",
        "statistics",
        "itertools",
        "functools",
        "operator",
        "collections",
        "string",
        "re",
        "textwrap",
        "datetime",
        "time",
        "calendar",
        "json",
        "csv",
        "copy",
        "dataclasses",
        "enum",
        "typing",
        "heapq",
        "bisect",
        "array",
        "pprint",
        "abc",
        "numbers",
    }
)


def _make_safe_import(allowed: frozenset = _SAFE_IMPORT_MODULES):
    """Return a custom __import__ that only allows safe modules."""
    if isinstance(__builtins__, dict):
        real_import = __builtins__["__import__"]
    else:
        real_import = __builtins__.__import__  # type: ignore[union-attr]

    def _safe_import(name: str, *args: Any, **kwargs: Any) -> Any:
        top_level = name.split(".")[0]
        if top_level not in allowed:
            raise ImportError(
                f"Import of '{name}' is not allowed. "
                f"Allowed modules: {', '.join(sorted(allowed))}"
            )
        return real_import(name, *args, **kwargs)

    return _safe_import


def _make_restricted_builtins() -> Dict[str, Any]:
    """Build a builtins dict with dangerous functions removed."""
    import builtins

    safe = {k: v for k, v in vars(builtins).items() if k not in _REMOVED_BUILTINS}
    safe["__import__"] = _make_safe_import()
    return safe


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------


@dataclass
class _ReplSession:
    session_id: str
    process: Any
    connection: Any
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    execution_count: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


def _execute_code(code: str, namespace: Dict[str, Any]) -> tuple[str, bool]:
    """Execute one snippet inside the isolated REPL worker."""
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    try:
        with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
            try:
                compiled = compile(code, "<repl>", "eval")
                value = eval(compiled, namespace)  # noqa: S307
                if value is not None:
                    print(repr(value))  # noqa: T201
            except SyntaxError:
                compiled = compile(code, "<repl>", "exec")
                exec(compiled, namespace)  # noqa: S102
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}", False

    output = stdout_buf.getvalue()
    error_output = stderr_buf.getvalue()
    if error_output:
        output += ("\n" if output else "") + error_output
    return output, True


def _repl_worker(connection: Any) -> None:
    """Own persistent state in a killable child process."""
    namespace: Dict[str, Any] = {"__builtins__": _make_restricted_builtins()}
    try:
        while True:
            message = connection.recv()
            operation = message.get("operation")
            if operation == "stop":
                return
            if operation == "reset":
                namespace = {"__builtins__": _make_restricted_builtins()}
                connection.send(("", True))
                continue
            if operation == "execute":
                connection.send(_execute_code(str(message.get("code", "")), namespace))
    except (EOFError, BrokenPipeError, OSError):
        return
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# REPL Tool
# ---------------------------------------------------------------------------


@ToolRegistry.register("repl")
class ReplTool(BaseTool):
    """Persistent Python REPL with session management.

    Parameters
    ----------
    timeout:
        Maximum execution time in seconds per call.
    max_output:
        Maximum characters of captured output.
    max_sessions:
        Maximum concurrent sessions (LRU eviction).
    """

    tool_id = "repl"

    def __init__(
        self,
        timeout: int = 30,
        max_output: int = 10000,
        max_sessions: int = 16,
    ) -> None:
        self._timeout = timeout
        self._max_output = max_output
        self._max_sessions = max_sessions
        self._sessions: Dict[str, _ReplSession] = {}
        self._lock = threading.Lock()
        self._process_context = multiprocessing.get_context("spawn")

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="repl",
            description=(
                "Execute Python code in a persistent REPL session. "
                "Variables, functions, and imports persist across calls "
                "within the same session."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python code to execute.",
                    },
                    "session_id": {
                        "type": "string",
                        "description": (
                            "Session ID for state persistence. "
                            "Omit to auto-create a new session."
                        ),
                    },
                    "reset": {
                        "type": "boolean",
                        "description": "Reset the session state before execution.",
                    },
                },
                "required": ["code"],
            },
            category="code",
            requires_confirmation=True,
            timeout_seconds=float(self._timeout),
            required_capabilities=["code:execute"],
        )

    def execute(self, **params: Any) -> ToolResult:
        code = params.get("code", "")
        session_id = params.get("session_id")
        reset = params.get("reset", False)

        if not code or not code.strip():
            return ToolResult(
                tool_name="repl",
                content="No code provided.",
                success=False,
            )

        # Security pattern check
        for pattern in _BLOCKED_PATTERNS:
            if pattern in code:
                return ToolResult(
                    tool_name="repl",
                    content=f"Blocked: code contains prohibited pattern '{pattern}'",
                    success=False,
                )

        # Resolve session
        session = self._resolve_session(session_id, reset)

        # Execute with timeout
        output, success = self._exec_with_timeout(code, session)

        # Update metadata on the returned session object even if a timed-out
        # worker was retired. A later call with the same ID gets fresh state.
        session.last_used = time.time()
        session.execution_count += 1

        # Truncate output
        if len(output) > self._max_output:
            output = output[: self._max_output] + "\n... (output truncated)"

        return ToolResult(
            tool_name="repl",
            content=output or "(no output)",
            success=success,
            metadata={
                "session_id": session.session_id,
                "execution_count": session.execution_count,
            },
        )

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def _resolve_session(
        self,
        session_id: Optional[str],
        reset: bool = False,
    ) -> _ReplSession:
        """Get or create a session, with LRU eviction at max_sessions."""
        with self._lock:
            if session_id and session_id in self._sessions and not reset:
                session = self._sessions[session_id]
                return session

            if session_id and session_id in self._sessions and reset:
                session = self._sessions[session_id]
                self._stop_session(session)
                del self._sessions[session_id]

            # Create new session
            sid = session_id or str(uuid.uuid4())

            # LRU eviction if at capacity
            if len(self._sessions) >= self._max_sessions:
                oldest_id = min(
                    self._sessions,
                    key=lambda k: self._sessions[k].last_used,
                )
                self._stop_session(self._sessions.pop(oldest_id))

            parent_connection, child_connection = self._process_context.Pipe()
            process = self._process_context.Process(
                target=_repl_worker,
                args=(child_connection,),
                daemon=True,
                name=f"diapason-repl-{sid}",
            )
            process.start()
            child_connection.close()
            session = _ReplSession(sid, process, parent_connection)
            self._sessions[sid] = session
            return session

    def _stop_session(self, session: _ReplSession) -> None:
        """Stop a worker and close its IPC channel."""
        try:
            if session.process.is_alive():
                session.connection.send({"operation": "stop"})
        except (BrokenPipeError, EOFError, OSError):
            pass
        try:
            session.connection.close()
        except OSError:
            pass
        session.process.join(timeout=0.2)
        if session.process.is_alive():
            session.process.terminate()
            session.process.join(timeout=1)
        if session.process.is_alive() and hasattr(session.process, "kill"):
            session.process.kill()
            session.process.join(timeout=1)

    def close(self) -> None:
        """Release all REPL worker processes."""
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            self._stop_session(session)

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def _exec_with_timeout(
        self,
        code: str,
        session: _ReplSession,
    ) -> tuple[str, bool]:
        """Execute code in a persistent child process with a hard timeout.

        Returns (output, success).
        """
        with session.lock:
            if not session.process.is_alive():
                self._retire_session(session)
                return "REPL worker stopped unexpectedly.", False
            try:
                session.connection.send({"operation": "execute", "code": code})
                if session.connection.poll(self._timeout):
                    output, success = session.connection.recv()
                    return str(output), bool(success)
            except (BrokenPipeError, EOFError, OSError):
                self._retire_session(session)
                return "REPL worker stopped unexpectedly.", False

            self._retire_session(session)
            return f"Execution timed out after {self._timeout} seconds.", False

    def _retire_session(self, session: _ReplSession) -> None:
        with self._lock:
            if self._sessions.get(session.session_id) is session:
                del self._sessions[session.session_id]
        self._stop_session(session)


__all__ = ["ReplTool"]
