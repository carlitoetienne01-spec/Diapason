use std::sync::Arc;
use std::time::Duration;
use tauri::menu::{MenuBuilder, MenuItemBuilder};
use tauri::tray::TrayIconBuilder;
use tauri::{Emitter, Manager};
use tauri_plugin_autostart::MacosLauncher;
use tokio::sync::Mutex;

mod live_speech;

const OLLAMA_PORT: u16 = 11434;
const DIAPASON_PORT: u16 = 8000;
const DESKTOP_UV_SYNC_ARGS: &[&str] = &[
    "sync",
    "--locked",
    "--extra",
    "desktop",
    "--extra",
    "dictation",
    "--extra",
    "voice-local",
    "--extra",
    "inference-cloud",
    "--extra",
    "inference-google",
    // diapason_rust lives in a uv dependency group (not the published
    // `desktop` extra) so pip installs from PyPI do not require it (#584).
    "--group",
    "desktop-native",
];
const DESKTOP_UV_SYNC_COMMAND: &str =
    "uv sync --locked --extra desktop --extra dictation --extra voice-local --extra inference-cloud --extra inference-google --group desktop-native";

/// Small, fast model used when startup needs a default Ollama tag.
const STARTUP_MODEL: &str = "qwen3.5:4b";

/// Tiny fallback model if even the startup model can't be pulled.
const FALLBACK_MODEL: &str = "qwen3:0.6b";

/// Qwen3.5 model variants, ordered smallest to largest.
/// Each entry is (ollama_tag, approximate_download_size_gb, min_ram_gb).
const QWEN35_MODELS: &[(&str, f64, f64)] = &[
    ("qwen3.5:0.8b", 1.0, 4.0),
    ("qwen3.5:2b", 2.7, 6.0),
    ("qwen3.5:4b", 3.4, 8.0),
    ("qwen3.5:9b", 6.6, 12.0),
    ("qwen3.5:27b", 17.0, 24.0),
    ("qwen3.5:35b", 24.0, 32.0),
    ("qwen3.5:122b", 81.0, 96.0),
];

/// Get total system RAM in GB.
/// Sur Windows, un enfant « console » ouvre SA PROPRE fenêtre noire.
///
/// `main.rs` rend l'APPLICATION sans console, ce qui est nécessaire mais pas
/// suffisant : chaque `where`, `git`, `uv` ou `ollama` lancé ensuite alloue
/// la sienne. `resolve_bin` est appelé quatre fois au démarrage — c'est une
/// dizaine de fenêtres noires qui clignotent à chaque lancement, sur une
/// application qui se veut discrète.
///
/// Sans effet ailleurs : le corps non-Windows rend la commande telle quelle,
/// pour que les sites d'appel n'aient pas à porter de `cfg`.
#[cfg(target_os = "windows")]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

#[cfg(target_os = "windows")]
fn sans_fenetre(cmd: &mut std::process::Command) -> &mut std::process::Command {
    use std::os::windows::process::CommandExt;
    cmd.creation_flags(CREATE_NO_WINDOW)
}

// Tous ses sites d'appel vivent dans des blocs `cfg(target_os = "windows")`
// — c'est bien le but. Sans cet `allow`, la construction macOS avertit d'un
// code mort qui ne l'est que pour elle.
#[cfg(not(target_os = "windows"))]
#[allow(dead_code)]
fn sans_fenetre(cmd: &mut std::process::Command) -> &mut std::process::Command {
    cmd
}

#[cfg(target_os = "windows")]
fn sans_fenetre_async(
    cmd: &mut tokio::process::Command,
) -> &mut tokio::process::Command {
    cmd.creation_flags(CREATE_NO_WINDOW)
}

#[cfg(not(target_os = "windows"))]
fn sans_fenetre_async(
    cmd: &mut tokio::process::Command,
) -> &mut tokio::process::Command {
    cmd
}

fn total_ram_gb() -> f64 {
    #[cfg(target_os = "macos")]
    {
        use std::process::Command;
        if let Ok(output) = Command::new("sysctl").args(["-n", "hw.memsize"]).output() {
            if let Ok(s) = String::from_utf8(output.stdout) {
                if let Ok(bytes) = s.trim().parse::<u64>() {
                    return bytes as f64 / (1024.0 * 1024.0 * 1024.0);
                }
            }
        }
    }
    #[cfg(target_os = "linux")]
    {
        if let Ok(contents) = std::fs::read_to_string("/proc/meminfo") {
            for line in contents.lines() {
                if line.starts_with("MemTotal:") {
                    if let Some(kb_str) = line.split_whitespace().nth(1) {
                        if let Ok(kb) = kb_str.parse::<u64>() {
                            return kb as f64 / (1024.0 * 1024.0);
                        }
                    }
                }
            }
        }
    }
    #[cfg(target_os = "windows")]
    {
        use std::process::Command;
        // `wmic` d'abord : il est instantané là où il existe encore. Mais il
        // est RETIRÉ PAR DÉFAUT de Windows 11 24H2 et de Server 2025 — sur
        // une machine récente, ce chemin ne rend rien et la fonction
        // retombait sur 8 Go inventés, qui décidaient ensuite du plan de
        // démarrage et du modèle chargé.
        //
        // Le repli est `Get-CimInstance`, le successeur officiel de wmic.
        // Il coûte le lancement d'un PowerShell (quelques centaines de
        // millisecondes) — acceptable : `total_ram_gb` n'est appelé qu'une
        // fois, au calcul du plan de démarrage.
        //
        // Pas d'appel FFI à GlobalMemoryStatusEx ici, bien qu'il soit plus
        // propre : `windows-sys` n'est qu'une dépendance transitive, et une
        // signature FFI écrite sans pouvoir la compiler bloquerait la
        // construction Windows au lieu de la dégrader.
        let mut wmic = Command::new("wmic");
        wmic.args(["OS", "get", "TotalVisibleMemorySize", "/value"]);
        let kilo_octets = sans_fenetre(&mut wmic)
            .output()
            .ok()
            .and_then(|o| String::from_utf8(o.stdout).ok())
            .and_then(|s| {
                s.lines()
                    .find_map(|l| l.strip_prefix("TotalVisibleMemorySize="))
                    .and_then(|v| v.trim().parse::<u64>().ok())
            })
            .or_else(|| {
                let mut ps = Command::new("powershell");
                ps.args([
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    "(Get-CimInstance Win32_OperatingSystem).TotalVisibleMemorySize",
                ]);
                sans_fenetre(&mut ps)
                    .output()
                    .ok()
                    .and_then(|o| String::from_utf8(o.stdout).ok())
                    .and_then(|s| s.trim().parse::<u64>().ok())
            });
        if let Some(kb) = kilo_octets {
            return kb as f64 / (1024.0 * 1024.0);
        }
    }
    8.0
}

/// Return the Qwen3.5 models that fit in `ram_gb`, smallest first.
fn models_that_fit_in(ram_gb: f64) -> Vec<&'static str> {
    QWEN35_MODELS
        .iter()
        .filter(|(_, _, min_ram)| ram_gb >= *min_ram)
        .map(|(tag, _, _)| *tag)
        .collect()
}

/// The default local model: the second-largest Qwen3.5 model that fits in
/// `ram_gb`. Falls back to the only fitting model, or FALLBACK_MODEL if none
/// fit. Deliberately NOT the largest — leaves RAM headroom for the OS/app.
fn default_local_model(ram_gb: f64) -> &'static str {
    let fitting = models_that_fit_in(ram_gb);
    match fitting.len() {
        0 => FALLBACK_MODEL,
        1 => fitting[0],
        n => fitting[n - 2],
    }
}

/// A resolved boot plan derived purely from the inference config + RAM.
/// Pure and side-effect-free so it can be unit-tested without spawning
/// processes or touching the network.
#[derive(Debug, Clone, PartialEq, Eq)]
struct BootPlan {
    /// Whether to start and wait for Ollama.
    launch_ollama: bool,
    /// The preferred Ollama model (None for custom endpoints).
    model_to_pull: Option<String>,
    /// Optional `(engine_key, bare_host)` override for a custom endpoint,
    /// e.g. `("lmstudio", "http://localhost:1234")`. Written into
    /// ~/.diapason/config.toml so `diapason serve` picks it up.
    engine_host: Option<(String, String)>,
    /// Args appended after `uv run diapason serve --port <port>`.
    serve_args: Vec<String>,
}

/// Default OpenAI-compatible engine key used when a custom endpoint config
/// omits one (LM Studio is the canonical local server).
const CUSTOM_FALLBACK_ENGINE: &str = "lmstudio";

/// Decide what to launch/pull/serve from the inference config + system RAM.
/// Pure: no I/O, no spawning.
fn boot_plan(cfg: &InferenceConfig, ram_gb: f64) -> BootPlan {
    match cfg.kind {
        SourceKind::Ollama => {
            let model = cfg
                .model
                .clone()
                .unwrap_or_else(|| default_local_model(ram_gb).to_string());
            BootPlan {
                launch_ollama: true,
                model_to_pull: Some(model.clone()),
                engine_host: None,
                serve_args: vec![
                    "--engine".into(),
                    "ollama".into(),
                    "--model".into(),
                    model,
                    "--agent".into(),
                    "simple".into(),
                ],
            }
        }
        SourceKind::Custom => {
            let engine = cfg
                .engine
                .clone()
                .unwrap_or_else(|| CUSTOM_FALLBACK_ENGINE.to_string());
            // Record (engine_key, bare_host) only when a host is configured, so
            // boot can write `[engine.<key>] host = ...` into config.toml. An
            // empty host is dropped (no override).
            let engine_host = cfg
                .host
                .clone()
                .filter(|h| !h.is_empty())
                .map(|h| (engine.clone(), h));
            // `model` may be empty if the config is malformed; `diapason serve`
            // surfaces a clear error then (there is no universal default model
            // for an arbitrary endpoint).
            let model = cfg.model.clone().unwrap_or_default();
            BootPlan {
                launch_ollama: false,
                model_to_pull: None,
                engine_host,
                serve_args: vec![
                    "--engine".into(),
                    engine,
                    "--model".into(),
                    model,
                    "--agent".into(),
                    "simple".into(),
                ],
            }
        }
    }
}

/// Get the user home directory, handling both Unix (HOME) and Windows (USERPROFILE).
fn home_dir() -> String {
    std::env::var("HOME")
        .or_else(|_| std::env::var("USERPROFILE"))
        .unwrap_or_default()
}

#[cfg(any(test, target_os = "linux"))]
fn session_linux_accepte_les_raccourcis_globaux(
    session_type: Option<&str>,
    wayland_display: Option<&str>,
) -> bool {
    // global-hotkey 0.8 ne prend en charge que X11. Sous Wayland, XWayland
    // permet tout de même d'ouvrir une connexion X11 : l'inscription rendait
    // alors Ok, mais aucune touche globale n'arrivait. Ce faux succès est pire
    // qu'une absence explicite, car l'interface promet un raccourci inerte.
    let session_wayland = session_type
        .map(str::trim)
        .is_some_and(|value| value.eq_ignore_ascii_case("wayland"));
    let socket_wayland = wayland_display
        .map(str::trim)
        .is_some_and(|value| !value.is_empty());
    !(session_wayland || socket_wayland)
}

fn raccourcis_globaux_disponibles() -> bool {
    #[cfg(target_os = "linux")]
    {
        return session_linux_accepte_les_raccourcis_globaux(
            std::env::var("XDG_SESSION_TYPE").ok().as_deref(),
            std::env::var("WAYLAND_DISPLAY").ok().as_deref(),
        );
    }
    #[cfg(not(target_os = "linux"))]
    {
        true
    }
}

/// Resolve full path to a binary by checking common locations.
/// macOS .app bundles don't inherit the shell PATH, so we probe manually.
fn resolve_bin(name: &str) -> String {
    let home = home_dir();

    #[cfg(not(target_os = "windows"))]
    let mut candidates = vec![
        format!("/opt/homebrew/bin/{name}"),
        format!("{home}/.local/bin/{name}"),
        format!("{home}/.cargo/bin/{name}"),
        format!("/usr/local/bin/{name}"),
        format!("/usr/bin/{name}"),
    ];

    #[cfg(target_os = "windows")]
    let mut candidates = {
        let localappdata = std::env::var("LOCALAPPDATA").unwrap_or_default();
        let programfiles = std::env::var("ProgramFiles").unwrap_or_default();
        let programfiles_x86 = std::env::var("ProgramFiles(x86)").unwrap_or_default();
        vec![
            // Git for Windows — standard install paths
            format!("{programfiles}\\Git\\cmd\\{name}.exe"),
            format!("{programfiles_x86}\\Git\\cmd\\{name}.exe"),
            format!("{localappdata}\\Programs\\Git\\cmd\\{name}.exe"),
            // Scoop package manager
            format!("{home}\\scoop\\shims\\{name}.exe"),
            // Cargo, local bin
            format!("{home}\\.cargo\\bin\\{name}.exe"),
            format!("{home}\\.local\\bin\\{name}.exe"),
            // Generic program locations
            format!("{localappdata}\\Programs\\{name}\\{name}.exe"),
            format!("{programfiles}\\{name}\\{name}.exe"),
            // Ollama installs to LOCALAPPDATA on Windows
            format!("{localappdata}\\Programs\\Ollama\\{name}.exe"),
            // uv installs via pip/pipx
            format!("{home}\\AppData\\Roaming\\Python\\Scripts\\{name}.exe"),
        ]
    };

    // An explicit `bundle.externalBin` would place a sidecar beside the
    // packaged executable. Keep supporting that layout, but do not confuse
    // support with distribution: Ollama's Windows archive includes more than
    // the executable, so the release workflow no longer copies only
    // `ollama.exe` and calls the resulting package complete.
    if let Ok(executable) = std::env::current_exe() {
        if let Some(directory) = executable.parent() {
            #[cfg(target_os = "windows")]
            candidates.insert(
                0,
                directory.join(format!("{name}.exe")).display().to_string(),
            );
            #[cfg(not(target_os = "windows"))]
            candidates.insert(0, directory.join(name).display().to_string());
        }
    }

    for path in &candidates {
        if std::path::Path::new(path).exists() {
            return path.clone();
        }
    }

    // Fallback: ask the OS to find it on PATH.
    // On Windows this uses `where.exe`, on Unix `which`.
    #[cfg(target_os = "windows")]
    {
        let mut ou = std::process::Command::new("where");
        if let Ok(output) = sans_fenetre(&mut ou)
            .arg(format!("{name}.exe"))
            .output()
        {
            if output.status.success() {
                let stdout = String::from_utf8_lossy(&output.stdout);
                if let Some(first_line) = stdout.lines().next() {
                    let p = first_line.trim();
                    if !p.is_empty() && std::path::Path::new(p).exists() {
                        return p.to_string();
                    }
                }
            }
        }
    }
    #[cfg(not(target_os = "windows"))]
    {
        if let Ok(output) = std::process::Command::new("which").arg(name).output() {
            if output.status.success() {
                let stdout = String::from_utf8_lossy(&output.stdout);
                if let Some(first_line) = stdout.lines().next() {
                    let p = first_line.trim();
                    if !p.is_empty() && std::path::Path::new(p).exists() {
                        return p.to_string();
                    }
                }
            }
        }
    }

    name.to_string()
}

/// Find the Diapason project root (contains pyproject.toml).
/// Checks explicit roots, installer-owned roots, walks up from the executable,
/// then probes common development clone locations.
/// Où le projet a été trouvé la dernière fois.
///
/// La liste de chemins connus de `locate_project_root` est une DEVINETTE. Elle
/// ne contenait pas « Projets » (l'orthographe française), et déplacer le dépôt
/// a suffi à faire croire à l'application qu'il fallait le retélécharger depuis
/// GitHub — jusqu'à afficher « Repository not found » à l'utilisateur. Se
/// souvenir d'un emplacement prouvé vaut mieux que deviner une liste.
fn remembered_root_file() -> std::path::PathBuf {
    std::path::PathBuf::from(home_dir())
        .join(".diapason")
        .join("project_root")
}

fn remember_project_root(path: &std::path::Path) {
    let file = remembered_root_file();
    if let Some(parent) = file.parent() {
        let _ = std::fs::create_dir_all(parent);
    }
    // N'écrire que si l'emplacement a changé : ce fichier est lu à chaque
    // démarrage, une réécriture systématique ne servirait à rien.
    let actuel = std::fs::read_to_string(&file).unwrap_or_default();
    let voulu = path.to_string_lossy();
    if actuel.trim() != voulu {
        let _ = std::fs::write(&file, voulu.as_bytes());
    }
}

fn find_project_root() -> Option<std::path::PathBuf> {
    let trouve = locate_project_root();
    if let Some(ref chemin) = trouve {
        remember_project_root(chemin);
    }
    trouve
}

fn project_candidates_in_install_root(root: &std::path::Path) -> [std::path::PathBuf; 2] {
    // Windows install.ps1 and the Unix installer both own an INSTALL root and
    // place the checkout below `src`. A few early/manual installations pointed
    // DIAPASON_HOME directly at the checkout, so keep that proven shape too.
    [root.join("src"), root.to_path_buf()]
}

fn installed_project_root() -> Option<std::path::PathBuf> {
    let mut install_roots = Vec::new();

    for name in ["DIAPASON_HOME", "OPENJARVIS_HOME", "JARVIS_HOME"] {
        if let Ok(value) = std::env::var(name) {
            if !value.trim().is_empty() {
                install_roots.push(std::path::PathBuf::from(value));
            }
        }
    }

    // Native Windows installs live here by default. Without this candidate a
    // freshly bootstrapped PC had a valid venv and checkout, yet the MSI said
    // the project was absent and tried to clone the private repository again.
    if let Ok(local_app_data) = std::env::var("LOCALAPPDATA") {
        if !local_app_data.trim().is_empty() {
            install_roots.push(std::path::PathBuf::from(local_app_data).join("Diapason"));
        }
    }

    if let Ok(xdg_data_home) = std::env::var("XDG_DATA_HOME") {
        if !xdg_data_home.trim().is_empty() {
            install_roots.push(std::path::PathBuf::from(xdg_data_home).join("diapason"));
        }
    }
    install_roots.push(std::path::PathBuf::from(home_dir()).join(".diapason"));

    install_roots
        .iter()
        .flat_map(|root| project_candidates_in_install_root(root))
        .find(|candidate| candidate.join("pyproject.toml").is_file())
}

fn locate_project_root() -> Option<std::path::PathBuf> {
    // 1. Explicit env var override. DIAPASON_ROOT is the current name;
    //    OPENJARVIS_ROOT still works so an existing shell profile does not
    //    break silently — the same contract as the Python side.
    for var in ["DIAPASON_ROOT", "OPENJARVIS_ROOT"] {
        if let Ok(root) = std::env::var(var) {
            let path = std::path::PathBuf::from(&root);
            if path.join("pyproject.toml").exists() {
                return Some(path);
            }
        }
    }

    // 1b. L'emplacement où le projet a RÉELLEMENT été trouvé la dernière fois.
    //     Passe avant la remontée depuis l'exécutable et avant la liste de
    //     chemins : une application installée dans /Applications ne peut pas
    //     remonter jusqu'au dépôt, et la liste ne devine que des noms anglais.
    if let Ok(texte) = std::fs::read_to_string(remembered_root_file()) {
        let chemin = std::path::PathBuf::from(texte.trim());
        if chemin.join("pyproject.toml").exists() {
            return Some(chemin);
        }
    }

    // 1c. Installer-owned locations. These are not guesses: they are the
    // paths written by scripts/install/install.sh and install.ps1.
    if let Some(path) = installed_project_root() {
        return Some(path);
    }

    // 2. Walk up from the running executable (works in dev and .app bundle)
    if let Ok(exe) = std::env::current_exe() {
        let mut dir = exe.parent().map(|p| p.to_path_buf());
        for _ in 0..8 {
            if let Some(ref d) = dir {
                if d.join("pyproject.toml").exists() {
                    return Some(d.clone());
                }
                dir = d.parent().map(|p| p.to_path_buf());
            }
        }
    }

    // 3. Fallback: well-known direct paths
    let home = home_dir();
    let direct = [
        format!("{home}/Diapason"),
        // Where a downloaded copy actually lands. Its absence is why an app
        // installed to /Applications — and therefore unable to find the root
        // by walking up from its own executable — fell through to cloning.
        format!("{home}/Downloads/Diapason"),
        format!("{home}/projects/hazy/Diapason"),
        format!("{home}/projects/Diapason"),
        // « Projets » : l'utilisateur de cette machine range son code là, et
        // son absence de cette liste a déclenché un retéléchargement.
        format!("{home}/Projets/Diapason"),
        format!("{home}/projets/Diapason"),
        format!("{home}/Documents/Projets/Diapason"),
        format!("{home}/src/Diapason"),
        format!("{home}/Documents/Diapason"),
        format!("{home}/Desktop/Diapason"),
        format!("{home}/Developer/Diapason"),
        format!("{home}/dev/Diapason"),
        format!("{home}/Code/Diapason"),
        format!("{home}/code/Diapason"),
        format!("{home}/repos/Diapason"),
        format!("{home}/github/Diapason"),
    ];
    for p in &direct {
        let path = std::path::PathBuf::from(p);
        if path.join("pyproject.toml").exists() {
            return Some(path);
        }
    }

    // 4. Shallow scan: look for Diapason one level inside common parent dirs.
    //    This catches clones like ~/Documents/my-stuff/Diapason without
    //    needing to enumerate every possible intermediate folder.
    let scan_parents = [
        format!("{home}/Documents"),
        format!("{home}/Desktop"),
        format!("{home}/Developer"),
        format!("{home}/projects"),
        format!("{home}/repos"),
        format!("{home}/src"),
        format!("{home}/Code"),
        format!("{home}/code"),
        format!("{home}/dev"),
        format!("{home}/github"),
    ];
    for parent in &scan_parents {
        let parent_path = std::path::PathBuf::from(parent);
        if let Ok(entries) = std::fs::read_dir(&parent_path) {
            for entry in entries.flatten() {
                let candidate = entry.path().join("Diapason");
                if candidate.join("pyproject.toml").exists() {
                    return Some(candidate);
                }
                // Also check if the entry itself is Diapason (case-insensitive match)
                if let Some(name) = entry.file_name().to_str() {
                    if name.eq_ignore_ascii_case("diapason")
                        && entry.path().join("pyproject.toml").exists()
                    {
                        return Some(entry.path());
                    }
                }
            }
        }
    }

    None
}

// ---------------------------------------------------------------------------
// BackendManager — owns the Ollama + Diapason server child processes
// ---------------------------------------------------------------------------

struct ChildHandle {
    child: tokio::process::Child,
}

impl ChildHandle {
    async fn kill(&mut self) {
        // Le serveur est lancé par « uv run diapason serve » : l'enfant direct
        // est `uv`, et le vrai serveur son petit-fils. Tuer l'enfant laissait
        // donc un serveur orphelin qui tenait le port, invisible à
        // l'application qui croyait l'avoir arrêté.
        //
        // On demande l'arrêt de tout le GROUPE (PID négatif). Le groupe existe
        // parce que le lancement pose `process_group(0)` ; si ce n'était pas le
        // cas, la commande échoue sans rien casser et on retombe sur l'enfant.
        #[cfg(unix)]
        if let Some(pid) = self.child.id() {
            let groupe = format!("-{pid}");
            let _ = std::process::Command::new("/bin/kill")
                .args(["-TERM", &groupe])
                .status();
            // Laisser une seconde à un arrêt propre avant d'insister.
            tokio::time::sleep(std::time::Duration::from_millis(1000)).await;
            let _ = std::process::Command::new("/bin/kill")
                .args(["-KILL", &groupe])
                .status();
        }
        // Windows n'a ni groupe de processus au sens POSIX ni signal : le
        // `child.kill()` ci-dessous tue `uv.exe` et laisse son petit-fils
        // `python.exe` VIVANT, tenant le port 8000. Exactement le défaut que
        // le bloc unix ci-dessus décrit, mais sans le correctif.
        //
        // `taskkill /T` parcourt l'arbre depuis le PID et n'a besoin d'aucun
        // groupe. `/F` force : on n'attend pas d'arrêt propre, parce qu'un
        // serveur qui ignore la demande est précisément le cas qu'on traite.
        // Sans `sans_fenetre`, cet arrêt ferait clignoter une fenêtre noire
        // de plus, au pire moment.
        #[cfg(target_os = "windows")]
        if let Some(pid) = self.child.id() {
            let mut tuer = std::process::Command::new("taskkill");
            tuer.args(["/PID", &pid.to_string(), "/T", "/F"]);
            let _ = sans_fenetre(&mut tuer).status();
        }
        let _ = self.child.kill().await;
    }
}

/// Rolling buffer holding the most recent ~16 KB of diapason stderr.
///
/// Populated by a background drainer task spawned at boot so the pipe
/// never fills and back-pressures `diapason serve`; consumed by the boot
/// path when surfacing failure messages.
type StderrTail = Arc<Mutex<Vec<u8>>>;

const STDERR_TAIL_LIMIT: usize = 16 * 1024;

struct BackendManager {
    ollama: Option<ChildHandle>,
    diapason: Option<ChildHandle>,
    diapason_stderr_tail: StderrTail,
}

impl Default for BackendManager {
    fn default() -> Self {
        Self {
            ollama: None,
            diapason: None,
            diapason_stderr_tail: Arc::new(Mutex::new(Vec::new())),
        }
    }
}

impl BackendManager {
    async fn stop_all(&mut self) {
        if let Some(ref mut h) = self.diapason {
            h.kill().await;
        }
        self.diapason = None;
        if let Some(ref mut h) = self.ollama {
            h.kill().await;
        }
        self.ollama = None;
    }
}

type SharedBackend = Arc<Mutex<BackendManager>>;

// ---------------------------------------------------------------------------
// Setup status (reported to frontend)
// ---------------------------------------------------------------------------

#[derive(serde::Serialize, Clone)]
struct SetupStatus {
    phase: String,
    detail: String,
    ollama_ready: bool,
    server_ready: bool,
    model_ready: bool,
    error: Option<String>,
    /// "ollama" | "custom" — lets the setup UI relabel the progress steps.
    source: String,
}

impl Default for SetupStatus {
    fn default() -> Self {
        Self {
            phase: "starting".into(),
            detail: "Initializing...".into(),
            ollama_ready: false,
            server_ready: false,
            model_ready: false,
            error: None,
            source: "ollama".into(),
        }
    }
}

type SharedStatus = Arc<Mutex<SetupStatus>>;

// ---------------------------------------------------------------------------
// Health-check helpers
// ---------------------------------------------------------------------------

fn url_est_locale(url: &str) -> bool {
    reqwest::Url::parse(url)
        .ok()
        .and_then(|url| url.host_str().map(str::to_owned))
        .is_some_and(|host| {
            host == "localhost"
                || host
                    .trim_start_matches('[')
                    .trim_end_matches(']')
                    .parse::<std::net::IpAddr>()
                    .is_ok_and(|ip| ip.is_loopback())
        })
}

fn constructeur_client_http(url: &str) -> reqwest::ClientBuilder {
    let constructeur = reqwest::Client::builder();
    if url_est_locale(url) {
        // Un VPN ou un proxy Windows peut annoncer une route globale que
        // reqwest applique aussi à 127.0.0.1. Le serveur répond alors bien à
        // curl, mais l'application le croit absent et tente d'en lancer un
        // second, qui échoue sur le port déjà occupé. Une adresse de boucle
        // ne quitte jamais la machine : son client ne doit consulter aucun
        // proxy système.
        constructeur.no_proxy()
    } else {
        constructeur
    }
}

fn client_http(url: &str) -> Result<reqwest::Client, String> {
    constructeur_client_http(url)
        .build()
        .map_err(|err| format!("HTTP client creation failed: {err}"))
}

async fn wait_for_url(url: &str, timeout: Duration) -> bool {
    let client = constructeur_client_http(url)
        .timeout(Duration::from_secs(2))
        .build()
        .unwrap();
    let deadline = tokio::time::Instant::now() + timeout;
    while tokio::time::Instant::now() < deadline {
        if let Ok(resp) = client.get(url).send().await {
            if resp.status().is_success() {
                return true;
            }
        }
        tokio::time::sleep(Duration::from_millis(500)).await;
    }
    false
}

/// True if a custom OpenAI-compatible endpoint answers at all (any HTTP
/// status counts — even a 404 proves the server is up). `host` is the bare
/// base URL; we probe `<host>/v1/models`.
async fn endpoint_reachable(host: &str, timeout: Duration) -> bool {
    let url = format!("{}/v1/models", host.trim_end_matches('/'));
    let client = match constructeur_client_http(&url)
        .timeout(Duration::from_secs(3))
        .build()
    {
        Ok(c) => c,
        Err(_) => return false,
    };
    let deadline = tokio::time::Instant::now() + timeout;
    while tokio::time::Instant::now() < deadline {
        if client.get(&url).send().await.is_ok() {
            return true;
        }
        tokio::time::sleep(Duration::from_millis(500)).await;
    }
    false
}

/// Outcome of waiting for `diapason serve` to become healthy.
///
/// Unlike [`wait_for_url`] this differentiates "server is up but degraded"
/// (HTTP 503 — usually inference engine failed to load) from "server never
/// came up" and from "child process died before serving anything", because
/// each needs a different user-facing message.
#[derive(Debug)]
enum DiapasonStartResult {
    /// `/health` returned 2xx.
    Ready,
    /// Server replied 503. The body is the actionable message (typically
    /// "engine not ready" or a model-load error).
    ServiceUnavailable(String),
    /// The `diapason serve` child exited before `/health` returned 2xx.
    EarlyExit { code: Option<i32>, stderr: String },
    /// Deadline elapsed without ever seeing 2xx or an early exit.
    Timeout,
}

/// Spawn a detached task that continuously drains `diapason serve`'s
/// stderr into a rolling tail buffer.
///
/// We MUST keep reading stderr for as long as the child runs — `diapason
/// serve` is chatty (engine load progress, request logs), and the OS
/// pipe buffer is small (4 KB on Windows, 64 KB on Linux). Once full,
/// the child's next stderr write blocks indefinitely and the server
/// hangs mid-operation. The drainer reads in chunks and keeps only the
/// last `STDERR_TAIL_LIMIT` bytes — enough to surface a tail trace if
/// the child later dies, without unbounded memory growth.
///
/// Returns immediately after spawning the task; the task ends naturally
/// when the child closes stderr (i.e. exits).
fn spawn_diapason_stderr_drainer(mut stderr: tokio::process::ChildStderr, tail: StderrTail) {
    use tokio::io::AsyncReadExt;
    tokio::spawn(async move {
        let mut buf = vec![0u8; 4096];
        loop {
            match stderr.read(&mut buf).await {
                Ok(0) => break,  // EOF — child closed stderr
                Err(_) => break, // pipe broke — also done
                Ok(n) => {
                    let mut t = tail.lock().await;
                    t.extend_from_slice(&buf[..n]);
                    if t.len() > STDERR_TAIL_LIMIT {
                        let drop_n = t.len() - STDERR_TAIL_LIMIT;
                        t.drain(..drop_n);
                    }
                }
            }
        }
    });
}

/// Read whatever the stderr drainer has buffered so far.
///
/// Safe to call at any time; returns an empty string before the
/// drainer has seen any bytes. Trimmed.
async fn read_diapason_stderr_tail(backend: &SharedBackend) -> String {
    let tail = backend.lock().await.diapason_stderr_tail.clone();
    let bytes = tail.lock().await.clone();
    String::from_utf8_lossy(&bytes).trim().to_string()
}

/// Poll `diapason serve` health, watching the child process state so we
/// never wait 10 minutes for a process that crashed in the first second.
async fn wait_for_diapason_health(
    url: &str,
    timeout: Duration,
    backend: &SharedBackend,
) -> DiapasonStartResult {
    let client = match constructeur_client_http(url)
        .timeout(Duration::from_secs(2))
        .build()
    {
        Ok(c) => c,
        Err(_) => return DiapasonStartResult::Timeout,
    };
    let deadline = tokio::time::Instant::now() + timeout;
    loop {
        // 1. Has the child already exited? `try_wait` is non-blocking; on
        // Windows where uv / python / the Rust extension can fail to load
        // very fast, this catches the crash within ~500ms instead of after
        // the full HTTP timeout window.
        let exit_status = {
            let mut mgr = backend.lock().await;
            match mgr.diapason.as_mut() {
                Some(h) => h.child.try_wait().ok().flatten(),
                None => None,
            }
        };
        if let Some(status) = exit_status {
            let stderr = read_diapason_stderr_tail(backend).await;
            return DiapasonStartResult::EarlyExit {
                code: status.code(),
                stderr,
            };
        }

        // 2. Try the health endpoint.
        match client.get(url).send().await {
            Ok(resp) => {
                let status = resp.status();
                if status.is_success() {
                    return DiapasonStartResult::Ready;
                }
                if status == reqwest::StatusCode::SERVICE_UNAVAILABLE {
                    // Server is up but the inference engine is not. This
                    // is a terminal-for-us state — polling won't change
                    // anything; the user has to fix their engine config.
                    let body = resp.text().await.unwrap_or_default();
                    return DiapasonStartResult::ServiceUnavailable(body);
                }
                // Other non-2xx (e.g. 404 during a brief routing-table
                // warmup window) — fall through and keep polling.
            }
            Err(_) => {
                // Connection refused / DNS / timeout — server still
                // booting. Keep polling.
            }
        }

        if tokio::time::Instant::now() >= deadline {
            return DiapasonStartResult::Timeout;
        }
        tokio::time::sleep(Duration::from_millis(500)).await;
    }
}

async fn ollama_has_model(model: &str) -> bool {
    let models = ollama_model_names().await;
    matching_installed_model(&models, model).is_some()
}

fn parse_ollama_model_names(body: &serde_json::Value) -> Vec<String> {
    body.get("models")
        .and_then(|m| m.as_array())
        .map(|models| {
            models
                .iter()
                .filter_map(|m| {
                    m.get("name")
                        .or_else(|| m.get("model"))
                        .and_then(|n| n.as_str())
                })
                .filter(|name| !name.trim().is_empty())
                .map(|name| name.to_string())
                .collect()
        })
        .unwrap_or_default()
}

fn model_names_match(installed: &str, requested: &str) -> bool {
    installed == requested
        || installed.strip_suffix(":latest") == Some(requested)
        || requested.strip_suffix(":latest") == Some(installed)
}

fn matching_installed_model(models: &[String], requested: &str) -> Option<String> {
    models
        .iter()
        .find(|model| model_names_match(model, requested))
        .cloned()
}

fn model_name_looks_embedding_only(model: &str) -> bool {
    let name = model.to_ascii_lowercase();
    [
        "embed",
        "embedding",
        "rerank",
        "minilm",
        "bge-",
        "bge_",
        "e5-",
        "e5_",
    ]
    .iter()
    .any(|marker| name.contains(marker))
}

fn preferred_installed_model(models: &[String]) -> Option<String> {
    models
        .iter()
        .find(|model| !model.trim().is_empty() && !model_name_looks_embedding_only(model))
        .or_else(|| models.iter().find(|model| !model.trim().is_empty()))
        .cloned()
}

fn startup_installed_model(requested_model: &str, installed_models: &[String]) -> Option<String> {
    matching_installed_model(installed_models, requested_model)
        .or_else(|| preferred_installed_model(installed_models))
}

fn should_persist_resolved_model(cfg: &InferenceConfig) -> bool {
    cfg.model
        .as_deref()
        .map(|model| model.trim().is_empty())
        .unwrap_or(true)
}

async fn ollama_model_names() -> Vec<String> {
    let url = format!("http://127.0.0.1:{}/api/tags", OLLAMA_PORT);
    let client = constructeur_client_http(&url)
        .timeout(Duration::from_secs(5))
        .build()
        .unwrap();
    if let Ok(resp) = client.get(&url).send().await {
        if let Ok(body) = resp.json::<serde_json::Value>().await {
            return parse_ollama_model_names(&body);
        }
    }
    Vec::new()
}

async fn pull_model(model: &str) -> Result<(), String> {
    let url = format!("http://127.0.0.1:{}/api/pull", OLLAMA_PORT);
    let client = constructeur_client_http(&url)
        .timeout(Duration::from_secs(600))
        .build()
        .map_err(|e| e.to_string())?;
    let resp = client
        .post(&url)
        .json(&serde_json::json!({"name": model, "stream": false}))
        .send()
        .await
        .map_err(|e| format!("Pull request failed: {}", e))?;
    if !resp.status().is_success() {
        return Err(format!("Pull returned status {}", resp.status()));
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// uv sync error formatting (pure helpers — unit-tested, see #331)
// ---------------------------------------------------------------------------

/// Last `max_chars` characters of a `uv sync` stderr stream, trimmed.
///
/// uv's actionable diagnostic almost always lands at the tail of the
/// stream, so when surfacing a failure to the user we show the end, not
/// the (usually noisy progress-spinner) beginning. Operates on `char`
/// boundaries so it never splits a multi-byte UTF-8 codepoint — important
/// because Windows consoles emit non-ASCII (cp9xx) bytes.
fn uv_sync_stderr_tail(stderr: &str, max_chars: usize) -> String {
    let total = stderr.chars().count();
    let skip = total.saturating_sub(max_chars);
    stderr
        .chars()
        .skip(skip)
        .collect::<String>()
        .trim()
        .to_string()
}

/// Error message shown when `uv sync` runs but exits non-zero (#331).
///
/// `exit_code` is `None` when the process was terminated by a signal with
/// no exit code (rendered as "unknown" rather than a misleading -1).
fn format_uv_sync_failure(root: &std::path::Path, exit_code: Option<i32>, stderr: &str) -> String {
    let code = exit_code
        .map(|c| c.to_string())
        .unwrap_or_else(|| "unknown".to_string());
    let tail = uv_sync_stderr_tail(stderr, 800);
    let rust_hint = if looks_like_rust_extension_build_error(stderr) {
        format!("\n\n{}", rust_toolchain_install_hint())
    } else {
        String::new()
    };
    format!(
        "`uv sync` failed in {} (exit {}). Last output:\n\n{}\n\n\
         Try opening a terminal in that directory and running \
         `{}` manually for the full output.{}",
        root.display(),
        code,
        tail,
        DESKTOP_UV_SYNC_COMMAND,
        rust_hint,
    )
}

/// Strip AppImage-injected environment from a subprocess command (#455).
///
/// When the Diapason desktop binary is shipped as an AppImage, the AppImage
/// runtime sets `LD_LIBRARY_PATH` (and friends) to the extracted-to-/tmp
/// bundled lib dir. Any child we spawn inherits that env by default — but the
/// children we spawn (`uv`, `ollama`, `git`) live outside the AppImage and
/// must NOT load their shared libraries from the AppImage's bundle. The
/// classic symptom: `uv` finds `python3`, `python3` tries to `import numpy`,
/// numpy's `.so` files try to dlopen libstdc++/libssl/libcrypto, the linker
/// picks the AppImage's versions which were built against a different glibc
/// or libcrypto API, and python dies silently — before any startup log
/// reaches us. The user sees "API Server — starting server..." forever.
///
/// Fix: when we detect we're inside an AppImage (the AppImage runtime sets
/// `$APPIMAGE` to the original image path), strip the leaked env vars before
/// spawn. Conditional on `APPIMAGE` being set so regular Linux installs that
/// legitimately use `LD_LIBRARY_PATH` are untouched. Linux-only — the
/// `#[cfg]` makes this a no-op on macOS / Windows.
#[cfg_attr(not(target_os = "linux"), allow(unused_variables))]
fn prepare_subprocess_for_appimage(cmd: &mut tokio::process::Command) {
    #[cfg(target_os = "linux")]
    {
        if std::env::var_os("APPIMAGE").is_some() {
            cmd.env_remove("LD_LIBRARY_PATH");
            cmd.env_remove("LD_PRELOAD");
            cmd.env_remove("APPIMAGE");
            cmd.env_remove("APPIMAGE_UUID");
            cmd.env_remove("APPDIR");
            cmd.env_remove("ARGV0");
        }
    }
}

/// Error message shown when `uv sync` can't even be spawned (#331) —
/// e.g. the resolved `uv` binary doesn't exist or isn't executable.
fn format_uv_sync_spawn_error(root: &std::path::Path, uv_bin: &str, err: &str) -> String {
    format!(
        "Could not run `uv sync`: {}. Verify uv is installed at \
         `{}` and the Diapason repo is at `{}`.",
        err,
        uv_bin,
        root.display(),
    )
}

fn rust_toolchain_install_hint() -> &'static str {
    "The desktop app needs the Rust toolchain to build `diapason_rust`. \
     Install Rust from https://rustup.rs. On Windows, also install Visual Studio \
     Build Tools with the C++ workload, then relaunch."
}

fn looks_like_rust_extension_build_error(stderr: &str) -> bool {
    let lower = stderr.to_ascii_lowercase();
    [
        "diapason-rust",
        "diapason_rust",
        "maturin",
        "cargo",
        "rustc",
        "link.exe",
        "visual studio",
    ]
    .iter()
    .any(|marker| lower.contains(marker))
}

fn format_missing_rust_toolchain() -> String {
    format!(
        "Could not find Rust's `cargo` command. {}\n\n\
         If Rust is already installed, close and relaunch the desktop app so \
         PATH includes `~/.cargo/bin`.",
        rust_toolchain_install_hint(),
    )
}

fn format_extension_import_failure(root: &std::path::Path, stderr: &str) -> String {
    let tail = uv_sync_stderr_tail(stderr, 4000);
    format!(
        "`diapason_rust` is still not importable after building. Last output:\n\n{}\n\n\
         Run these manually for the full build log:\n\n\
           cd {}\n\
           {}\n\
           uv run python -c \"import diapason_rust\"",
        if tail.is_empty() {
            "(no stderr output)"
        } else {
            &tail
        },
        root.display(),
        DESKTOP_UV_SYNC_COMMAND,
    )
}

fn add_cargo_bin_to_path(cmd: &mut tokio::process::Command) {
    let mut paths: Vec<std::path::PathBuf> = std::env::var_os("PATH")
        .map(|path| std::env::split_paths(&path).collect())
        .unwrap_or_default();
    paths.insert(
        0,
        std::path::PathBuf::from(home_dir())
            .join(".cargo")
            .join("bin"),
    );
    if let Ok(joined) = std::env::join_paths(paths) {
        cmd.env("PATH", joined);
    }
}

async fn verify_diapason_rust_extension(
    root: &std::path::Path,
    uv_bin: &str,
) -> Result<(), String> {
    let mut cmd = tokio::process::Command::new(uv_bin);
    sans_fenetre_async(&mut cmd);
    cmd.args(["run", "python", "-c", "import diapason_rust"])
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::piped())
        .current_dir(root);
    prepare_subprocess_for_appimage(&mut cmd);
    add_cargo_bin_to_path(&mut cmd);

    match cmd.output().await {
        Ok(out) if out.status.success() => Ok(()),
        Ok(out) => {
            let stderr = String::from_utf8_lossy(&out.stderr);
            Err(format_extension_import_failure(root, &stderr))
        }
        Err(e) => Err(format!(
            "Could not verify `diapason_rust`: {}. Verify uv is installed at `{}`.",
            e, uv_bin
        )),
    }
}

fn port_owner_hint() -> String {
    if cfg!(target_os = "windows") {
        format!("netstat -ano | findstr :{}", DIAPASON_PORT)
    } else {
        format!("lsof -i :{}", DIAPASON_PORT)
    }
}

fn format_port_unavailable(port: u16, reason: &str) -> String {
    format!(
        "Port {} is not available: {}. Stop the process using that port or \
         change the Diapason port, then relaunch.\n\nTo identify it:\n  {}",
        port,
        reason,
        port_owner_hint(),
    )
}

/// Le port est-il réellement libre ?
///
/// MESURÉ sur macOS le 20 août 2026, contre un vrai serveur détenant
/// `0.0.0.0:8000` : une liaison sur `127.0.0.1:8000` RÉUSSIT. La bibliothèque
/// standard de Rust pose `SO_REUSEADDR` par défaut sur Unix, et deux adresses
/// différentes sur le même port ne se voient alors pas. Le contrôle d'origine,
/// qui ne testait que le loopback, était donc aveugle au serveur qu'il devait
/// justement détecter : c'est ainsi que deux serveurs ont coexisté, le lien le
/// plus spécifique gagnant le routage et l'autre devenant un zombie muet.
///
/// La même mesure donne le remède : pour un détenteur donné, la liaison sur
/// SA PROPRE adresse reste refusée. Tester les deux formes couvre donc les
/// deux détenteurs possibles, sans dépendance supplémentaire.
///
/// Limite assumée : un détenteur lié à une adresse tierce (par ex.
/// `192.168.0.10:8000`) échappe encore aux deux liaisons. La sonde `/health`
/// qui précède couvre ce cas dès lors qu'il répond.
/// Qui ÉCOUTE sur ce port, d'après le NOYAU. `None` = on n'a pas pu demander.
///
/// Sonder en tentant des liaisons, c'est deviner : quatre adresses littérales
/// ne couvriront jamais les N adresses d'une machine. MESURÉ — un serveur lié
/// à `192.168.0.121`, exactement ce que `serve-service install --allow-network`
/// installe pour que le téléphone du maillage atteigne ce Mac, échappait aux
/// quatre sondes. `lsof` répond pour toutes les adresses d'un coup.
#[cfg(unix)]
fn port_listeners(port: u16) -> Option<Vec<String>> {
    let sortie = std::process::Command::new("lsof")
        .args([
            "-nP",
            &format!("-iTCP:{port}"),
            "-sTCP:LISTEN",
            "-F",
            "pn",
        ])
        .env("LC_ALL", "C")
        .env("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")
        .output()
        .ok()?;
    let code = sortie.status.code()?;
    if code != 0 && code != 1 {
        return None;
    }
    let texte = String::from_utf8_lossy(&sortie.stdout);
    if code == 1 && !texte.trim().is_empty() {
        return None;
    }
    let mut trouves = Vec::new();
    let mut pid: Option<String> = None;
    for ligne in texte.lines() {
        if let Some(reste) = ligne.strip_prefix('p') {
            pid = Some(reste.to_string());
        } else if let Some(adresse) = ligne.strip_prefix('n') {
            if let Some(ref p) = pid {
                trouves.push(format!("PID {p} sur {adresse}"));
            }
        }
    }
    Some(trouves)
}

#[cfg(not(unix))]
fn port_listeners(_port: u16) -> Option<Vec<String>> {
    None
}

fn port_conflict(port: u16) -> Option<String> {
    // Le noyau d'abord : il voit toutes les adresses, y compris celle du
    // maillage, et il nomme le détenteur.
    if let Some(auditeurs) = port_listeners(port) {
        if auditeurs.is_empty() {
            return None;
        }
        return Some(auditeurs.join(", "));
    }

    // Repli quand `lsof` est absent : les liaisons directes. Elles ne voient
    // qu'un détenteur sur l'une de ces quatre formes, mais mieux vaut un
    // contrôle partiel que pas de contrôle.
    for addr in ["0.0.0.0", "127.0.0.1", "::", "::1"] {
        match std::net::TcpListener::bind((addr, port)) {
            Ok(_) => {}
            // SEULE « adresse déjà utilisée » prouve une occupation. Un autre
            // échec — bac à sable, pile réseau absente — n'en prouve rien, et
            // bloquer le démarrage là-dessus transformerait un contrôle en
            // panne.
            Err(err) if err.kind() == std::io::ErrorKind::AddrInUse => {
                return Some(format!("{addr}: {err}"));
            }
            Err(_) => {}
        }
    }
    None
}

fn check_jarvis_port_available() -> Result<(), String> {
    match port_conflict(DIAPASON_PORT) {
        None => Ok(()),
        Some(raison) => Err(format_port_unavailable(DIAPASON_PORT, &raison)),
    }
}

// ---------------------------------------------------------------------------
// Backend boot sequence (runs in background after app launch)
// ---------------------------------------------------------------------------

async fn boot_backend(backend: SharedBackend, status: SharedStatus) {
    // Decide the inference source (default Ollama) before launching anything.
    let cfg = read_inference_config();
    let plan = boot_plan(&cfg, total_ram_gb());
    {
        let mut s = status.lock().await;
        s.source = match cfg.kind {
            SourceKind::Ollama => "ollama",
            SourceKind::Custom => "custom",
        }
        .into();
    }

    // For the Ollama path, model resolution may fall back to FALLBACK_MODEL; we
    // record what is actually available here so the serve command below uses
    // it instead of the originally-planned tag. None on the custom path.
    let mut serve_model_override: Option<String> = None;

    if plan.launch_ollama {
        // Phase 1: Start Ollama
        {
            let mut s = status.lock().await;
            s.phase = "ollama".into();
            s.detail = "Starting inference engine...".into();
        }

        // Try an explicitly packaged sidecar first, then system Ollama.
        let ollama_child = {
            let ollama_bin = resolve_bin("ollama");
            let mut sidecar_cmd = tokio::process::Command::new(&ollama_bin);
            sans_fenetre_async(&mut sidecar_cmd);
            sidecar_cmd
                .arg("serve")
                .env("OLLAMA_HOST", format!("127.0.0.1:{}", OLLAMA_PORT))
                .stdout(std::process::Stdio::null())
                .stderr(std::process::Stdio::null());
            // Avoid LD_LIBRARY_PATH leak when running inside an AppImage (#455).
            prepare_subprocess_for_appimage(&mut sidecar_cmd);
            sidecar_cmd.spawn().ok()
        };

        if let Some(child) = ollama_child {
            backend.lock().await.ollama = Some(ChildHandle { child });
        }

        let ollama_url = format!("http://127.0.0.1:{}/api/tags", OLLAMA_PORT);
        if !wait_for_url(&ollama_url, Duration::from_secs(30)).await {
            let mut s = status.lock().await;
            s.error = Some("Could not start Ollama. Install it from https://ollama.com".into());
            return;
        }

        {
            let mut s = status.lock().await;
            s.ollama_ready = true;
            s.detail = "Inference engine ready.".into();
        }

        // Phase 2: Resolve one model to serve. Prefer an installed model on
        // first run so startup does not depend on a download succeeding.
        let model = plan
            .model_to_pull
            .clone()
            .unwrap_or_else(|| STARTUP_MODEL.to_string());
        {
            let mut s = status.lock().await;
            s.phase = "model".into();
            s.detail = format!("Checking for {}...", model);
        }

        let installed_models = ollama_model_names().await;
        let resolved_model = if let Some(installed) =
            startup_installed_model(&model, &installed_models)
        {
            installed
        } else {
            {
                let mut s = status.lock().await;
                s.detail = format!("Downloading {}... (this may take a minute)", model);
            }
            match pull_model(&model).await {
                Ok(()) => model.clone(),
                Err(e) => {
                    eprintln!("Warning: failed to pull {}: {}", model, e);

                    // If a local model appeared while pulling, use it instead of
                    // making startup depend on another network pull.
                    if let Some(installed) = preferred_installed_model(&ollama_model_names().await)
                    {
                        installed
                    } else if ollama_has_model(FALLBACK_MODEL).await {
                        FALLBACK_MODEL.to_string()
                    } else {
                        {
                            let mut s = status.lock().await;
                            s.detail = format!("Downloading {}...", FALLBACK_MODEL);
                        }
                        if let Err(e2) = pull_model(FALLBACK_MODEL).await {
                            if let Some(installed) =
                                preferred_installed_model(&ollama_model_names().await)
                            {
                                installed
                            } else {
                                let mut s = status.lock().await;
                                s.error = Some(format!("Failed to download model: {}", e2));
                                return;
                            }
                        } else {
                            FALLBACK_MODEL.to_string()
                        }
                    }
                }
            }
        };

        if resolved_model != model {
            let mut s = status.lock().await;
            s.detail = format!("Using installed model {}.", resolved_model);
        }

        serve_model_override = Some(resolved_model.clone());

        // Persist only first-run/default resolution. If the user explicitly
        // configured a model, do not overwrite that choice with a temporary
        // fallback selected just to keep startup nonfatal.
        if should_persist_resolved_model(&cfg) {
            let mut persisted = cfg.clone();
            persisted.model = Some(resolved_model);
            let _ = write_inference_config(&persisted);
        }

        {
            let mut s = status.lock().await;
            s.model_ready = true;
            s.detail = "Model ready.".into();
        }
    } else {
        // Custom OpenAI-compatible endpoint: never start Ollama, never download.
        let host = plan
            .engine_host
            .as_ref()
            .map(|(_, v)| v.clone())
            .unwrap_or_default();
        {
            let mut s = status.lock().await;
            s.phase = "model".into();
            s.detail = format!("Connecting to {}...", host);
        }
        if host.is_empty() || !endpoint_reachable(&host, Duration::from_secs(15)).await {
            let mut s = status.lock().await;
            s.error = Some(format!(
                "Could not reach your custom inference server at {}. \
                 Start the server (e.g. LM Studio) and check the URL in Settings, then relaunch.",
                if host.is_empty() {
                    "(no URL set)"
                } else {
                    host.as_str()
                }
            ));
            return;
        }
        // Point `diapason serve` at the user's endpoint by writing the engine
        // host into ~/.diapason/config.toml (the env var alone is shadowed by
        // the engine's non-empty default host in the Python layer).
        if let Some((engine, host)) = &plan.engine_host {
            if let Err(e) = set_engine_host_in_config(engine, host) {
                let mut s = status.lock().await;
                s.error = Some(format!("Could not write engine config: {}", e));
                return;
            }
        }
        {
            let mut s = status.lock().await;
            s.ollama_ready = true;
            s.model_ready = true;
            s.detail = "Connected to custom endpoint.".into();
        }
    }

    // Phase 3: Start diapason serve
    {
        let mut s = status.lock().await;
        s.phase = "server".into();
        s.detail = "Starting API server...".into();
    }

    let uv_bin = resolve_bin("uv");

    // Verify uv is actually installed. Concrete per-OS instructions —
    // the generic "install it from astral.sh" was the #1 source of
    // confusion on the Discord support thread; users couldn't tell whether
    // to use winget, scoop, pip, or the official installer.
    if !std::path::Path::new(&uv_bin).exists() && uv_bin == "uv" {
        let mut s = status.lock().await;
        #[cfg(target_os = "windows")]
        let msg = "Could not find 'uv' (Python package manager). \
                   To install on Windows, open PowerShell and run:\n\n\
                   powershell -ExecutionPolicy Bypass -c \"irm https://astral.sh/uv/install.ps1 | iex\"\n\n\
                   Then close and relaunch this app. \
                   (If the install completes but the app still can't find uv, \
                   you may need to log out and back in so PATH refreshes.)";
        #[cfg(target_os = "macos")]
        let msg = "Could not find 'uv' (Python package manager). \
                   To install on macOS, open Terminal and run:\n\n\
                   curl -LsSf https://astral.sh/uv/install.sh | sh\n\n\
                   Then relaunch this app.";
        #[cfg(target_os = "linux")]
        let msg = "Could not find 'uv' (Python package manager). \
                   To install on Linux, open a terminal and run:\n\n\
                   curl -LsSf https://astral.sh/uv/install.sh | sh\n\n\
                   Then relaunch this app.";
        #[cfg(not(any(target_os = "windows", target_os = "macos", target_os = "linux")))]
        let msg = "Could not find 'uv' (Python package manager). \
                   Install it from https://astral.sh/uv then relaunch.";
        s.error = Some(msg.into());
        return;
    }

    let project_root = find_project_root();

    if project_root.is_none() {
        let mut s = status.lock().await;
        #[cfg(target_os = "windows")]
        let message = "Diapason's local backend is not installed. The desktop \
                       package contains the native window, but not Ollama, \
                       Python, or the private source repository. Run the \
                       authenticated Windows bootstrap first, then relaunch:\n\n\
                       deploy\\windows\\install.ps1\n\n\
                       Expected project: %LOCALAPPDATA%\\Diapason\\src. If you \
                       installed elsewhere, set DIAPASON_HOME to the install \
                       root or DIAPASON_ROOT to the source directory.";
        #[cfg(not(target_os = "windows"))]
        let message = "Diapason's local backend is not installed. The desktop \
                       package contains the native window, but not Ollama, \
                       Python, or the private source repository. Run the \
                       authenticated installer first, then relaunch. If the \
                       project already exists, set DIAPASON_HOME to its install \
                       root, DIAPASON_ROOT to the source directory, or write \
                       that source path to ~/.diapason/project_root.";
        s.error = Some(message.into());
        return;
    }

    // If something is already serving on our port, decide what to do based
    // on what it actually responds with — don't blindly kill it (#455).
    //
    // The OLD behaviour was: any HTTP response (even 404) → `fuser -k 8000/tcp`
    // / `taskkill /PID /F`. That broke the legitimate case where a user had
    // already started `diapason serve` in a terminal and then launched the
    // desktop app — the app killed their server, then raced to spawn its
    // own, sometimes losing the race and hanging.
    //
    // New behaviour, by response shape:
    //   * 2xx /health        — healthy diapason serve. Attach to it; skip the
    //                          uv-sync + spawn dance entirely. Done.
    //   * 503                — server is up but engine isn't ready. Surface
    //                          an actionable message; don't kill (matches
    //                          our wait_for_diapason_health 503 contract).
    //   * any other status   — something else is listening on the port. Tell
    //                          the user via the error banner instead of
    //                          force-killing a foreign service.
    //   * Err (conn refused) — nothing is listening. Proceed to spawn.
    //
    // TODO(#455 follow-up): validate /health response body before attaching
    // so a multi-user host can't trivially spoof us. Also accept a port
    // override from config instead of hard-coding DIAPASON_PORT.
    {
        let health_url = format!("http://127.0.0.1:{}/health", DIAPASON_PORT);
        let client = constructeur_client_http(&health_url)
            .timeout(Duration::from_secs(2))
            .build()
            .unwrap();
        match client.get(&health_url).send().await {
            Ok(resp) if resp.status().is_success() => {
                // Confirm with a second probe — the first might have caught
                // a flickering server (engine half-loaded, dying mid-stop,
                // etc.) and we don't want to claim ready off a 2-second
                // snapshot. Small sleep between to give the server room.
                tokio::time::sleep(Duration::from_millis(500)).await;
                let confirm = client
                    .get(&health_url)
                    .send()
                    .await
                    .map(|r| r.status().is_success())
                    .unwrap_or(false);
                if !confirm {
                    // First probe was 2xx but the second wasn't — fall
                    // through to the spawn path. The server probably went
                    // away between probes.
                    // (No early return — we want to spawn our own.)
                } else {
                    // Attach to the existing healthy server. Mark every
                    // pre-spawn step done so the setup UI doesn't show a
                    // half-progress bar (model_ready / ollama_ready stay
                    // false otherwise because we skipped those steps).
                    let mut s = status.lock().await;
                    s.phase = "ready".into();
                    s.detail = format!(
                        "Connected to existing API server on port {}.",
                        DIAPASON_PORT,
                    );
                    s.server_ready = true;
                    s.model_ready = true;
                    s.ollama_ready = true;
                    return;
                }
            }
            Ok(resp) if resp.status() == reqwest::StatusCode::SERVICE_UNAVAILABLE => {
                let mut s = status.lock().await;
                s.error = Some(format!(
                    "An API server is already running on port {} but its \
                     inference engine isn't ready (HTTP 503). If this is your \
                     `diapason serve`, wait for it to finish loading and relaunch. \
                     Otherwise, stop that service or change the port.",
                    DIAPASON_PORT,
                ));
                return;
            }
            Ok(resp) => {
                // Something else (a different web server, a stale process,
                // a 4xx-returning instance) is on our port. Don't kill it —
                // give the user actionable info instead.
                let mut s = status.lock().await;
                s.error = Some(format!(
                    "Port {} is already in use by another service (it answered \
                     /health with HTTP {}). Stop that service or change the \
                     Diapason port, then relaunch.\n\nTo identify it:\n  {}",
                    DIAPASON_PORT,
                    resp.status(),
                    port_owner_hint(),
                ));
                return;
            }
            Err(_) => {
                // Nothing listening — proceed to the normal spawn path.
            }
        }
    }

    if let Err(err) = check_jarvis_port_available() {
        let mut s = status.lock().await;
        s.error = Some(err);
        return;
    }

    let root = project_root.as_ref().unwrap();

    let cargo_bin = resolve_bin("cargo");
    if !std::path::Path::new(&cargo_bin).exists() && cargo_bin == "cargo" {
        let mut s = status.lock().await;
        s.error = Some(format_missing_rust_toolchain());
        return;
    }

    // Install dependencies automatically (handles fresh clones).
    //
    // Previously we ran `uv sync` with both stdout AND stderr piped to
    // /dev/null and discarded the exit code (`let _ = …`). When `uv sync`
    // failed — Windows path issues, network problems, lockfile conflicts —
    // the user saw no error, the boot continued, `uv run diapason serve`
    // then ran in an under-provisioned venv, and the user waited the full
    // 600s health-check window before getting "Diapason server did not
    // become healthy in time" with no actionable detail (issue #331).
    //
    // Now: capture stderr, check the exit status, surface a useful error
    // to the user BEFORE the long server-start wait. The status detail
    // message also indicates this can take a couple of minutes on first
    // boot so users don't restart the app thinking it's stuck.
    {
        let mut s = status.lock().await;
        s.detail = "Installing dependencies (uv sync — may take 1-2 min on first boot)...".into();
    }
    let mut sync_cmd = tokio::process::Command::new(&uv_bin);
    sans_fenetre_async(&mut sync_cmd);
    // Le 28 août 2026, le diagnostic annonçait `dictation` tandis que cette
    // liste l'omettait. Une commande affichée qui ne reproduit pas le chemin
    // réel transforme chaque incident de démarrage en fausse piste.
    sync_cmd
        .args(DESKTOP_UV_SYNC_ARGS)
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::piped())
        .current_dir(root);
    // Avoid LD_LIBRARY_PATH leak when running inside an AppImage (#455).
    prepare_subprocess_for_appimage(&mut sync_cmd);
    add_cargo_bin_to_path(&mut sync_cmd);
    let sync_output = sync_cmd.output().await;
    match sync_output {
        Ok(out) if !out.status.success() => {
            let stderr = String::from_utf8_lossy(&out.stderr);
            let mut s = status.lock().await;
            s.error = Some(format_uv_sync_failure(root, out.status.code(), &stderr));
            return;
        }
        Err(e) => {
            let mut s = status.lock().await;
            s.error = Some(format_uv_sync_spawn_error(root, &uv_bin, &e.to_string()));
            return;
        }
        Ok(_) => {} // success — fall through
    }

    {
        let mut s = status.lock().await;
        s.detail = "Verifying Rust extension (diapason_rust)...".into();
    }
    if let Err(err) = verify_diapason_rust_extension(root, &uv_bin).await {
        let mut s = status.lock().await;
        s.error = Some(err);
        return;
    }

    {
        let mut s = status.lock().await;
        s.detail = format!("Starting API server from {}...", root.display());
    }

    let mut cmd = tokio::process::Command::new(&uv_bin);
    sans_fenetre_async(&mut cmd);
    // Le serveur mène son propre groupe de processus, pour qu'on puisse
    // l'arrêter EN ENTIER. Sans cela, « uv » seul recevait le signal et le
    // serveur Python survivait, orphelin, en tenant le port.
    #[cfg(unix)]
    cmd.process_group(0);
    let mut serve_argv: Vec<String> = vec![
        "run".into(),
        "diapason".into(),
        "serve".into(),
        "--port".into(),
        DIAPASON_PORT.to_string(),
    ];
    serve_argv.extend(plan.serve_args.iter().cloned());
    // If the Ollama pull fell back to a different tag than planned, serve the
    // tag that is actually present. boot_plan always emits `--model` followed
    // immediately by its value, so `i + 1` is in bounds.
    if let Some(m) = &serve_model_override {
        match serve_argv.iter().position(|a| a == "--model") {
            Some(i) if i + 1 < serve_argv.len() => serve_argv[i + 1] = m.clone(),
            _ => eprintln!(
                "Warning: resolved model {:?} could not be applied; \
                 '--model <value>' not found in serve args {:?}",
                m, serve_argv
            ),
        }
    }
    cmd.args(&serve_argv)
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::piped())
        .current_dir(root);
    // Avoid LD_LIBRARY_PATH leak when running inside an AppImage (#455) —
    // do this BEFORE cmd.env() calls below so our explicit cloud-key env
    // additions aren't accidentally stripped.
    prepare_subprocess_for_appimage(&mut cmd);

    // Inject cloud API keys from secure desktop storage.
    for (key, value) in read_cloud_keys() {
        cmd.env(&key, &value);
    }
    // Dernier contrôle, JUSTE avant de lancer.
    //
    // La sonde /health du début est séparée d'ici par `uv sync`, qui prend une
    // à deux minutes au premier démarrage. Un serveur lancé pendant ce
    // temps — par launchd, par un terminal, par une seconde copie de
    // l'application — n'était pas vu, et on en démarrait un deuxième. Vérifier
    // au plus près du lancement réduit la fenêtre à ce qu'elle peut être.
    if let Some(raison) = port_conflict(DIAPASON_PORT) {
        let health_url = format!("http://127.0.0.1:{}/health", DIAPASON_PORT);
        let sonde = constructeur_client_http(&health_url)
            .timeout(Duration::from_secs(3))
            .build()
            .ok();
        let sain = match sonde {
            Some(client) => client
                .get(&health_url)
                .send()
                .await
                .map(|r| r.status().is_success())
                .unwrap_or(false),
            None => false,
        };
        let mut s = status.lock().await;
        if sain {
            // Quelqu'un a fait le travail pendant qu'on préparait : on s'y
            // attache plutôt que de lui disputer le port.
            s.phase = "ready".into();
            s.detail = format!(
                "Connected to an API server that started on port {} while \
                 dependencies were installing.",
                DIAPASON_PORT,
            );
            s.server_ready = true;
            s.model_ready = true;
            s.ollama_ready = true;
        } else {
            // Occupé mais muet : exactement le zombie observé. Ne rien lancer
            // par-dessus, et nommer ce qu'on a mesuré.
            s.error = Some(format_port_unavailable(DIAPASON_PORT, &raison));
        }
        return;
    }

    let jarvis_child = cmd.spawn();

    match jarvis_child {
        Ok(mut child) => {
            // Start draining stderr immediately. If we wait until the
            // health check returns we risk filling the 4 KB Windows pipe
            // buffer during startup logging and hanging the child before
            // it can bind its HTTP port — exactly the symptom in #309.
            let stderr_handle = child.stderr.take();
            let mut mgr = backend.lock().await;
            let tail = mgr.diapason_stderr_tail.clone();
            mgr.diapason = Some(ChildHandle { child });
            drop(mgr);
            if let Some(stderr) = stderr_handle {
                spawn_diapason_stderr_drainer(stderr, tail);
            }
        }
        Err(e) => {
            let mut s = status.lock().await;
            s.error = Some(format!(
                "Could not start diapason server: {}. \
                 Make sure uv is installed (https://astral.sh/uv) and the Diapason repo is cloned at {}",
                e,
                root.display(),
            ));
            return;
        }
    }

    let server_url = format!("http://127.0.0.1:{}/health", DIAPASON_PORT);
    match wait_for_diapason_health(&server_url, Duration::from_secs(600), &backend).await {
        DiapasonStartResult::Ready => {}
        DiapasonStartResult::ServiceUnavailable(body) => {
            let mut s = status.lock().await;
            s.error = Some(format!(
                "Diapason server is running but the inference engine is not available \
                 (HTTP 503). This usually means the configured model couldn't be loaded.\n\n\
                 Check the server logs, or run 'uv run diapason serve --port {}{}' \
                 from {} to see the engine error.\n\n\
                 Server response:\n{}",
                DIAPASON_PORT,
                // Show the args actually passed (after `serve --port <port>`),
                // including any post-fallback `--model` override.
                match serve_argv.get(5..) {
                    Some(rest) if !rest.is_empty() => format!(" {}", rest.join(" ")),
                    _ => String::new(),
                },
                root.display(),
                body.trim(),
            ));
            return;
        }
        DiapasonStartResult::EarlyExit { code, stderr } => {
            // `None` here means the OS didn't expose an exit code — on
            // Unix that's a signal kill (SIGKILL/SIGSEGV/...), on Windows
            // it means the process was terminated externally (Task
            // Manager, parent-of-parent, AV). "unknown" covers both.
            let code_str = code
                .map(|c| c.to_string())
                .unwrap_or_else(|| "unknown".into());
            let mut s = status.lock().await;
            s.error = Some(if stderr.is_empty() {
                format!(
                    "Diapason server exited (code {}) before becoming ready.\n\n\
                     No stderr output. Check that:\n\
                     1. uv is installed ({})\n\
                     2. The Diapason repo is at {}\n\
                     3. 'uv sync' completes in that directory",
                    code_str,
                    uv_bin,
                    root.display(),
                )
            } else {
                format!(
                    "Diapason server exited (code {}) before becoming ready.\n\nStderr:\n{}",
                    code_str, stderr,
                )
            });
            return;
        }
        DiapasonStartResult::Timeout => {
            let stderr = read_diapason_stderr_tail(&backend).await;
            let mut s = status.lock().await;
            s.error = Some(if stderr.is_empty() {
                format!(
                    "Diapason server did not become ready within 10 minutes. Check that:\n\
                     1. uv is installed ({})\n\
                     2. The Diapason repo is at {}\n\
                     3. Run 'uv sync' in that directory",
                    uv_bin,
                    root.display(),
                )
            } else {
                format!(
                    "Diapason server did not become ready within 10 minutes.\n\nStderr:\n{}",
                    stderr,
                )
            });
            return;
        }
    }

    {
        let mut s = status.lock().await;
        s.server_ready = true;
        s.phase = "ready".into();
        s.detail = "All systems ready.".into();
    }

    // Phase 4: done. We intentionally do NOT auto-pull the rest of the
    // Qwen3.5 ladder here. The previous behavior walked every model that
    // "fit" in RAM (up to qwen3.5:122b ≈ 81 GB) and pulled each one in an
    // un-cancellable background task — so the app silently consumed tens of
    // gigabytes with no way to stop short of deleting it. The startup model
    // pulled in Phase 2 is enough to make the app fully usable; additional
    // models are now opt-in (Settings → "ollama pull <model>", or the
    // `pull_model` command invoked from the UI).
}

// ---------------------------------------------------------------------------
// Tauri commands
// ---------------------------------------------------------------------------

fn api_base() -> String {
    format!("http://127.0.0.1:{}", DIAPASON_PORT)
}

fn local_api_key_path() -> std::path::PathBuf {
    for name in ["DIAPASON_HOME", "OPENJARVIS_HOME", "JARVIS_HOME"] {
        if let Ok(root) = std::env::var(name) {
            if !root.trim().is_empty() {
                return std::path::PathBuf::from(root)
                    .join("auth")
                    .join("local_api_key");
            }
        }
    }
    if let Ok(root) = std::env::var("XDG_DATA_HOME") {
        if !root.trim().is_empty() {
            return std::path::PathBuf::from(root)
                .join("diapason")
                .join("auth")
                .join("local_api_key");
        }
    }
    std::path::PathBuf::from(home_dir())
        .join(".diapason")
        .join("auth")
        .join("local_api_key")
}

fn local_api_key() -> String {
    for name in ["DIAPASON_API_KEY", "OPENJARVIS_API_KEY", "JARVIS_API_KEY"] {
        if let Ok(value) = std::env::var(name) {
            if !value.trim().is_empty() {
                return value.trim().to_string();
            }
        }
    }
    let path = local_api_key_path();
    let generated = std::fs::read_to_string(&path)
        .unwrap_or_default()
        .trim()
        .to_string();
    if !generated.is_empty() {
        return generated;
    }
    let config_path = path
        .parent()
        .and_then(std::path::Path::parent)
        .map(|root| root.join("config.toml"));
    config_path
        .and_then(|config| std::fs::read_to_string(config).ok())
        .and_then(|text| text.parse::<toml_edit::DocumentMut>().ok())
        .and_then(|doc| {
            doc.get("server")?
                .get("auth")?
                .get("api_key")?
                .as_str()
                .map(str::to_owned)
        })
        .unwrap_or_default()
}

fn authenticated(request: reqwest::RequestBuilder) -> reqwest::RequestBuilder {
    let is_loopback = request
        .try_clone()
        .and_then(|clone| clone.build().ok())
        .map(|request| url_est_locale(request.url().as_str()))
        .unwrap_or(false);
    if !is_loopback {
        return request;
    }
    let key = local_api_key();
    if key.is_empty() {
        request
    } else {
        request.bearer_auth(key)
    }
}

#[tauri::command]
async fn get_setup_status(state: tauri::State<'_, SharedStatus>) -> Result<SetupStatus, String> {
    Ok(state.lock().await.clone())
}

#[tauri::command]
fn get_api_base() -> String {
    eprintln!("[desktop-api] API base requested");
    api_base()
}

#[tauri::command]
fn get_local_api_key() -> String {
    let key = local_api_key();
    eprintln!(
        "[desktop-api] local API credential requested: available={}",
        !key.is_empty()
    );
    key
}

/// Un seul démarrage de serveur à la fois.
///
/// Deux `boot_backend` concurrents passent tous deux la sonde /health — rien
/// n'écoute encore — puis lancent chacun leur serveur. Il suffisait d'ouvrir
/// l'application pendant qu'un démarrage manuel était en vol, ou de cliquer
/// deux fois sur Start. Le drapeau retombe à la fin du démarrage, quel qu'en
/// soit le résultat, pour qu'un échec ne condamne pas les tentatives suivantes.
static BOOT_IN_FLIGHT: std::sync::atomic::AtomicBool =
    std::sync::atomic::AtomicBool::new(false);

/// Remet le drapeau à false quoi qu'il arrive, y compris sur une panique.
///
/// Un `store(false)` posé APRÈS l'await ne s'exécute jamais si le démarrage
/// panique : le drapeau resterait à true et l'application refuserait tout
/// démarrage jusqu'à son redémarrage complet. Un garde qui se bloque lui-même
/// est pire que le doublon qu'il prévient — d'où `Drop`, que le déroulement de
/// pile exécute aussi.
struct BootGuard;

impl Drop for BootGuard {
    fn drop(&mut self) {
        BOOT_IN_FLIGHT.store(false, std::sync::atomic::Ordering::SeqCst);
    }
}

fn spawn_boot_backend(backend: SharedBackend, status: SharedStatus) -> bool {
    use std::sync::atomic::Ordering;
    if BOOT_IN_FLIGHT
        .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
        .is_err()
    {
        return false;
    }
    tauri::async_runtime::spawn(async move {
        let _garde = BootGuard;
        boot_backend(backend, status).await;
    });
    true
}

#[tauri::command]
async fn start_backend(
    backend: tauri::State<'_, SharedBackend>,
    status: tauri::State<'_, SharedStatus>,
) -> Result<(), String> {
    let b = backend.inner().clone();
    let s = status.inner().clone();
    if !spawn_boot_backend(b, s) {
        return Err("A server start is already in progress.".into());
    }
    Ok(())
}

#[tauri::command]
async fn stop_backend(backend: tauri::State<'_, SharedBackend>) -> Result<(), String> {
    backend.lock().await.stop_all().await;
    Ok(())
}

#[tauri::command]
async fn check_health(api_url: String) -> Result<serde_json::Value, String> {
    let url = format!(
        "{}/health",
        if api_url.is_empty() {
            api_base()
        } else {
            api_url
        }
    );
    let resp = client_http(&url)?
        .get(&url)
        .send()
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    resp.json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))
}

/// Fetch voice readiness through the native authenticated client.
///
/// WebSocket handshakes still happen in the WebView, but their readiness gate
/// should not depend on WebKit completing a CORS preflight during app startup.
#[tauri::command]
async fn get_voice_live_health() -> Result<serde_json::Value, String> {
    let url = format!("{}/v1/voice/live/health", api_base());
    let response = authenticated(
        client_http(&url)?
            .get(&url)
            .timeout(std::time::Duration::from_secs(5)),
    )
    .send()
    .await
    .map_err(|err| format!("Voice service connection failed: {err}"))?;
    let status = response.status();
    let body = response
        .text()
        .await
        .map_err(|err| format!("Voice service response failed: {err}"))?;
    if !status.is_success() {
        return Err(format!("Voice service health returned HTTP {status}"));
    }
    serde_json::from_str(&body).map_err(|err| format!("Voice service returned invalid JSON: {err}"))
}

#[tauri::command]
async fn fetch_energy(api_url: String) -> Result<serde_json::Value, String> {
    let base = if api_url.is_empty() {
        api_base()
    } else {
        api_url
    };
    let url = format!("{}/v1/telemetry/energy", base);
    let resp = authenticated(client_http(&url)?.get(&url))
        .send()
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    resp.json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))
}

#[tauri::command]
async fn fetch_telemetry(api_url: String) -> Result<serde_json::Value, String> {
    let base = if api_url.is_empty() {
        api_base()
    } else {
        api_url
    };
    let url = format!("{}/v1/telemetry/stats", base);
    let resp = authenticated(client_http(&url)?.get(&url))
        .send()
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    resp.json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))
}

#[tauri::command]
async fn fetch_traces(api_url: String, limit: u32) -> Result<serde_json::Value, String> {
    let base = if api_url.is_empty() {
        api_base()
    } else {
        api_url
    };
    let url = format!("{}/v1/traces?limit={}", base, limit);
    let resp = authenticated(client_http(&url)?.get(&url))
        .send()
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    resp.json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))
}

#[tauri::command]
async fn fetch_trace(api_url: String, trace_id: String) -> Result<serde_json::Value, String> {
    let base = if api_url.is_empty() {
        api_base()
    } else {
        api_url
    };
    let url = format!("{}/v1/traces/{}", base, trace_id);
    let resp = authenticated(client_http(&url)?.get(&url))
        .send()
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    resp.json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))
}

#[tauri::command]
async fn fetch_learning_stats(api_url: String) -> Result<serde_json::Value, String> {
    let base = if api_url.is_empty() {
        api_base()
    } else {
        api_url
    };
    let url = format!("{}/v1/learning/stats", base);
    let resp = authenticated(client_http(&url)?.get(&url))
        .send()
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    resp.json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))
}

#[tauri::command]
async fn fetch_learning_policy(api_url: String) -> Result<serde_json::Value, String> {
    let base = if api_url.is_empty() {
        api_base()
    } else {
        api_url
    };
    let url = format!("{}/v1/learning/policy", base);
    let resp = authenticated(client_http(&url)?.get(&url))
        .send()
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    resp.json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))
}

#[tauri::command]
async fn fetch_memory_stats(api_url: String) -> Result<serde_json::Value, String> {
    let base = if api_url.is_empty() {
        api_base()
    } else {
        api_url
    };
    let url = format!("{}/v1/memory/stats", base);
    let resp = authenticated(client_http(&url)?.get(&url))
        .send()
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    resp.json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))
}

#[tauri::command]
async fn search_memory(
    api_url: String,
    query: String,
    top_k: u32,
) -> Result<serde_json::Value, String> {
    let base = if api_url.is_empty() {
        api_base()
    } else {
        api_url
    };
    let url = format!("{}/v1/memory/search", base);
    let resp = authenticated(client_http(&url)?.post(&url))
        .json(&serde_json::json!({"query": query, "top_k": top_k}))
        .send()
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    resp.json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))
}

#[tauri::command]
async fn fetch_agents(api_url: String) -> Result<serde_json::Value, String> {
    let base = if api_url.is_empty() {
        api_base()
    } else {
        api_url
    };
    let url = format!("{}/v1/agents", base);
    let resp = authenticated(client_http(&url)?.get(&url))
        .send()
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    resp.json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))
}

#[tauri::command]
async fn fetch_models(api_url: String) -> Result<serde_json::Value, String> {
    let base = if api_url.is_empty() {
        api_base()
    } else {
        api_url
    };
    // Bounded: reqwest has no default request timeout, so a backend that
    // accepts the connection and then stalls used to hang this call forever,
    // and with it anything awaiting the model list.
    let url = format!("{}/v1/models", base);
    let resp = authenticated(
        client_http(&url)?
            .get(&url)
            .timeout(Duration::from_secs(15)),
    )
    .send()
    .await
    .map_err(|e| format!("Connection failed: {}", e))?;
    resp.json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))
}

#[tauri::command]
async fn run_diapason_command(args: Vec<String>) -> Result<String, String> {
    let uv_bin = resolve_bin("uv");

    let mut cmd_args = vec!["run".to_string(), "diapason".to_string()];
    cmd_args.extend(args.iter().cloned());

    let mut cmd = tokio::process::Command::new(&uv_bin);
    sans_fenetre_async(&mut cmd);
    cmd.args(&cmd_args);
    // Run from the project root so `uv run diapason` resolves the Diapason
    // project regardless of the app's launch cwd. In a packaged install the
    // cwd isn't the checkout, so without this `diapason` isn't found and the
    // backend never starts — the UI then shows "Failed to get response"
    // (see #531).
    if let Some(ref root) = find_project_root() {
        cmd.current_dir(root);
    }

    if args.first().map(|a| a.as_str() == "serve").unwrap_or(false) {
        // Cette voie lançait un serveur sans rien vérifier : ni sonde de port,
        // ni verrou, ni suivi du processus lancé. C'était un second lanceur, à
        // un `invoke` de distance de n'importe quelle partie de l'interface, et
        // il ne pouvait pas voir un serveur déjà en place. On la ferme au
        // profit de `start_backend`, qui interroge le noyau, refuse un
        // démarrage déjà en vol, et suit ce qu'il a lancé.
        return Err(
            "Use the start_backend command instead: it checks the port and \
             refuses to start a second server."
                .to_string(),
        );
    }

    // Commande courte (`stop`, `status`, …) : on l'attend et on rend sa sortie.
    let output = cmd
        .output()
        .await
        .map_err(|e| format!("Failed to launch diapason: {}", e))?;
    if output.status.success() {
        Ok(String::from_utf8_lossy(&output.stdout).to_string())
    } else {
        Err(String::from_utf8_lossy(&output.stderr).to_string())
    }
}

#[tauri::command]
async fn fetch_savings(api_url: String) -> Result<serde_json::Value, String> {
    let base = if api_url.is_empty() {
        api_base()
    } else {
        api_url
    };
    let url = format!("{}/v1/savings", base);
    let resp = authenticated(client_http(&url)?.get(&url))
        .send()
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    resp.json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))
}

/// Transcribe audio via the speech API endpoint.
#[tauri::command]
async fn transcribe_audio(
    api_url: String,
    audio_data: Vec<u8>,
    filename: String,
) -> Result<serde_json::Value, String> {
    let url = format!("{}/v1/speech/transcribe", api_url);
    let client = client_http(&url)?;

    let part = reqwest::multipart::Part::bytes(audio_data)
        .file_name(filename)
        .mime_str("audio/webm")
        .map_err(|e| format!("Failed to create multipart: {}", e))?;

    let form = reqwest::multipart::Form::new().part("file", part);

    let resp = authenticated(client.post(&url))
        .multipart(form)
        .send()
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    let status = resp.status();
    let body = resp
        .text()
        .await
        .map_err(|e| format!("Invalid response: {}", e))?;
    if !status.is_success() {
        let detail = serde_json::from_str::<serde_json::Value>(&body)
            .ok()
            .and_then(|value| {
                value
                    .get("detail")
                    .and_then(|detail| detail.as_str())
                    .map(str::to_string)
            })
            .filter(|detail| !detail.is_empty())
            .unwrap_or(body);
        return Err(format!(
            "Transcription failed ({}): {}",
            status.as_u16(),
            detail
        ));
    }
    serde_json::from_str(&body).map_err(|e| format!("Invalid response: {}", e))
}

/// Paste text into the frontmost OS application (macOS: pbcopy + Cmd+V).
/// Ouvre une URL http(s) dans le navigateur PAR DÉFAUT du système.
///
/// Le WebView bloque `window.open` : le bouton « Connect » des sources
/// OAuth cliquait dans le vide (constaté le 24 août 2026 — identifiants
/// enregistrés, fenêtre Google jamais ouverte). Une navigation OAuth doit
/// vivre dans le vrai navigateur de toute façon : cookies du compte,
/// gestionnaire de mots de passe, barre d'adresse lisible.
/// L'ouvreur d'URL du système — un par plateforme, et pas un de moins.
///
/// Cette fonction lançait `open` SANS AUCUN `cfg`, sur les trois systèmes.
/// Sur Windows, `open` n'existe pas : erreur propre, le frontend basculait
/// sur `window.open`. Sur Linux, en revanche, `/usr/bin/open` existe
/// souvent — c'est `openvt`, d'util-linux, qui ouvre une console virtuelle.
/// Le lancement RÉUSSISSAIT, rien ne s'ouvrait, la commande rendait `Ok`,
/// et le `catch` du frontend ne se déclenchait donc jamais. Le bouton
/// « Connecter » d'un connecteur OAuth ne faisait rien, sans un mot.
///
/// Un faux succès est pire qu'une erreur : l'erreur, elle, a un chemin de
/// repli (§100).
fn lancer_le_navigateur(url: &str) -> std::io::Result<std::process::Child> {
    #[cfg(target_os = "macos")]
    {
        std::process::Command::new("open").arg(url).spawn()
    }
    #[cfg(target_os = "windows")]
    {
        // `start` est une commande INTERNE de cmd.exe : il n'existe aucun
        // `start.exe` à lancer. Et son premier argument est le TITRE de la
        // fenêtre — sans la chaîne vide, une URL serait prise pour un titre
        // et rien ne s'ouvrirait. C'est le piège classique de cette ligne.
        let mut command = std::process::Command::new("cmd");
        sans_fenetre(&mut command)
            .args(["/C", "start", "", url])
            .spawn()
    }
    #[cfg(all(unix, not(target_os = "macos")))]
    {
        // `xdg-open`, et jamais `open` : voir la docstring ci-dessus.
        std::process::Command::new("xdg-open").arg(url).spawn()
    }
}

#[tauri::command]
fn open_external_url(url: String) -> Result<(), String> {
    if !(url.starts_with("http://") || url.starts_with("https://")) {
        return Err("URL non http(s) refusée".into());
    }
    lancer_le_navigateur(&url).map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
fn paste_to_frontmost(text: String) -> Result<String, String> {
    if text.is_empty() {
        return Err("No text to paste".into());
    }
    #[cfg(target_os = "macos")]
    {
        use std::io::Write;
        use std::process::{Command, Stdio};
        let mut child = Command::new("pbcopy")
            .stdin(Stdio::piped())
            .spawn()
            .map_err(|e| format!("pbcopy failed: {e}"))?;
        if let Some(mut stdin) = child.stdin.take() {
            stdin
                .write_all(text.as_bytes())
                .map_err(|e| format!("pbcopy write failed: {e}"))?;
        }
        let status = child.wait().map_err(|e| format!("pbcopy wait: {e}"))?;
        if !status.success() {
            return Err("pbcopy exited with error".into());
        }
        let out = Command::new("osascript")
            .args([
                "-e",
                "tell application \"System Events\" to keystroke \"v\" using command down",
            ])
            .output()
            .map_err(|e| format!("osascript failed: {e}"))?;
        if !out.status.success() {
            let err = String::from_utf8_lossy(&out.stderr);
            return Err(format!(
                "Paste failed (grant Accessibility to Diapason): {err}"
            ));
        }
        Ok(format!("Pasted {} chars", text.chars().count()))
    }
    #[cfg(not(target_os = "macos"))]
    {
        Err("paste_to_frontmost is currently implemented for macOS only".into())
    }
}

// ---------------------------------------------------------------------------
// Pointeur piloté par la main
// ---------------------------------------------------------------------------

#[derive(Debug, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
struct EvenementPointeur {
    #[serde(default)]
    active: bool,
    action: String,
    x: Option<f64>,
    y: Option<f64>,
    #[serde(default)]
    scroll_y: i32,
}

#[derive(Debug, PartialEq)]
enum CommandePointeur {
    Aucune,
    Deplacer { x: f64, y: f64 },
    Cliquer { x: f64, y: f64, double: bool },
    Defiler { lignes: i32 },
}

fn coordonnee_pointeur(nom: &str, valeur: Option<f64>) -> Result<f64, String> {
    let valeur = valeur.ok_or_else(|| format!("coordonnée {nom} absente"))?;
    if !valeur.is_finite() || !(0.0..=1.0).contains(&valeur) {
        return Err(format!("coordonnée {nom} hors de l'écran : {valeur}"));
    }
    Ok(valeur)
}

fn valider_evenement_pointeur(
    evenement: EvenementPointeur,
) -> Result<CommandePointeur, String> {
    if !evenement.active || evenement.action == "NONE" {
        return Ok(CommandePointeur::Aucune);
    }
    match evenement.action.as_str() {
        "MOVE" => Ok(CommandePointeur::Deplacer {
            x: coordonnee_pointeur("x", evenement.x)?,
            y: coordonnee_pointeur("y", evenement.y)?,
        }),
        "CLICK" | "DOUBLE_CLICK" => Ok(CommandePointeur::Cliquer {
            x: coordonnee_pointeur("x", evenement.x)?,
            y: coordonnee_pointeur("y", evenement.y)?,
            double: evenement.action == "DOUBLE_CLICK",
        }),
        "SCROLL" if evenement.scroll_y != 0 => Ok(CommandePointeur::Defiler {
            lignes: evenement.scroll_y.clamp(-10, 10),
        }),
        "SCROLL" => Ok(CommandePointeur::Aucune),
        autre => Err(format!("action de pointeur inconnue : {autre}")),
    }
}

#[cfg(target_os = "macos")]
fn appliquer_commande_pointeur(commande: CommandePointeur) -> Result<(), String> {
    use core_graphics::display::CGDisplay;
    use core_graphics::event::{
        CGEvent, CGEventTapLocation, CGEventType, CGMouseButton, EventField, ScrollEventUnit,
    };
    use core_graphics::event_source::{CGEventSource, CGEventSourceStateID};
    use core_graphics::geometry::CGPoint;

    #[link(name = "ApplicationServices", kind = "framework")]
    extern "C" {
        fn CGPreflightPostEventAccess() -> bool;
        fn CGRequestPostEventAccess() -> bool;
    }

    if commande == CommandePointeur::Aucune {
        return Ok(());
    }
    if !unsafe { CGPreflightPostEventAccess() } {
        // Cette fonction ouvre la vraie demande macOS. Rendre Ok ici serait
        // promettre un mouvement que le système vient précisément de refuser.
        unsafe { CGRequestPostEventAccess() };
        return Err(
            "Autorise Diapason dans Réglages Système → Confidentialité et sécurité → Accessibilité, puis réactive le mode pointeur."
                .into(),
        );
    }

    let source = || {
        CGEventSource::new(CGEventSourceStateID::HIDSystemState)
            .map_err(|_| "Core Graphics n'a pas créé la source du pointeur".to_string())
    };
    let position = |x: f64, y: f64| {
        let cadre = CGDisplay::main().bounds();
        CGPoint::new(
            cadre.origin.x + x * cadre.size.width,
            cadre.origin.y + y * cadre.size.height,
        )
    };
    let poster_souris = |kind: CGEventType, point: CGPoint, etat_clic: i64| {
        let evenement = CGEvent::new_mouse_event(source()?, kind, point, CGMouseButton::Left)
            .map_err(|_| "Core Graphics n'a pas créé l'événement de souris".to_string())?;
        if etat_clic > 0 {
            evenement.set_integer_value_field(EventField::MOUSE_EVENT_CLICK_STATE, etat_clic);
        }
        evenement.post(CGEventTapLocation::HID);
        Ok::<(), String>(())
    };

    match commande {
        CommandePointeur::Aucune => Ok(()),
        CommandePointeur::Deplacer { x, y } => {
            poster_souris(CGEventType::MouseMoved, position(x, y), 0)
        }
        CommandePointeur::Cliquer { x, y, double } => {
            let point = position(x, y);
            let etat = if double { 2 } else { 1 };
            poster_souris(CGEventType::MouseMoved, point, 0)?;
            poster_souris(CGEventType::LeftMouseDown, point, etat)?;
            poster_souris(CGEventType::LeftMouseUp, point, etat)
        }
        CommandePointeur::Defiler { lignes } => {
            let evenement = CGEvent::new_scroll_event(
                source()?,
                ScrollEventUnit::LINE,
                1,
                lignes,
                0,
                0,
            )
            .map_err(|_| "Core Graphics n'a pas créé le défilement".to_string())?;
            evenement.post(CGEventTapLocation::HID);
            Ok(())
        }
    }
}

#[cfg(not(target_os = "macos"))]
fn appliquer_commande_pointeur(commande: CommandePointeur) -> Result<(), String> {
    if commande == CommandePointeur::Aucune {
        Ok(())
    } else {
        Err("Le pointeur par la main est disponible sur macOS dans cette première version.".into())
    }
}

#[tauri::command]
fn apply_pointer_event(event: EvenementPointeur) -> Result<(), String> {
    appliquer_commande_pointeur(valider_evenement_pointeur(event)?)
}

// ---------------------------------------------------------------------------
// Cloud API key management
// ---------------------------------------------------------------------------

const SECURE_KEY_SERVICE: &str = "Diapason Cloud Keys";
const MANAGED_CLOUD_KEY_NAMES: &[&str] = &[
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "OPENROUTER_API_KEY",
    "MINIMAX_API_KEY",
    "TAVILY_API_KEY",
];

/// Legacy path used by older desktop builds. New saves never write here.
fn legacy_cloud_keys_path() -> std::path::PathBuf {
    let home = home_dir();
    std::path::PathBuf::from(home)
        .join(".diapason")
        .join("cloud-keys.env")
}

fn validate_cloud_key_name(key_name: &str) -> Result<(), String> {
    let valid = !key_name.is_empty()
        && key_name.len() <= 128
        && key_name.ends_with("_API_KEY")
        && key_name
            .chars()
            .all(|ch| ch.is_ascii_uppercase() || ch.is_ascii_digit() || ch == '_');
    if valid {
        Ok(())
    } else {
        Err(format!("Invalid API key name: {}", key_name))
    }
}

fn engine_api_key_name(engine: &str) -> String {
    let normalized: String = engine
        .chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() {
                ch.to_ascii_uppercase()
            } else {
                '_'
            }
        })
        .collect();
    let trimmed = normalized.trim_matches('_');
    let engine_name = if trimmed.is_empty() {
        CUSTOM_FALLBACK_ENGINE.to_ascii_uppercase()
    } else {
        trimmed.to_string()
    };
    format!("{}_API_KEY", engine_name)
}

fn managed_cloud_key_names() -> Vec<String> {
    let mut names: Vec<String> = MANAGED_CLOUD_KEY_NAMES
        .iter()
        .map(|name| (*name).to_string())
        .collect();

    let cfg = read_inference_config();
    if matches!(&cfg.kind, SourceKind::Custom) {
        let engine = cfg
            .engine
            .unwrap_or_else(|| CUSTOM_FALLBACK_ENGINE.to_string());
        let key_name = engine_api_key_name(&engine);
        if validate_cloud_key_name(&key_name).is_ok() {
            names.push(key_name);
        }
    }

    names.sort();
    names.dedup();
    names
}

fn secure_store_get(key_name: &str) -> Result<Option<String>, String> {
    validate_cloud_key_name(key_name)?;
    let entry = keyring::Entry::new(SECURE_KEY_SERVICE, key_name).map_err(|err| {
        format!(
            "Failed to open secure key storage for {}: {}",
            key_name, err
        )
    })?;
    match entry.get_password() {
        Ok(value) => Ok(Some(value)),
        Err(keyring::Error::NoEntry) => Ok(None),
        Err(err) => Err(format!(
            "Failed to read {} from secure key storage: {}",
            key_name, err
        )),
    }
}

fn secure_store_set(key_name: &str, key_value: &str) -> Result<(), String> {
    validate_cloud_key_name(key_name)?;
    let entry = keyring::Entry::new(SECURE_KEY_SERVICE, key_name).map_err(|err| {
        format!(
            "Failed to open secure key storage for {}: {}",
            key_name, err
        )
    })?;
    if key_value.is_empty() {
        return match entry.delete_credential() {
            Ok(()) => Ok(()),
            Err(keyring::Error::NoEntry) => Ok(()),
            Err(err) => Err(format!(
                "Failed to remove {} from secure key storage: {}",
                key_name, err
            )),
        };
    }
    entry
        .set_password(key_value)
        .map_err(|err| format!("Failed to save {} in secure key storage: {}", key_name, err))
}

fn read_legacy_cloud_keys() -> Vec<(String, String)> {
    let path = legacy_cloud_keys_path();
    let mut keys = Vec::new();
    if let Ok(contents) = std::fs::read_to_string(&path) {
        for line in contents.lines() {
            let line = line.trim();
            if line.is_empty() || line.starts_with('#') {
                continue;
            }
            if let Some((k, v)) = line.split_once('=') {
                keys.push((k.trim().to_string(), v.trim().to_string()));
            }
        }
    }
    keys
}

fn migrate_legacy_cloud_keys() {
    let path = legacy_cloud_keys_path();
    if !path.exists() {
        return;
    }

    let legacy_keys = read_legacy_cloud_keys();
    if legacy_keys.is_empty() {
        let _ = std::fs::remove_file(&path);
        return;
    }

    let mut migrated_all = true;
    for (key, value) in legacy_keys {
        if value.is_empty() {
            continue;
        }
        if secure_store_set(&key, &value).is_err() {
            migrated_all = false;
        }
    }

    if migrated_all {
        let _ = std::fs::remove_file(path);
    }
}

/// Read cloud keys from secure desktop storage and return key=value pairs.
fn read_cloud_keys() -> Vec<(String, String)> {
    migrate_legacy_cloud_keys();
    managed_cloud_key_names()
        .into_iter()
        .filter_map(|key| match secure_store_get(&key) {
            Ok(Some(value)) if !value.is_empty() => Some((key, value)),
            _ => None,
        })
        .collect()
}

async fn reload_cloud_keys(keys: Vec<(String, String)>) {
    let reload_url = format!("http://127.0.0.1:{}/v1/cloud/reload", DIAPASON_PORT);
    let key_map: serde_json::Map<String, serde_json::Value> = keys
        .into_iter()
        .map(|(key, value)| (key, serde_json::Value::String(value)))
        .collect();
    if let Ok(client) = client_http(&reload_url) {
        let _ = authenticated(client.post(&reload_url))
            .json(&serde_json::json!({ "keys": key_map }))
            .timeout(std::time::Duration::from_secs(10))
            .send()
            .await;
    }
}

/// Save a single cloud API key to secure desktop storage.
#[tauri::command]
async fn save_cloud_key(key_name: String, key_value: String) -> Result<(), String> {
    let key_value = key_value.trim().to_string();
    secure_store_set(&key_name, &key_value)?;

    // Tell the running server to hot-reload its cloud engine so the user
    // doesn't need to restart the app after entering an API key.
    reload_cloud_keys(vec![(key_name, key_value)]).await;

    Ok(())
}

/// Get which cloud providers have keys configured (without exposing values).
#[tauri::command]
async fn get_cloud_key_status() -> Result<serde_json::Value, String> {
    migrate_legacy_cloud_keys();
    let status: Vec<serde_json::Value> = managed_cloud_key_names()
        .into_iter()
        .map(|key| {
            let set = matches!(secure_store_get(&key), Ok(Some(value)) if !value.is_empty());
            serde_json::json!({ "key": key, "set": set })
        })
        .collect();
    Ok(serde_json::json!(status))
}

/// Return the current inference-source config for the Settings UI.
#[tauri::command]
async fn get_inference_source() -> Result<InferenceConfig, String> {
    Ok(read_inference_config())
}

/// Persist the chosen inference source. `host` is normalized to a bare base
/// URL. For custom endpoints, an optional API key is stored in secure desktop
/// storage under `<ENGINE>_API_KEY`. Applies on next app launch.
#[tauri::command]
async fn set_inference_source(
    kind: String,
    model: Option<String>,
    host: Option<String>,
    engine: Option<String>,
    api_key: Option<String>,
) -> Result<(), String> {
    let kind = match kind.as_str() {
        "ollama" => SourceKind::Ollama,
        "custom" => SourceKind::Custom,
        other => return Err(format!("Unknown inference source kind: {:?}", other)),
    };
    let cfg = InferenceConfig {
        kind,
        model: model.filter(|m| !m.is_empty()),
        host: host.map(|h| normalize_host(&h)).filter(|h| !h.is_empty()),
        engine: engine.filter(|e| !e.is_empty()),
    };
    if let SourceKind::Custom = cfg.kind {
        if cfg.host.is_none() {
            return Err("A server URL is required for a custom endpoint.".into());
        }
        if cfg.model.as_deref().unwrap_or("").is_empty() {
            return Err("A model name is required for a custom endpoint.".into());
        }
        if let Some(key) = api_key.filter(|k| !k.is_empty()) {
            let engine = cfg
                .engine
                .clone()
                .unwrap_or_else(|| CUSTOM_FALLBACK_ENGINE.to_string());
            let key_name = engine_api_key_name(&engine);
            // Save the key before persisting the config: if the key can't be
            // written, surface it and DON'T record a custom source whose
            // credential is missing (which would fail confusingly at runtime).
            save_cloud_key(key_name, key)
                .await
                .map_err(|e| format!("Could not store the API key: {}", e))?;
        }
    }
    write_inference_config(&cfg)
}

/// Pull a model via Ollama (called from frontend download button).
#[tauri::command]
async fn pull_ollama_model(model_name: String) -> Result<serde_json::Value, String> {
    pull_model(&model_name)
        .await
        .map_err(|e| format!("Failed to pull {}: {}", model_name, e))?;
    Ok(serde_json::json!({"status": "ok", "model": model_name}))
}

/// Delete a model from Ollama.
#[tauri::command]
async fn delete_ollama_model(model_name: String) -> Result<serde_json::Value, String> {
    let url = format!("http://127.0.0.1:{}/api/delete", OLLAMA_PORT);
    let client = constructeur_client_http(&url)
        .timeout(Duration::from_secs(30))
        .build()
        .map_err(|e| e.to_string())?;
    let resp = client
        .delete(&url)
        .json(&serde_json::json!({"name": model_name}))
        .send()
        .await
        .map_err(|e| format!("Delete failed: {}", e))?;
    if !resp.status().is_success() {
        return Err(format!("Delete returned status {}", resp.status()));
    }
    Ok(serde_json::json!({"status": "deleted", "model": model_name}))
}

// ---------------------------------------------------------------------------
// Inference-source selection (~/.diapason/inference.json)
// ---------------------------------------------------------------------------

#[derive(serde::Serialize, serde::Deserialize, Clone, Copy, Debug, Default, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
enum SourceKind {
    #[default]
    Ollama,
    Custom,
}

#[derive(serde::Serialize, serde::Deserialize, Clone, Debug, Default)]
struct InferenceConfig {
    #[serde(default)]
    kind: SourceKind,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    model: Option<String>,
    /// Bare base URL (no trailing `/v1`), custom only.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    host: Option<String>,
    /// OpenAI-compatible engine key (e.g. "lmstudio"), custom only.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    engine: Option<String>,
}

/// Path to the inference-source config (~/.diapason/inference.json).
fn inference_config_path() -> std::path::PathBuf {
    std::path::PathBuf::from(home_dir())
        .join(".diapason")
        .join("inference.json")
}

/// Parse config text. Any error (missing/garbage) yields the Ollama default —
/// a broken file must never strand the user with no working inference source.
fn parse_inference_config(text: &str) -> InferenceConfig {
    serde_json::from_str::<InferenceConfig>(text).unwrap_or_default()
}

/// Read the on-disk inference config, or the Ollama default if absent.
fn read_inference_config() -> InferenceConfig {
    match std::fs::read_to_string(inference_config_path()) {
        Ok(text) => parse_inference_config(&text),
        Err(_) => InferenceConfig::default(),
    }
}

/// Write the inference config to disk (pretty JSON).
fn write_inference_config(cfg: &InferenceConfig) -> Result<(), String> {
    let path = inference_config_path();
    if let Some(parent) = path.parent() {
        let _ = std::fs::create_dir_all(parent);
    }
    let json = serde_json::to_string_pretty(cfg).map_err(|e| e.to_string())?;
    std::fs::write(&path, json + "\n")
        .map_err(|e| format!("Failed to save inference config: {}", e))
}

/// Upsert `[engine.<engine>] host = "<host>"` into an existing config.toml
/// string, preserving all other content/formatting. Pure: string in, string out.
fn upsert_engine_host(existing: &str, engine: &str, host: &str) -> Result<String, String> {
    let mut doc = existing
        .parse::<toml_edit::DocumentMut>()
        .map_err(|e| format!("Invalid config.toml: {}", e))?;
    doc["engine"][engine]["host"] = toml_edit::value(host);
    Ok(doc.to_string())
}

/// Write the custom-endpoint host into ~/.diapason/config.toml so
/// `diapason serve` (which reads that file via load_config) points at it.
/// The `<ENGINE>_HOST` env var is unreliable — it is shadowed by the engine's
/// non-empty default host in the Python layer — so config.toml is the override.
fn set_engine_host_in_config(engine: &str, host: &str) -> Result<(), String> {
    let path = std::path::PathBuf::from(home_dir())
        .join(".diapason")
        .join("config.toml");
    if let Some(parent) = path.parent() {
        let _ = std::fs::create_dir_all(parent);
    }
    let existing = std::fs::read_to_string(&path).unwrap_or_default();
    let updated = upsert_engine_host(&existing, engine, host)?;
    std::fs::write(&path, updated).map_err(|e| format!("Failed to write config.toml: {}", e))
}

/// Normalize a user-entered server URL to a bare base host: trim whitespace,
/// drop a trailing `/v1` segment (the engine re-appends its own api prefix),
/// then drop any trailing slash.
fn normalize_host(raw: &str) -> String {
    let s = raw.trim().trim_end_matches('/');
    let s = s.strip_suffix("/v1").unwrap_or(s);
    s.trim_end_matches('/').to_string()
}

/// Check speech backend health.
#[tauri::command]
async fn speech_health(api_url: String) -> Result<serde_json::Value, String> {
    let url = format!("{}/v1/speech/health", api_url);
    let resp = authenticated(client_http(&url)?.get(&url))
        .send()
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    let body: serde_json::Value = resp
        .json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))?;
    Ok(body)
}

// ---------------------------------------------------------------------------
// Native macOS overlay — NSPanel + WKWebView, entirely bypassing Tauri's
// window management so we get proper always-on-top, transparency, non-
// activating panel behaviour and cross-Space support.
// ---------------------------------------------------------------------------

#[cfg(target_os = "macos")]
mod native_overlay {
    use objc::declare::ClassDecl;
    use objc::runtime::{Class, Object, Sel, BOOL, NO, YES};
    use objc::{class, msg_send, sel, sel_impl};
    use std::sync::atomic::{AtomicUsize, Ordering};

    /// Raw pointer to the NSPanel, stored as usize for atomicity.
    static PANEL_PTR: AtomicUsize = AtomicUsize::new(0);
    /// Raw pointer to the WKWebView inside the panel.
    static WEBVIEW_PTR: AtomicUsize = AtomicUsize::new(0);
    /// Raw pointer to the previously-frontmost NSRunningApplication.
    static PREV_APP: AtomicUsize = AtomicUsize::new(0);

    // CoreGraphics geometry types expected by AppKit.
    #[repr(C)]
    #[derive(Copy, Clone)]
    struct CGPoint {
        x: f64,
        y: f64,
    }
    #[repr(C)]
    #[derive(Copy, Clone)]
    struct CGSize {
        width: f64,
        height: f64,
    }
    #[repr(C)]
    #[derive(Copy, Clone)]
    struct CGRect {
        origin: CGPoint,
        size: CGSize,
    }

    /// Create an autoreleased NSString from a Rust &str.
    unsafe fn nsstring(s: &str) -> *mut Object {
        let obj: *mut Object = msg_send![class!(NSString), alloc];
        msg_send![obj,
            initWithBytes: s.as_ptr()
            length: s.len()
            encoding: 4usize  // NSUTF8StringEncoding
        ]
    }

    // ------------------------------------------------------------------
    // Conversation persistence
    // ------------------------------------------------------------------

    fn conversation_path() -> std::path::PathBuf {
        std::path::PathBuf::from(super::home_dir())
            .join(".diapason")
            .join("overlay-conversation.json")
    }

    pub fn load_conversation() -> String {
        std::fs::read_to_string(conversation_path()).unwrap_or_else(|_| "[]".into())
    }

    /// Read cloud API keys and return a JSON array of model IDs
    /// whose provider has a key configured.
    fn cloud_models_json() -> String {
        let keys = super::read_cloud_keys();
        let mut models: Vec<&str> = Vec::new();
        for (name, value) in &keys {
            if value.is_empty() {
                continue;
            }
            match name.as_str() {
                "OPENAI_API_KEY" => models.extend(["gpt-4o", "gpt-4o-mini"]),
                "ANTHROPIC_API_KEY" => {
                    models.extend(["claude-sonnet-4-20250514", "claude-haiku-4-20250414"])
                }
                "GEMINI_API_KEY" | "GOOGLE_API_KEY" => {
                    models.extend(["gemini-2.5-flash", "gemini-2.5-pro"])
                }
                _ => {}
            }
        }
        serde_json::to_string(&models).unwrap_or_else(|_| "[]".into())
    }

    fn save_conversation(json: &str) {
        let path = conversation_path();
        if let Some(parent) = path.parent() {
            let _ = std::fs::create_dir_all(parent);
        }
        let _ = std::fs::write(&path, json);
    }

    /// Apply every transparency trick to the WKWebView.
    /// Called once at creation and again after the page finishes loading.
    unsafe fn force_transparent(wv: *mut Object) {
        let clear: *mut Object = msg_send![class!(NSColor), clearColor];
        let _: () = msg_send![wv, _setDrawsBackground: NO];
        let no_num: *mut Object = msg_send![class!(NSNumber), numberWithBool: NO];
        let _: () = msg_send![wv, setValue: no_num forKey: nsstring("drawsBackground")];
        let _: () = msg_send![wv, setUnderPageBackgroundColor: clear];
        // Also inject CSS to nuke any remaining background
        let js = nsstring(
            "document.documentElement.style.background='transparent';\
             document.body.style.background='transparent';",
        );
        let nil: *mut Object = std::ptr::null_mut();
        let _: () = msg_send![wv, evaluateJavaScript: js completionHandler: nil];
    }

    // ------------------------------------------------------------------
    // Public API (must be called on the main thread)
    // ------------------------------------------------------------------

    /// Build the native overlay panel.  Call once during app setup.
    pub unsafe fn create(html: &str, api_port: u16) {
        // --- Custom NSPanel subclass that accepts keyboard input ------
        if Class::get("JarvisOverlayPanel").is_none() {
            let sup = Class::get("NSPanel").unwrap();
            let mut decl = ClassDecl::new("JarvisOverlayPanel", sup).unwrap();
            extern "C" fn yes(_: &Object, _: Sel) -> BOOL {
                YES
            }
            decl.add_method(
                sel!(canBecomeKeyWindow),
                yes as extern "C" fn(&Object, Sel) -> BOOL,
            );
            decl.register();
        }

        // --- WKNavigationDelegate — re-apply transparency after load --
        if Class::get("JarvisOverlayNavDelegate").is_none() {
            let sup = Class::get("NSObject").unwrap();
            let mut decl = ClassDecl::new("JarvisOverlayNavDelegate", sup).unwrap();
            extern "C" fn did_finish(_: &Object, _: Sel, wv: *mut Object, _nav: *mut Object) {
                unsafe {
                    force_transparent(wv);
                }
            }
            decl.add_method(
                sel!(webView:didFinishNavigation:),
                did_finish as extern "C" fn(&Object, Sel, *mut Object, *mut Object),
            );
            decl.register();
        }

        // --- WKScriptMessageHandler so JS can call hide() ------------
        if Class::get("JarvisOverlayMsgHandler").is_none() {
            let sup = Class::get("NSObject").unwrap();
            let mut decl = ClassDecl::new("JarvisOverlayMsgHandler", sup).unwrap();
            extern "C" fn on_msg(_: &Object, _: Sel, _ctrl: *mut Object, msg: *mut Object) {
                unsafe {
                    let body: *mut Object = msg_send![msg, body];
                    if body.is_null() {
                        return;
                    }
                    let c: *const std::os::raw::c_char = msg_send![body, UTF8String];
                    if c.is_null() {
                        return;
                    }
                    if let Ok(s) = std::ffi::CStr::from_ptr(c).to_str() {
                        if s == "hide" {
                            hide();
                        } else if let Some(json) = s.strip_prefix("save:") {
                            save_conversation(json);
                        } else if let Some(coords) = s.strip_prefix("drag:") {
                            drag(coords);
                        }
                    }
                }
            }
            decl.add_method(
                sel!(userContentController:didReceiveScriptMessage:),
                on_msg as extern "C" fn(&Object, Sel, *mut Object, *mut Object),
            );
            decl.register();
        }

        // --- Create the NSPanel --------------------------------------
        let frame = CGRect {
            origin: CGPoint { x: 0.0, y: 0.0 },
            size: CGSize {
                width: 560.0,
                height: 400.0,
            },
        };
        // NSWindowStyleMaskNonactivatingPanel = 1 << 7
        let style: u64 = 1 << 7;

        let cls = Class::get("JarvisOverlayPanel").unwrap();
        let panel: *mut Object = msg_send![cls, alloc];
        let panel: *mut Object = msg_send![panel,
            initWithContentRect: frame
            styleMask: style
            backing: 2u64       // NSBackingStoreBuffered
            defer: NO
        ];

        // Window level — NSFloatingWindowLevel (3).
        let _: () = msg_send![panel, setLevel: 3_i64];
        // canJoinAllSpaces (1) | fullScreenAuxiliary (1<<8)
        let _: () = msg_send![panel, setCollectionBehavior: 257_u64];
        let _: () = msg_send![panel, setHidesOnDeactivate: NO];
        let _: () = msg_send![panel, setOpaque: NO];
        let _: () = msg_send![panel, setHasShadow: NO];
        let _: () = msg_send![panel, setMovableByWindowBackground: YES];

        let clear: *mut Object = msg_send![class!(NSColor), clearColor];
        let _: () = msg_send![panel, setBackgroundColor: clear];
        let _: () = msg_send![panel, center];

        // --- WKWebView -----------------------------------------------
        let cfg: *mut Object = msg_send![class!(WKWebViewConfiguration), alloc];
        let cfg: *mut Object = msg_send![cfg, init];

        // Attach message handler ("overlay" channel)
        let hcls = Class::get("JarvisOverlayMsgHandler").unwrap();
        let handler: *mut Object = msg_send![hcls, alloc];
        let handler: *mut Object = msg_send![handler, init];
        let uc: *mut Object = msg_send![cfg, userContentController];
        let _: () = msg_send![uc,
            addScriptMessageHandler: handler
            name: nsstring("overlay")
        ];

        let wv: *mut Object = msg_send![class!(WKWebView), alloc];
        let wv: *mut Object = msg_send![wv,
            initWithFrame: frame
            configuration: cfg
        ];

        // ---- Make the webview fully transparent ----
        force_transparent(wv);

        // Set navigation delegate so we re-apply after page loads
        let nav_cls = Class::get("JarvisOverlayNavDelegate").unwrap();
        let nav_del: *mut Object = msg_send![nav_cls, alloc];
        let nav_del: *mut Object = msg_send![nav_del, init];
        let _: () = msg_send![wv, setNavigationDelegate: nav_del];

        let _: () = msg_send![panel, setContentView: wv];
        WEBVIEW_PTR.store(wv as usize, Ordering::SeqCst);

        // Inject saved conversation into the HTML template, then load it.
        // Use the API server as the base URL so fetch() is same-origin.
        // Escape "</" so the JSON can't prematurely close the <script> tag.
        // ("\/" is valid JSON — resolves back to "/" when parsed.)
        let saved = load_conversation().replace("</", "<\\/");
        let cloud = cloud_models_json();
        let filled = html
            .replace("__SAVED_MESSAGES__", &saved)
            .replace("__CLOUD_MODELS__", &cloud);
        let base_str = nsstring(&format!("http://127.0.0.1:{}", api_port));
        let base_url: *mut Object = msg_send![class!(NSURL), URLWithString: base_str];
        let _: () = msg_send![wv,
            loadHTMLString: nsstring(&filled)
            baseURL: base_url
        ];

        PANEL_PTR.store(panel as usize, Ordering::SeqCst);
    }

    pub unsafe fn toggle() {
        let ptr = PANEL_PTR.load(Ordering::SeqCst);
        if ptr == 0 {
            return;
        }
        let panel = ptr as *mut Object;
        let vis: BOOL = msg_send![panel, isVisible];
        if vis != NO {
            hide();
        } else {
            show();
        }
    }

    pub unsafe fn show() {
        let ptr = PANEL_PTR.load(Ordering::SeqCst);
        if ptr == 0 {
            return;
        }
        let panel = ptr as *mut Object;

        // Re-apply transparency every time (the webview can reset it)
        let wv_ptr = WEBVIEW_PTR.load(Ordering::SeqCst);
        if wv_ptr != 0 {
            force_transparent(wv_ptr as *mut Object);
        }

        // Remember the currently-frontmost app so we can restore it.
        let ws: *mut Object = msg_send![class!(NSWorkspace), sharedWorkspace];
        let front: *mut Object = msg_send![ws, frontmostApplication];
        if !front.is_null() {
            let _: () = msg_send![front, retain];
            let old = PREV_APP.swap(front as usize, Ordering::SeqCst);
            if old != 0 {
                let _: () = msg_send![(old as *mut Object), release];
            }
        }

        // Activate our process so the panel receives keyboard input.
        let app: *mut Object = msg_send![class!(NSApplication), sharedApplication];
        let _: () = msg_send![app, activateIgnoringOtherApps: YES];
        let nil: *mut Object = std::ptr::null_mut();
        let _: () = msg_send![panel, makeKeyAndOrderFront: nil];

        // Focus the text field inside the webview.
        let wv: *mut Object = msg_send![panel, contentView];
        let js = nsstring("document.getElementById('input').focus()");
        let _: () = msg_send![wv, evaluateJavaScript: js completionHandler: nil];
    }

    /// Move the panel by a screen-space delta (called from JS drag handler).
    unsafe fn drag(coords: &str) {
        let ptr = PANEL_PTR.load(Ordering::SeqCst);
        if ptr == 0 {
            return;
        }
        let panel = ptr as *mut Object;
        let Some((dxs, dys)) = coords.split_once(',') else {
            return;
        };
        let Ok(dx) = dxs.parse::<f64>() else { return };
        let Ok(dy) = dys.parse::<f64>() else { return };
        // NSWindow frame origin is bottom-left; screen Y increases upward,
        // but mouse screenY increases downward, so invert dy.
        let frame: CGRect = msg_send![panel, frame];
        let origin = CGPoint {
            x: frame.origin.x + dx,
            y: frame.origin.y - dy,
        };
        let _: () = msg_send![panel, setFrameOrigin: origin];
    }

    pub unsafe fn hide() {
        let ptr = PANEL_PTR.load(Ordering::SeqCst);
        if ptr == 0 {
            return;
        }
        let panel = ptr as *mut Object;
        let nil: *mut Object = std::ptr::null_mut();
        let _: () = msg_send![panel, orderOut: nil];

        // Give focus back to whatever app was frontmost before.
        let prev = PREV_APP.swap(0, Ordering::SeqCst);
        if prev != 0 {
            let prev_app = prev as *mut Object;
            let _: BOOL = msg_send![prev_app, activateWithOptions: 2_u64];
            let _: () = msg_send![prev_app, release];
        }
    }
}

/// Dispatch a closure onto the main thread via GCD.
#[cfg(target_os = "macos")]
fn on_main_thread(f: impl FnOnce() + Send + 'static) {
    dispatch::Queue::main().exec_async(f);
}

// ---------------------------------------------------------------------------
// Overlay Tauri commands (thin wrappers that dispatch to the main thread)
// ---------------------------------------------------------------------------

#[tauri::command]
async fn get_overlay_conversation() -> Result<String, String> {
    #[cfg(target_os = "macos")]
    {
        Ok(native_overlay::load_conversation())
    }
    #[cfg(not(target_os = "macos"))]
    Ok("[]".into())
}

/// La superposition n'existe que sur macOS — et le dire vaut mieux que
/// rendre `Ok`.
///
/// Ces deux commandes rendaient `Ok(())` sur un corps VIDE partout ailleurs :
/// l'appelant concluait que la superposition avait basculé, alors qu'aucune
/// n'existait. C'est le §5 — ne jamais faire semblant — et le §100 — jamais
/// de faux SUCCESS. Le motif correct est déjà dans ce fichier, deux cents
/// lignes plus haut : `paste_to_frontmost` répond « implemented for macOS
/// only » plutôt que de ne rien faire en silence.
///
/// La superposition est un NSPanel non activant construit sur trois classes
/// Objective-C déclarées à l'exécution. Ce n'est pas une fonction qu'on
/// porte en quelques lignes : sur Windows et Linux, elle n'existera pas
/// tant que quelqu'un ne l'aura pas réécrite.
#[cfg(not(target_os = "macos"))]
const SANS_SUPERPOSITION: &str = "La superposition demande macOS : elle repose sur un NSPanel non activant, sans équivalent porté sur ce système.";

#[tauri::command]
async fn toggle_overlay() -> Result<(), String> {
    #[cfg(target_os = "macos")]
    {
        on_main_thread(|| unsafe { native_overlay::toggle() });
        Ok(())
    }
    #[cfg(not(target_os = "macos"))]
    Err(SANS_SUPERPOSITION.into())
}

#[tauri::command]
async fn hide_overlay() -> Result<(), String> {
    #[cfg(target_os = "macos")]
    {
        on_main_thread(|| unsafe { native_overlay::hide() });
        Ok(())
    }
    #[cfg(not(target_os = "macos"))]
    Err(SANS_SUPERPOSITION.into())
}

/// Ramène la fenêtre principale au premier plan, à la demande d'un autre
/// appareil du maillage.
///
/// Les trois appels sont nécessaires, et dans cet ordre : `set_focus()` seul
/// laisse une fenêtre masquée ou réduite exactement où elle était. Le
/// raccourci Alt+Espace l'avait déjà appris ; cette séquence est la sienne.
///
/// À noter : sur macOS l'application est signée de façon ad hoc, et
/// `set_focus()` ne passe pas toujours au-dessus de l'espace plein écran
/// d'une autre application. L'écran demandé est bien ouvert dans tous les
/// cas — c'est la fenêtre qui peut rester derrière.
#[tauri::command]
fn focus_main_window(app: tauri::AppHandle) -> Result<(), String> {
    let window = app
        .get_webview_window("main")
        .ok_or_else(|| "La fenêtre principale de Diapason est introuvable.".to_string())?;
    let _ = window.show();
    let _ = window.set_focus();
    let _ = window.unminimize();
    Ok(())
}

// ---------------------------------------------------------------------------
// App entry point
// ---------------------------------------------------------------------------

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let backend: SharedBackend = Arc::new(Mutex::new(BackendManager::default()));
    let status: SharedStatus = Arc::new(Mutex::new(SetupStatus::default()));

    let boot_backend_ref = backend.clone();
    let boot_status_ref = status.clone();

    tauri::Builder::default()
        .manage(backend.clone())
        .manage(status.clone())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .plugin(tauri_plugin_autostart::init(
            MacosLauncher::LaunchAgent,
            Some(vec!["--hidden"]),
        ))
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.set_focus();
            }
        }))
        .setup(move |app| {
            // Un menu d'application, pour que ⌘R recharge vraiment.
            //
            // La fenêtre n'en avait aucun : ⌘R ne faisait RIEN, et une page
            // ouverte gardait indéfiniment un état vieilli — des tâches créées
            // ailleurs n'apparaissaient pas, un projet supprimé restait à
            // l'écran. Le rafraîchissement au retour du focus couvre le cas
            // courant ; ceci donne le geste explicite quand on veut forcer.
            {
                use tauri::menu::{PredefinedMenuItem, SubmenuBuilder};

                let recharger = MenuItemBuilder::with_id("reload", "Recharger")
                    .accelerator("CmdOrCtrl+R")
                    .build(app)?;
                let application = SubmenuBuilder::new(app, "Diapason")
                    .item(&PredefinedMenuItem::hide(app, None)?)
                    .item(&PredefinedMenuItem::hide_others(app, None)?)
                    .separator()
                    .item(&PredefinedMenuItem::quit(app, None)?)
                    .build()?;
                // Le menu Édition est indispensable : sans lui, ⌘C, ⌘V et ⌘A
                // sont morts dans toute l'application — un champ de saisie où
                // l'on ne peut pas coller n'est pas un champ de saisie.
                let edition = SubmenuBuilder::new(app, "Édition")
                    .item(&PredefinedMenuItem::undo(app, None)?)
                    .item(&PredefinedMenuItem::redo(app, None)?)
                    .separator()
                    .item(&PredefinedMenuItem::cut(app, None)?)
                    .item(&PredefinedMenuItem::copy(app, None)?)
                    .item(&PredefinedMenuItem::paste(app, None)?)
                    .item(&PredefinedMenuItem::select_all(app, None)?)
                    .build()?;
                let affichage = SubmenuBuilder::new(app, "Affichage")
                    .item(&recharger)
                    .separator()
                    .item(&PredefinedMenuItem::fullscreen(app, None)?)
                    .build()?;
                let barre = MenuBuilder::new(app)
                    .item(&application)
                    .item(&edition)
                    .item(&affichage)
                    .build()?;
                app.set_menu(barre)?;
                app.on_menu_event(move |app, event| {
                    if event.id().as_ref() == "reload" {
                        if let Some(window) = app.get_webview_window("main") {
                            // `eval` plutôt qu'un rechargement natif : on veut
                            // que la page reparte de zéro comme dans un
                            // navigateur, état React compris.
                            let _ = window.eval("window.location.reload()");
                        }
                    }
                });
            }

            // System tray
            let show = MenuItemBuilder::with_id("show", "Show / Hide").build(app)?;
            let health = MenuItemBuilder::with_id("health", "Health: starting...")
                .enabled(false)
                .build(app)?;
            let quit = MenuItemBuilder::with_id("quit", "Quit Diapason").build(app)?;

            let menu = MenuBuilder::new(app)
                .item(&show)
                .separator()
                .item(&health)
                .separator()
                .item(&quit)
                .build()?;

            // Keep the health item alive and actually update it. It used to
            // read "Health: starting..." forever — there was no set_text call
            // anywhere in this file — so the tray asserted a state it never
            // checked, and still said "starting" hours later with the backend
            // down. Poll every 10s and tell the truth.
            {
                let health_item = health.clone();
                tauri::async_runtime::spawn(async move {
                    let url = format!("{}/health", api_base());
                    let client = match client_http(&url) {
                        Ok(client) => client,
                        Err(_) => {
                            let _ = health_item.set_text("Backend: client error");
                            return;
                        }
                    };
                    loop {
                        let label = match client
                            .get(&url)
                            .timeout(std::time::Duration::from_secs(3))
                            .send()
                            .await
                        {
                            Ok(r) if r.status().is_success() => "Backend: reachable",
                            Ok(_) => "Backend: error",
                            Err(_) => "Backend: unreachable",
                        };
                        let _ = health_item.set_text(label);
                        tokio::time::sleep(std::time::Duration::from_secs(10)).await;
                    }
                });
            }

            let _tray = TrayIconBuilder::with_id("main")
                // A TEMPLATE icon, not the app tile: menu bar icons are
                // monochrome silhouettes that macOS recolors per theme —
                // the colored tile showed up as a black square blob.
                .icon(tauri::include_image!("icons/tray-icon.png"))
                .icon_as_template(true)
                .tooltip("Diapason")
                .menu(&menu)
                .on_menu_event(move |app, event| match event.id().as_ref() {
                    "show" => {
                        if let Some(window) = app.get_webview_window("main") {
                            if window.is_visible().unwrap_or(false) {
                                let _ = window.hide();
                            } else {
                                let _ = window.show();
                                let _ = window.set_focus();
                            }
                        }
                    }
                    "quit" => {
                        app.exit(0);
                    }
                    _ => {}
                })
                .build(app)?;

            // Create native macOS overlay panel
            #[cfg(target_os = "macos")]
            unsafe {
                native_overlay::create(include_str!("overlay.html"), DIAPASON_PORT);
            }

            // Register Cmd+Shift+Space to toggle the overlay
            {
                use tauri_plugin_global_shortcut::{
                    Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState,
                };
                // La superposition n'existe que sur macOS, donc son raccourci
                // ne s'enregistre que là. Ailleurs, ce bloc réservait
                // Cmd+Shift+Espace pour un rappel dont le corps était VIDE :
                // la touche était saisie à l'utilisateur, et rien n'arrivait.
                //
                // Pire sur Windows : `Modifiers::META` s'y traduit en MOD_WIN.
                // On confisquait donc Win+Maj+Espace — enregistré, inerte, et
                // impossible à diagnostiquer depuis l'autre bout.
                #[cfg(target_os = "macos")]
                {
                    let sc =
                        Shortcut::new(Some(Modifiers::META | Modifiers::SHIFT), Code::Space);
                    if let Err(e) = app.global_shortcut().on_shortcut(sc, |_app, _sc, ev| {
                        if ev.state == ShortcutState::Pressed {
                            unsafe {
                                native_overlay::toggle();
                            }
                        }
                    }) {
                        eprintln!("Warning: could not register Cmd+Shift+Space: {e}");
                    }
                }

                // Push-to-talk is DELIBERATELY not registered here.
                //
                // There were two independent dictation chains: this one
                // (Cmd+Alt+Space → ptt-start/ptt-stop → getUserMedia inside the
                // WebView → paste_to_frontmost) and the Python one (hold
                // Control → CGEventTap → sounddevice → faster-whisper →
                // clipboard-preserving paste), which runs as a LaunchAgent.
                //
                // The Python chain is the product: it works with every window
                // closed, which this one cannot — getUserMedia lives in the
                // WebView, so closing the window silences the microphone while
                // the shortcut still fires. Two chains also meant two hotkeys
                // and two answers to "why did nothing happen".
                //
                // To restore the in-window chain, re-register the shortcut
                // below and stop the agent (`diapason dictate-service uninstall`).
                let _ = (ShortcutState::Pressed, ShortcutState::Released);

                // Parler à Diapason : ceci n'a rien de spécifique à macOS —
                // le rappel montre la fenêtre et émet un événement, ce que
                // les trois systèmes savent faire. Seul l'ACCORD change.
                //
                // Option+Espace est un choix libre sur macOS. Sur Windows,
                // Alt+Espace est LE MENU SYSTÈME de la fenêtre : l'enregistrer
                // globalement volerait à l'utilisateur un raccourci que tout
                // son système lui a appris. On prend Ctrl+Maj+Espace, libre
                // sur Windows comme sur Linux.
                #[cfg(target_os = "macos")]
                let talk = Shortcut::new(Some(Modifiers::ALT), Code::Space);
                #[cfg(not(target_os = "macos"))]
                let talk =
                    Shortcut::new(Some(Modifiers::CONTROL | Modifiers::SHIFT), Code::Space);
                let talk_handle = app.handle().clone();
                if !raccourcis_globaux_disponibles() {
                    eprintln!(
                        "Talk global shortcut disabled: global-hotkey supports X11, \
                         but this Linux session uses Wayland. Use the visible Talk button."
                    );
                } else if let Err(e) = app.global_shortcut().on_shortcut(
                    talk,
                    move |app, _sc, ev| {
                        if ev.state != ShortcutState::Pressed {
                            return;
                        }
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                            let _ = window.unminimize();
                        }
                        let _ = talk_handle.emit("talk-toggle", ());
                    },
                ) {
                    eprintln!("Warning: could not register the Talk shortcut: {e}");
                }
            }

            // Auto-start backend services on launch
            spawn_boot_backend(boot_backend_ref, boot_status_ref);

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            focus_main_window,
            get_setup_status,
            get_api_base,
            get_local_api_key,
            start_backend,
            stop_backend,
            check_health,
            get_voice_live_health,
            fetch_energy,
            fetch_telemetry,
            fetch_traces,
            fetch_trace,
            fetch_learning_stats,
            fetch_learning_policy,
            fetch_memory_stats,
            search_memory,
            fetch_agents,
            fetch_models,
            run_diapason_command,
            fetch_savings,
            open_external_url,
            transcribe_audio,
            paste_to_frontmost,
            apply_pointer_event,
            speech_health,
            pull_ollama_model,
            delete_ollama_model,
            save_cloud_key,
            get_cloud_key_status,
            get_inference_source,
            set_inference_source,
            toggle_overlay,
            hide_overlay,
            get_overlay_conversation,
            live_speech::live_dictation_available,
            live_speech::start_live_dictation,
            live_speech::stop_live_dictation,
        ])
        .build(tauri::generate_context!())
        .expect("error while building Diapason Desktop")
        .run(move |_app, event| {
            if let tauri::RunEvent::ExitRequested { .. } = event {
                let b = backend.clone();
                tauri::async_runtime::spawn(async move {
                    b.lock().await.stop_all().await;
                });
            }
        });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {

    /// Un port libre doit être annoncé libre.
    ///
    /// Le repli par liaisons essaie « :: ». Sur une pile double, une liaison
    /// IPv6 non restreinte réserve AUSSI l'IPv4 : si les sondes se
    /// chevauchaient, la suivante échouerait sur AddrInUse et le contrôle
    /// déclarerait occupé un port que personne ne tient — l'application
    /// refuserait alors de démarrer.
    #[test]
    fn un_port_libre_ne_se_bloque_pas_lui_meme() {
        let ephemere = std::net::TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let port = ephemere.local_addr().unwrap().port();
        drop(ephemere);
        assert_eq!(super::port_conflict(port), None);
    }

    /// Un détenteur sur une adresse TIERCE doit être vu.
    ///
    /// C'est le test qui distingue le correctif de ce qu'il remplace : la
    /// version par liaisons n'essayait que 0.0.0.0, 127.0.0.1, :: et ::1, et
    /// rendait donc « libre » face à un serveur lié à l'adresse du Mac sur le
    /// réseau — exactement ce que `serve-service install --allow-network`
    /// installe pour le maillage. Interroger le noyau voit toutes les adresses.
    #[test]
    fn un_detenteur_sur_une_adresse_tierce_est_detecte() {
        // Trouver une adresse locale qui ne soit ni le joker ni le loopback.
        let sonde = match std::net::UdpSocket::bind(("0.0.0.0", 0)) {
            Ok(s) => s,
            Err(_) => return,
        };
        if sonde.connect(("8.8.8.8", 53)).is_err() {
            return;
        }
        let locale = match sonde.local_addr() {
            Ok(a) => a.ip(),
            Err(_) => return,
        };
        if locale.is_loopback() || locale.is_unspecified() {
            return; // machine sans adresse réseau : rien à prouver ici
        }
        let detenteur = match std::net::TcpListener::bind((locale, 0)) {
            Ok(l) => l,
            Err(_) => return,
        };
        let port = detenteur.local_addr().unwrap().port();
        let verdict = super::port_conflict(port);
        assert!(
            verdict.is_some(),
            "un détenteur sur {locale} doit être vu, pas seulement sur le loopback"
        );
        drop(detenteur);
    }

    /// Et un détenteur sur le loopback aussi, évidemment.
    #[test]
    fn un_auditeur_est_detecte() {
        let detenteur = std::net::TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let port = detenteur.local_addr().unwrap().port();
        assert!(super::port_conflict(port).is_some());
    }
    use super::{
        boot_plan, default_local_model, format_extension_import_failure,
        format_missing_rust_toolchain, format_port_unavailable, format_uv_sync_failure,
        format_uv_sync_spawn_error, matching_installed_model, model_names_match, normalize_host,
        parse_inference_config, parse_ollama_model_names, preferred_installed_model,
        project_candidates_in_install_root, session_linux_accepte_les_raccourcis_globaux,
        should_persist_resolved_model, startup_installed_model, upsert_engine_host, url_est_locale,
        uv_sync_stderr_tail, InferenceConfig, SourceKind, DESKTOP_UV_SYNC_ARGS,
        DESKTOP_UV_SYNC_COMMAND, CommandePointeur, EvenementPointeur,
        valider_evenement_pointeur,
    };
    use std::path::Path;

    fn evenement_pointeur(action: &str) -> EvenementPointeur {
        EvenementPointeur {
            active: true,
            action: action.into(),
            x: Some(0.25),
            y: Some(0.75),
            scroll_y: 0,
        }
    }

    #[test]
    fn une_commande_inactive_ne_touche_jamais_le_curseur() {
        let mut evenement = evenement_pointeur("CLICK");
        evenement.active = false;
        assert_eq!(
            valider_evenement_pointeur(evenement).unwrap(),
            CommandePointeur::Aucune
        );
    }

    #[test]
    fn une_coordonnee_hors_ecran_est_refusee() {
        let mut evenement = evenement_pointeur("MOVE");
        evenement.x = Some(1.2);
        let erreur = valider_evenement_pointeur(evenement).unwrap_err();
        assert!(erreur.contains("hors de l'écran"));
    }

    #[test]
    fn le_double_clic_conserve_sa_nature() {
        assert_eq!(
            valider_evenement_pointeur(evenement_pointeur("DOUBLE_CLICK")).unwrap(),
            CommandePointeur::Cliquer {
                x: 0.25,
                y: 0.75,
                double: true,
            }
        );
    }

    #[test]
    fn un_defilement_est_borne_avant_core_graphics() {
        let mut evenement = evenement_pointeur("SCROLL");
        evenement.scroll_y = 500;
        assert_eq!(
            valider_evenement_pointeur(evenement).unwrap(),
            CommandePointeur::Defiler { lignes: 10 }
        );
    }

    #[test]
    fn le_loopback_ne_passe_jamais_par_le_proxy_systeme() {
        assert!(url_est_locale("http://127.0.0.1:8000/health"));
        assert!(url_est_locale("http://localhost:11434/api/tags"));
        assert!(url_est_locale("http://[::1]:8000/health"));
    }

    #[test]
    fn un_endpoint_distant_conserve_la_configuration_reseau() {
        assert!(!url_est_locale("https://api.openai.com/v1/models"));
        assert!(!url_est_locale("http://192.168.0.198:8001/v1/mesh/me"));
        assert!(!url_est_locale("pas une url"));
    }

    #[test]
    fn install_root_checks_the_installer_layout_before_the_legacy_layout() {
        let candidates = project_candidates_in_install_root(Path::new(
            r"C:\Users\Carlito\AppData\Local\Diapason",
        ));
        assert_eq!(
            candidates[0],
            Path::new(r"C:\Users\Carlito\AppData\Local\Diapason").join("src")
        );
        assert_eq!(
            candidates[1],
            Path::new(r"C:\Users\Carlito\AppData\Local\Diapason")
        );
    }

    #[test]
    fn les_raccourcis_linux_restent_actifs_sous_x11() {
        assert!(session_linux_accepte_les_raccourcis_globaux(
            Some("x11"),
            None
        ));
    }

    #[test]
    fn les_raccourcis_linux_ne_promettent_rien_sous_wayland() {
        assert!(!session_linux_accepte_les_raccourcis_globaux(
            Some("wayland"),
            Some("wayland-0")
        ));
    }

    #[test]
    fn un_socket_wayland_suffit_meme_si_le_type_de_session_manque() {
        assert!(!session_linux_accepte_les_raccourcis_globaux(
            None,
            Some("wayland-1")
        ));
    }

    #[test]
    fn tail_returns_whole_string_when_shorter_than_limit() {
        assert_eq!(uv_sync_stderr_tail("short error", 800), "short error");
    }

    #[test]
    fn la_commande_affichee_est_celle_qui_est_executee() {
        assert_eq!(
            DESKTOP_UV_SYNC_COMMAND,
            format!("uv {}", DESKTOP_UV_SYNC_ARGS.join(" "))
        );
    }

    #[test]
    fn tail_keeps_the_end_not_the_beginning() {
        // uv's actionable line is at the end; the spinner noise is at the start.
        let s = format!("{}ACTUAL ERROR HERE", "spinner-noise ".repeat(200));
        let tail = uv_sync_stderr_tail(&s, 40);
        assert!(tail.ends_with("ACTUAL ERROR HERE"), "tail was: {tail:?}");
        assert!(!tail.contains("spinner-noise spinner-noise spinner-noise"));
        assert!(tail.chars().count() <= 40);
    }

    #[test]
    fn tail_trims_surrounding_whitespace() {
        assert_eq!(uv_sync_stderr_tail("  \n padded \n  ", 800), "padded");
    }

    #[test]
    fn tail_never_splits_a_multibyte_codepoint() {
        // Each "é" is 2 bytes / 1 char. A byte-based slice could panic or
        // produce invalid UTF-8; the char-based tail must not.
        let s = "é".repeat(500);
        let tail = uv_sync_stderr_tail(&s, 100);
        assert_eq!(tail.chars().count(), 100);
        assert!(tail.chars().all(|c| c == 'é'));
    }

    #[test]
    fn failure_message_includes_exit_code_and_tail_and_hint() {
        let msg = format_uv_sync_failure(
            Path::new("/home/u/.diapason/src"),
            Some(2),
            "error: failed to resolve numpy==2.1.3",
        );
        assert!(msg.contains("exit 2"));
        assert!(msg.contains("/home/u/.diapason/src"));
        assert!(msg.contains("failed to resolve numpy==2.1.3"));
        assert!(msg.contains(DESKTOP_UV_SYNC_COMMAND)); // actionable next step
    }

    #[test]
    fn failure_message_renders_missing_exit_code_as_unknown() {
        // Process killed by signal → no exit code. Must not show a misleading -1.
        let msg = format_uv_sync_failure(Path::new("/x"), None, "boom");
        assert!(msg.contains("exit unknown"));
        assert!(!msg.contains("exit -1"));
    }

    #[test]
    fn spawn_error_names_the_binary_and_root() {
        let msg = format_uv_sync_spawn_error(
            Path::new("/repo"),
            "C:\\Users\\me\\.local\\bin\\uv.exe",
            "No such file or directory (os error 2)",
        );
        assert!(msg.contains("C:\\Users\\me\\.local\\bin\\uv.exe"));
        assert!(msg.contains("/repo"));
        assert!(msg.contains("No such file or directory"));
    }

    #[test]
    fn missing_rust_toolchain_message_names_cargo_and_installer() {
        let msg = format_missing_rust_toolchain();
        assert!(msg.contains("cargo"));
        assert!(msg.contains("https://rustup.rs"));
        assert!(msg.contains("diapason_rust"));
        assert!(msg.contains("Visual Studio Build Tools"));
    }

    #[test]
    fn uv_sync_rust_failure_mentions_toolchain() {
        let msg = format_uv_sync_failure(
            Path::new("C:\\Users\\me\\Diapason"),
            Some(1),
            "maturin failed: linker `link.exe` not found while building diapason-rust",
        );
        assert!(msg.contains("exit 1"));
        assert!(msg.contains("link.exe"));
        assert!(msg.contains("https://rustup.rs"));
        assert!(msg.contains("Visual Studio Build Tools"));
    }

    #[test]
    fn extension_import_failure_names_verification_command() {
        let msg = format_extension_import_failure(
            Path::new("C:\\Users\\me\\Diapason"),
            "ModuleNotFoundError: No module named 'diapason_rust'",
        );
        assert!(msg.contains("diapason_rust"));
        assert!(msg.contains(DESKTOP_UV_SYNC_COMMAND));
        assert!(msg.contains("uv run python -c \"import diapason_rust\""));
        assert!(msg.contains("ModuleNotFoundError"));
    }

    #[test]
    fn port_unavailable_message_names_port_and_owner_hint() {
        let msg = format_port_unavailable(8000, "address already in use");
        assert!(msg.contains("Port 8000 is not available"));
        assert!(msg.contains("address already in use"));
        assert!(msg.contains("To identify it"));
        assert!(msg.contains("8000"));
    }

    #[test]
    fn default_local_model_picks_second_largest_that_fits() {
        // QWEN35_MODELS min_ram ladder: 4,6,8,12,24,32,96 GB
        assert_eq!(default_local_model(4.0), "qwen3.5:0.8b"); // only one fits
        assert_eq!(default_local_model(8.0), "qwen3.5:2b"); // fits 0.8/2/4 → 2nd-largest
        assert_eq!(default_local_model(16.0), "qwen3.5:4b"); // fits ..9b → 2nd-largest
        assert_eq!(default_local_model(32.0), "qwen3.5:27b"); // fits 0.8/2/4/9/27/35b → 2nd-largest is 27b
        assert_eq!(default_local_model(128.0), "qwen3.5:35b"); // fits all → 2nd-largest
    }

    #[test]
    fn default_local_model_falls_back_when_nothing_fits() {
        assert_eq!(default_local_model(1.0), super::FALLBACK_MODEL);
    }

    #[test]
    fn parse_ollama_model_names_reads_nonempty_names() {
        let body = serde_json::json!({
            "models": [
                {"name": "llama3.2:latest"},
                {"name": ""},
                {"name": "qwen3.5:4b"},
                {"model": "mistral:latest"}
            ]
        });
        assert_eq!(
            parse_ollama_model_names(&body),
            vec![
                "llama3.2:latest".to_string(),
                "qwen3.5:4b".to_string(),
                "mistral:latest".to_string()
            ]
        );
    }

    #[test]
    fn model_names_match_treats_latest_as_optional() {
        assert!(model_names_match("llama3.2:latest", "llama3.2"));
        assert!(model_names_match("llama3.2", "llama3.2:latest"));
        assert!(model_names_match("qwen3.5:4b", "qwen3.5:4b"));
        assert!(!model_names_match("llama3.2:latest", "qwen3.5:4b"));
    }

    #[test]
    fn installed_model_helpers_pick_matching_or_first_model() {
        let models = vec!["llama3.2:latest".to_string(), "qwen3.5:4b".to_string()];
        assert_eq!(
            matching_installed_model(&models, "llama3.2"),
            Some("llama3.2:latest".to_string())
        );
        assert_eq!(
            preferred_installed_model(&models),
            Some("llama3.2:latest".to_string())
        );
    }

    #[test]
    fn preferred_installed_model_skips_embedding_names_when_chat_model_exists() {
        let models = vec![
            "nomic-embed-text:latest".to_string(),
            "llama3.2:latest".to_string(),
        ];
        assert_eq!(
            preferred_installed_model(&models),
            Some("llama3.2:latest".to_string())
        );
    }

    #[test]
    fn startup_installed_model_uses_existing_model_for_defaults() {
        let models = vec!["llama3.2:latest".to_string()];
        assert_eq!(
            startup_installed_model("qwen3.5:4b", &models),
            Some("llama3.2:latest".to_string())
        );
    }

    #[test]
    fn startup_installed_model_uses_existing_model_when_configured_model_missing() {
        let models = vec!["llama3.2:latest".to_string()];
        assert_eq!(
            startup_installed_model("qwen3.5:4b", &models),
            Some("llama3.2:latest".to_string())
        );
    }

    #[test]
    fn resolved_model_is_only_persisted_when_no_model_was_configured() {
        let default_cfg = InferenceConfig {
            kind: SourceKind::Ollama,
            ..Default::default()
        };
        assert!(should_persist_resolved_model(&default_cfg));

        let empty_cfg = InferenceConfig {
            kind: SourceKind::Ollama,
            model: Some(" ".into()),
            ..Default::default()
        };
        assert!(should_persist_resolved_model(&empty_cfg));

        let user_cfg = InferenceConfig {
            kind: SourceKind::Ollama,
            model: Some("qwen3.5:9b".into()),
            ..Default::default()
        };
        assert!(!should_persist_resolved_model(&user_cfg));
    }

    #[test]
    fn parse_defaults_to_ollama_when_file_missing_or_garbage() {
        assert!(matches!(
            parse_inference_config("").kind,
            SourceKind::Ollama
        ));
        assert!(matches!(
            parse_inference_config("not json").kind,
            SourceKind::Ollama
        ));
    }

    #[test]
    fn parse_reads_custom_endpoint() {
        let cfg = parse_inference_config(
            r#"{"kind":"custom","model":"qwen2.5-7b","host":"http://localhost:1234","engine":"lmstudio"}"#,
        );
        assert!(matches!(cfg.kind, SourceKind::Custom));
        assert_eq!(cfg.model.as_deref(), Some("qwen2.5-7b"));
        assert_eq!(cfg.host.as_deref(), Some("http://localhost:1234"));
        assert_eq!(cfg.engine.as_deref(), Some("lmstudio"));
    }

    #[test]
    fn normalize_host_strips_trailing_slash_and_v1() {
        assert_eq!(
            normalize_host("http://localhost:1234/v1"),
            "http://localhost:1234"
        );
        assert_eq!(
            normalize_host("http://localhost:1234/v1/"),
            "http://localhost:1234"
        );
        assert_eq!(
            normalize_host("http://localhost:1234/"),
            "http://localhost:1234"
        );
        assert_eq!(normalize_host("http://host:8000"), "http://host:8000");
    }

    #[test]
    fn boot_plan_ollama_launches_and_pulls_one_model() {
        let cfg = InferenceConfig {
            kind: SourceKind::Ollama,
            ..Default::default()
        };
        let plan = boot_plan(&cfg, 16.0);
        assert!(plan.launch_ollama);
        assert_eq!(plan.model_to_pull.as_deref(), Some("qwen3.5:4b"));
        assert!(plan.engine_host.is_none());
        assert!(plan
            .serve_args
            .windows(2)
            .any(|w| w == ["--engine", "ollama"]));
        assert!(plan
            .serve_args
            .windows(2)
            .any(|w| w == ["--model", "qwen3.5:4b"]));
    }

    #[test]
    fn boot_plan_ollama_respects_pinned_model() {
        let cfg = InferenceConfig {
            kind: SourceKind::Ollama,
            model: Some("qwen3.5:9b".into()),
            ..Default::default()
        };
        let plan = boot_plan(&cfg, 16.0);
        assert_eq!(plan.model_to_pull.as_deref(), Some("qwen3.5:9b"));
    }

    #[test]
    fn boot_plan_custom_skips_ollama_and_sets_engine_host() {
        let cfg = InferenceConfig {
            kind: SourceKind::Custom,
            model: Some("qwen2.5-7b".into()),
            host: Some("http://localhost:1234".into()),
            engine: Some("lmstudio".into()),
        };
        let plan = boot_plan(&cfg, 16.0);
        assert!(!plan.launch_ollama);
        assert!(plan.model_to_pull.is_none());
        assert_eq!(
            plan.engine_host,
            Some(("lmstudio".to_string(), "http://localhost:1234".to_string()))
        );
        assert!(plan
            .serve_args
            .windows(2)
            .any(|w| w == ["--engine", "lmstudio"]));
        assert!(plan
            .serve_args
            .windows(2)
            .any(|w| w == ["--model", "qwen2.5-7b"]));
    }

    #[test]
    fn boot_plan_custom_defaults_engine_to_lmstudio() {
        let cfg = InferenceConfig {
            kind: SourceKind::Custom,
            model: Some("m".into()),
            host: Some("http://h:1".into()),
            engine: None,
        };
        let plan = boot_plan(&cfg, 16.0);
        assert_eq!(plan.engine_host.as_ref().unwrap().0, "lmstudio");
        assert!(plan
            .serve_args
            .windows(2)
            .any(|w| w == ["--engine", "lmstudio"]));
    }

    #[test]
    fn boot_plan_custom_omits_engine_host_when_no_host() {
        // No configured host → don't set engine_host (no override to write).
        let cfg = InferenceConfig {
            kind: SourceKind::Custom,
            model: Some("m".into()),
            host: None,
            engine: Some("lmstudio".into()),
        };
        let plan = boot_plan(&cfg, 16.0);
        assert!(plan.engine_host.is_none());
    }

    #[test]
    fn boot_plan_ollama_uses_fallback_model_on_low_ram() {
        // Below the smallest model's min_ram → default_local_model → FALLBACK_MODEL.
        let cfg = InferenceConfig {
            kind: SourceKind::Ollama,
            ..Default::default()
        };
        let plan = boot_plan(&cfg, 1.0);
        assert_eq!(plan.model_to_pull.as_deref(), Some(super::FALLBACK_MODEL));
    }

    #[test]
    fn upsert_engine_host_writes_into_empty_config() {
        let out = upsert_engine_host("", "lmstudio", "http://localhost:1234").unwrap();
        let doc: toml_edit::DocumentMut = out.parse().unwrap();
        assert_eq!(
            doc["engine"]["lmstudio"]["host"].as_str(),
            Some("http://localhost:1234")
        );
    }

    #[test]
    fn upsert_engine_host_preserves_existing_content() {
        let existing = "[intelligence]\ndefault_model = \"keep-me\"\n";
        let out = upsert_engine_host(existing, "vllm", "http://host:8000").unwrap();
        let doc: toml_edit::DocumentMut = out.parse().unwrap();
        assert_eq!(
            doc["intelligence"]["default_model"].as_str(),
            Some("keep-me")
        );
        assert_eq!(
            doc["engine"]["vllm"]["host"].as_str(),
            Some("http://host:8000")
        );
    }

    #[test]
    fn upsert_engine_host_updates_existing_host() {
        let existing = "[engine.lmstudio]\nhost = \"http://old:1\"\n";
        let out = upsert_engine_host(existing, "lmstudio", "http://new:2").unwrap();
        let doc: toml_edit::DocumentMut = out.parse().unwrap();
        assert_eq!(
            doc["engine"]["lmstudio"]["host"].as_str(),
            Some("http://new:2")
        );
    }

    // -----------------------------------------------------------------
    // #455 — AppImage subprocess env-strip helper
    // -----------------------------------------------------------------
    //
    // `prepare_subprocess_for_appimage` strips LD_LIBRARY_PATH (and the
    // related AppImage runtime variables) from a child `Command` ONLY
    // when the parent process is itself running inside an AppImage —
    // detected by the presence of the `APPIMAGE` env variable that the
    // AppImage runtime sets to the original .AppImage path. We can't
    // observe the env_remove calls directly through tokio's Command
    // API (it doesn't expose its env map publicly), so these tests
    // exercise the documented contract on each platform:
    //
    //   * on macOS / Windows: the function is a no-op regardless of env.
    //   * on Linux without $APPIMAGE: also a no-op.
    //   * on Linux with $APPIMAGE: it doesn't panic, doesn't return an
    //     error, and the calling code that follows succeeds. The
    //     observable behaviour test is the integration repro on a real
    //     AppImage build (covered in PR test plan).
    //
    // The Mutex serialises any test that touches the process-wide
    // `APPIMAGE` env var so cargo test's parallel runner can't race two
    // tests setting and unsetting it concurrently. `static Mutex` works
    // on a const path since Rust 1.63 (and Tauri's MSRV is well above).

    static APPIMAGE_ENV_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());

    // Pick a binary that exists on every test target so the test body is
    // doing something other than constructing an obviously-broken command
    // path on Windows.
    #[cfg(target_os = "windows")]
    const HARMLESS_BIN: &str = "cmd";
    #[cfg(not(target_os = "windows"))]
    const HARMLESS_BIN: &str = "/bin/true";

    #[test]
    fn prepare_subprocess_for_appimage_no_appimage_is_safe() {
        let _guard = APPIMAGE_ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        let prev = std::env::var_os("APPIMAGE");
        // SAFETY: APPIMAGE_ENV_LOCK serialises every test that touches
        // this env var, so the mutation is single-threaded for the
        // duration of the lock. The 2024-edition env mutation rules
        // require the `unsafe` block but the guard makes it sound.
        unsafe {
            std::env::remove_var("APPIMAGE");
        }
        let mut cmd = tokio::process::Command::new(HARMLESS_BIN);
        super::prepare_subprocess_for_appimage(&mut cmd);
        if let Some(v) = prev {
            unsafe {
                std::env::set_var("APPIMAGE", v);
            }
        }
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn prepare_subprocess_for_appimage_with_appimage_set_is_safe() {
        let _guard = APPIMAGE_ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        let prev = std::env::var_os("APPIMAGE");
        unsafe {
            std::env::set_var("APPIMAGE", "/tmp/test.AppImage");
        }
        let mut cmd = tokio::process::Command::new(HARMLESS_BIN);
        super::prepare_subprocess_for_appimage(&mut cmd);
        unsafe {
            if let Some(v) = prev {
                std::env::set_var("APPIMAGE", v);
            } else {
                std::env::remove_var("APPIMAGE");
            }
        }
    }
}
