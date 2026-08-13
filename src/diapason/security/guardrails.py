"""GuardrailsEngine — security-aware inference engine wrapper."""

from __future__ import annotations

from collections.abc import AsyncIterator
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

    async def stream(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Buffer, scan, then release output so sensitive tokens never leak."""
        messages = self._process_input_messages(messages)
        accumulated: list[str] = []
        async for token in self._engine.stream(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        ):
            accumulated.append(token)
            if not self._scan_output:
                yield token

        if not self._scan_output:
            return
        full_output = "".join(accumulated)
        if not full_output:
            return
        result = self._scan_text(full_output)
        if result.clean:
            for token in accumulated:
                yield token
            return
        yield self._handle_findings(full_output, result, "output")

    async def stream_full(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> AsyncIterator["StreamChunk"]:
        """Buffer rich chunks and scan all textual output before release."""
        messages = self._process_input_messages(messages)
        buffered: list[StreamChunk] = []
        accumulated: list[str] = []
        async for chunk in self._engine.stream_full(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        ):
            buffered.append(chunk)
            if chunk.content:
                accumulated.append(chunk.content)

        if not self._scan_output:
            for chunk in buffered:
                yield chunk
            return

        full_output = "".join(accumulated)
        result = self._scan_text(full_output) if full_output else ScanResult()
        if result.clean:
            for chunk in buffered:
                yield chunk
            return

        sanitized = self._handle_findings(full_output, result, "output")
        content_emitted = False
        for chunk in buffered:
            content = None
            if chunk.content and not content_emitted:
                content = sanitized
                content_emitted = True
            yield replace(chunk, content=content)

    def list_models(self) -> List[str]:
        """Delegate to wrapped engine."""
        return self._engine.list_models()

    def health(self) -> bool:
        """Delegate to wrapped engine."""
        return self._engine.health()


__all__ = ["GuardrailsEngine", "SecurityBlockError"]
