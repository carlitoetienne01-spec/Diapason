# La sécurité

Diapason active ses contrôles de sécurité dès l'installation. Il analyse les prompts et les sorties du modèle, protège les frontières de sortie d'appareil, authentifie l'API locale, limite le débit des requêtes et des outils, applique la politique de capacités, exige une approbation pour les outils sensibles, et enregistre des métadonnées d'audit qui rendent toute falsification visible — sans jamais conserver les secrets détectés.

---

## Le tour d'horizon

Le module de sécurité compte quatre composants utilisables indépendamment :

<div class="grid cards" markdown>

- :material-shield-search: **GuardrailsEngine**

    ---

    Enveloppe n'importe quel `InferenceEngine` d'une analyse avant et après l'appel. Trois modes : WARN, REDACT et BLOCK.

    [:octicons-arrow-right-24: Aller à GuardrailsEngine](#guardrailsengine)

- :material-key-remove: **SecretScanner**

    ---

    Détecte dans le texte les clés d'API, les jetons, les mots de passe et les chaînes de connexion.

    [:octicons-arrow-right-24: Aller à SecretScanner](#secretscanner)

- :material-account-lock: **PIIScanner**

    ---

    Détecte les adresses courriel, les numéros de sécurité sociale, les numéros de carte bancaire, les numéros de téléphone et les adresses IP publiques.

    [:octicons-arrow-right-24: Aller à PIIScanner](#piiscanner)

- :material-file-lock: **La politique des fichiers**

    ---

    Bloque l'accès à `.env`, `*.pem`, `id_rsa` et aux autres fichiers de secrets.

    [:octicons-arrow-right-24: Aller à la politique des fichiers](#file-policy)

</div>

---

## GuardrailsEngine

`GuardrailsEngine` enveloppe n'importe quel `InferenceEngine` et analyse à la fois les messages d'entrée et le contenu de sortie. Il n'est pas enregistré dans `EngineRegistry` — tu le crées directement, en enveloppant une instance de moteur existante.

### Les modes

| Mode | Constante | Comportement |
|------|----------|----------|
| Warn | `RedactionMode.WARN` | Publie un événement `SECURITY_ALERT` mais laisse passer le texte tel quel. C'est le mode par défaut. |
| Redact | `RedactionMode.REDACT` | Remplace les correspondances par `[REDACTED:pattern_name]` avant de les passer au moteur, et à la sortie du moteur. |
| Block | `RedactionMode.BLOCK` | Lève `SecurityBlockError` dès qu'une détection a lieu. |

### L'usage de base

=== "Le mode warn (par défaut)"

    ```python title="warn_mode.py"
    from diapason.engine.ollama import OllamaEngine
    from diapason.security.guardrails import GuardrailsEngine
    from diapason.security.types import RedactionMode
    from diapason.core.types import Message, Role

    engine = OllamaEngine()
    guarded = GuardrailsEngine(engine)  # (1)!

    messages = [Message(role=Role.USER, content="Ma clé d'API est sk-abc123xyz")]
    response = guarded.generate(messages, model="qwen3:8b")
    # La clé est consignée comme un avertissement, mais le texte passe inchangé
    print(response["content"])
    ```

    1. Par défaut : `mode=RedactionMode.WARN`, `scan_input=True`, `scan_output=True`.

=== "Le mode redact"

    ```python title="redact_mode.py"
    from diapason.engine.ollama import OllamaEngine
    from diapason.security.guardrails import GuardrailsEngine
    from diapason.security.types import RedactionMode
    from diapason.core.types import Message, Role

    engine = OllamaEngine()
    guarded = GuardrailsEngine(engine, mode=RedactionMode.REDACT)  # (1)!

    messages = [Message(role=Role.USER, content="Ma clé est sk-abc123xyz, aide-moi à déboguer")]
    response = guarded.generate(messages, model="qwen3:8b")
    # Entrée envoyée au moteur : "Ma clé est [REDACTED:openai_key], aide-moi à déboguer"
    ```

    1. Les motifs sensibles des messages d'entrée sont remplacés avant d'atteindre le modèle.

=== "Le mode block"

    ```python title="block_mode.py"
    from diapason.engine.ollama import OllamaEngine
    from diapason.security.guardrails import GuardrailsEngine, SecurityBlockError
    from diapason.security.types import RedactionMode
    from diapason.core.types import Message, Role

    engine = OllamaEngine()
    guarded = GuardrailsEngine(engine, mode=RedactionMode.BLOCK)

    try:
        messages = [Message(role=Role.USER, content="AKIA1234567890ABCDEF")]
        guarded.generate(messages, model="qwen3:8b")
    except SecurityBlockError as exc:
        print(f"Bloqué : {exc}")
        # Bloqué : Security scan blocked input: 1 finding(s) detected
    ```

### Les paramètres du constructeur

| Paramètre | Type | Défaut | Description |
|-----------|------|---------|-------------|
| `engine` | `InferenceEngine` | — | Le moteur d'inférence enveloppé |
| `scanners` | `list[BaseScanner]` | `[SecretScanner(), PIIScanner()]` | Les analyseurs à lancer |
| `mode` | `RedactionMode` | `WARN` | L'action quand il y a une détection |
| `scan_input` | `bool` | `True` | Analyser les messages d'entrée |
| `scan_output` | `bool` | `True` | Analyser le contenu de sortie |
| `bus` | `EventBus` | `None` | Le bus d'événements pour les événements de sécurité |

### L'intégration au bus d'événements

Quand un `bus` est fourni, `GuardrailsEngine` publie un événement à chaque résultat d'analyse :

| Événement | Quand |
|-------|------|
| `SECURITY_ALERT` | Une détection en mode WARN ou REDACT |
| `SECURITY_BLOCK` | Une détection en mode BLOCK |

Tu peux t'abonner à ces événements avec un `AuditLogger` pour bâtir un journal persistant des événements de sécurité. Voir [Le journal d'audit](#audit-logger) plus bas.

### Des analyseurs sur mesure

Tu peux passer n'importe quel jeu de sous-classes de `BaseScanner` pour restreindre ou étendre l'analyse :

```python title="custom_scanners.py"
from diapason.security.guardrails import GuardrailsEngine
from diapason.security.scanner import SecretScanner
from diapason.security.types import RedactionMode

# N'analyser que les secrets, laisser de côté les données personnelles
guarded = GuardrailsEngine(
    engine,
    scanners=[SecretScanner()],
    mode=RedactionMode.REDACT,
)
```

### Le fil de l'eau

Quand l'analyse de la sortie est active, `GuardrailsEngine.stream()` et
`stream_full()` mettent la complétion en tampon, l'analysent, et ne relâchent
qu'ensuite le contenu propre ou assaini. Ce choix sacrifie délibérément la
latence du premier jeton contre une garantie stricte : un secret coupé en deux
par une frontière de jetons n'est jamais émis avant que l'analyseur ait pu
l'évaluer. Ne mets `scan_output = false` que dans un déploiement local
explicitement de confiance, qui accepte ce risque.

---

## SecretScanner

`SecretScanner` détecte les clés d'API, les jetons, les mots de passe et les autres secrets à l'aide d'expressions régulières. Chaque motif porte un `ThreatLevel`.

### La référence des motifs

| Nom du motif | Niveau de menace | Ce qu'il attrape |
|---|---|---|
| `openai_key` | CRITICAL | `sk-` suivi d'au moins 20 caractères alphanumériques |
| `anthropic_key` | CRITICAL | `sk-ant-` suivi d'au moins 20 caractères |
| `aws_access_key` | CRITICAL | `AKIA` suivi de 16 caractères alphanumériques majuscules |
| `github_token` | CRITICAL | `ghp_`, `gho_`, `ghs_`, `ghr_`, `github_pat_` suivis d'au moins 36 caractères |
| `stripe_key` | CRITICAL | `sk_live_`, `sk_test_`, `pk_live_`, `pk_test_` suivis d'au moins 20 caractères |
| `private_key` | CRITICAL | L'en-tête de clé privée PEM `-----BEGIN PRIVATE KEY-----` |
| `password_assignment` | HIGH | `password = "..."`, `passwd: "..."`, etc. |
| `db_connection_string` | HIGH | Les URL `postgres://`, `mysql://`, `mongodb://`, `redis://` |
| `slack_token` | HIGH | `xoxb-`, `xoxp-`, `xoxo-`, `xoxr-`, `xoxs-` suivis du jeton |
| `generic_api_key` | HIGH | `api_key = "..."`, `secret_key = "..."`, `auth_token = "..."` |

### L'usage direct

```python title="secret_scanner.py"
from diapason.security.scanner import SecretScanner

scanner = SecretScanner()

# Analyser le texte
result = scanner.scan("Ma clé est sk-abc123xyz789 et elle est secrète")
print(result.clean)           # False
print(result.highest_threat)  # ThreatLevel.CRITICAL
for finding in result.findings:
    print(f"  {finding.pattern_name} : {finding.description} en [{finding.start}:{finding.end}]")

# Caviarder le texte
clean = scanner.redact("Jeton : sk-abc123xyz789")  # gitleaks:allow
print(clean)  # Jeton : [REDACTED:openai_key]
```

---

## PIIScanner

`PIIScanner` détecte les données personnelles identifiantes à l'aide d'expressions régulières calibrées pour les formats américains courants.

### La référence des motifs

| Nom du motif | Niveau de menace | Ce qu'il attrape |
|---|---|---|
| `us_ssn` | CRITICAL | Les numéros de sécurité sociale américains, au format `XXX-XX-XXXX` |
| `credit_card_visa` | CRITICAL | Les numéros de carte Visa (16 chiffres commençant par 4) |
| `credit_card_mastercard` | CRITICAL | Les numéros Mastercard (16 chiffres commençant par 51 à 55) |
| `credit_card_amex` | CRITICAL | Les numéros Amex (15 chiffres commençant par 34 ou 37) |
| `email` | MEDIUM | Les adresses courriel standard |
| `us_phone` | MEDIUM | Les numéros de téléphone américains, dans les formats courants |
| `ipv4_public` | LOW | Les adresses IPv4 publiques (les plages RFC1918 sont exclues) |

!!! note "Les adresses IP privées"
    Le motif `ipv4_public` exclut volontairement les plages privées (10.x.x.x, 172.16–31.x.x, 192.168.x.x, 127.x.x.x). Une adresse IP interne n'est pas considérée comme sensible par défaut.

### L'usage direct

```python title="pii_scanner.py"
from diapason.security.scanner import PIIScanner

scanner = PIIScanner()

text = "Écris à john@example.com ou appelle le 555-867-5309"
result = scanner.scan(text)

for finding in result.findings:
    print(f"{finding.pattern_name}: threat={finding.threat_level.value}")
# email: threat=medium
# us_phone: threat=medium

clean = scanner.redact(text)
print(clean)
# Écris à [REDACTED:email] ou appelle le [REDACTED:us_phone]
```

---

## La politique des fichiers {#file-policy}

Le module de politique des fichiers empêche l'accès aux fichiers de secrets et de clés. Il est utilisé en interne par `FileReadTool` et par le chemin d'ingestion de la mémoire, mais tu peux t'en servir directement.

### Les motifs de fichiers sensibles

Le frozenset `DEFAULT_SENSITIVE_PATTERNS` contient les motifs glob suivants :

| Motif | Description |
|---------|-------------|
| `.env`, `.env.*`, `*.env` | Les fichiers de variables d'environnement |
| `.secret`, `*.secrets` | Les fichiers de secrets génériques |
| `credentials.*` | Les fichiers d'identifiants |
| `*.pem`, `*.key` | Les certificats TLS/SSL et les clés privées |
| `*.p12`, `*.pfx`, `*.jks` | Les fichiers PKCS et les magasins de clés Java |
| `id_rsa`, `id_ed25519` | Les clés privées SSH |
| `.htpasswd` | Les fichiers de mots de passe Apache |
| `.pgpass` | Les fichiers de mots de passe PostgreSQL |
| `.netrc` | Les fichiers d'identifiants FTP/SSH |

### L'usage

```python title="file_policy.py"
from pathlib import Path
from diapason.security.file_policy import is_sensitive_file, filter_sensitive_paths

# Vérifier un seul fichier
print(is_sensitive_file(".env"))           # True
print(is_sensitive_file("server.key"))     # True
print(is_sensitive_file("README.md"))      # False

# Filtrer une liste de chemins
paths = [
    Path("README.md"),
    Path(".env"),
    Path("src/main.py"),
    Path("server.pem"),
]
safe = filter_sensitive_paths(paths)
print(safe)  # [PosixPath('README.md'), PosixPath('src/main.py')]
```

### L'intégration avec FileReadTool

Le `FileReadTool` intégré appelle `is_sensitive_file()` avant de lire le moindre chemin. Une tentative de lecture d'un fichier sensible lève une erreur au lieu de rendre le contenu du fichier. Ce comportement ne se désactive pas au niveau de l'outil — si tu as besoin d'un accès aux fichiers sans restriction, configure l'agent sans `FileReadTool`.

---

## Le journal d'audit {#audit-logger}

`AuditLogger` conserve les événements de sécurité dans une base SQLite en ajout seul. Il peut s'abonner au bus d'événements pour les capter tout seul, ou tu peux appeler `log()` à la main.

### L'intégration au bus d'événements (automatique)

```python title="audit_bus.py"
from diapason.core.events import EventBus
from diapason.security.audit import AuditLogger
from diapason.security.guardrails import GuardrailsEngine
from diapason.security.types import RedactionMode
from diapason.engine.ollama import OllamaEngine

bus = EventBus()

# AuditLogger s'abonne à SECURITY_SCAN, SECURITY_ALERT et SECURITY_BLOCK
audit = AuditLogger(db_path="~/.diapason/audit.db", bus=bus)

engine = OllamaEngine()
guarded = GuardrailsEngine(
    engine,
    mode=RedactionMode.WARN,
    bus=bus,
)

# Les événements de sécurité sont maintenant conservés tout seuls
```

### L'enregistrement à la main

```python title="audit_manual.py"
import time
from diapason.security.audit import AuditLogger
from diapason.security.types import SecurityEvent, SecurityEventType

audit = AuditLogger(db_path="./audit.db")

event = SecurityEvent(
    event_type=SecurityEventType.SECRET_DETECTED,
    timestamp=time.time(),
    findings=[],
    content_preview="sk-...",
    action_taken="redacted",
)
audit.log(event)
```

### Interroger le journal d'audit

```python title="audit_query.py"
from diapason.security.audit import AuditLogger

audit = AuditLogger(db_path="~/.diapason/audit.db")

# Les événements récents
events = audit.query(limit=20)

# Filtrer par type d'événement
secret_events = audit.query(event_type="secret_detected")

# Filtrer par intervalle de temps
import time
recent = audit.query(since=time.time() - 3600)  # la dernière heure

# Compter tous les événements
print(f"Total des événements : {audit.count()}")

audit.close()
```

---

## La configuration

Les réglages de sécurité vivent dans la section `[security]` de `~/.diapason/config.toml`.

```toml title="~/.diapason/config.toml"
[security]
enabled = true
scan_input = true
scan_output = true
mode = "warn"               # "warn" | "redact" | "block"
secret_scanner = true
pii_scanner = true
audit_log_path = "~/.diapason/audit.db"
enforce_tool_confirmation = true
```

### La référence de configuration

| Clé | Type | Défaut | Description |
|-----|------|---------|-------------|
| `enabled` | `bool` | `true` | Active le sous-système de sécurité |
| `scan_input` | `bool` | `true` | Analyse les messages entrés par l'utilisateur |
| `scan_output` | `bool` | `true` | Analyse le contenu sorti du modèle |
| `mode` | `str` | `"warn"` | L'action quand il y a une détection : `warn`, `redact` ou `block` |
| `secret_scanner` | `bool` | `true` | Passe `SecretScanner` sur tout le texte |
| `pii_scanner` | `bool` | `true` | Passe `PIIScanner` sur tout le texte |
| `audit_log_path` | `str` | `~/.diapason/audit.db` | Le chemin du journal d'audit SQLite |
| `enforce_tool_confirmation` | `bool` | `true` | Accepté par le chargeur, mais **pas appliqué aujourd'hui**. Voir [L'accès système](system-access.md#le-comportement-de-confirmation) pour savoir quand les demandes de confirmation ont vraiment lieu |

!!! tip "Commence en warn, resserre ensuite"
    `mode = "warn"` est un bon point de départ : il te laisse observer quels motifs se déclenchent sans perturber l'usage normal. Passe à `"redact"` une fois que tu es sûr que l'analyseur ne produit pas trop de faux positifs pour ton usage.

---

## Écrire son propre analyseur

Implémente `BaseScanner` et passe une instance à `GuardrailsEngine` :

```python title="custom_scanner.py"
import re
from diapason.security._stubs import BaseScanner
from diapason.security.types import ScanFinding, ScanResult, ThreatLevel


class InternalUrlScanner(BaseScanner):
    """Détecte les URL de services internes qui ne doivent pas sortir."""

    scanner_id = "internal_urls"

    PATTERN = re.compile(r"https?://internal\.[a-z0-9.-]+\.[a-z]{2,}")

    def scan(self, text: str) -> ScanResult:
        findings = []
        for match in self.PATTERN.finditer(text):
            findings.append(ScanFinding(
                pattern_name="internal_url",
                matched_text=match.group(0),
                threat_level=ThreatLevel.MEDIUM,
                start=match.start(),
                end=match.end(),
                description="URL de service interne",
            ))
        return ScanResult(findings=findings)

    def redact(self, text: str) -> str:
        return self.PATTERN.sub("[REDACTED:internal_url]", text)


# À utiliser avec GuardrailsEngine
from diapason.security.guardrails import GuardrailsEngine
from diapason.security.types import RedactionMode

guarded = GuardrailsEngine(
    engine,
    scanners=[InternalUrlScanner()],
    mode=RedactionMode.REDACT,
)
```

---

## Voir aussi

- [Architecture : la sécurité](../architecture/security.md) — la conception du pipeline, le flux d'événements et l'intégration de la politique des fichiers
- [Référence d'API : security](../api-reference/diapason/security/index.md) — toutes les signatures de classes et de fonctions
- [Les outils](tools.md) — comment `FileReadTool` se sert de la politique des fichiers
- [La configuration](../getting-started/configuration.md) — la référence de configuration complète
