"""Tests for SecretScanner and PIIScanner."""

from __future__ import annotations

import functools
import re
import unicodedata

import pytest

from diapason.security.scanner import (
    PIIScanner,
    SecretScanner,
    _redact_python,
    _scan_python,
)
from diapason.security.types import ThreatLevel
from tests.security.test_guardrails_reserve import motifs_rust, tout_unicode

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
# 28/09/2026 : scanner.py disait son repli « intentionally feature-equivalent »
# à l'extension. Il ne l'était pas. La casse et le blanc sont tranchés (voir
# le commentaire de SECRET_PATTERNS dans scanner.rs) et les deux fichiers
# portent désormais les mêmes chaînes. Ce que les deux moteurs lisent encore
# autrement — l'IPv4, les bornes de mot, les chiffres d'Unicode 16, U+001C..
# U+001F dans une URI de base, la position d'une trouvaille — est montré par
# un xfail strict chacun : le jour où l'un se ferme, son test passe et
# échoue, pour qu'on retire la marque au lieu de laisser une promesse périmée.


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
    # Le repli trouve par _scan_python et masque par _redact_python, deux
    # boucles qui compilent chacune ses motifs. 28/09/2026 : un re.IGNORECASE
    # rendu au seul _redact_python laissait toute la suite verte — il masquait
    # « RISK-ASSESSMENT-FRAMEWORK-2026 » que scan() déclarait propre. Les deux
    # moitiés se comparent donc à l'extension.
    if scanner._rust_impl is None:
        pytest.skip("extension absente : seul le repli s'applique, rien à comparer")
    ecarts = []
    for texte in textes:
        trouves, du_repli = _trouves(scanner, texte), _trouves_du_repli(scanner, texte)
        if trouves != du_repli:
            ecarts.append(
                f"{texte!r} : l'extension trouve {trouves}, le repli {du_repli}"
            )
            continue
        masque = scanner.redact(texte)
        masque_du_repli = _redact_python(texte, type(scanner).PATTERNS)
        if masque != masque_du_repli:
            ecarts.append(
                f"{texte!r} : l'extension rend {masque!r}, le repli {masque_du_repli!r}"
            )
    return ecarts


# Un témoin par motif, dans la casse de son format. Les valeurs ont des
# espaces et les jetons sont assemblés : un balayage de secrets du dépôt ne
# doit pas les prendre pour de vraies clés.
_CORPS = "abcdefghijklmnopqrstuvwxyz0123456789ABCD"
TEMOINS = {
    SecretScanner: [
        "sk-" + _CORPS,
        "sk-ant-" + _CORPS,
        "AKIA" + "ABCDEFGHIJKLMNOP",
        "gh" + "p_" + _CORPS,
        "github" + "_pat_" + _CORPS,
        'password = "correct horse battery"',
        "passwd: 'correct horse battery'",
        'pwd="correct horse"',
        "postgres://admin:correct@horse.example.com/prod",
        "mysql://root:correct@horse.example.com/app",
        "mongodb://u:correct@horse.example.com",
        "redis://:correct@horse.example.com:6379",
        "-----BEGIN RSA PRIVATE KEY-----",
        "xo" + "xb-1234567890-abcdef",
        "pk" + "_test_" + _CORPS,
        "api_key = 'correct horse battery'",
        'secret_key: "correct horse battery"',
        "auth_token='correct horse battery'",
        '{"password": "correct horse battery"}',
        "{'api_key': 'correct horse battery'}",
    ],
    # i, k et s : les lettres que re.IGNORECASE étend hors de l'ASCII.
    PIIScanner: ["écrire à louis.kirk@example.com demain"],
}


@functools.cache
def _casses_de_re(lettre: str) -> str:
    """Chaque caractère que re.IGNORECASE confond avec ``lettre``."""
    return "".join(
        t.group() for t in re.finditer(re.escape(lettre), tout_unicode(), re.I)
    )


def _variantes(temoin: str) -> list[str]:
    """Le témoin recassé en bloc, puis lettre par lettre, sur toute l'orbite
    que re.IGNORECASE lui connaît (İ et ı pour i, K pour k, ſ pour s)."""
    variantes = {
        temoin.upper(),
        temoin.lower(),
        temoin.capitalize(),
        temoin.title(),
        temoin.swapcase(),
    }
    for rang, lettre in enumerate(temoin):
        for autre in _casses_de_re(lettre):
            variantes.add(temoin[:rang] + autre + temoin[rang + 1 :])
    return sorted(variantes)


def _par(classe, chemin: str):
    """Un scanner qui passe par l'extension, ou par le repli forcé."""
    objet = classe()
    if chemin == "repli":
        objet._rust_impl = None
    elif objet._rust_impl is None:
        pytest.skip("extension absente : le repli reste éprouvé")
    return objet


class TestLaCasseEstDecideeMotifParMotif:
    """§5 : un mot de passe en majuscules ne sort pas en clair, jamais.

    28/09/2026 : « Password: "…" » et « PASSWORD = '…' » passaient EN CLAIR
    par l'extension, celle que le flux applique, et n'étaient masqués que
    par le repli. Les deux chemins sont éprouvés : l'extension ici, le repli
    forcé à côté.
    """

    @pytest.mark.parametrize("chemin", ["extension", "repli"])
    @pytest.mark.parametrize(
        ("texte", "nom"),
        [
            ('Password: "correct horse battery"', "password_assignment"),
            ("PASSWORD = 'correct horse battery'", "password_assignment"),
            ("PassWd:'correct horse battery'", "password_assignment"),
            ("api_KEY='correct horse battery'", "generic_api_key"),
            ('Secret_Key: "correct horse battery"', "generic_api_key"),
            ("AUTH_TOKEN = 'correct horse battery'", "generic_api_key"),
            ("AP\u0130_KEY = 'correct horse battery'", "generic_api_key"),
            ("Postgres://admin:correct@horse.example.com/prod", "db_connection_string"),
            ("RED\u0130S://:correct@horse.example.com", "db_connection_string"),
            ("Sk-" + _CORPS, "openai_key"),
            ("G" + "hp_" + _CORPS, "github_token"),
            ("Xo" + "xb-1234567890-abcdef", "slack_token"),
        ],
    )
    def test_un_secret_qui_reste_utilisable_est_masque_dans_toute_casse(
        self, chemin, texte, nom
    ):
        """§5 : le mot-clé qu'on tape, la majuscule d'un début de phrase."""
        masque = _par(SecretScanner, chemin).redact(texte)
        assert masque == f"[REDACTED:{nom}]", (
            f"{texte!r} sort {masque!r} par le {chemin} : le secret reste lisible"
        )

    @pytest.mark.parametrize("chemin", ["extension", "repli"])
    @pytest.mark.parametrize(
        "texte",
        [
            "SK-" + _CORPS.upper(),
            "RISK-ASSESSMENT-FRAMEWORK-2026",
            "akia" + "0123456789abcdef",
            "DISK_TEST_ABCDEFGHIJKLMNOPQRSTUV",
            "-----begin rsa private key-----",
        ],
    )
    def test_un_jeton_recasse_ailleurs_qu_en_tete_n_est_plus_une_cle(
        self, chemin, texte
    ):
        """§5 : un (?i) complet masquait de la prose pour une clé détruite.

        scan() et redact() sont deux chemins dans le repli : un IGNORECASE
        rendu au seul redact() masquait ce que scan() déclarait propre.
        """
        scanner = _par(SecretScanner, chemin)
        trouves = scanner.scan(texte).findings
        assert not trouves, (
            f"{texte!r} masqué par le {chemin} ({trouves[0].pattern_name}) : ni "
            "la casse de son format, ni une majuscule de début de phrase"
        )
        assert scanner.redact(texte) == texte, (
            f"{texte!r} sort {scanner.redact(texte)!r} du masque du {chemin}, que "
            "scan() déclare propre"
        )


class TestLeBlancEstCeluiDeRe:
    """§5 : un blanc que re lit comme tel ne fait pas passer un secret.

    28/09/2026 : le \\s de re admet U+001C..U+001F, celui de Rust non.
    « Password\\x1c: '…' » ou une carte coupée de \\x1c sortaient en clair
    par l'extension, masqués par le seul repli.
    """

    @pytest.mark.parametrize("chemin", ["extension", "repli"])
    @pytest.mark.parametrize("blanc", ["\x1c", "\x1d", "\x1e", "\x1f"])
    @pytest.mark.parametrize(
        ("gabarit", "classe", "nom"),
        [
            ("Password{b}: 'correct horse'", SecretScanner, "password_assignment"),
            ("API_KEY ={b}'correct horse battery'", SecretScanner, "generic_api_key"),
            ("4111{b}1111{b}1111{b}1111", PIIScanner, "credit_card_visa"),
            ("5555{b}5555 5555 4444", PIIScanner, "credit_card_mastercard"),
            ("3782{b}822463{b}10005", PIIScanner, "credit_card_amex"),
            ("+1{b}202{b}555{b}0199", PIIScanner, "us_phone"),
            ("+1{b}(202){b}555{b}0199", PIIScanner, "us_phone"),
        ],
    )
    def test_un_separateur_de_controle_ne_fait_pas_passer_un_secret(
        self, chemin, blanc, gabarit, classe, nom
    ):
        """§5 : un séparateur d'information (U+001C..U+001F) est un blanc pour re."""
        texte = gabarit.format(b=blanc)
        masque = _par(classe, chemin).redact(texte)
        assert masque == f"[REDACTED:{nom}]", (
            f"{texte!r} sort {masque!r} par le {chemin} : le secret reste lisible"
        )


class TestUneCleEntreGuillemets:
    """§5 : un mot de passe rangé dans un objet JSON ne sort pas en clair.

    28/09/2026 : « {"password": "…"} », comme « {'api_key': '…'} » dans un
    dict Python, passait par les DEUX moteurs : le guillemet fermant de la clé
    s'intercalait entre le mot-clé et « : ».
    """

    @pytest.mark.parametrize("chemin", ["extension", "repli"])
    @pytest.mark.parametrize(
        ("texte", "masque"),
        [
            (
                '{"password": "correct horse battery"}',
                '{"[REDACTED:password_assignment]}',
            ),
            ('{"Password":"correct horse"}', '{"[REDACTED:password_assignment]}'),
            ("{'api_key': 'correct horse battery'}", "{'[REDACTED:generic_api_key]}"),
            (
                '{"AUTH_TOKEN" : "correct horse battery"}',
                '{"[REDACTED:generic_api_key]}',
            ),
            (
                "- 'secret_key': \"correct horse battery\"",
                "- '[REDACTED:generic_api_key]",
            ),
        ],
    )
    def test_une_cle_entre_guillemets_est_masquee(self, chemin, texte, masque):
        """§5 : la clé d'un objet, pas seulement le nom d'une variable."""
        rendu = _par(SecretScanner, chemin).redact(texte)
        assert rendu == masque, (
            f"{texte!r} sort {rendu!r} par le {chemin} : le secret reste lisible"
        )

    @pytest.mark.parametrize("chemin", ["extension", "repli"])
    @pytest.mark.parametrize(
        "texte",
        [
            'le champ "password" reste vide',
            "{'password': None}",
            '{"api_key": ""}',
        ],
    )
    def test_une_cle_sans_valeur_citee_reste_intacte(self, chemin, texte):
        """§5 : le guillemet admis ne fait pas d'un mot une affectation."""
        rendu = _par(SecretScanner, chemin).redact(texte)
        assert rendu == texte, f"{texte!r} sort {rendu!r} par le {chemin}"


# Un témoin par motif qui lit un blanc, une espace à chaque place où il le lit.
TEMOINS_DU_BLANC = {
    SecretScanner: [
        "password = 'correct horse'",
        'api_key : "correct horse battery"',
        '{"password" : "correct horse"}',
    ],
    PIIScanner: [
        "4111 1111 1111 1111",
        "5555 5555 5555 4444",
        "3782 822463 10005",
        "+1 (202) 555 0199",
        "+1 202 555 0199",
        "202 555 0199",
    ],
}


class TestLeRepliFaitCommeLExtension:
    """§5 : un repli qui se dit équivalent doit l'être, ou cesser de le dire."""

    def test_les_deux_fichiers_portent_les_memes_chaines(self):
        """§5 : une chaîne corrigée d'un seul côté rouvrirait l'écart de casse."""
        rust = {m.nom: m.source for m in motifs_rust()}
        python = {
            nom: source
            for classe in (SecretScanner, PIIScanner)
            for nom, (source, _niveau, _description) in classe.PATTERNS.items()
        }
        # L'écart IPv4 est montré à part, xfail, en attendant d'être tranché.
        rust.pop("ipv4_address")
        python.pop("ipv4_public")
        differents = sorted(
            f"{nom} : scanner.rs {rust.get(nom)!r}, scanner.py {python.get(nom)!r}"
            for nom in rust.keys() | python.keys()
            if rust.get(nom) != python.get(nom)
        )
        assert not differents, "les deux tables divergent :\n" + "\n".join(differents)

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
            "écart relevé le 28/09/2026, à trancher : le \\w de Rust, donc son "
            "\\b, compte comme lettres les marques (Mn, Mc, Me), U+200C et "
            "U+200D, les Pc autres que _, les lettres cerclées et 4 433 points "
            "d'Unicode 16 ; celui de re, les 915 chiffres No (², ½, ①). Un "
            "numéro collé à un é décomposé ou à U+200D n'est masqué que par le "
            "repli, collé à ² que par l'extension. Aucune chaîne commune ne les "
            "aligne : (?-u:\\b) n'existe pas dans re, (?a:\\b) pas dans Rust"
        ),
    )
    def test_le_repli_et_l_extension_voient_les_memes_bornes_de_mot(self):
        """§5 : un numéro de carte ne doit pas dépendre du moteur chargé."""
        ecarts = _ecarts(
            PIIScanner(),
            [
                "cle\u0301123-45-6789",
                "carte\u200d4111 1111 1111 1111",
                "x\u00b2123-45-6789",
            ],
        )
        assert not ecarts, "le repli n'est pas équivalent :\n" + "\n".join(ecarts)

    @pytest.mark.xfail(
        tuple(map(int, unicodedata.unidata_version.split("."))) < (16,),
        strict=True,
        reason=(
            "écart relevé le 28/09/2026 : regex-syntax 0.8.10 lit Unicode 16, "
            f"re celui de Python ({unicodedata.unidata_version}) ; les 80 "
            "chiffres qu'ajoute Unicode 16 (U+10D40, U+16130…) sont un \\d pour "
            "l'extension seule, qui masque plus que le repli. Se ferme avec "
            "Python 3.14"
        ),
    )
    def test_le_repli_et_l_extension_lisent_les_memes_chiffres(self):
        """§5 : le \\d des deux moteurs suit leur version d'Unicode."""
        ecarts = _ecarts(PIIScanner(), ["\U0001613023-45-6789"])
        assert not ecarts, "le repli n'est pas équivalent :\n" + "\n".join(ecarts)

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "écart relevé le 28/09/2026, à trancher : dans le corps d'une URI "
            "de base, le [^\\s] de Rust admet U+001C..U+001F, celui de re non. "
            "L'extension masque « redis://\\x1c… », le repli pas. Aligner "
            "l'extension élargirait ce qui passe ; le repli s'alignerait par "
            "« (?:[^\\s]|[\\x1c-\\x1f]) »"
        ),
    )
    def test_le_repli_et_l_extension_lisent_le_meme_corps_d_uri(self):
        """§5 : une URI de base ne doit pas dépendre du moteur chargé."""
        ecarts = _ecarts(SecretScanner(), ["redis://\x1cadmin:correct@horse.example"])
        assert not ecarts, "le repli n'est pas équivalent :\n" + "\n".join(ecarts)

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "écart relevé le 28/09/2026, à trancher : start et end comptent "
            "des octets UTF-8 dans l'extension, des caractères dans le repli ; "
            "audit.py les journalise tels quels"
        ),
    )
    def test_le_repli_et_l_extension_situent_une_trouvaille_au_meme_endroit(self):
        """§5 : une position journalisée doit désigner le même caractère."""
        scanner = PIIScanner()
        if scanner._rust_impl is None:
            pytest.skip("extension absente : seul le repli s'applique")
        texte = "Écrire à louis@example.com"

        def positions(resultat):
            return [(f.start, f.end) for f in resultat.findings]

        assert positions(scanner.scan(texte)) == positions(
            _scan_python(texte, PIIScanner.PATTERNS)
        ), "l'extension et le repli ne situent pas l'adresse au même endroit"

    @pytest.mark.parametrize("classe", [SecretScanner, PIIScanner])
    def test_le_repli_et_l_extension_lisent_le_meme_blanc(self, classe):
        """§5 : « Password\\x1c: '…' » n'était masqué que par le repli.

        Chaque blanc de re, à chaque place où un témoin porte une espace :
        l'extension doit rendre exactement ce que rend le repli.
        """
        blancs = [t.group() for t in re.finditer(r"\s", tout_unicode())]
        ecarts = _ecarts(
            classe(),
            [
                temoin[:rang] + blanc + temoin[rang + 1 :]
                for temoin in TEMOINS_DU_BLANC[classe]
                for rang, car in enumerate(temoin)
                if car == " "
                for blanc in blancs
            ],
        )
        assert not ecarts, f"{len(ecarts)} écarts de blanc, dont :\n" + "\n".join(
            ecarts[:10]
        )

    @pytest.mark.parametrize("classe", [SecretScanner, PIIScanner])
    def test_le_repli_et_l_extension_lisent_la_casse_pareil(self, classe):
        """§5 : « Password: "…" » n'était masqué que si l'extension manquait.

        Chaque témoin, recassé en bloc puis lettre par lettre sur toute
        l'orbite de re.IGNORECASE : l'extension doit rendre exactement ce que
        rend le repli.
        """
        ecarts = _ecarts(
            classe(), [v for temoin in TEMOINS[classe] for v in _variantes(temoin)]
        )
        assert not ecarts, f"{len(ecarts)} écarts de casse, dont :\n" + "\n".join(
            ecarts[:10]
        )
