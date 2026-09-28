"""Tests for SecretScanner and PIIScanner."""

from __future__ import annotations

import pytest

from diapason.security.scanner import PIIScanner, SecretScanner, _scan_python
from diapason.security.types import ThreatLevel

# ---------------------------------------------------------------------------
# SecretScanner tests
# ---------------------------------------------------------------------------


class TestSecretScanner:
    def test_secret_scanner_openai_key(self) -> None:
        scanner = SecretScanner()
        result = scanner.scan("my key is sk-abc123def456ghi789jkl012")
        assert not result.clean
        assert any(f.pattern_name == "openai_key" for f in result.findings)
        assert any(f.threat_level == ThreatLevel.CRITICAL for f in result.findings)

    def test_secret_scanner_anthropic_key(self) -> None:
        scanner = SecretScanner()
        result = scanner.scan("key=sk-ant-abc123def456ghi789jkl012")
        assert not result.clean
        assert any(f.pattern_name == "anthropic_key" for f in result.findings)

    def test_secret_scanner_aws_key(self) -> None:
        scanner = SecretScanner()
        result = scanner.scan("AKIA1234567890ABCDEF")
        assert not result.clean
        assert any(f.pattern_name == "aws_access_key" for f in result.findings)

    def test_secret_scanner_github_token(self) -> None:
        scanner = SecretScanner()
        token = "ghp_" + "a" * 36
        result = scanner.scan(f"token = {token}")
        assert not result.clean
        assert any(f.pattern_name == "github_token" for f in result.findings)

    def test_secret_scanner_private_key(self) -> None:
        scanner = SecretScanner()
        result = scanner.scan("-----BEGIN RSA PRIVATE KEY-----\nMIIE...")
        assert not result.clean
        assert any(f.pattern_name == "private_key" for f in result.findings)

    def test_secret_scanner_password(self) -> None:
        scanner = SecretScanner()
        result = scanner.scan('password = "mysecretpass"')
        assert not result.clean
        assert any(f.pattern_name == "password_assignment" for f in result.findings)
        assert any(f.threat_level == ThreatLevel.HIGH for f in result.findings)

    def test_secret_scanner_db_string(self) -> None:
        scanner = SecretScanner()
        result = scanner.scan("postgres://user:pass@host:5432/mydb")
        assert not result.clean
        assert any(f.pattern_name == "db_connection_string" for f in result.findings)

    def test_secret_scanner_clean(self) -> None:
        scanner = SecretScanner()
        result = scanner.scan("This is a perfectly normal text with no secrets.")
        assert result.clean
        assert result.highest_threat is None

    def test_secret_scanner_redact(self) -> None:
        scanner = SecretScanner()
        text = "my key is sk-abc123def456ghi789jkl012"
        redacted = scanner.redact(text)
        assert "[REDACTED:openai_key]" in redacted
        assert "sk-abc123" not in redacted

    def test_secret_scanner_slack_token(self) -> None:
        scanner = SecretScanner()
        result = scanner.scan("slack: xoxb-123456789-abcde")
        assert not result.clean
        assert any(f.pattern_name == "slack_token" for f in result.findings)

    def test_secret_scanner_stripe_key(self) -> None:
        scanner = SecretScanner()
        result = scanner.scan("sk_test_abcdefghijklmnopqrst")  # gitleaks:allow
        assert not result.clean
        assert any(f.pattern_name == "stripe_key" for f in result.findings)

    def test_secret_scanner_generic_api_key(self) -> None:
        scanner = SecretScanner()
        result = scanner.scan('api_key = "my_super_secret_key_1234"')
        assert not result.clean
        assert any(f.pattern_name == "generic_api_key" for f in result.findings)


# ---------------------------------------------------------------------------
# PIIScanner tests
# ---------------------------------------------------------------------------


class TestPIIScanner:
    def test_pii_scanner_email(self) -> None:
        scanner = PIIScanner()
        result = scanner.scan("contact me at user@example.com please")
        assert not result.clean
        assert any(f.pattern_name == "email" for f in result.findings)
        assert any(f.threat_level == ThreatLevel.MEDIUM for f in result.findings)

    def test_pii_scanner_ssn(self) -> None:
        scanner = PIIScanner()
        result = scanner.scan("My SSN is 123-45-6789")
        assert not result.clean
        assert any(f.pattern_name == "us_ssn" for f in result.findings)
        assert any(f.threat_level == ThreatLevel.CRITICAL for f in result.findings)

    def test_pii_scanner_visa(self) -> None:
        scanner = PIIScanner()
        result = scanner.scan("card: 4111 1111 1111 1111")
        assert not result.clean
        assert any(f.pattern_name == "credit_card_visa" for f in result.findings)

    def test_pii_scanner_mastercard(self) -> None:
        scanner = PIIScanner()
        result = scanner.scan("card: 5111 1111 1111 1111")
        assert not result.clean
        assert any(f.pattern_name == "credit_card_mastercard" for f in result.findings)

    def test_pii_scanner_amex(self) -> None:
        scanner = PIIScanner()
        result = scanner.scan("card: 3411 123456 12345")
        assert not result.clean
        assert any(f.pattern_name == "credit_card_amex" for f in result.findings)

    def test_pii_scanner_phone(self) -> None:
        scanner = PIIScanner()
        result = scanner.scan("Call me at (555) 123-4567")
        assert not result.clean
        assert any(f.pattern_name == "us_phone" for f in result.findings)

    def test_pii_scanner_clean(self) -> None:
        scanner = PIIScanner()
        result = scanner.scan("This is a perfectly normal text with no PII.")
        assert result.clean

    def test_pii_scanner_redact(self) -> None:
        scanner = PIIScanner()
        text = "email me at user@example.com"
        redacted = scanner.redact(text)
        assert "[REDACTED:email]" in redacted
        assert "user@example.com" not in redacted

    def test_pii_scanner_ssn_redact(self) -> None:
        scanner = PIIScanner()
        text = "SSN: 123-45-6789"
        redacted = scanner.redact(text)
        assert "[REDACTED:us_ssn]" in redacted
        assert "123-45-6789" not in redacted


# ---------------------------------------------------------------------------
# ScanResult property tests
# ---------------------------------------------------------------------------


class TestScanResult:
    def test_highest_threat_critical(self) -> None:
        scanner = SecretScanner()
        result = scanner.scan("sk-abc123def456ghi789jkl012")
        assert result.highest_threat == ThreatLevel.CRITICAL

    def test_highest_threat_none_when_clean(self) -> None:
        scanner = SecretScanner()
        result = scanner.scan("clean text")
        assert result.highest_threat is None

    def test_multiple_findings(self) -> None:
        scanner = SecretScanner()
        text = 'password = "secret123" and key sk-abc123def456ghi789jkl012'
        result = scanner.scan(text)
        assert len(result.findings) >= 2


# ---------------------------------------------------------------------------
# Le repli Python face à l'extension
# ---------------------------------------------------------------------------
#
# 28/09/2026 : scanner.py dit son repli « intentionally feature-equivalent »
# à l'extension. Il ne l'est pas, et ces tests le MONTRENT sans le corriger :
# la décision (quel côté a raison, quel nom garder) reste à prendre. strict :
# le jour où l'écart se ferme, le test passe et échoue, pour qu'on retire la
# marque au lieu de laisser une promesse périmée.


def _trouves(scanner, texte: str) -> list[tuple[str, str]]:
    return sorted(
        (f.pattern_name, f.matched_text) for f in scanner.scan(texte).findings
    )


def _trouves_du_repli(scanner, texte: str) -> list[tuple[str, str]]:
    return sorted(
        (f.pattern_name, f.matched_text)
        for f in _scan_python(texte, type(scanner).PATTERNS).findings
    )


def _ecarts(scanner, textes: list[str]) -> list[str]:
    if scanner._rust_impl is None:
        pytest.skip("extension absente : seul le repli s'applique, rien à comparer")
    return [
        f"{texte!r} : l'extension trouve {_trouves(scanner, texte)}, "
        f"le repli {_trouves_du_repli(scanner, texte)}"
        for texte in textes
        if _trouves(scanner, texte) != _trouves_du_repli(scanner, texte)
    ]


class TestLeRepliFaitCommeLExtension:
    """§5 : un repli qui se dit équivalent doit l'être, ou cesser de le dire."""

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "écart relevé le 28/09/2026, à trancher : le repli (ipv4_public) "
            "écarte 10/8, 172.16/12, 192.168/16, 127/8 et 0/8 par des regards "
            "avant, l'extension (ipv4_address) masque toute adresse ; et les "
            "noms diffèrent, [REDACTED:ipv4_public] contre "
            "[REDACTED:ipv4_address]"
        ),
    )
    def test_le_repli_et_l_extension_trouvent_les_memes_adresses_ipv4(self):
        """§5 : selon que l'extension charge ou non, 10.0.0.1 sort masqué ou pas."""
        ecarts = _ecarts(
            PIIScanner(),
            ["Serveur interne 10.0.0.1 joint.", "DNS public 8.8.8.8 ici."],
        )
        assert not ecarts, "le repli n'est pas équivalent :\n" + "\n".join(ecarts)

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "écart relevé le 28/09/2026, à trancher : _scan_python compile "
            "chaque motif avec re.IGNORECASE, scanner.rs est sensible à la "
            'casse — « Password: "…" » passe EN CLAIR par l\'extension, celle '
            "que le flux applique"
        ),
    )
    def test_le_repli_et_l_extension_lisent_la_casse_pareil(self):
        """§5 : « Password: "…" » n'est masqué que si l'extension manque."""
        ecarts = _ecarts(
            SecretScanner(),
            ['Password: "correct horse battery"', "SK-abcdefghijklmnopqrstuvwxyz"],
        )
        assert not ecarts, "le repli n'est pas équivalent :\n" + "\n".join(ecarts)
