"""§5/§100 : la preuve Windows doit précéder l'installateur, sans publication."""

from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/parite-windows.yml"


def lire():
    return yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)


class TestWorkflowPariteWindows:
    def test_les_bancs_llm_et_capsule_ont_des_preuves_liees_a_ce_run(self):
        """§100 : ni un ancien reçu de capsule ni une sonde de modèle ne suffisent."""
        etapes = lire()["jobs"]["build"]["steps"]
        contrats = next(s["run"] for s in etapes if s.get("id") == "contrats")
        for nom in ("REPORT", "NONCE", "RUN_ID"):
            assert f"DIAPASON_CAPSULE_TEST_{nom}" in contrats
        assert contrats.index("capsule-request.json") < contrats.index("cargo test")
        llm = next(s["run"] for s in etapes if s.get("id") == "preuve_llm")
        assert "scripts\\prouver_llm_windows.py" in llm
        assert '--workdir "$essai" --download' in llm
        assert llm.index("$codePreuve = $LASTEXITCODE") < llm.index("Copy-Item")
        assert "Get-ChildItem" not in llm, "ne collecter que les preuves synthétiques"
        assert "'report.json','dialogue.json','backend-events.jsonl'" in llm
        assert "if ($codePreuve -ne 0)" in llm

    def test_la_voix_avance_apres_un_echec_de_fenetre_sans_livrer_nsis(self):
        """§100 : les deux bancs sont indépendants, la livraison exige les deux."""
        etapes = lire()["jobs"]["build"]["steps"]
        preuve = next(s for s in etapes if s.get("id") == "preuve_native")
        nsis = next(s for s in etapes if s.get("id") == "nsis")
        assert "!cancelled()" in preuve["if"], "un arrêt manuel reste prioritaire"
        assert "steps.profil.outcome == 'success'" in preuve["if"]
        assert "steps.frontend.outcome == 'success'" in preuve["if"]
        assert "steps.contrats" not in preuve["if"], "la voix peut être exercée seule"
        assert "success()" in nsis["if"], (
            "un échec Tauri bloque toujours l'installateur"
        )
        assert "steps.preuve_native.outcome == 'success'" in nsis["if"]

    def test_le_diagnostic_de_chargement_ne_masque_pas_lechec_des_contrats(self):
        """§100 : le chargeur refusait le PE avant toute sortie des tests Rust."""
        script = next(
            s["run"]
            for s in lire()["jobs"]["build"]["steps"]
            if s.get("id") == "contrats"
        )
        assert "diagnostiquer_chargement_windows.py" in script
        assert '"$env:BETA_OUTPUT\\chargement-windows.json"' in script
        assert script.index("$env:BETA_PYTHON $diagnostic") < script.index(
            "throw 'Contrats Tauri Windows refuses'"
        ), "le diagnostic conserve le refus initial"

    def test_le_bundle_tauri_existe_avant_les_contrats_rust(self):
        """§100 : le bundle Python seul laissait frontendDist absent sur le PC."""
        etapes = lire()["jobs"]["build"]["steps"]
        construction = next(
            i for i, s in enumerate(etapes) if s.get("id") == "frontend"
        )
        contrats = next(i for i, s in enumerate(etapes) if s.get("id") == "contrats")
        script = etapes[construction]["run"]
        assert construction < contrats, "le vrai bundle doit précéder generate_context!"
        assert "npm run build:tauri" in script, (
            "le build Python ne produit pas frontend/dist"
        )
        assert script.index("npm run build\n") < script.index("npm run build:tauri"), (
            "les deux applications doivent recevoir leur bundle"
        )
        assert "Test-Path -LiteralPath 'dist\\index.html'" in script, (
            "la sortie attendue doit être vérifiée avant cargo test"
        )

    def test_le_driver_recoit_ses_chemins_qa_et_garde_les_wav_sur_echec(self):
        """§100 : le driver refusait profil et rapport placés hors de son essai."""
        etape = next(
            s
            for s in lire()["jobs"]["build"]["steps"]
            if s.get("id") == "preuve_native"
        )
        script = etape["run"]
        assert "$env:DIAPASON_HOME = Join-Path $essai 'profil'" in script
        assert '--output "$essai\\rapport.json" --workdir "$essai"' in script
        assert "'.diapason-backend'" in script, (
            "le driver refuse les sources non gérées"
        )
        assert script.index("$codePreuve = $LASTEXITCODE") < script.index("Copy-Item")
        assert script.index("Copy-Item") < script.index("if ($codePreuve -ne 0)")
        assert "Get-ChildItem" not in script, "aucune collecte de tout le profil"
        assert (
            "@('fr-tts.wav','fr-narration.wav','en-tts.wav','en-narration.wav')"
            in script
        )

    def test_seule_une_demande_manuelle_lance_le_pc(self):
        """§5 : ne pas lancer des modèles lourds sur un push de routine."""
        w = lire()
        assert set(w["on"]) == {"workflow_dispatch"}, (
            "le lancement doit rester explicite"
        )
        entrees = w["on"]["workflow_dispatch"]["inputs"]
        assert entrees["mode"]["default"] == "diagnostic", (
            "aucun poids ne doit être téléchargé par défaut"
        )
        assert entrees["mode"]["options"] == ["diagnostic", "complet"], (
            "les deux actions doivent être distinctes"
        )
        for job in w["jobs"].values():
            assert job["runs-on"] == ["self-hosted", "windows-local"], (
                "exiger le vrai PC Windows"
            )

    def test_le_diagnostic_ne_recoit_ni_sources_ni_cle(self):
        """§5 : lire la RAM ne doit ni installer ni inspecter les données du PC."""
        w = lire()
        assert w["permissions"] == {"contents": "read"}, (
            "permissions minimales par défaut"
        )
        diagnostic = w["jobs"]["diagnostic"]
        assert "inputs.mode == 'diagnostic'" in diagnostic["if"], (
            "un mode explicite doit borner ce parcours"
        )
        assert len(diagnostic["steps"]) == 2, (
            "sonde locale et conservation du rapport seulement"
        )
        texte = str(diagnostic)
        for interdit in (
            "secrets.",
            "GH_TOKEN",
            "uv sync",
            "snapshot",
            "Get-ChildItem",
            "Get-Content",
            "Win32_UserAccount",
            "SerialNumber",
            "UserName",
        ):
            assert interdit not in texte, (
                "le diagnostic ne doit lire ni données ni installations"
            )

    def test_le_jeton_du_brouillon_reste_sur_sa_seule_etape(self):
        """§100 : le code de la snapshot n'a pas besoin du jeton GitHub."""
        job = lire()["jobs"]["build"]
        assert "inputs.mode == 'complet'" in job["if"], (
            "le test complet doit être choisi"
        )
        assert job["permissions"] == {"contents": "write"}, (
            "GitHub exige ce droit pour lire un brouillon privé"
        )
        jetons = [s for s in job["steps"] if "GH_TOKEN" in s.get("env", {})]
        assert len(jetons) == 1, "ne pas transmettre le jeton aux helpers ou modèles"
        assert "extraire sans liens" in jetons[0]["name"], (
            "le jeton ne sert qu'à recevoir la snapshot"
        )

    def test_la_preuve_native_complete_est_obligatoire_avant_nsis(self):
        """§100 : une ancienne fumée de gestion ne valide pas la nouvelle voix."""
        etapes = lire()["jobs"]["build"]["steps"]
        preuve = next(
            i
            for i, s in enumerate(etapes)
            if "scripts\\verifier_parite_windows.py" in s.get("run", "")
        )
        signature = next(
            i
            for i, s in enumerate(etapes)
            if "TAURI_SIGNING_PRIVATE_KEY" in s.get("env", {})
        )
        assert preuve < signature, (
            "aucun installateur ne doit précéder sa preuve native"
        )
        assert "$codePreuve = $LASTEXITCODE" in etapes[preuve]["run"]
        assert "if ($codePreuve -ne 0)" in etapes[preuve]["run"], (
            "une erreur doit bloquer la livraison"
        )
        assert etapes[signature]["env"]["DIAPASON_WINDOWS_COMPLET"] == "1", (
            "le binaire doit sélectionner le profil réellement testé"
        )
        assert "DIAPASON_WINDOWS_BETA_GESTION" not in etapes[signature]["env"], (
            "ne pas compiler le serveur bridé"
        )

    def test_sources_et_profils_restent_dans_le_dossier_du_run(self):
        """§5 : les essais ne doivent pas lire le compte Diapason du runner."""
        texte = WORKFLOW.read_text()
        for declaration in (
            '"BETA_SOURCE=$racine\\profil\\src"',
            '"DIAPASON_HOME=$racine\\profil"',
            '"HF_HOME=$racine\\profil\\hf-cache"',
        ):
            assert declaration in texte, (
                "toutes les données de test doivent être explicitement isolées"
            )
        assert "--windows-complet --target x86_64-pc-windows-msvc" in texte, (
            "la snapshot doit attester ce profil"
        )
        assert "--extra voice-windows" in texte, (
            "les dépendances vocales doivent être installées"
        )

    def test_le_workflow_ne_publie_rien_et_garde_les_echecs(self):
        """§100 : l'artefact est à relire, un build vert ne vaut pas publication."""
        texte = WORKFLOW.read_text()
        for interdit in (
            "gh release",
            "gh api",
            "desktop-latest",
            "pypi-publish",
            "ssh ",
            "scp ",
        ):
            assert interdit not in texte, (
                "aucune publication ou machine de production n'est dans ce workflow"
            )
        sortie = lire()["jobs"]["build"]["steps"][-1]
        assert sortie["uses"] == "actions/upload-artifact@v4", (
            "garder un artefact révisable"
        )
        assert sortie["if"] == "always()", (
            "garder le rapport d'échec pour comprendre un blocage"
        )


# Les contextes sont rendus sans moteur Actions ni accès à un runner réel.
def rendre(texte, contextes):
    import re

    return re.sub(
        r"\$\{\{\s*([^}]*?)\s*\}\}",
        lambda m: contextes.get(m.group(1), ""),
        texte,
    )


def etape(identifiant, job="build"):
    return next(s for s in lire()["jobs"][job]["steps"] if s.get("id") == identifiant)


def simuler_echec(identifiant, *, annule=False):
    """Conditions relues : deux bancs indépendants, succès global irréversible."""
    resultats = {}
    succes = True
    for s in lire()["jobs"]["build"]["steps"]:
        if s.get("id") == "rapport":
            break
        condition = s.get("if")
        if s.get("id") in {"preuve_native", "preuve_llm"}:
            assert condition == (
                "${{ !cancelled() && steps.profil.outcome == 'success' "
                "&& steps.frontend.outcome == 'success' }}"
            ), "la preuve ne démarre qu'après la préparation vérifiée"
            executer = (
                not annule
                and resultats.get("profil") == "success"
                and resultats.get("frontend") == "success"
            )
        elif condition:
            assert (
                condition == "success() && steps.preuve_native.outcome == 'success'"
            ), "une condition nouvelle doit être relue avant de simuler le pipeline"
            executer = (
                not annule and succes and resultats.get("preuve_native") == "success"
            )
        else:
            executer = succes
        assert "continue-on-error" not in s, "ne pas masquer un échec de preuve"
        resultat = "skipped"
        if executer:
            resultat = "failure" if s["id"] == identifiant else "success"
            succes = succes and resultat == "success"
        resultats[s["id"]] = resultat
    return resultats


def pouvoirs_shell51():
    """§5 : aucune commande CIM réelle ; seuls parseur et fixtures sont permis."""
    import os
    import shutil
    import subprocess

    import pytest

    if os.name != "nt":
        pytest.skip("PowerShell 5.1 natif disponible seulement sur le banc Windows")
    executable = shutil.which("powershell.exe")
    if not executable:
        pytest.skip("PowerShell 5.1 absent")
    version = subprocess.run(
        [
            executable,
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "[Console]::Write($PSVersionTable.PSVersion.ToString())",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if version.returncode != 0 or not version.stdout.startswith("5.1."):
        pytest.skip("ce banc exige le moteur PowerShell 5.1")
    return executable


def executer_shell_fictif(tmp_path, script, environnement):
    """Ne transmettre aucune vraie clé au sous-processus de test."""
    import os
    import subprocess

    executable = pouvoirs_shell51()
    fichier = tmp_path / "fixture.ps1"
    fichier.write_text(script, encoding="utf-8-sig")
    autorises = ("SystemRoot", "WINDIR", "Path", "PATH", "PSModulePath", "TEMP", "TMP")
    env = {k: os.environ[k] for k in autorises if k in os.environ}
    env.update(
        {
            "GH_TOKEN": "TEMOIN-FICTIF-NON-SECRET",
            "TAURI_SIGNING_PRIVATE_KEY": "TEMOIN-FICTIF-NON-SECRET",
            **environnement,
        }
    )
    return subprocess.run(
        [
            executable,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(fichier),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


class TestRapportsWorkflowPariteWindows:
    def test_les_uploads_ne_dependent_pas_d_un_export_tardif(self):
        """§5 : une panne de setup ne doit jamais transformer le chemin en /*."""
        import ntpath

        contextes = {
            "runner.temp": r"D:\runner-temp",
            "github.run_id": "123",
            "github.run_attempt": "2",
        }
        for job, attendu in (
            ("build", r"D:\runner-temp\diapason-beta-123-2\artefact"),
            ("diagnostic", r"D:\runner-temp\diapason-diagnostic-123-2\diagnostic.json"),
        ):
            sortie = lire()["jobs"][job]["steps"][-1]
            assert sortie["if"] == "always()", "la collecte doit survivre à l'échec"
            expression = sortie["with"]["path"]
            assert "BETA_OUTPUT" not in expression, "cet export peut manquer"
            assert "steps." not in expression, "un output de step peut manquer"
            chemin = ntpath.normpath(rendre(expression, contextes))
            assert chemin == attendu, (
                "le chemin doit rester constant et dans runner.temp"
            )
            assert "*" not in chemin, "ne conserver aucun glob susceptible de s'élargir"

    def test_le_collecteur_ne_recoit_que_des_outcomes_explicitement_nommes(self):
        """§100 : outputs, environnement et erreurs peuvent contenir du privé."""
        import re

        collecte = etape("rapport")
        assert collecte["if"] == "always()", "collecter aussi les premiers échecs"
        autres = {
            s["id"]
            for s in lire()["jobs"]["build"]["steps"]
            if s.get("id") not in {"rapport", "artefacts"}
        }
        recus = set()
        for nom, valeur in collecte["env"].items():
            if nom == "RAPPORT_DOSSIER":
                continue
            correspondance = re.fullmatch(
                r"\$\{\{ steps\.([a-z_]+)\.outcome \}\}", valeur
            )
            assert correspondance, "aucun contexte libre ne doit entrer dans le rapport"
            recus.add(correspondance[1])
        assert recus == autres, "inclure setup, réception, préparation, preuve et NSIS"
        corps = collecte["run"]
        for interdit in (
            "toJSON(steps)",
            "Get-ChildItem",
            "Get-Content",
            "Get-Item Env:",
            "$env:GH_TOKEN",
            "$env:TAURI_SIGNING_PRIVATE_KEY",
            "$_.Exception",
            "$Error[",
            "Out-String",
        ):
            assert interdit not in corps, "ne jamais sérialiser de contenu libre"
        assert not re.search(r"\$Error\b", corps), "ne pas sérialiser la pile d'erreurs"
        assert "run-status.json" in corps, "un rapport de statut fixe doit être produit"
        assert "New-Item -ItemType Directory" in corps, (
            "créer le dossier même sans setup"
        )

    def test_les_echecs_precoces_gardent_leurs_outcomes_et_bloquent_nsis(self):
        """§5/§100 : conserver setup/SHA/prepare/helper sans signer après panne."""
        import ntpath

        for phase in (
            "node",
            "rust",
            "initialisation",
            "reception",
            "preparation",
            "profil",
            "frontend",
            "contrats",
            "preuve_native",
            "preuve_llm",
        ):
            resultats = simuler_echec(phase)
            assert resultats[phase] == "failure", "la panne doit être conservée"
            assert resultats["nsis"] == "skipped", "aucune clé de signature après échec"
            contextes = {
                "runner.temp": r"D:\run-temp",
                "github.run_id": "111",
                "github.run_attempt": "3",
                **{f"steps.{n}.outcome": v for n, v in resultats.items()},
            }
            collecte = etape("rapport")
            valeurs = {k: rendre(v, contextes) for k, v in collecte["env"].items()}
            assert "failure" in valeurs.values(), (
                "le collecteur reçoit réellement la panne"
            )
            assert ntpath.normpath(valeurs["RAPPORT_DOSSIER"]) == (
                r"D:\run-temp\diapason-beta-111-3\artefact"
            ), "collecter même si BETA_OUTPUT et BETA_PYTHON sont absents"

    def test_nsis_exige_explicitement_la_reussite_de_la_preuve(self):
        """§100 : même une preuve sautée ne doit pas rendre les clés disponibles."""
        signature = etape("nsis")
        assert (
            signature["if"] == "success() && steps.preuve_native.outcome == 'success'"
        ), "l'état global et le résultat de la preuve doivent tous deux être verts"
        assert simuler_echec("aucune")["nsis"] == "success", (
            "le parcours vert reste possible"
        )
        for s in lire()["jobs"]["build"]["steps"]:
            if s.get("id") != "nsis":
                assert "secrets." not in str(s), "les clés restent exclusives à NSIS"

    def test_une_preuve_audio_reussie_nefface_pas_un_echec_tauri(self):
        """§100 : le second banc peut passer sans rendre le premier vert."""
        resultats = simuler_echec("contrats")
        assert resultats["preuve_native"] == "success", "l'essai audio continue"
        assert resultats["nsis"] == "skipped", "la panne de fenêtre reste bloquante"
        assert simuler_echec("aucune", annule=True)["preuve_native"] == "skipped", (
            "une annulation ne lance aucun modèle"
        )

    def test_finally_conserve_un_echec_diagnostic_generique(
        self,
    ):
        """§5 : une panne CIM doit conserver un JSON générique, pas ses détails."""
        diagnostic = etape("diagnostic", "diagnostic")
        corps = diagnostic["run"]
        assert "try {" in corps and "catch {" in corps and "finally {" in corps, (
            "l'écriture doit survivre à la première requête CIM refusée"
        )
        finalement = corps.split("finally {", 1)[1]
        assert "Set-Content -LiteralPath" in finalement, "écrire aussi en cas d'échec"
        assert "diagnosticUnavailable" in corps, "cause générique et stable"
        for interdit in ("$_", "$Error[", ".Exception", "Format-List", "Out-String"):
            assert interdit not in corps, (
                "ne pas exporter les détails système d'une erreur"
            )

    def test_power_shell51_parse_tous_les_scripts_sans_les_executer(self, tmp_path):
        """§5 : le vrai parseur Windows 5.1 doit accepter les snippets, sans CIM."""
        pouvoirs_shell51()
        for i, s in enumerate(
            s for job in lire()["jobs"].values() for s in job["steps"] if "run" in s
        ):
            if s.get("shell") == "cmd":
                continue
            source = tmp_path / f"source-{i}.ps1"
            source.write_text(s["run"], encoding="utf-8-sig")
            parseur = (
                "$erreurs=$null\n"
                "[void][System.Management.Automation.Language.Parser]::ParseFile("
                "$env:SOURCE_PS,[ref]$null,[ref]$erreurs)\n"
                "if (@($erreurs).Count -gt 0) { exit 1 }\n"
            )
            resultat = executer_shell_fictif(
                tmp_path, parseur, {"SOURCE_PS": str(source)}
            )
            assert resultat.returncode == 0, (
                "un snippet du workflow ne se parse pas en PS5.1"
            )

    def test_collecteur_power_shell_sans_texte_prive(self, tmp_path):
        """§5/§100 : exécuter le collecteur réel avec quatre échecs fictifs."""
        import json

        pouvoirs_shell51()
        collecte = etape("rapport")
        for phase in ("node", "reception", "preparation", "preuve_native"):
            dossier = tmp_path / phase
            resultats = simuler_echec(phase)
            env = {
                nom: (
                    str(dossier)
                    if nom == "RAPPORT_DOSSIER"
                    else rendre(
                        valeur, {f"steps.{n}.outcome": v for n, v in resultats.items()}
                    )
                )
                for nom, valeur in collecte["env"].items()
            }
            resultat = executer_shell_fictif(tmp_path, collecte["run"], env)
            assert resultat.returncode == 0, (
                "le collecteur réel doit réussir sans setup"
            )
            texte = (dossier / "run-status.json").read_text(encoding="utf-8-sig")
            rapport = json.loads(texte)
            assert set(rapport) == {"schemaVersion", "mode", "status", "steps"}, (
                "aucun champ libre ou détail d'environnement"
            )
            assert rapport["status"] == "failure", "le rapport ne doit pas dire succès"
            assert rapport["steps"][phase] == "failure", "nommer l'étape en échec"
            assert "TEMOIN-FICTIF" not in texte + resultat.stdout + resultat.stderr, (
                "aucune variable étrangère dans le rapport ou les sorties"
            )

    def test_le_diagnostic_power_shell_mocke_cim_et_driveinfo(self, tmp_path):
        """§5 : aucun accès matériel ; un faux CIM vérifie aussi le catch/finally."""
        import json

        pouvoirs_shell51()
        script = etape("diagnostic", "diagnostic")["run"]
        mocks = r"""
function Get-CimInstance {
  param([string]$ClassName)
  if ($env:ECHEC_CIM -eq '1') { throw 'TEMOIN-PRIVE-ERREUR' }
  switch ($ClassName) {
    'Win32_ComputerSystem' {
      [pscustomobject]@{
        TotalPhysicalMemory=16000000000
        UserName='TEMOIN-PRIVE'
      }
    }
    'Win32_Processor' {
      [pscustomobject]@{
        Name='CPU fixture'
        NumberOfCores=4
        NumberOfLogicalProcessors=8
        SerialNumber='TEMOIN-PRIVE'
      }
    }
    'Win32_OperatingSystem' {
      [pscustomobject]@{
        BuildNumber='fixture'
        OSArchitecture='64-bit'
        RegisteredUser='TEMOIN-PRIVE'
      }
    }
    'Win32_VideoController' {
      [pscustomobject]@{
        Name='GPU fixture'
        DriverVersion='fixture'
        DeviceID='TEMOIN-PRIVE'
      }
    }
  }
}
function New-Object {
  param([string]$TypeName, $ArgumentList)
  if ($TypeName -ne 'System.IO.DriveInfo') { throw 'Constructeur inattendu' }
  [pscustomobject]@{AvailableFreeSpace=42000000000}
}
"""
        for echoue in (False, True):
            dossier = tmp_path / str(echoue)
            resultat = executer_shell_fictif(
                tmp_path,
                mocks + script,
                {
                    "RAPPORT_DOSSIER": str(dossier),
                    "RUNNER_TEMP": str(tmp_path),
                    "ECHEC_CIM": "1" if echoue else "0",
                },
            )
            texte = (dossier / "diagnostic.json").read_text(encoding="utf-8-sig")
            rapport = json.loads(texte)
            assert (resultat.returncode != 0) == echoue, (
                "l'échec doit rester un échec de job"
            )
            assert rapport["status"] == ("failure" if echoue else "success"), (
                "le statut doit provenir de la vraie tentative"
            )
            assert "TEMOIN-PRIVE" not in texte + resultat.stdout + resultat.stderr, (
                "ne pas conserver l'exception ni les propriétés CIM non choisies"
            )


class TestUvPriveWorkflowPariteWindows:
    def test_uv_et_python_restent_dans_les_outils_du_run(self):
        """§5 : aucun registre, bin ou cache Python du compte du runner."""
        import re

        script = etape("initialisation")["run"]
        for declaration in (
            "$env:UV_PYTHON_INSTALL_DIR = $pythonDir",
            "$env:UV_CACHE_DIR = $cache",
            "$env:TEMP = $temporaire",
            "$env:TMP = $temporaire",
            '"UV_PYTHON_INSTALL_DIR=$pythonDir"',
            '"UV_CACHE_DIR=$cache"',
            '"TEMP=$temporaire"',
            '"TMP=$temporaire"',
            '"BETA_UV=$uv"',
        ):
            assert declaration in script, "initialiser et exporter les chemins privés"
        for sous_dossier in ("python", "cache", "tmp"):
            assert f"Join-Path $outils '{sous_dossier}'" in script, (
                "chaque écriture uv doit rester sous outils"
            )
        installation = next(
            ligne for ligne in script.splitlines() if "& $uv python install" in ligne
        )
        for option in (
            "--no-config",
            "--no-bin",
            "--no-registry",
            '--install-dir "$pythonDir"',
        ):
            assert option in installation, "ne pas modifier l'installation du runner"
        recherche = next(
            ligne for ligne in script.splitlines() if "& $uv python find" in ligne
        )
        for option in (
            "--no-config",
            "--no-project",
            "--managed-python",
            "--no-python-downloads",
        ):
            assert option in recherche, "la recherche ne doit ni découvrir ni installer"
        assert script.index("Push-Location $outils") < script.index(recherche), (
            "chercher l'interpréteur hors de tout projet"
        )
        assert "finally {" in script and "Pop-Location" in script, (
            "rendre le dossier de travail même en cas d'échec"
        )
        assert "StartsWith" in script and "$installation" in script, (
            "refuser un Python trouvé hors de l'installation privée"
        )
        for s in lire()["jobs"]["build"]["steps"]:
            corps = s.get("run", "")
            assert not re.search(r"(?m)^\s*uv\s+", corps), "aucun uv global"
            assert "(Get-Command uv)" not in corps, "le helper reçoit le chemin privé"
        helper = etape("preuve_native")["run"]
        assert '--uv "$env:BETA_UV"' in helper, "pas de résolution uv via PATH"

    def test_uv_est_epingle_et_verifie_avant_toute_execution(self):
        """§100 : un ZIP latest non vérifié ne doit pas amorcer le build."""
        import re

        script = etape("initialisation")["run"]
        assert "$uvVersion = '0.13.7'" in script, "version officielle revue"
        assert (
            "0cdc5b38fe5a8168ed6a25814f5ba43c21d313dd3187314fccb37b7cec46e021" in script
        ), "SHA-256 vérifié contre l'asset et son checksum officiel"
        assert "/latest/" not in script, (
            "la version ne doit pas dériver au prochain run"
        )
        assert "Get-FileHash -Algorithm SHA256 -LiteralPath" in script, (
            "calculer l'empreinte des octets reçus"
        )
        verification = script.index("Get-FileHash")
        assert verification < script.index("Expand-Archive"), (
            "rejeter l'archive avant extraction"
        )
        assert verification < script.index("& $uv python install"), (
            "ne jamais exécuter uv non vérifié"
        )
        assert re.search(r"if .*uvSha256.*throw", script), (
            "une empreinte différente doit arrêter l'amorçage"
        )

    def test_l_assemblage_ne_peut_pas_effacer_le_rapport_final(self):
        """§100 : le statut est écrit après tous les producteurs du paquet."""
        etapes = lire()["jobs"]["build"]["steps"]
        assert [s["id"] for s in etapes[-2:]] == ["rapport", "artefacts"], (
            "aucun assemblage ni build ne doit suivre l'écriture du statut"
        )
