"""Static scanner for outbound-capable modules.

Shared by the outbound ratchet test. Kept separate from the test module so it
can be imported by tooling (e.g. to regenerate the manifest) without pytest.

An "outbound" call is one that opens a network connection or hands data to a
third-party client library. Detection is by AST, not text: a call whose root
receiver name belongs to a known transport / SDK, invoking a known network
verb (or a client constructor). This deliberately flags loopback calls too —
the point is that EVERY outbound-capable module is accounted for, and loopback
exemptions are decided by a human in the manifest, not guessed by the scanner.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterable, Set

# Roots whose calls can leave the machine, and the attribute names that make
# such a call. A client *constructor* counts on its own (openai.OpenAI(...)),
# because constructing it is already reading a credential.
_TRANSPORT_VERBS = {
    "httpx": {
        "get", "post", "put", "patch", "delete", "stream",
        "request", "Client", "AsyncClient", "send",
    },
    "requests": {"get", "post", "put", "patch", "delete", "request", "Session", "head"},
    "aiohttp": {"ClientSession", "request", "get", "post"},
    "urllib": {"urlopen"},
    "websockets": {"connect"},
    "socket": {"create_connection", "socket"},
    "smtplib": {"SMTP", "SMTP_SSL"},
    "imaplib": {"IMAP4", "IMAP4_SSL"},
    "ftplib": {"FTP", "FTP_TLS"},
}

# SDK client constructors: any call to these names is outbound-capable.
_SDK_CONSTRUCTORS = {
    "OpenAI",
    "AsyncOpenAI",
    "Anthropic",
    "AsyncAnthropic",
    "Posthog",
    "Deepgram",
    "DeepgramClient",
    "ElevenLabs",
    "Cartesia",
    "Groq",
}

# Directories that are not shippable runtime code.
_SKIP_DIRS = {"__pycache__", "tests", "evals", "bench"}


def _root_name(node: ast.AST) -> str:
    """Return the leftmost identifier of an attribute/name chain."""
    while isinstance(node, ast.Attribute):
        node = node.value
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _call_is_outbound(call: ast.Call) -> bool:
    func = call.func
    if isinstance(func, ast.Attribute):
        root = _root_name(func)
        verb = func.attr
        verbs = _TRANSPORT_VERBS.get(root)
        if verbs and verb in verbs:
            return True
        if verb in _SDK_CONSTRUCTORS:
            return True
    elif isinstance(func, ast.Name):
        if func.id in _SDK_CONSTRUCTORS:
            return True
        if func.id == "urlopen":
            return True
    return False


def module_is_outbound(source: str) -> bool:
    """True when a module contains at least one outbound-capable call."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _call_is_outbound(node):
            return True
    return False


def scan_outbound_modules(src_root: Path) -> Set[str]:
    """Return the set of ``openjarvis/...`` paths that are outbound-capable."""
    found: Set[str] = set()
    for path in _iter_sources(src_root):
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if module_is_outbound(source):
            found.add(path.relative_to(src_root).as_posix())
    return found


def _iter_sources(src_root: Path) -> Iterable[Path]:
    for path in src_root.rglob("*.py"):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        yield path
