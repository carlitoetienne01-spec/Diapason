"""Concrete security scanners — secrets and PII detection."""

from __future__ import annotations

import re
from typing import Dict, Tuple

from diapason._rust_bridge import get_rust_module, scan_result_from_json
from diapason.security._stubs import BaseScanner
from diapason.security.types import ScanResult, ThreatLevel

# ---------------------------------------------------------------------------
# SecretScanner
# ---------------------------------------------------------------------------


class SecretScanner(BaseScanner):
    """Detect API keys, tokens, passwords, and other secrets in text."""

    scanner_id = "secrets"

    def __init__(self) -> None:
        try:
            _rust = get_rust_module()
            self._rust_impl = _rust.SecretScanner()
        except (ImportError, AttributeError, RuntimeError):
            # Security must not disappear merely because the optional native
            # accelerator is unavailable.  The Python implementation below is
            # intentionally feature-equivalent, just slower.
            self._rust_impl = None

    PATTERNS: Dict[str, Tuple[str, ThreatLevel, str]] = {
        "openai_key": (
            r"sk-[A-Za-z0-9_-]{20,}",
            ThreatLevel.CRITICAL,
            "OpenAI API key",
        ),
        "anthropic_key": (
            r"sk-ant-[A-Za-z0-9_-]{20,}",
            ThreatLevel.CRITICAL,
            "Anthropic API key",
        ),
        "aws_access_key": (
            r"AKIA[0-9A-Z]{16}",
            ThreatLevel.CRITICAL,
            "AWS access key",
        ),
        "github_token": (
            r"(?:ghp|gho|ghs|ghr|github_pat)_[A-Za-z0-9_]{36,}",
            ThreatLevel.CRITICAL,
            "GitHub token",
        ),
        "password_assignment": (
            r"""(?:password|passwd|pwd)\s*[=:]\s*['"]([^'"]{4,})['"]""",
            ThreatLevel.HIGH,
            "Password assignment",
        ),
        "db_connection_string": (
            r"(?:postgres|mysql|mongodb|redis)://[^\s]{10,}",
            ThreatLevel.HIGH,
            "Database connection string",
        ),
        "private_key": (
            r"-----BEGIN (?:RSA )?PRIVATE KEY-----",
            ThreatLevel.CRITICAL,
            "Private key",
        ),
        "slack_token": (
            r"xox[bpors]-[A-Za-z0-9\-]{10,}",
            ThreatLevel.HIGH,
            "Slack token",
        ),
        "stripe_key": (
            r"(?:sk|pk)_(?:test|live)_[A-Za-z0-9]{20,}",
            ThreatLevel.CRITICAL,
            "Stripe key",
        ),
        "generic_api_key": (
            r"""(?:api_key|secret_key|auth_token)\s*[=:]\s*['"]([^'"]{8,})['"]""",
            ThreatLevel.HIGH,
            "Generic API key/secret",
        ),
    }

    def scan(self, text: str) -> ScanResult:
        """Scan *text* for secret patterns using Rust or the safe fallback."""
        if self._rust_impl is not None:
            return scan_result_from_json(self._rust_impl.scan(text))
        return _scan_python(text, self.PATTERNS)

    def redact(self, text: str) -> str:
        """Replace secret matches with ``[REDACTED:{pattern_name}]``."""
        if self._rust_impl is not None:
            return self._rust_impl.redact(text)
        return _redact_python(text, self.PATTERNS)


# ---------------------------------------------------------------------------
# PIIScanner
# ---------------------------------------------------------------------------


class PIIScanner(BaseScanner):
    """Detect personally identifiable information in text."""

    scanner_id = "pii"

    def __init__(self) -> None:
        try:
            _rust = get_rust_module()
            self._rust_impl = _rust.PIIScanner()
        except (ImportError, AttributeError, RuntimeError):
            self._rust_impl = None

    PATTERNS: Dict[str, Tuple[str, ThreatLevel, str]] = {
        "email": (
            r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
            ThreatLevel.MEDIUM,
            "Email address",
        ),
        "us_ssn": (
            r"\b\d{3}-\d{2}-\d{4}\b",
            ThreatLevel.CRITICAL,
            "US Social Security Number",
        ),
        "credit_card_visa": (
            r"\b4\d{3}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",
            ThreatLevel.CRITICAL,
            "Visa credit card",
        ),
        "credit_card_mastercard": (
            r"\b5[1-5]\d{2}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",
            ThreatLevel.CRITICAL,
            "Mastercard credit card",
        ),
        "credit_card_amex": (
            r"\b3[47]\d{2}[\s-]?\d{6}[\s-]?\d{5}\b",
            ThreatLevel.CRITICAL,
            "Amex credit card",
        ),
        "us_phone": (
            r"\b(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
            ThreatLevel.MEDIUM,
            "US phone number",
        ),
        "ipv4_public": (
            r"\b(?!10\.)(?!172\.(?:1[6-9]|2\d|3[01])\.)(?!192\.168\.)(?!127\.)(?!0\.)\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",
            ThreatLevel.LOW,
            "Public IPv4 address",
        ),
    }

    def scan(self, text: str) -> ScanResult:
        """Scan *text* for PII patterns using Rust or the safe fallback."""
        if self._rust_impl is not None:
            return scan_result_from_json(self._rust_impl.scan(text))
        return _scan_python(text, self.PATTERNS)

    def redact(self, text: str) -> str:
        """Replace PII matches with ``[REDACTED:{pattern_name}]``."""
        if self._rust_impl is not None:
            return self._rust_impl.redact(text)
        return _redact_python(text, self.PATTERNS)


def _scan_python(
    text: str,
    patterns: Dict[str, Tuple[str, ThreatLevel, str]],
) -> ScanResult:
    """Pure-Python scanner used when the Rust accelerator is unavailable."""
    from diapason.security.types import ScanFinding

    result = ScanResult()
    for name, (pattern, level, description) in patterns.items():
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            result.findings.append(
                ScanFinding(
                    pattern_name=name,
                    matched_text=match.group(0),
                    threat_level=level,
                    start=match.start(),
                    end=match.end(),
                    description=description,
                )
            )
    return result


def _redact_python(
    text: str,
    patterns: Dict[str, Tuple[str, ThreatLevel, str]],
) -> str:
    result = text
    for name, (pattern, _level, _description) in patterns.items():
        result = re.sub(
            pattern,
            f"[REDACTED:{name}]",
            result,
            flags=re.IGNORECASE,
        )
    return result


__all__ = ["PIIScanner", "SecretScanner"]
