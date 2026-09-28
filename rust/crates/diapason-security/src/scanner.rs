//! Concrete security scanners — secrets and PII detection.

use crate::types::{ScanFinding, ScanResult, ThreatLevel};
use once_cell::sync::Lazy;
use regex::Regex;

struct PatternDef {
    name: &'static str,
    regex: Regex,
    threat: ThreatLevel,
    description: &'static str,
}

macro_rules! pattern {
    ($name:expr, $pat:expr, $threat:expr, $desc:expr) => {
        PatternDef {
            name: $name,
            regex: Regex::new($pat).unwrap(),
            threat: $threat,
            description: $desc,
        }
    };
}

// La casse, décidée motif par motif le 28/09/2026. Ces motifs étaient tous
// sensibles à la casse ici, alors que le repli Python (scanner.py) les
// compilait sous re.IGNORECASE. Or c'est cette extension que le flux
// applique : « Password: "correct horse battery" », « PASSWORD = '…' » ou
// « API_KEY='…' » sortaient EN CLAIR dès qu'elle était chargée, et n'étaient
// masqués que lorsqu'elle manquait. scanner.py porte désormais les mêmes
// chaînes, sans drapeau global, et la même règle :
//
// - un MOT-CLÉ qu'un humain tape (le nom d'une affectation, un schéma d'URI,
//   insensible à la casse selon la RFC 3986 §3.1) se lit sans égard à la
//   casse, par un « (?i:…) » borné au mot-clé. Ce que le repli masquait doit
//   l'être ici aussi : restreindre ce qui passe en clair, jamais l'élargir.
//
// - un JETON garde la casse que son émetteur lui fixe, à une exception près :
//   la majuscule initiale qu'une correction automatique pose en début de
//   phrase (« Sk-… », « Ghp_… », « Xoxb-… »). Elle laisse le corps intact,
//   la clé reste utilisable : [Ss]k-, [Gg]hp_, [Xx]ox, [SsPp]k_. Toute autre
//   casse recasse aussi le corps, en base62 sensible à la casse, et détruit
//   la clé ; un (?i) complet y masquait en revanche de la prose, mesuré :
//   « RISK-ASSESSMENT-FRAMEWORK-2026 » devenait une clé OpenAI, et
//   « DISK_TEST_ABCDEFGHIJKLMNOPQRSTUV » une clé Stripe.
//   AKIA commence déjà par une capitale et reste tel quel : l'identifiant
//   AWS n'est pas le secret, et un (?i) trouvait 9 « clés » dans 16 Mo de
//   base64 aléatoire, contre 0 — autant de passages d'une image corrompus.
//   L'en-tête PEM reste en capitales (RFC 7468 §2) : LibreSSL 3.3.6 refuse
//   « -----begin rsa private key----- », « no start line ». Le repli a
//   perdu son IGNORECASE dans le même commit.
//
// Le « i » s'écrit [iİı] dans un mot-clé : le re de Python, sous IGNORECASE,
// lit aussi İ (U+0130) et ı (U+0131) comme un i — la majuscule turque de
// « api_key » est « APİ_KEY » —, alors que le (?i) de Rust ne suit que le
// repliement simple d'Unicode et les refuse. Mesuré sur les 1 114 112 points
// de code : c'est la seule lettre ASCII où les deux moteurs divergent (k et s
// admettent K U+212A et ſ U+017F des deux côtés).
//
// Le blanc s'écrit [\s\x1c-\x1f], ici et dans PII_PATTERNS (28/09/2026) : le
// \s de re admet U+001C..U+001F, celui de Rust non — mesuré sur les
// 1 114 112 points de code, c'est leur seul écart, et dans ce sens-là.
// « Password\x1c: '…' », « API_KEY\x1f= '…' » ou une carte coupée de \x1c
// sortaient en clair par l'extension, masqués par le seul repli. La classe
// élargie est, dans les deux moteurs, exactement le \s de re. Le corps d'une
// URI de base garde son [^\s] : celui de Rust admet déjà U+001C..U+001F, et
// l'exclure élargirait ce qui passe. Ce que le repli y masque de moins est
// nommé dans test_scanner.py.
static SECRET_PATTERNS: Lazy<Vec<PatternDef>> = Lazy::new(|| {
    vec![
        pattern!(
            "openai_key",
            r"[Ss]k-[A-Za-z0-9_-]{20,}",
            ThreatLevel::Critical,
            "OpenAI API key"
        ),
        pattern!(
            "anthropic_key",
            r"[Ss]k-ant-[A-Za-z0-9_-]{20,}",
            ThreatLevel::Critical,
            "Anthropic API key"
        ),
        pattern!(
            "aws_access_key",
            r"AKIA[0-9A-Z]{16}",
            ThreatLevel::Critical,
            "AWS access key"
        ),
        pattern!(
            "github_token",
            r"[Gg](?:hp|ho|hs|hr|ithub_pat)_[A-Za-z0-9_]{36,}",
            ThreatLevel::Critical,
            "GitHub token"
        ),
        pattern!(
            "password_assignment",
            r#"(?i:password|passwd|pwd)[\s\x1c-\x1f]*[=:][\s\x1c-\x1f]*['"]([^'"]{4,})['"]"#,
            ThreatLevel::High,
            "Password assignment"
        ),
        pattern!(
            "db_connection_string",
            r"(?i:postgres|mysql|mongodb|red[iİı]s)://[^\s]{10,}",
            ThreatLevel::High,
            "Database connection string"
        ),
        pattern!(
            "private_key",
            r"-----BEGIN (?:RSA )?PRIVATE KEY-----",
            ThreatLevel::Critical,
            "Private key"
        ),
        pattern!(
            "slack_token",
            r"[Xx]ox[bpors]-[A-Za-z0-9\-]{10,}",
            ThreatLevel::High,
            "Slack token"
        ),
        pattern!(
            "stripe_key",
            r"[SsPp]k_(?:test|live)_[A-Za-z0-9]{20,}",
            ThreatLevel::Critical,
            "Stripe key"
        ),
        pattern!(
            "generic_api_key",
            r#"(?i:ap[iİı]_key|secret_key|auth_token)[\s\x1c-\x1f]*[=:][\s\x1c-\x1f]*['"]([^'"]{8,})['"]"#,
            ThreatLevel::High,
            "Generic API key/secret"
        ),
    ]
});

// Le blanc s'y écrit [\s\x1c-\x1f] : voir le commentaire de SECRET_PATTERNS.
static PII_PATTERNS: Lazy<Vec<PatternDef>> = Lazy::new(|| {
    vec![
        pattern!(
            "email",
            r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
            ThreatLevel::Medium,
            "Email address"
        ),
        pattern!(
            "us_ssn",
            r"\b\d{3}-\d{2}-\d{4}\b",
            ThreatLevel::Critical,
            "US Social Security Number"
        ),
        pattern!(
            "credit_card_visa",
            r"\b4\d{3}[-\s\x1c-\x1f]?\d{4}[-\s\x1c-\x1f]?\d{4}[-\s\x1c-\x1f]?\d{4}\b",
            ThreatLevel::Critical,
            "Visa credit card"
        ),
        pattern!(
            "credit_card_mastercard",
            r"\b5[1-5]\d{2}[-\s\x1c-\x1f]?\d{4}[-\s\x1c-\x1f]?\d{4}[-\s\x1c-\x1f]?\d{4}\b",
            ThreatLevel::Critical,
            "Mastercard credit card"
        ),
        pattern!(
            "credit_card_amex",
            r"\b3[47]\d{2}[-\s\x1c-\x1f]?\d{6}[-\s\x1c-\x1f]?\d{5}\b",
            ThreatLevel::Critical,
            "Amex credit card"
        ),
        pattern!(
            "us_phone",
            // Un téléphone doit RESSEMBLER à un téléphone : indicatif +1,
            // parenthèses, ou de vrais séparateurs. Tous les séparateurs
            // étaient optionnels, si bien que dix chiffres quelconques
            // suffisaient — 48273 × 91847 = 4433730231 ressortait
            // « [REDACTED:us_phone] », et avec lui tout numéro de commande,
            // horodatage en millisecondes ou montant en centimes.
            r"(?:\+1[-.\s\x1c-\x1f]?)?\(\d{3}\)[-.\s\x1c-\x1f]?\d{3}[-.\s\x1c-\x1f]?\d{4}|\+1[-.\s\x1c-\x1f]?\d{3}[-.\s\x1c-\x1f]?\d{3}[-.\s\x1c-\x1f]?\d{4}|\b\d{3}[-.\s\x1c-\x1f]\d{3}[-.\s\x1c-\x1f]\d{4}\b",
            ThreatLevel::Medium,
            "US phone number"
        ),
        pattern!(
            "ipv4_address",
            r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",
            ThreatLevel::Low,
            "IPv4 address"
        ),
    ]
});

fn scan_with_patterns(text: &str, patterns: &[PatternDef]) -> ScanResult {
    let mut findings = Vec::new();
    for p in patterns {
        for m in p.regex.find_iter(text) {
            findings.push(ScanFinding {
                pattern_name: p.name.to_string(),
                matched_text: m.as_str().to_string(),
                threat_level: p.threat,
                start: m.start(),
                end: m.end(),
                description: p.description.to_string(),
            });
        }
    }
    ScanResult { findings }
}

fn redact_with_patterns(text: &str, patterns: &[PatternDef]) -> String {
    let mut result = text.to_string();
    for p in patterns {
        result = p
            .regex
            .replace_all(&result, format!("[REDACTED:{}]", p.name))
            .to_string();
    }
    result
}

/// Detect API keys, tokens, passwords, and other secrets.
pub struct SecretScanner;

impl SecretScanner {
    pub fn new() -> Self {
        Self
    }

    pub fn scan(&self, text: &str) -> ScanResult {
        scan_with_patterns(text, &SECRET_PATTERNS)
    }

    pub fn redact(&self, text: &str) -> String {
        redact_with_patterns(text, &SECRET_PATTERNS)
    }
}

impl Default for SecretScanner {
    fn default() -> Self {
        Self::new()
    }
}

/// Detect personally identifiable information.
pub struct PIIScanner;

impl PIIScanner {
    pub fn new() -> Self {
        Self
    }

    pub fn scan(&self, text: &str) -> ScanResult {
        scan_with_patterns(text, &PII_PATTERNS)
    }

    pub fn redact(&self, text: &str) -> String {
        redact_with_patterns(text, &PII_PATTERNS)
    }
}

impl Default for PIIScanner {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_secret_scanner_openai_key() {
        let scanner = SecretScanner::new();
        let text = "My key is sk-abcdefghijklmnopqrstuvwxyz1234";
        let result = scanner.scan(text);
        assert!(!result.clean());
        assert_eq!(result.findings[0].pattern_name, "openai_key");
    }

    #[test]
    fn test_secret_scanner_redact() {
        let scanner = SecretScanner::new();
        let text = "key: sk-abcdefghijklmnopqrstuvwxyz1234";
        let redacted = scanner.redact(text);
        assert!(redacted.contains("[REDACTED:openai_key]"));
        assert!(!redacted.contains("sk-"));
    }

    #[test]
    fn test_pii_scanner_email() {
        let scanner = PIIScanner::new();
        let result = scanner.scan("Contact user@example.com for info");
        assert!(!result.clean());
        assert_eq!(result.findings[0].pattern_name, "email");
    }

    #[test]
    fn test_pii_scanner_ssn() {
        let scanner = PIIScanner::new();
        let result = scanner.scan("SSN: 123-45-6789");
        assert!(!result.clean());
        assert_eq!(result.findings[0].pattern_name, "us_ssn");
        assert_eq!(result.highest_threat(), Some(ThreatLevel::Critical));
    }

    #[test]
    fn test_clean_text() {
        let scanner = SecretScanner::new();
        let result = scanner.scan("Hello, this is safe text.");
        assert!(result.clean());
    }

    fn noms(texte: &str) -> Vec<String> {
        SecretScanner::new()
            .scan(texte)
            .findings
            .into_iter()
            .map(|f| f.pattern_name)
            .collect()
    }

    // 28/09/2026 : chacun de ces textes sortait en clair par l'extension,
    // alors que le repli Python le masquait. Voir le commentaire de
    // SECRET_PATTERNS. Des valeurs à espaces : un balayage de secrets ne les
    // prend pas pour de vraies clés.
    #[test]
    fn un_mot_cle_de_secret_se_lit_dans_toutes_les_casses() {
        let cas = [
            (r#"Password: "correct horse""#, "password_assignment"),
            ("PASSWORD = 'correct horse'", "password_assignment"),
            ("PassWd:'correct horse'", "password_assignment"),
            ("PWD=\"correct horse\"", "password_assignment"),
            ("api_KEY='correct horse'", "generic_api_key"),
            ("API_KEY: \"correct horse\"", "generic_api_key"),
            ("Secret_Key = 'correct horse'", "generic_api_key"),
            ("AUTH_TOKEN='correct horse'", "generic_api_key"),
            (
                "Postgres://admin:correct@horse.example.com/prod",
                "db_connection_string",
            ),
            (
                "MYSQL://root:correct@horse.example.com/app",
                "db_connection_string",
            ),
            (
                "MongoDB://u:correct@horse.example.com",
                "db_connection_string",
            ),
            (
                "REDIS://:correct@horse.example.com:6379",
                "db_connection_string",
            ),
        ];
        for (texte, nom) in cas {
            assert!(
                noms(texte).iter().any(|n| n == nom),
                "{texte:?} doit être reconnu comme {nom} : le repli Python le masque"
            );
            let masque = SecretScanner::new().redact(texte);
            assert!(
                masque.contains(&format!("[REDACTED:{nom}]")) && !masque.contains("correct"),
                "{texte:?} doit sortir masqué, pas {masque:?}"
            );
        }
    }

    #[test]
    fn le_i_d_un_mot_cle_admet_les_i_turcs_que_le_repli_admet() {
        // re.IGNORECASE lit İ (U+0130) et ı (U+0131) comme un i ; le (?i) de
        // Rust non. Sans le [iİı], « APİ_KEY » fuyait par l'extension seule.
        for (texte, nom) in [
            ("AP\u{130}_KEY = 'correct horse'", "generic_api_key"),
            ("ap\u{131}_key = 'correct horse'", "generic_api_key"),
            (
                "RED\u{130}S://:correct@horse.example.com",
                "db_connection_string",
            ),
            (
                "red\u{131}s://:correct@horse.example.com",
                "db_connection_string",
            ),
        ] {
            assert!(
                noms(texte).iter().any(|n| n == nom),
                "{texte:?} : le repli Python le masque, l'extension doit aussi"
            );
        }
        // K (U+212A) et ſ (U+017F) : le repliement simple d'Unicode les
        // donne déjà aux deux moteurs.
        for (texte, nom) in [
            (
                "PA\u{17F}\u{17F}WORD = 'correct horse'",
                "password_assignment",
            ),
            ("API_\u{212A}EY = 'correct horse'", "generic_api_key"),
        ] {
            assert!(
                noms(texte).iter().any(|n| n == nom),
                "{texte:?} : s long et signe kelvin sont s et k pour les deux moteurs"
            );
        }
    }

    // 28/09/2026 : le \s de re admet U+001C..U+001F, celui de Rust non ; ces
    // textes n'étaient masqués que par le repli Python.
    #[test]
    fn un_blanc_que_re_lit_comme_tel_ne_fait_pas_passer_un_secret() {
        for blanc in ['\u{1c}', '\u{1d}', '\u{1e}', '\u{1f}'] {
            for (texte, nom, pii) in [
                (
                    format!("Password{blanc}: 'correct horse'"),
                    "password_assignment",
                    false,
                ),
                (
                    format!("API_KEY ={blanc}'correct horse battery'"),
                    "generic_api_key",
                    false,
                ),
                (
                    format!("4111{blanc}1111{blanc}1111{blanc}1111"),
                    "credit_card_visa",
                    true,
                ),
                (
                    format!("5555{blanc}5555 5555 4444"),
                    "credit_card_mastercard",
                    true,
                ),
                (
                    format!("3782{blanc}822463{blanc}10005"),
                    "credit_card_amex",
                    true,
                ),
                (
                    format!("+1{blanc}202{blanc}555{blanc}0199"),
                    "us_phone",
                    true,
                ),
                (
                    format!("+1{blanc}(202){blanc}555{blanc}0199"),
                    "us_phone",
                    true,
                ),
            ] {
                let masque = if pii {
                    PIIScanner::new().redact(&texte)
                } else {
                    SecretScanner::new().redact(&texte)
                };
                assert_eq!(
                    masque,
                    format!("[REDACTED:{nom}]"),
                    "{texte:?} : le repli Python le masque en entier, l'extension doit aussi"
                );
            }
        }
    }

    #[test]
    fn un_jeton_admet_la_majuscule_d_un_debut_de_phrase() {
        // La correction automatique capitalise « sk-… » tapé en tête de
        // phrase ; le corps reste intact, la clé reste utilisable.
        let corps = "abcdefghijklmnopqrstuvwxyz0123456789ABCD";
        for (texte, nom) in [
            (format!("Sk-{corps}"), "openai_key"),
            (format!("Sk-ant-{corps}"), "anthropic_key"),
            (format!("Ghp_{corps}"), "github_token"),
            (format!("Github_pat_{corps}"), "github_token"),
            (format!("Xoxb-{corps}"), "slack_token"),
            (format!("Pk_test_{corps}"), "stripe_key"),
        ] {
            assert!(
                noms(&texte).iter().any(|n| n == nom),
                "{texte:?} doit être reconnu comme {nom} : la clé reste utilisable"
            );
        }
    }

    #[test]
    fn un_jeton_garde_la_casse_que_son_emetteur_lui_fixe() {
        // Toute autre casse recasse le corps et détruit la clé ; un (?i)
        // complet masquait en revanche de la prose, ces textes-ci entre
        // autres.
        for texte in [
            "SK-ABCDEFGHIJKLMNOPQRSTUVWXYZ",
            "sK-abcdefghijklmnopqrstuvwxyz",
            "RISK-ASSESSMENT-FRAMEWORK-2026",
            "akia0123456789abcdef",
            "GHP_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
            "XOXB-1234567890-ABCDEF",
            "DISK_TEST_ABCDEFGHIJKLMNOPQRSTUV",
            "-----begin rsa private key-----",
        ] {
            assert!(
                noms(texte).is_empty(),
                "{texte:?} n'a pas la casse de son format : {:?}",
                noms(texte)
            );
        }
        // Seul le préfixe est contraint : le corps d'une clé, écrit
        // [A-Za-z0-9_-], garde ses deux casses.
        assert_eq!(
            SecretScanner::new().redact("sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
            "[REDACTED:openai_key]",
            "le corps d'une clé garde ses deux casses"
        );
    }
}
