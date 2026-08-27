"""Guards for the diapason-rust packaging split (#584 / #615).

``diapason_rust`` is the native PyO3 extension. It is NOT published to PyPI,
so it must not appear in the published ``desktop`` extra — listing it there
breaks ``pip install diapason[desktop]`` at install time. It lives in the uv
``desktop-native`` dependency group instead (excluded from wheel metadata),
which the desktop app installs from source via
``uv sync --group desktop-native``.
"""

from __future__ import annotations

import json
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parent.parent.parent
PYPROJECT = ROOT / "pyproject.toml"
DESKTOP_LIB_RS = ROOT / "frontend" / "src-tauri" / "src" / "lib.rs"
WINDOWS_INSTALL_PS1 = ROOT / "deploy" / "windows" / "install.ps1"
WINDOWS_SERVICE_PS1 = ROOT / "deploy" / "windows" / "diapason-service.ps1"
WINDOWS_VERIFY_PS1 = ROOT / "deploy" / "windows" / "verify.ps1"
WINDOWS_TAURI_VALIDATION = (
    ROOT / "frontend" / "src-tauri" / "tauri.windows-validation.conf.json"
)
DESKTOP_WORKFLOW = ROOT / ".github" / "workflows" / "desktop.yml"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
QUICKSTART_SH = ROOT / "scripts" / "quickstart.sh"


def _pyproject() -> dict:
    return tomllib.loads(PYPROJECT.read_text())


def test_diapason_rust_not_in_published_desktop_extra() -> None:
    desktop = _pyproject()["project"]["optional-dependencies"]["desktop"]
    assert not any("diapason-rust" in dep for dep in desktop), (
        "diapason-rust must not be in the published `desktop` extra — it is "
        "not on PyPI, so it breaks `pip install diapason[desktop]`."
    )


def test_diapason_rust_lives_in_uv_dependency_group() -> None:
    group = _pyproject()["dependency-groups"]["desktop-native"]
    assert any("diapason-rust" in dep for dep in group)


def test_diapason_rust_has_local_uv_path_source() -> None:
    src = _pyproject()["tool"]["uv"]["sources"]["diapason-rust"]
    assert src["path"] == "rust/crates/diapason-python"


def test_desktop_app_syncs_the_native_group() -> None:
    # Otherwise the group's diapason_rust is never installed for the app.
    assert '"desktop-native"' in DESKTOP_LIB_RS.read_text(), (
        "the desktop app must `uv sync --group desktop-native` so the native "
        "extension is built at launch."
    )


def test_windows_installer_syncs_the_native_group() -> None:
    """Le groupe natif est synchronisé — QUAND Rust est là pour le bâtir.

    Ce test exigeait la commande en dur, inconditionnelle. Or ce groupe tire
    `diapason-rust`, que uv.lock déclare comme une source de RÉPERTOIRE sans
    aucune roue : uv doit le compiler, avec rustc 1.88, les outils MSVC, CMake
    et NASM — que l'installateur ne vérifiait ni n'installait. Sur un PC neuf
    la commande échouait, et le script s'arrêtait là.

    La dépendance était pourtant connue : ci.yml installe
    dtolnay/rust-toolchain en étape séparée avant chaque appel à maturin.
    Seule cette ligne l'ignorait. Constaté le 26 août 2026, avant que Carlito
    n'y passe une soirée.

    Le test garde donc l'intention — bâtir l'extension quand c'est possible —
    au lieu d'une chaîne de caractères.
    """
    script = WINDOWS_INSTALL_PS1.read_text()
    assert "--group', 'desktop-native'" in script or (
        "--group desktop-native" in script
    ), "l'installateur ne bâtit plus jamais l'extension native"
    assert "Get-Command cargo" in script, (
        "l'installateur exige Rust sans vérifier qu'il est là"
    )
    assert "Rustlang.Rustup" in script, (
        "l'installateur doit dire comment obtenir Rust, pas seulement le "
        "constater absent"
    )
    for outil in ("Get-Command cmake", "Get-Command nasm", "VC.Tools.x86.x64"):
        assert outil in script, (
            f"l'installateur ne vérifie pas {outil} avant de lancer la "
            "construction native"
        )


def test_quickstart_installs_web_search_dependencies() -> None:
    quickstart = QUICKSTART_SH.read_text()
    assert "--extra tools-search" in quickstart


def test_quickstart_refuses_a_port_already_served() -> None:
    """Quickstart ne doit pas empiler un serveur sur un autre.

    Cette assertion vivait dans le test des dépendances de recherche web, et
    portait sur la formulation exacte du message. On vérifie désormais le
    MÉCANISME : la question est posée au noyau — un ``curl /health`` ne voit
    pas un détenteur muet — et un port occupé fait échouer le script.
    """
    quickstart = QUICKSTART_SH.read_text()
    assert "port_listeners" in quickstart, "le port doit être vérifié"
    assert "lsof" in quickstart, "la question doit être posée au noyau"
    assert "already served by" in quickstart, "un port occupé doit faire échouer"


def test_l_installateur_windows_cherche_un_python_qui_convient() -> None:
    """Il prenait le premier `python3` du PATH et abandonnait s'il ne
    convenait pas.

    Sur Windows 11, ce premier-là est presque toujours l'alias du Microsoft
    Store — `%LOCALAPPDATA%\\Microsoft\\WindowsApps\\python3.exe` — qui masque
    le Python que winget vient d'installer. Le script trouvait donc un 3.14,
    le refusait à juste titre, et s'arrêtait sans jamais regarder le 3.13 posé
    deux minutes plus tôt.

    Constaté sur la machine de Carlito le 26 août 2026, à la première
    exécution réelle : c'est exactement le genre de défaut qu'aucune relecture
    ne trouve et que la première tentative révèle.
    """
    script = WINDOWS_INSTALL_PS1.read_text()
    assert 'py "-$v"' in script or "py -3.13" in script, (
        "l'installateur n'interroge pas le lanceur `py`, seul moyen fiable "
        "de trouver une version précise sur Windows"
    )
    assert "3.12" in script and "3.11" in script, (
        "il doit essayer plusieurs versions, pas seulement la plus récente"
    )
    assert "py -0p" in script, (
        "le message d'échec doit dire comment VOIR ce qui est installé"
    )
    assert "App execution aliases" in script, (
        "le message d'échec doit nommer la cause la plus probable — l'alias "
        "du Microsoft Store — et non se contenter de « pas trouvé »"
    )


def test_le_banc_windows_ne_confond_pas_un_ecouteur_et_aucun() -> None:
    """Un unique résultat PowerShell est déroulé en objet scalaire.

    Sur le premier PC réel, le banc affichait ``listeners=127.0.0.1`` puis
    déclarait la frontière loopback en échec : ``.Count`` ne comptait pas
    l'objet unique rendu par la fonction. Les deux sockets doivent être
    enveloppés au point d'appel, avant que leur cardinalité soit consultée.
    """
    script = WINDOWS_VERIFY_PS1.read_text()
    assert "$apiListeners = @(Get-Listeners $ListenPort)" in script, (
        "un seul écouteur API redevient un scalaire et son Count ment"
    )
    assert "$meshListeners = @(Get-Listeners $LanPort)" in script, (
        "un seul écouteur Mesh redevient un scalaire et son Count ment"
    )


def test_le_service_windows_ne_resynchronise_pas_le_venv_a_chaque_session() -> None:
    """`uv run` au logon peut élaguer le groupe natif posé à l'installation."""
    script = WINDOWS_SERVICE_PS1.read_text(encoding="utf-8")
    assert ".venv\\Scripts\\diapason.exe" in script
    assert '$serveArgs = "run diapason serve' not in script
    assert "-Execute $diapasonPath" in script


def test_l_installateur_peut_activer_le_mesh_sans_exposer_l_api() -> None:
    script = WINDOWS_INSTALL_PS1.read_text(encoding="utf-8")
    assert "[switch] $MaillageReseau" in script
    assert "DIAPASON_MESH_NETWORK" in script
    assert "$serviceArgs += '-MaillageReseau'" in script
    assert 'uv run --project "%SRC%" diapason' not in script
    assert '"%SRC%\\.venv\\Scripts\\diapason.exe" %*' in script
    assert "deploy\\windows\\verify.ps1" in script
    assert "$verifyFlags += '-RequireNative'" in script
    assert "$verifyFlags += '-RequireMesh'" in script


def test_l_installateur_windows_ne_promet_aucun_retry_inexistant() -> None:
    script = WINDOWS_INSTALL_PS1.read_text(encoding="utf-8")
    assert "bg-orchestrator" not in script
    assert "No background retry exists on Windows" in script
    assert "github.io/Diapason/" not in script


def test_tauri_reconnait_le_repertoire_pose_par_l_installateur_windows() -> None:
    source = DESKTOP_LIB_RS.read_text(encoding="utf-8")
    assert 'std::env::var("LOCALAPPDATA")' in source
    assert '.join("Diapason")' in source
    assert 'root.join("src")' in source
    assert 'args(["ls-remote"' not in source, (
        "l'application ne doit pas tenter silencieusement de cloner le dépôt privé"
    )


def test_tauri_essaie_le_sidecar_embarque_avant_l_installation_systeme() -> None:
    source = DESKTOP_LIB_RS.read_text(encoding="utf-8")
    assert "std::env::current_exe()" in source
    assert "candidates.insert(0, directory.join(name)" in source
    assert 'directory.join(format!("{name}.exe"))' in source


def test_le_workflow_bureau_valide_sur_le_runner_local_sans_simuler_windows() -> None:
    workflow = DESKTOP_WORKFLOW.read_text(encoding="utf-8")
    assert "runs-on: [self-hosted, macos-local]" in workflow
    assert workflow.count("vars.RUNNERS_GITHUB == 'true'") >= 2
    assert "platform: windows-latest" in workflow, (
        "la matrice Windows doit rester prête à être rallumée sur un vrai runner"
    )


def test_le_runner_windows_local_construit_un_msi_de_validation() -> None:
    workflow = DESKTOP_WORKFLOW.read_text(encoding="utf-8")
    assert "build-windows-local:" in workflow
    assert "runs-on: [self-hosted, windows-local]" in workflow
    assert "vars.RUNNER_WINDOWS_LOCAL == 'true'" in workflow
    assert "tauri.windows-validation.conf.json" in workflow
    assert "Diapason\\artifacts" in workflow
    assert "diapason-windows-validation-msi" in workflow

    config = json.loads(WINDOWS_TAURI_VALIDATION.read_text())
    bundle = config["bundle"]
    assert bundle["targets"] == ["msi"]
    assert bundle["createUpdaterArtifacts"] is False
    assert "externalBin" not in bundle


def test_le_workflow_ne_fabrique_pas_un_sidecar_ollama_incomplet() -> None:
    """L'archive Windows porte le CLI ET ses bibliothèques GPU.

    Le workflow historique extrayait uniquement ``ollama.exe`` et déclarait
    ce fichier comme ``externalBin``. Le MSI pouvait donc réussir alors que
    son moteur était incomplet. L'installateur de la plateforme pose Ollama ;
    Tauri le résout ensuite dans son emplacement système.
    """
    workflow = DESKTOP_WORKFLOW.read_text(encoding="utf-8")
    assert "download-ollama" not in workflow
    assert '"externalBin"' not in workflow


def test_le_banc_windows_verifie_les_frontieres_sans_les_modifier() -> None:
    script = WINDOWS_VERIFY_PS1.read_text(encoding="utf-8")
    assert "[switch] $RequireNative" in script
    assert "[switch] $RequireMesh" in script
    assert ".venv\\Scripts\\diapason.exe" in script
    assert "import diapason_rust" in script
    assert "Get-NetTCPConnection" in script
    assert "/v1/chat/completions" in script
    assert "/v1/mesh/presence" in script
    assert "Start-ScheduledTask" not in script
    assert "Register-ScheduledTask" not in script
    assert "Unregister-ScheduledTask" not in script


def test_le_banc_windows_exige_404_hors_du_mesh() -> None:
    script = WINDOWS_VERIFY_PS1.read_text(encoding="utf-8")
    for preuve in ("mesh.no_chat", "mesh.no_health", "mesh.no_docs"):
        assert preuve in script
    assert script.count("-eq 404") >= 3
    assert "$presenceStatus -eq 403" in script


def test_le_job_windows_accepte_un_runner_local_et_parse_powershell() -> None:
    """Le runner de service ne doit pas dépendre de PowerShell Core.

    Constaté sur le premier passage Windows du 27 août 2026 : le PC avait le
    parseur Windows PowerShell 5.1 utilisé par nos installateurs, mais pas
    `pwsh`. Les deux matrices mouraient donc avant d'analyser un seul `.ps1`.
    """
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    assert "RUNNER_WINDOWS_LOCAL == 'true'" in workflow
    assert '["self-hosted","windows-local"]' in workflow
    assert "System.Management.Automation.Language.Parser" in workflow
    assert "git ls-files '*.ps1'" in workflow
    assert "shell: powershell" in workflow
    assert "shell: pwsh" not in workflow


def test_les_scripts_powershell_non_ascii_portent_un_bom() -> None:
    """Windows PowerShell 5.1 lit un `.ps1` SANS BOM comme du Windows-1252.

    Un tiret cadratin « — », trois octets en UTF-8, y devient une séquence
    contenant un guillemet typographique — que PowerShell accepte comme
    délimiteur de chaîne. Les chaînes se déséquilibrent alors, et l'analyseur
    signale une erreur des dizaines de lignes plus loin, à un endroit qui n'a
    rien à voir.

    Constaté le 26 août 2026 : après avoir ajouté des explications en français
    à `diapason-service.ps1`, le script est devenu inanalysable —
    « Le terminateur " est manquant dans la chaîne » ligne 232, pour une cause
    située ligne 11. C'est un défaut que rien ne révèle sur macOS, où le
    fichier n'est jamais lu par PowerShell 5.1.

    Le BOM lève l'ambiguïté : avec lui, PowerShell lit de l'UTF-8 et les
    accents sont des accents.
    """
    fautifs = []
    for script in sorted(WINDOWS_INSTALL_PS1.parent.glob("*.ps1")):
        octets = script.read_bytes()
        a_un_bom = octets[:3] == b"\xef\xbb\xbf"
        non_ascii = any(o > 127 for o in octets[3:] if a_un_bom) or (
            not a_un_bom and any(o > 127 for o in octets)
        )
        if non_ascii and not a_un_bom:
            fautifs.append(script.name)
    assert not fautifs, (
        f"scripts PowerShell non-ASCII sans BOM UTF-8 : {fautifs}. "
        "PowerShell 5.1 les lira en Windows-1252 et les accents casseront "
        "l'analyse des chaînes."
    )
