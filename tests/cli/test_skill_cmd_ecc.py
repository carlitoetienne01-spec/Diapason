"""`diapason skill sync ecc` : montrer avant d'importer, n'importer que la liste.

28/09/2026. Décision de Carlito : une SÉLECTION de compétences ECC, sans
leurs scripts. `sync` importait tout ce qu'une source listait, sans rien
montrer d'abord ; une collision entre sources se taisait ; et rien ne
disait qu'une copie importée avait vieilli (§5 : ce qui est sur le disque
doit se dire tel qu'il est).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from diapason.cli import cli
from diapason.core.config import load_config

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git absent")


def _git(depot: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(depot), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
    )


def _ecrire(depot: Path, dossier: str, nom: str, corps: str) -> None:
    d = depot / "skills" / dossier
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {nom}\ndescription: {nom} guide\nmetadata:\n  origin: ECC\n"
        f"---\n\n{corps}",
        encoding="utf-8",
    )


@pytest.fixture(scope="module")
def _depot_modele(tmp_path_factory) -> Path:
    """Le dépôt git est construit UNE fois par module, puis copié : trois
    processus git par test, sous `-n auto`, suffisaient à retarder les tests
    de réactivité des autres ouvriers (délais de 2 s)."""
    depot = tmp_path_factory.mktemp("modele") / "ECC"
    _ecrire(
        depot,
        "alpha",
        "alpha",
        "# Alpha\n\n## MCP Requirements\n\n- `firecrawl_search`\n\n## Steps\n\nx\n",
    )
    _ecrire(depot, "beta", "beta", "# Beta\n")
    _ecrire(depot, "gamma-dir", "gamma", "# Gamma\n")
    (depot / "skills" / "alpha" / "scripts").mkdir()
    (depot / "skills" / "alpha" / "scripts" / "go.sh").write_text("echo\n")
    (depot / "VERSION").write_text("2.2.1\n")
    (depot / "LICENSE").write_text("MIT License\n")
    _git(depot, "init", "-q")
    _git(depot, "add", ".")
    _git(depot, "commit", "-qm", "init")
    return depot


@pytest.fixture
def banc(tmp_path: Path, monkeypatch, _depot_modele: Path):
    depot = tmp_path / "ECC"
    shutil.copytree(_depot_modele, depot, symlinks=True)

    skills = tmp_path / "skills"
    config = tmp_path / "config.toml"

    def configurer(noms: str = '["alpha"]', enabled: str = "true") -> None:
        config.write_text(
            "[skills]\n"
            f'skills_dir = "{skills}"\n'
            "[[skills.sources]]\n"
            'source = "ecc"\n'
            f'path = "{depot}"\n'
            f"enabled = {enabled}\n"
            "[skills.sources.filter]\n"
            f"names = {noms}\n",
            encoding="utf-8",
        )
        load_config.cache_clear()

    configurer()
    monkeypatch.setenv("DIAPASON_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("DIAPASON_CONFIG", str(config))
    monkeypatch.chdir(tmp_path)
    load_config.cache_clear()
    yield depot, skills, configurer
    load_config.cache_clear()


def _lancer(*args: str):
    load_config.cache_clear()
    return CliRunner().invoke(cli, ["skill", *args])


class TestLeDryRunMontreSansEcrire:
    def test_la_liste_s_affiche_et_rien_n_est_ecrit(self, banc):
        depot, skills, _ = banc
        sortie = _lancer("sync", "ecc", "--dry-run")
        assert sortie.exit_code == 0, sortie.output
        assert not skills.exists(), "--dry-run a écrit sur le disque"
        texte = sortie.output
        assert "alpha — origine ECC" in texte
        assert "jetons" in texte and "sections — nouvelle" in texte
        assert "outils cités : firecrawl_search" in texte
        assert "ressources absentes (jamais importées) : scripts/" in texte
        assert "rien n'a été écrit" in texte
        assert "beta" not in texte, "une compétence hors liste ne s'affiche pas"

    def test_un_nom_de_dossier_est_explique(self, banc):
        _, _, configurer = banc
        configurer('["gamma-dir"]')
        texte = _lancer("sync", "ecc", "--dry-run").output
        assert "introuvable en amont" in texte
        assert "son nom est « gamma »" in texte, "le bon nom doit être donné"


class TestLImportNeSuitQueLaListe:
    def test_seuls_les_noms_autorises_sont_importes(self, banc):
        _, skills, _ = banc
        sortie = _lancer("sync", "ecc")
        assert sortie.exit_code == 0, sortie.output
        installees = sorted(p.name for p in (skills / "ecc").iterdir())
        assert installees == ["alpha"], f"hors liste importé : {installees}"
        assert not (skills / "ecc" / "alpha" / "scripts").exists()
        assert "kickstart" in sortie.output, "la relance du service doit être dite"

    def test_source_coupee_n_importe_rien(self, banc):
        _, skills, configurer = banc
        configurer(enabled="false")
        sortie = _lancer("sync", "ecc")
        assert "source coupée" in sortie.output
        assert not skills.exists()

    @pytest.mark.parametrize("noms", ['["*"]', '"alpha"', '["al*"]'])
    def test_joker_ou_chaine_refuses(self, banc, noms):
        _, skills, configurer = banc
        configurer(noms)
        sortie = _lancer("sync", "ecc")
        assert sortie.exit_code == 1
        assert not skills.exists()

    def test_with_scripts_refuse(self, banc):
        sortie = _lancer("sync", "ecc", "--with-scripts")
        assert sortie.exit_code == 1 and "plafond" in sortie.output

    def test_install_par_nom_contourne_pas_la_liste(self, banc):
        _, skills, _ = banc
        sortie = _lancer("install", "ecc:beta")
        assert sortie.exit_code == 1 and "filter" in sortie.output
        assert not skills.exists()

    def test_sans_bloc_de_configuration_le_bloc_est_montre(
        self, banc, tmp_path, monkeypatch
    ):
        vide = tmp_path / "vide.toml"
        vide.write_text("")
        monkeypatch.setenv("DIAPASON_CONFIG", str(vide))
        sortie = _lancer("sync", "ecc", "--dry-run")
        assert sortie.exit_code == 1
        assert "[[skills.sources]]" in sortie.output


class TestUnDossierDeMethodesEnLienEstRefuse:
    def test_force_ne_vide_jamais_le_clone(self, banc):
        """29/09/2026 : ``skills/ecc`` en lien vers le clone faisait vider
        ``skills/<nom>`` DANS le clone par ``sync ecc --force``."""
        depot, skills, _ = banc
        skills.mkdir()
        (skills / "ecc").symlink_to(depot / "skills")
        brouillon = depot / "skills" / "alpha" / "brouillon.md"
        brouillon.write_text("non suivi, irremplaçable")
        sortie = _lancer("sync", "ecc", "--force")
        assert sortie.exit_code == 1, sortie.output
        assert "lien symbolique" in sortie.output
        assert brouillon.exists(), "le clone a été touché"
        assert (depot / "skills" / "alpha" / "SKILL.md").exists()


class TestLesStatutsDisentLEtatDeLaCopie:
    def test_a_jour_puis_changee_puis_alteree_puis_retiree(self, banc):
        depot, skills, _ = banc
        _lancer("sync", "ecc")
        assert "alpha" in _lancer("sync", "ecc", "--dry-run").output
        assert "— à jour" in _lancer("sync", "ecc", "--dry-run").output

        _ecrire(depot, "alpha", "alpha", "# Alpha v2\n")
        _git(depot, "commit", "-qam", "v2")
        texte = _lancer("sync", "ecc", "--dry-run").output
        assert "changée en amont (" in texte, texte

        sans_force = _lancer("sync", "ecc").output
        assert "relance avec --force" in sans_force
        copie = skills / "ecc" / "alpha" / "SKILL.md"
        assert "v2" not in copie.read_text(), "réimporté sans --force"
        _lancer("sync", "ecc", "--force")
        assert "v2" in copie.read_text(), "--force doit réimporter"

        copie.write_text(copie.read_text() + "\nretouche à la main\n")
        assert "copie altérée" in _lancer("sync", "ecc", "--dry-run").output

        _git(depot, "rm", "-rq", "skills/alpha")
        _git(depot, "commit", "-qm", "retrait")
        texte = _lancer("sync", "ecc").output
        assert "retirée en amont" in texte
        assert copie.exists(), "une compétence retirée en amont n'est pas effacée"

    def test_hors_liste_se_dit(self, banc):
        _, _, configurer = banc
        _lancer("sync", "ecc")
        configurer('["beta"]')
        texte = _lancer("sync", "ecc", "--dry-run").output
        assert "alpha — hors liste" in texte


class TestUneCollisionEstSignaleeJamaisTue:
    def test_la_meme_competence_dans_une_autre_source(self, banc):
        _, skills, _ = banc
        autre = skills / "hermes" / "alpha"
        autre.mkdir(parents=True)
        (autre / "SKILL.md").write_text("---\nname: alpha\ndescription: h\n---\nx\n")
        (autre / ".source").write_text('source = "hermes:alpha"\n')
        texte = _lancer("sync", "ecc", "--dry-run").output
        assert "collision : « alpha » existe aussi dans la source hermes" in texte


class TestLaRechercheNeRenvoiePasVersUnRefus:
    def test_la_recherche_ecc_indique_la_liste_pas_install(self, banc):
        """`install ecc:<nom>` est refusé : la recherche ne doit pas y envoyer."""
        texte = _lancer("search", "alpha", "--source", "ecc").output
        assert "alpha" in texte
        assert "skill install" not in texte, texte
        assert "filter.names" in texte
