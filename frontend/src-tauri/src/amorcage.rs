//! L'amorçage : ce que l'app installe ELLE-MÊME au premier lancement.
//!
//! Jusqu'au 13 septembre 2026, un Mac vierge qui ouvrait Diapason.app lisait
//! « Diapason's local backend is not installed. Run the authenticated
//! installer first ». Cet installateur (`curl … | bash`) exigeait `git` —
//! donc Xcode —, clonait un dépôt privé, et son étape Ollama ne marchait que
//! sous Linux. Trois murs, aucun franchissable sans terminal. Demandé :
//! « télécharger, installer normalement, sans ligne de commande ».
//!
//! Ce module télécharge donc, quand ils manquent, les quatre morceaux que la
//! fenêtre ne contient pas — et rien d'autre :
//!
//!   1. `uv`      — depuis les releases GitHub d'Astral ;
//!   2. `ollama`  — depuis les releases GitHub d'Ollama ;
//!   3. le code Python de Diapason — une archive `git archive` publiée avec
//!      chaque release de l'app, sous la même version ;
//!   4. `diapason_rust` — la roue (wheel) précompilée de l'extension PyO3,
//!      publiée au même endroit, pour ne pas exiger `cargo` ni un éditeur de
//!      liens chez l'utilisateur.
//!
//! Tout atterrit sous le dossier d'installation (`~/.diapason` ; sur Windows
//! `%LOCALAPPDATA%\Diapason`) : `bin/` pour les exécutables, `src/` pour le
//! code, `roues/` pour la wheel. `lib.rs` connaît déjà `src/` comme racine
//! installée ; `resolve_bin` regarde désormais `bin/` en premier.
//!
//! Un dépôt de développement (`~/Projets/Diapason`) reste prioritaire : si
//! `find_project_root` trouve autre chose que `src/`, on n'y touche pas. On
//! ne remplace jamais le travail de quelqu'un par une archive.
//!
//! L'extraction passe par le `tar` du système (bsdtar sur macOS ET sur
//! Windows 10+, où il lit aussi les zip) : une dépendance de moins à
//! compiler, et un outil qui existe partout où cette app peut tourner.

use std::path::{Path, PathBuf};

/// La version de l'app, gravée à la compilation. L'archive du code et la
/// wheel sont cherchées sous la release `desktop-v<version>` : l'app et son
/// backend avancent ensemble, et une mise à jour de l'app entraîne celle du
/// code Python au démarrage suivant.
pub const VERSION_APP: &str = env!("CARGO_PKG_VERSION");

/// Où les releases sont publiées. Surchargeable par `DIAPASON_BACKEND_URL`
/// (une base d'URL, avec ou sans `/` final) pour tester l'amorçage contre un
/// serveur local avant qu'une release existe.
const DEPOT_RELEASES: &str = "https://github.com/carlitoetienne01-spec/Diapason";

/// Le nom du fichier-témoin qui dit quelle version du code est installée
/// dans `src/`. Absent : rien n'est installé. Différent de `VERSION_APP` : on
/// retélécharge.
const TEMOIN_VERSION: &str = ".diapason-backend";

/// Ce que décrit `backend.json`, publié avec chaque release.
#[derive(Debug, Clone, PartialEq, serde::Deserialize)]
pub struct Manifeste {
    pub version: String,
    /// La version de Python que `uv` doit installer — celle de la wheel.
    pub python: String,
    /// Le nom de l'archive du code (`git archive`, un dossier de tête).
    pub source: String,
    /// Cible Rust → nom de la wheel. Une cible absente : pas de wheel
    /// précompilée, `uv sync` devra compiler (et exiger `cargo`).
    #[serde(default)]
    pub wheels: std::collections::HashMap<String, String>,
}

/// La cible Rust de cette compilation, telle que nommée dans `backend.json`
/// et dans les archives d'Astral.
pub fn cible() -> &'static str {
    match (std::env::consts::OS, std::env::consts::ARCH) {
        ("macos", "aarch64") => "aarch64-apple-darwin",
        ("macos", _) => "x86_64-apple-darwin",
        ("windows", "aarch64") => "aarch64-pc-windows-msvc",
        ("windows", _) => "x86_64-pc-windows-msvc",
        (_, "aarch64") => "aarch64-unknown-linux-gnu",
        _ => "x86_64-unknown-linux-gnu",
    }
}

fn home() -> PathBuf {
    PathBuf::from(
        std::env::var("HOME")
            .or_else(|_| std::env::var("USERPROFILE"))
            .unwrap_or_default(),
    )
}

/// Le dossier d'installation — le même que celui que `lib.rs` sonde dans
/// `installed_project_root`, pour que ce qu'on y pose soit retrouvé. Seul
/// `DIAPASON_HOME` est lu ici : les noms d'avant la migration ne vivent que
/// dans le code de compatibilité de `lib.rs`, et le contrôle d'identité du
/// projet refuse qu'ils s'étendent (CI rouge le 13 septembre 2026).
pub fn dossier_installation() -> PathBuf {
    if let Ok(v) = std::env::var("DIAPASON_HOME") {
        if !v.trim().is_empty() {
            return PathBuf::from(v);
        }
    }
    #[cfg(target_os = "windows")]
    {
        if let Ok(local) = std::env::var("LOCALAPPDATA") {
            if !local.trim().is_empty() {
                return PathBuf::from(local).join("Diapason");
            }
        }
    }
    home().join(".diapason")
}

pub fn dossier_bin() -> PathBuf {
    dossier_installation().join("bin")
}

pub fn dossier_source() -> PathBuf {
    dossier_installation().join("src")
}

pub fn dossier_roues() -> PathBuf {
    dossier_installation().join("roues")
}

/// Le chemin d'un exécutable géré par l'amorçage : `bin/<nom>/<nom>`, avec
/// l'extension du système. Un dossier par outil, et le binaire appelé par son
/// vrai chemin — pas de lien : Ollama cherche ses bibliothèques (`lib/ollama`)
/// à côté de son exécutable, et un lien symbolique l'aurait envoyé chercher
/// dans `bin/`, où il n'y a rien, pour retomber en CPU sans un mot.
pub fn executable_gere(nom: &str) -> PathBuf {
    let fichier = if cfg!(target_os = "windows") {
        format!("{nom}.exe")
    } else {
        nom.to_string()
    };
    dossier_bin().join(nom).join(fichier)
}

/// La base d'URL des releases de l'app pour `version`.
pub fn url_base_backend(version: &str) -> String {
    if let Ok(v) = std::env::var("DIAPASON_BACKEND_URL") {
        let v = v.trim().trim_end_matches('/');
        if !v.is_empty() {
            return v.to_string();
        }
    }
    format!("{DEPOT_RELEASES}/releases/download/desktop-v{version}")
}

/// L'archive de `uv` pour cette cible : (URL, faut-il retirer un dossier de
/// tête). Astral publie des `.tar.gz` avec un dossier `uv-<cible>/` sur Unix
/// et des `.zip` à plat sur Windows.
pub fn archive_uv(cible: &str) -> (String, bool) {
    if cible.contains("windows") {
        (
            format!("https://github.com/astral-sh/uv/releases/latest/download/uv-{cible}.zip"),
            false,
        )
    } else {
        (
            format!("https://github.com/astral-sh/uv/releases/latest/download/uv-{cible}.tar.gz"),
            true,
        )
    }
}

/// L'archive d'Ollama pour ce système. Le binaire macOS est universel ; les
/// deux archives sont à plat (`ollama` ou `ollama.exe` à la racine, plus
/// `lib/` quand il y en a).
pub fn archive_ollama(cible: &str) -> Option<String> {
    let base = "https://github.com/ollama/ollama/releases/latest/download";
    if cible.contains("apple-darwin") {
        Some(format!("{base}/ollama-darwin.tgz"))
    } else if cible.contains("windows") {
        Some(format!("{base}/ollama-windows-amd64.zip"))
    } else if cible.starts_with("x86_64") {
        Some(format!("{base}/ollama-linux-amd64.tgz"))
    } else if cible.starts_with("aarch64") {
        Some(format!("{base}/ollama-linux-arm64.tgz"))
    } else {
        None
    }
}

pub fn analyser_manifeste(texte: &str) -> Result<Manifeste, String> {
    // Un BOM UTF-8 en tête fait refuser tout le fichier à serde_json — et un
    // `Out-File -Encoding utf8` de PowerShell 5.1 en pose un (release 1.0.3,
    // réparée à la main le 14 septembre 2026). On le tolère ici.
    let texte = texte.trim_start_matches('\u{feff}');
    let m: Manifeste =
        serde_json::from_str(texte).map_err(|e| format!("backend.json illisible : {e}"))?;
    if m.version.trim().is_empty() || m.source.trim().is_empty() || m.python.trim().is_empty() {
        return Err("backend.json incomplet : version, source et python sont requis".into());
    }
    Ok(m)
}

/// La version du code installé dans `racine`, si un témoin existe.
pub fn version_installee(racine: &Path) -> Option<String> {
    std::fs::read_to_string(racine.join(TEMOIN_VERSION))
        .ok()
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
}

/// Faut-il (re)télécharger le code ? Oui s'il n'y a pas de témoin, ou si la
/// version installée n'est pas celle de l'app. Un `pyproject.toml` présent
/// sans témoin est une installation faite autrement (l'ancien script) : on la
/// respecte et on ne télécharge pas par-dessus.
pub fn doit_installer_source(racine: &Path, version_app: &str) -> bool {
    match version_installee(racine) {
        Some(v) => v != version_app,
        None => !racine.join("pyproject.toml").is_file(),
    }
}

/// Le pourcentage entier d'un téléchargement, ou rien sans taille annoncée.
pub fn pourcentage(recu: u64, total: Option<u64>) -> Option<u8> {
    let total = total.filter(|t| *t > 0)?;
    Some(((recu.saturating_mul(100)) / total).min(100) as u8)
}

fn taille_lisible(octets: u64) -> String {
    if octets >= 1_000_000_000 {
        format!("{:.1} Go", octets as f64 / 1e9)
    } else if octets >= 1_000_000 {
        format!("{} Mo", octets / 1_000_000)
    } else {
        format!("{} ko", octets / 1_000)
    }
}

/// Le texte d'avancement affiché sur l'écran de configuration.
pub fn texte_avancement(quoi: &str, recu: u64, total: Option<u64>) -> String {
    match pourcentage(recu, total) {
        Some(p) => format!("{quoi} — {p} % de {}", taille_lisible(total.unwrap_or(0))),
        None => format!("{quoi} — {}", taille_lisible(recu)),
    }
}

/// Télécharge `url` dans `destination`, en écrivant d'abord dans un fichier
/// `.partiel` : un téléchargement coupé ne laisse pas une archive tronquée
/// qui passerait pour complète au lancement suivant.
pub async fn telecharger(
    url: &str,
    destination: &Path,
    mut avancement: impl FnMut(u64, Option<u64>),
) -> Result<(), String> {
    if let Some(parent) = destination.parent() {
        std::fs::create_dir_all(parent)
            .map_err(|e| format!("impossible de créer {} : {e}", parent.display()))?;
    }
    let client = reqwest::Client::builder()
        .user_agent(format!("Diapason/{VERSION_APP}"))
        .connect_timeout(std::time::Duration::from_secs(20))
        .build()
        .map_err(|e| e.to_string())?;
    let mut reponse = client
        .get(url)
        .send()
        .await
        .map_err(|e| format!("téléchargement impossible ({url}) : {e}"))?;
    if !reponse.status().is_success() {
        return Err(format!(
            "téléchargement refusé ({url}) : HTTP {}",
            reponse.status().as_u16()
        ));
    }
    let total = reponse.content_length();
    let partiel = destination.with_extension("partiel");
    let mut fichier = tokio::fs::File::create(&partiel)
        .await
        .map_err(|e| format!("impossible d'écrire {} : {e}", partiel.display()))?;
    let mut recu: u64 = 0;
    use tokio::io::AsyncWriteExt;
    while let Some(morceau) = reponse
        .chunk()
        .await
        .map_err(|e| format!("téléchargement interrompu ({url}) : {e}"))?
    {
        fichier
            .write_all(&morceau)
            .await
            .map_err(|e| format!("écriture impossible ({}) : {e}", partiel.display()))?;
        recu += morceau.len() as u64;
        avancement(recu, total);
    }
    fichier.flush().await.map_err(|e| e.to_string())?;
    drop(fichier);
    if let Some(t) = total {
        if recu != t {
            let _ = std::fs::remove_file(&partiel);
            return Err(format!(
                "téléchargement incomplet ({url}) : {recu} octets sur {t}"
            ));
        }
    }
    std::fs::rename(&partiel, destination).map_err(|e| {
        format!(
            "impossible de renommer {} : {e}",
            partiel.display()
        )
    })?;
    Ok(())
}

/// Le `tar` du système. macOS et Linux l'ont toujours ; Windows 10 (1803) et
/// suivants livrent bsdtar dans System32, qui lit aussi les zip.
fn commande_tar() -> std::process::Command {
    #[cfg(target_os = "windows")]
    {
        let systeme = std::env::var("SystemRoot").unwrap_or_else(|_| "C:\\Windows".into());
        std::process::Command::new(format!("{systeme}\\System32\\tar.exe"))
    }
    #[cfg(not(target_os = "windows"))]
    {
        std::process::Command::new("/usr/bin/tar")
    }
}

/// Extrait `archive` dans `destination` (créée au besoin, vidée d'abord :
/// une extraction par-dessus une ancienne version laisserait des fichiers
/// fantômes que Python importerait encore).
pub fn extraire(archive: &Path, destination: &Path, retirer_dossier_de_tete: bool) -> Result<(), String> {
    if destination.exists() {
        std::fs::remove_dir_all(destination)
            .map_err(|e| format!("impossible de vider {} : {e}", destination.display()))?;
    }
    std::fs::create_dir_all(destination)
        .map_err(|e| format!("impossible de créer {} : {e}", destination.display()))?;
    let mut cmd = commande_tar();
    cmd.arg("-xf").arg(archive).arg("-C").arg(destination);
    if retirer_dossier_de_tete {
        cmd.arg("--strip-components=1");
    }
    let sortie = cmd
        .output()
        .map_err(|e| format!("tar introuvable ou refusé : {e}"))?;
    if !sortie.status.success() {
        return Err(format!(
            "extraction de {} échouée : {}",
            archive.display(),
            String::from_utf8_lossy(&sortie.stderr).trim()
        ));
    }
    Ok(())
}

#[cfg(unix)]
fn rendre_executable(chemin: &Path) -> Result<(), String> {
    use std::os::unix::fs::PermissionsExt;
    let mut permissions = std::fs::metadata(chemin)
        .map_err(|e| format!("{} : {e}", chemin.display()))?
        .permissions();
    permissions.set_mode(0o755);
    std::fs::set_permissions(chemin, permissions).map_err(|e| format!("{} : {e}", chemin.display()))
}

#[cfg(not(unix))]
fn rendre_executable(_chemin: &Path) -> Result<(), String> {
    Ok(())
}

/// Ce que l'amorçage a décidé, pour la suite du démarrage.
#[derive(Debug, Default, Clone)]
pub struct Amorcage {
    /// La racine du code quand c'est l'amorçage qui la gère (`src/`).
    /// `None` : un dépôt de développement a été trouvé, on n'y touche pas.
    pub racine_geree: Option<PathBuf>,
    /// La wheel de `diapason_rust` à installer si l'import échoue.
    pub roue: Option<PathBuf>,
    /// La version de Python à écrire dans `.python-version`.
    pub python: Option<String>,
}

/// Télécharge et installe un exécutable manquant dans `bin/`.
async fn assurer_executable(
    nom: &str,
    url: &str,
    retirer_dossier_de_tete: bool,
    mut signaler: impl FnMut(String),
) -> Result<PathBuf, String> {
    let cible_bin = executable_gere(nom);
    if cible_bin.is_file() {
        return Ok(cible_bin);
    }
    let extension = if url.ends_with(".zip") { "zip" } else { "tgz" };
    let archive = dossier_installation()
        .join("telechargements")
        .join(format!("{nom}.{extension}"));
    let quoi = format!("Téléchargement de {nom}");
    telecharger(url, &archive, |recu, total| {
        signaler(texte_avancement(&quoi, recu, total));
    })
    .await?;
    signaler(format!("Installation de {nom}…"));
    let dossier = cible_bin
        .parent()
        .ok_or_else(|| format!("chemin sans dossier : {}", cible_bin.display()))?
        .to_path_buf();
    extraire(&archive, &dossier, retirer_dossier_de_tete)?;
    let _ = std::fs::remove_file(&archive);
    if !cible_bin.is_file() {
        return Err(format!(
            "l'archive de {nom} ne contient pas `{}` à l'endroit attendu ({})",
            cible_bin.file_name().map(|n| n.to_string_lossy().to_string()).unwrap_or_default(),
            dossier.display()
        ));
    }
    rendre_executable(&cible_bin)?;
    Ok(cible_bin)
}

/// `uv`, s'il manque partout ailleurs.
pub async fn assurer_uv(deja_present: bool, signaler: impl FnMut(String)) -> Result<Option<PathBuf>, String> {
    if deja_present {
        return Ok(None);
    }
    let (url, tete) = archive_uv(cible());
    assurer_executable("uv", &url, tete, signaler).await.map(Some)
}

/// `ollama`, s'il manque partout ailleurs.
pub async fn assurer_ollama(deja_present: bool, signaler: impl FnMut(String)) -> Result<Option<PathBuf>, String> {
    if deja_present {
        return Ok(None);
    }
    let url = archive_ollama(cible())
        .ok_or_else(|| format!("aucune archive Ollama connue pour {}", cible()))?;
    assurer_executable("ollama", &url, false, signaler).await.map(Some)
}

/// Le code Python et la wheel, pour la version de l'app, dans `src/` et
/// `roues/`. Ne fait rien si `src/` porte déjà cette version.
pub async fn assurer_source(
    version_app: &str,
    mut signaler: impl FnMut(String),
) -> Result<Amorcage, String> {
    let racine = dossier_source();
    let base = url_base_backend(version_app);
    let mut resultat = Amorcage {
        racine_geree: Some(racine.clone()),
        ..Default::default()
    };

    // Une wheel déjà téléchargée pour cette version sert encore si l'import
    // échoue plus tard (venv recréé, par exemple).
    let roue_existante = std::fs::read_dir(dossier_roues())
        .ok()
        .and_then(|d| {
            d.filter_map(|e| e.ok().map(|e| e.path()))
                .find(|p| p.extension().is_some_and(|x| x == "whl"))
        });

    if !doit_installer_source(&racine, version_app) {
        resultat.roue = roue_existante;
        return Ok(resultat);
    }

    signaler("Lecture de la version à installer…".into());
    let url_manifeste = format!("{base}/backend.json");
    let manifeste_chemin = dossier_installation().join("telechargements").join("backend.json");
    telecharger(&url_manifeste, &manifeste_chemin, |_, _| {}).await.map_err(|e| {
        format!(
            "{e}\n\nAucune version {version_app} du backend n'est publiée à cette adresse. \
             Si tu développes Diapason, garde ton dépôt : écris son chemin dans \
             ~/.diapason/project_root."
        )
    })?;
    let manifeste = analyser_manifeste(
        &std::fs::read_to_string(&manifeste_chemin).map_err(|e| e.to_string())?,
    )?;
    if manifeste.version != version_app {
        return Err(format!(
            "backend.json annonce la version {} alors que l'app est en {version_app}",
            manifeste.version
        ));
    }

    let archive = dossier_installation()
        .join("telechargements")
        .join(&manifeste.source);
    let quoi = "Téléchargement du code de Diapason";
    telecharger(&format!("{base}/{}", manifeste.source), &archive, |recu, total| {
        signaler(texte_avancement(quoi, recu, total));
    })
    .await?;
    signaler("Installation du code…".into());
    extraire(&archive, &racine, true)?;
    let _ = std::fs::remove_file(&archive);
    if !racine.join("pyproject.toml").is_file() {
        return Err(format!(
            "l'archive {} ne contient pas de pyproject.toml à sa racine",
            manifeste.source
        ));
    }

    // La wheel, si une existe pour cette cible. Sans elle, `uv sync` devra
    // compiler l'extension et l'erreur existante (« install Rust ») le dira.
    let _ = std::fs::remove_dir_all(dossier_roues());
    if let Some(nom_roue) = manifeste.wheels.get(cible()) {
        let roue = dossier_roues().join(nom_roue);
        let quoi = "Téléchargement de l'extension native";
        telecharger(&format!("{base}/{nom_roue}"), &roue, |recu, total| {
            signaler(texte_avancement(quoi, recu, total));
        })
        .await?;
        resultat.roue = Some(roue);
    }

    // Python : la version de la wheel, pour que `uv` n'en choisisse pas une
    // autre (une wheel cp313 n'importe pas dans un 3.14).
    std::fs::write(racine.join(".python-version"), format!("{}\n", manifeste.python))
        .map_err(|e| format!("impossible d'écrire .python-version : {e}"))?;
    std::fs::write(racine.join(TEMOIN_VERSION), format!("{version_app}\n"))
        .map_err(|e| format!("impossible d'écrire le témoin de version : {e}"))?;
    resultat.python = Some(manifeste.python);
    Ok(resultat)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn la_cible_est_une_des_six_connues() {
        let c = cible();
        assert!(
            [
                "aarch64-apple-darwin",
                "x86_64-apple-darwin",
                "aarch64-pc-windows-msvc",
                "x86_64-pc-windows-msvc",
                "aarch64-unknown-linux-gnu",
                "x86_64-unknown-linux-gnu",
            ]
            .contains(&c),
            "cible inconnue : {c}"
        );
    }

    #[test]
    fn les_archives_uv_suivent_le_nommage_d_astral() {
        let (url, tete) = archive_uv("aarch64-apple-darwin");
        assert!(url.ends_with("/uv-aarch64-apple-darwin.tar.gz"), "{url}");
        assert!(tete, "les tar.gz d'Astral ont un dossier de tête");
        let (url, tete) = archive_uv("x86_64-pc-windows-msvc");
        assert!(url.ends_with("/uv-x86_64-pc-windows-msvc.zip"), "{url}");
        assert!(!tete, "les zip d'Astral sont à plat");
    }

    #[test]
    fn ollama_a_une_archive_par_systeme() {
        assert!(archive_ollama("aarch64-apple-darwin").unwrap().ends_with("ollama-darwin.tgz"));
        assert!(archive_ollama("x86_64-apple-darwin").unwrap().ends_with("ollama-darwin.tgz"));
        assert!(archive_ollama("x86_64-pc-windows-msvc").unwrap().ends_with("ollama-windows-amd64.zip"));
        assert!(archive_ollama("x86_64-unknown-linux-gnu").unwrap().ends_with("ollama-linux-amd64.tgz"));
        assert!(archive_ollama("riscv64-inconnu").is_none());
    }

    #[test]
    fn l_url_des_releases_suit_la_version_de_l_app() {
        // La variable d'environnement, si une autre session l'a posée, ne doit
        // pas fausser ce test : on la retire le temps de l'assertion.
        let ancienne = std::env::var("DIAPASON_BACKEND_URL").ok();
        std::env::remove_var("DIAPASON_BACKEND_URL");
        let url = url_base_backend("1.2.3");
        if let Some(v) = ancienne {
            std::env::set_var("DIAPASON_BACKEND_URL", v);
        }
        assert_eq!(
            url,
            "https://github.com/carlitoetienne01-spec/Diapason/releases/download/desktop-v1.2.3"
        );
    }

    #[test]
    fn le_manifeste_exige_ses_trois_champs() {
        let m = analyser_manifeste(
            r#"{"version":"1.0.0","python":"3.13","source":"diapason-src-1.0.0.tar.gz",
                "wheels":{"aarch64-apple-darwin":"diapason_rust-0.1.0-cp313-cp313-macosx_11_0_arm64.whl"}}"#,
        )
        .expect("manifeste valide");
        assert_eq!(m.python, "3.13");
        assert_eq!(m.wheels.len(), 1);
        assert!(analyser_manifeste(r#"{"version":"1.0.0"}"#).is_err(), "source et python manquent");
        let avec_bom = "\u{feff}{\"version\":\"1\",\"python\":\"3.13\",\"source\":\"s.tgz\"}";
        assert!(analyser_manifeste(avec_bom).is_ok(), "le BOM d'un Out-File utf8 ne doit pas tout casser");
        assert!(analyser_manifeste("pas du json").is_err());
        // Sans `wheels` : valide, on compilera.
        assert!(analyser_manifeste(r#"{"version":"1","python":"3.13","source":"s.tgz"}"#).is_ok());
    }

    #[test]
    fn le_temoin_de_version_decide_du_retelechargement() {
        let d = tempfile::tempdir().unwrap();
        let racine = d.path().join("src");
        // Rien : on installe.
        assert!(doit_installer_source(&racine, "1.0.0"));
        // Un pyproject sans témoin : une installation faite autrement, on la garde.
        std::fs::create_dir_all(&racine).unwrap();
        std::fs::write(racine.join("pyproject.toml"), "").unwrap();
        assert!(!doit_installer_source(&racine, "1.0.0"));
        // Témoin à la bonne version : rien à faire.
        std::fs::write(racine.join(TEMOIN_VERSION), "1.0.0\n").unwrap();
        assert!(!doit_installer_source(&racine, "1.0.0"));
        // L'app a avancé : on retélécharge.
        assert!(doit_installer_source(&racine, "1.0.1"));
    }

    #[test]
    fn le_pourcentage_est_borne_et_muet_sans_total() {
        assert_eq!(pourcentage(50, Some(200)), Some(25));
        assert_eq!(pourcentage(300, Some(200)), Some(100));
        assert_eq!(pourcentage(50, Some(0)), None);
        assert_eq!(pourcentage(50, None), None);
        assert_eq!(texte_avancement("X", 5_000_000, Some(20_000_000)), "X — 25 % de 20 Mo");
        assert_eq!(texte_avancement("X", 1_500_000_000, None), "X — 1.5 Go");
    }

    /// Le premier lancement, pour de vrai, hors interface : un dossier
    /// d'installation jetable, les vraies archives d'Astral et d'Ollama, le
    /// code et la wheel servis par un serveur local (`DIAPASON_BACKEND_URL`),
    /// puis `uv sync` et l'import de l'extension. Ignoré par défaut : ~200 Mo
    /// de réseau et plusieurs minutes. À lancer après tout changement ici :
    ///
    ///   DIAPASON_BACKEND_URL=http://127.0.0.1:8765 \
    ///   cargo test --release amorcage_reel -- --ignored --nocapture
    #[tokio::test]
    #[ignore]
    async fn amorcage_reel() {
        let Ok(base) = std::env::var("DIAPASON_BACKEND_URL") else {
            panic!("pose DIAPASON_BACKEND_URL vers un serveur qui sert dist/backend/");
        };
        let jetable = tempfile::tempdir().unwrap();
        std::env::set_var("DIAPASON_HOME", jetable.path());
        let mut journal = |t: String| eprintln!("  {t}");

        let uv = assurer_uv(false, &mut journal).await.expect("uv").expect("téléchargé");
        assert!(uv.is_file(), "{}", uv.display());
        let sortie = std::process::Command::new(&uv).arg("--version").output().unwrap();
        assert!(sortie.status.success(), "uv --version doit répondre");
        eprintln!("  uv : {}", String::from_utf8_lossy(&sortie.stdout).trim());

        let ollama = assurer_ollama(false, &mut journal).await.expect("ollama").expect("téléchargé");
        let sortie = std::process::Command::new(&ollama).arg("--version").output().unwrap();
        assert!(sortie.status.success(), "ollama --version doit répondre");
        eprintln!("  ollama : {}", String::from_utf8_lossy(&sortie.stdout).trim());

        let a = assurer_source(VERSION_APP, &mut journal).await.expect("source");
        let racine = a.racine_geree.clone().unwrap();
        assert!(racine.join("pyproject.toml").is_file());
        assert_eq!(version_installee(&racine).as_deref(), Some(VERSION_APP));
        let roue = a.roue.clone().expect("une wheel pour cette cible");
        eprintln!("  code : {} ; wheel : {}", racine.display(), roue.display());
        // Relancé : rien à refaire.
        let b = assurer_source(VERSION_APP, &mut |_| {}).await.unwrap();
        assert_eq!(b.roue, a.roue, "la wheel déjà téléchargée doit être réutilisée");

        eprintln!("  uv sync…");
        let args = crate::args_uv_sync(true);
        let sortie = std::process::Command::new(&uv)
            .args(&args)
            .current_dir(&racine)
            .output()
            .unwrap();
        assert!(
            sortie.status.success(),
            "uv sync : {}",
            String::from_utf8_lossy(&sortie.stderr)
        );
        let sortie = std::process::Command::new(&uv)
            .args(["pip", "install", "--python", ".venv"])
            .arg(&roue)
            .current_dir(&racine)
            .output()
            .unwrap();
        assert!(sortie.status.success(), "wheel : {}", String::from_utf8_lossy(&sortie.stderr));
        let sortie = std::process::Command::new(&uv)
            .args(["run", "python", "-c", "import diapason_rust, diapason; print(diapason.__file__)"])
            .current_dir(&racine)
            .output()
            .unwrap();
        assert!(sortie.status.success(), "import : {}", String::from_utf8_lossy(&sortie.stderr));
        eprintln!("  import : {}", String::from_utf8_lossy(&sortie.stdout).trim());
        // Un second `uv sync --inexact` ne doit pas retirer la wheel.
        let sortie = std::process::Command::new(&uv).args(&args).current_dir(&racine).output().unwrap();
        assert!(sortie.status.success());
        let sortie = std::process::Command::new(&uv)
            .args(["run", "python", "-c", "import diapason_rust"])
            .current_dir(&racine)
            .output()
            .unwrap();
        assert!(sortie.status.success(), "la wheel a été élaguée par le second uv sync");
        let _ = base;
    }

    #[cfg(unix)]
    #[test]
    fn l_extraction_retire_le_dossier_de_tete_et_vide_la_destination() {
        let d = tempfile::tempdir().unwrap();
        // Une archive comme celle d'Astral : un dossier de tête, un binaire.
        let source = d.path().join("uv-test");
        std::fs::create_dir_all(&source).unwrap();
        std::fs::write(source.join("uv"), "#!/bin/sh\necho ok\n").unwrap();
        let archive = d.path().join("uv.tgz");
        let statut = std::process::Command::new("/usr/bin/tar")
            .args(["-czf"])
            .arg(&archive)
            .arg("-C")
            .arg(d.path())
            .arg("uv-test")
            .status()
            .unwrap();
        assert!(statut.success());

        let destination = d.path().join("dest");
        std::fs::create_dir_all(&destination).unwrap();
        std::fs::write(destination.join("fantome"), "").unwrap();
        extraire(&archive, &destination, true).expect("extraction");
        assert!(destination.join("uv").is_file(), "le binaire doit être à plat");
        assert!(!destination.join("fantome").exists(), "la destination doit être vidée d'abord");

        extraire(&archive, &destination, false).expect("extraction sans strip");
        assert!(destination.join("uv-test").join("uv").is_file());
    }
}
