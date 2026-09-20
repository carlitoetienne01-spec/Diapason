"""GuardrailsEngine — security-aware inference engine wrapper."""

from __future__ import annotations

import re
from collections import deque
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import replace
from typing import Any, Dict, List, Optional, Sequence

from diapason.core.events import EventBus, EventType
from diapason.core.types import Message
from diapason.engine._stubs import InferenceEngine, StreamChunk
from diapason.security._stubs import BaseScanner
from diapason.security.scanner import PIIScanner, SecretScanner
from diapason.security.types import RedactionMode, ScanResult


class SecurityBlockError(Exception):
    """Raised when mode is BLOCK and security findings are detected."""


# 2026-09-19: the rich stream withheld the whole answer; the plain stream
# released long secrets in pieces. 128 only covers FIXED patterns (at most
# 36 characters), never arbitrary keys, email addresses or quoted values.
_STREAM_HOLDBACK = 128
_STREAM_RELEASE_STEP = 48  # amortize scanning without waiting for a paragraph

# An assignment may contain arbitrarily much whitespace and a multiline
# quoted value. Retain its beginning until the closing quote makes it
# scannable, even when that beginning lies outside the fixed holdback.
_OPEN_ASSIGNMENT = re.compile(
    r"""(?:password|passwd|pwd|api_key|secret_key|auth_token)\s*"""
    r"""(?:[=:]\s*(?:['"][^'"]*)?)?\Z""",
    re.IGNORECASE,
)


def _safe_prefix(text: str) -> int:
    """A boundary that future built-in scanner matches cannot cross.

    Fixed patterns fit inside the tail. Unbounded token-shaped patterns
    cannot cross whitespace, so never split a word/URI/email. The only
    unbounded patterns spanning whitespace are the assignments above.
    Custom scanners have no such contract and must use full buffering.
    New built-in patterns require reviewing this boundary and its tests.
    """
    end = max(0, len(text) - _STREAM_HOLDBACK)
    assignment = _OPEN_ASSIGNMENT.search(text)
    if assignment is not None:
        end = min(end, assignment.start())
    # Only whitespace shared by Python and Rust: str.isspace() additionally
    # accepts U+001C..U+001F, which Rust's database-URI pattern can consume.
    while end and text[end - 1] not in " \t\r\n\f\v":
        end -= 1
    return end


def _text_only(chunk: StreamChunk) -> bool:
    # 2026-09-19: releasing a tool or final metadata before the scan finishes
    # could trigger an action early or report a finish before the held text.
    return all(
        value is None
        for value in (
            chunk.tool_calls,
            chunk.finish_reason,
            chunk.usage,
            chunk.content_blocks,
            chunk.tool_results,
        )
    )


class GuardrailsEngine(InferenceEngine):
    """Wraps an existing ``InferenceEngine`` with security scanning.

    Not registered in ``EngineRegistry`` — instantiated dynamically to wrap
    any engine at runtime.

    Parameters
    ----------
    engine:
        The wrapped inference engine.
    scanners:
        List of scanners to run.  Defaults to ``SecretScanner`` + ``PIIScanner``.
    mode:
        Action taken on findings: WARN, REDACT, or BLOCK.
    scan_input:
        Whether to scan input messages.
    scan_output:
        Whether to scan output content.
    bus:
        Optional event bus for publishing security events.
    """

    def __init__(
        self,
        engine: InferenceEngine,
        *,
        scanners: Optional[List[BaseScanner]] = None,
        mode: RedactionMode = RedactionMode.REDACT,
        scan_input: bool = True,
        scan_output: bool = True,
        bus: Optional[EventBus] = None,
    ) -> None:
        self._engine = engine
        self._scanners: List[BaseScanner] = (
            scanners
            if scanners is not None
            else [
                SecretScanner(),
                PIIScanner(),
            ]
        )
        self._mode = mode
        self._scan_input = scan_input
        self._scan_output = scan_output
        self._bus = bus

    # -- properties ----------------------------------------------------------

    @property
    def engine_id(self) -> str:  # type: ignore[override]
        """Delegate to the wrapped engine."""
        return self._engine.engine_id

    # -- scanning helpers ----------------------------------------------------

    def _scan_text(self, text: str) -> ScanResult:
        """Run all scanners on *text* and merge findings."""
        merged = ScanResult()
        for scanner in self._scanners:
            result = scanner.scan(text)
            merged.findings.extend(result.findings)
        return merged

    def _redact_text(self, text: str) -> str:
        """Run all scanners' redact() on *text*."""
        result = text
        for scanner in self._scanners:
            result = scanner.redact(result)
        return result

    def _handle_findings(
        self,
        text: str,
        result: ScanResult,
        direction: str,
    ) -> str:
        """Apply the configured mode to findings.

        Parameters
        ----------
        text:
            The original text.
        result:
            Scan result containing findings.
        direction:
            ``"input"`` or ``"output"`` — used in event data.

        Returns
        -------
        str
            Possibly modified text (unchanged for WARN, redacted for REDACT).

        Raises
        ------
        SecurityBlockError
            If mode is BLOCK.
        """
        finding_dicts = [
            {
                "pattern": f.pattern_name,
                "threat": f.threat_level.value,
                "description": f.description,
            }
            for f in result.findings
        ]

        if self._mode == RedactionMode.WARN:
            if self._bus:
                self._bus.publish(
                    EventType.SECURITY_ALERT,
                    {
                        "direction": direction,
                        "findings": finding_dicts,
                        "mode": "warn",
                    },
                )
            return text

        if self._mode == RedactionMode.REDACT:
            if self._bus:
                self._bus.publish(
                    EventType.SECURITY_ALERT,
                    {
                        "direction": direction,
                        "findings": finding_dicts,
                        "mode": "redact",
                    },
                )
            return self._redact_text(text)

        # BLOCK mode
        if self._bus:
            self._bus.publish(
                EventType.SECURITY_BLOCK,
                {
                    "direction": direction,
                    "findings": finding_dicts,
                    "mode": "block",
                },
            )
        raise SecurityBlockError(
            f"Security scan blocked {direction}: "
            f"{len(result.findings)} finding(s) detected"
        )

    def _process_input_messages(self, messages: Sequence[Message]) -> Sequence[Message]:
        """Scan and, if configured, sanitize inference inputs."""
        if not self._scan_input:
            return messages
        processed = list(messages)
        for i, msg in enumerate(processed):
            if not msg.content:
                continue
            result = self._scan_text(msg.content)
            if result.clean:
                continue
            processed[i] = Message(
                role=msg.role,
                content=self._handle_findings(msg.content, result, "input"),
                name=msg.name,
                tool_calls=msg.tool_calls,
                tool_call_id=msg.tool_call_id,
                metadata=msg.metadata,
                images=msg.images,
            )
        return processed

    # -- InferenceEngine interface -------------------------------------------

    def generate(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Scan input, call wrapped engine, scan output."""
        messages = self._process_input_messages(messages)

        # Call wrapped engine
        response = self._engine.generate(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )

        # Scan output
        if self._scan_output:
            content = response.get("content", "")
            if content:
                result = self._scan_text(content)
                if not result.clean:
                    response["content"] = self._handle_findings(
                        content, result, "output"
                    )

        return response

    async def _checked_stream(
        self, source: AsyncIterator[StreamChunk]
    ) -> AsyncIterator[StreamChunk]:
        """Release clean text prefixes; retain metadata and ambiguous content."""
        buffered: deque[StreamChunk] = deque()
        pending_chars = 0
        new_chars = 0
        check_after = _STREAM_RELEASE_STEP
        progressive = self._mode != RedactionMode.BLOCK and all(
            type(scanner) in (SecretScanner, PIIScanner) for scanner in self._scanners
        )
        async with aclosing(source):
            async for chunk in source:
                if not self._scan_output:
                    yield chunk
                    continue
                buffered.append(chunk)
                size = len(chunk.content or "")
                pending_chars += size
                new_chars += size
                progressive = progressive and _text_only(chunk)
                if not progressive or new_chars < check_after:
                    continue
                text = "".join(item.content or "" for item in buffered)
                new_chars = 0
                # An unusually long token/open quote cannot yet be released.
                # Back off geometrically instead of rescanning a growing
                # megabyte at every token; normal prose keeps the 48-char step.
                check_after = max(_STREAM_RELEASE_STEP, pending_chars // 2)
                if not self._scan_text(text).clean:
                    progressive = False
                    continue
                remaining = _safe_prefix(text)
                pending_chars -= remaining
                if remaining:
                    check_after = _STREAM_RELEASE_STEP
                while remaining and buffered:
                    item = buffered.popleft()
                    content = item.content or ""
                    if len(content) <= remaining:
                        yield item
                        remaining -= len(content)
                    else:
                        yield replace(item, content=content[:remaining])
                        buffered.appendleft(replace(item, content=content[remaining:]))
                        remaining = 0

        if not buffered:
            return
        text = "".join(chunk.content or "" for chunk in buffered)
        result = self._scan_text(text) if text else ScanResult()
        if result.clean:
            for chunk in buffered:
                yield chunk
            return

        # Already emitted prefixes cannot contain a finding or the start of
        # one. Redact the remaining text ONCE, preserving every metadata
        # fragment exactly once, in its original order. BLOCK emits nothing.
        sanitized = self._handle_findings(text, result, "output")
        content_emitted = False
        for chunk in buffered:
            content = None
            if chunk.content and not content_emitted:
                content = sanitized
                content_emitted = True
            yield replace(chunk, content=content)

    async def stream(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Use the same safe boundaries as rich output, including long secrets."""
        messages = self._process_input_messages(messages)

        async def chunks() -> AsyncIterator[StreamChunk]:
            async with aclosing(
                self._engine.stream(
                    messages,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                )
            ) as source:
                async for token in source:
                    yield StreamChunk(content=token)

        async with aclosing(self._checked_stream(chunks())) as checked:
            async for chunk in checked:
                if chunk.content is not None:
                    yield chunk.content

    async def stream_full(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        """Stream verified text without releasing tools or terminal data early."""
        messages = self._process_input_messages(messages)
        source = self._engine.stream_full(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
        async with aclosing(self._checked_stream(source)) as checked:
            async for chunk in checked:
                yield chunk

    def list_models(self) -> List[str]:
        """Delegate to wrapped engine."""
        return self._engine.list_models()

    def health(self) -> bool:
        """Delegate to wrapped engine."""
        return self._engine.health()


__all__ = ["GuardrailsEngine", "SecurityBlockError"]
