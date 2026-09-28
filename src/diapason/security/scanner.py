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
            # accelerator is unavailable.  The Python implementation below
            # compiles the very strings of scanner.rs, just slower.  The two
            # engines still differ on IPv4, on word boundaries (\b, \w), on
            # the Unicode digits \d admits, on U+001C..U+001F inside a
            # database URI, and on finding offsets (UTF-8 bytes in Rust):
            # test_scanner.py names each one with a strict xfail.
            self._rust_impl = None

    # 28/09/2026 : chaque motif était compilé sous re.IGNORECASE, ceux de
    # scanner.rs ne l'étaient pas — et c'est l'extension que le flux
    # applique : « Password: "…" » sortait en clair dès qu'elle était
    # chargée. Même chaîne des deux côtés désormais, la casse décidée motif
    # par motif (voir le commentaire de SECRET_PATTERNS dans scanner.rs) :
    # (?i:…) sur les mots-clés qu'on tape ; pour les jetons, la casse du
    # format et la seule majuscule initiale d'un début de phrase. Le blanc
    # s'écrit [\s\x1c-\x1f] : c'est le \s de re, que celui de Rust n'atteint
    # qu'avec U+001C..U+001F. Le ['"]? d'une affectation lit le guillemet
    # fermant d'une clé JSON ou d'un dict, qui fuyait par les deux moteurs
    # (même commentaire).
    PATTERNS: Dict[str, Tuple[str, ThreatLevel, str]] = {
        "openai_key": (
            r"[Ss]k-[A-Za-z0-9_-]{20,}",
            ThreatLevel.CRITICAL,
            "OpenAI API key",
        ),
        "anthropic_key": (
            r"[Ss]k-ant-[A-Za-z0-9_-]{20,}",
            ThreatLevel.CRITICAL,
            "Anthropic API key",
        ),
        "aws_access_key": (
            r"AKIA[0-9A-Z]{16}",
            ThreatLevel.CRITICAL,
            "AWS access key",
        ),
        "github_token": (
            r"[Gg](?:hp|ho|hs|hr|ithub_pat)_[A-Za-z0-9_]{36,}",
            ThreatLevel.CRITICAL,
            "GitHub token",
        ),
        "password_assignment": (
            r"""(?i:password|passwd|pwd)['"]?[\s\x1c-\x1f]*[=:][\s\x1c-\x1f]*['"]([^'"]{4,})['"]""",
            ThreatLevel.HIGH,
            "Password assignment",
        ),
        "db_connection_string": (
            r"(?i:postgres|mysql|mongodb|red[iİı]s)://[^\s]{10,}",
            ThreatLevel.HIGH,
            "Database connection string",
        ),
        "private_key": (
            r"-----BEGIN (?:RSA )?PRIVATE KEY-----",
            ThreatLevel.CRITICAL,
            "Private key",
        ),
        "slack_token": (
            r"[Xx]ox[bpors]-[A-Za-z0-9\-]{10,}",
            ThreatLevel.HIGH,
            "Slack token",
        ),
        "stripe_key": (
            r"[SsPp]k_(?:test|live)_[A-Za-z0-9]{20,}",
            ThreatLevel.CRITICAL,
            "Stripe key",
        ),
        "generic_api_key": (
            r"""(?i:ap[iİı]_key|secret_key|auth_token)['"]?[\s\x1c-\x1f]*[=:][\s\x1c-\x1f]*['"]([^'"]{8,})['"]""",
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
            # Sans (?i), comme dans scanner.rs : la classe nomme déjà les deux
            # casses ASCII. re.IGNORECASE n'y ajoutait que İ, ı, ſ et K
            # (U+212A), qu'une adresse ASCII ne contient pas ; une adresse
            # internationalisée (« josé@… ») échappe aux deux moteurs.
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
            r"\b4\d{3}[-\s\x1c-\x1f]?\d{4}[-\s\x1c-\x1f]?\d{4}[-\s\x1c-\x1f]?\d{4}\b",
            ThreatLevel.CRITICAL,
            "Visa credit card",
        ),
        "credit_card_mastercard": (
            r"\b5[1-5]\d{2}[-\s\x1c-\x1f]?\d{4}[-\s\x1c-\x1f]?\d{4}[-\s\x1c-\x1f]?\d{4}\b",
            ThreatLevel.CRITICAL,
            "Mastercard credit card",
        ),
        "credit_card_amex": (
            r"\b3[47]\d{2}[-\s\x1c-\x1f]?\d{6}[-\s\x1c-\x1f]?\d{5}\b",
            ThreatLevel.CRITICAL,
            "Amex credit card",
        ),
        "us_phone": (
            # Voir scanner.rs : dix chiffres quelconques ne sont pas un
            # numéro de téléphone. Il faut un indicatif +1, des parenthèses,
            # ou de vrais séparateurs entre les groupes.
            r"(?:\+1[-.\s\x1c-\x1f]?)?\(\d{3}\)[-.\s\x1c-\x1f]?\d{3}[-.\s\x1c-\x1f]?\d{4}|\+1[-.\s\x1c-\x1f]?\d{3}[-.\s\x1c-\x1f]?\d{3}[-.\s\x1c-\x1f]?\d{4}|\b\d{3}[-.\s\x1c-\x1f]\d{3}[-.\s\x1c-\x1f]\d{4}\b",
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
        for match in re.finditer(pattern, text):
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
        result = re.sub(pattern, f"[REDACTED:{name}]", result)
    return result


__all__ = ["PIIScanner", "SecretScanner"]
