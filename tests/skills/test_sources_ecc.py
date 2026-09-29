"""La source « ecc » : un clone LOCAL, lu sans réseau et sans rien y écrire.

28/09/2026. Carlito rattache une sélection de compétences ECC. Le
GitHubResolver générique aurait fait ``git pull --ff-only`` dans son clone
(réseau, et mutation d'un dépôt que l'installation Codex avait modifié), et
son rglob aurait pris ``.agents/skills/…`` ou une traduction de
``docs/ja-JP`` avant la copie canonique de ``skills/`` (§5 : ce qu'on
importe doit être ce qu'on croit importer).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from diapason.core.config import SkillSourceConfig
from diapason.skills.sources.ecc import (
    AllowListError,
    EccResolver,
    allowed_names,
    cited_tools,
    headings,
    served_skills,
)

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git absent")


def _skill(root: Path, dossier: str, nom: str, corps: str, origine="ECC", desc=""):
    d = root / dossier
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {nom}\ndescription: {desc or 'Canonical ' + nom}\n"
        f"metadata:\n  origin: {origine}\n---\n\n{corps}",
        encoding="utf-8",
    )
    return d


def _git(depot: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(depot), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
    )


@pytest.fixture
def depot(tmp_path: Path) -> Path:
    """Un faux clone ECC : canoniques sous skills/, copies ailleurs."""
    depot = tmp_path / "ECC"
    skills = depot / "skills"
    _skill(
        skills,
        "alpha",
        "alpha",
        textwrap.dedent("""\
            # Alpha

            Use Claude Code's Task tool, then `beta` for the rest.

            ## MCP Requirements

            - **firecrawl** — `firecrawl_search`, `firecrawl_scrape`

            ## Workflow

            ```
            ## Executive Summary
            firecrawl_search(query: "x")
            ```

            Write a failing test first; `read_csv` is plain code.
            """),
    )
    _skill(skills, "beta", "beta", "# Beta\n\n## One\n\ntext\n")
    gamma = _skill(skills, "gamma-dir", "gamma", "# Gamma\n", origine="community")
    (gamma / "references").mkdir()
    (gamma / "references" / "x.md").write_text("annexe\n")
    (gamma / "scripts").mkdir()
    (gamma / "scripts" / "run.sh").write_text("rm -rf /\n")
    (gamma / "hooks").mkdir()
    (gamma / "hooks" / "h.json").write_text("{}\n")
    for copie in (".agents/skills", ".kiro/skills", "docs/ja-JP/skills"):
        _skill(depot / copie, "alpha", "alpha", "# copie\n", desc="STALE copy")
    (depot / "VERSION").write_text("9.9.9\n")
    (depot / "LICENSE").write_text("MIT License\n\nCopyright\n")
    _git(depot, "init", "-q")
    _git(depot, "add", ".")
    _git(depot, "commit", "-qm", "init")
    return depot


class TestLaSourceEccNeLitQueLesCanoniques:
    def test_seul_skills_etoile_est_lu(self, depot: Path):
        """898 SKILL.md dans le vrai clone, 286 canoniques : les copies de
        .agents, .kiro et docs/<langue> diffèrent et ne doivent jamais
        l'emporter."""
        vues = EccResolver(depot).list_skills()
        assert sorted(s.name for s in vues) == ["alpha", "beta", "gamma"]
        for s in vues:
            assert s.path.parent == depot / "skills", f"{s.path} hors de skills/"
            assert s.description != "STALE copy", "une copie non canonique a gagné"

    def test_un_skill_md_lie_symboliquement_est_ignore(self, depot: Path, tmp_path):
        dehors = tmp_path / "dehors.md"
        dehors.write_text("---\nname: piege\ndescription: x\n---\nsecret\n")
        lien = depot / "skills" / "piege"
        lien.mkdir()
        (lien / "SKILL.md").symlink_to(dehors)
        noms = [s.name for s in EccResolver(depot).list_skills()]
        assert "piege" not in noms, "un lien peut pointer n'importe où sur le disque"


class TestLaSourceEccNeToucheNiAuReseauNiAuClone:
    def test_aucune_commande_git_ne_tire_ni_n_ecrit(self, depot: Path):
        vues: list[list[str]] = []

        def espion(argv, **kwargs):
            vues.append(list(argv))
            return subprocess.run(argv, **kwargs)

        resolver = EccResolver(depot, runner=espion)
        resolver.sync()
        resolver.list_skills()
        assert vues, "l'état du dépôt doit être lu par git"
        interdits = {"pull", "fetch", "clone", "push", "remote", "checkout", "reset"}
        for argv in vues:
            assert not interdits & set(argv), f"commande qui touche au clone : {argv}"
            assert argv[:3] == ["git", "-C", str(depot)], argv

    def test_git_status_ne_reecrit_pas_l_index(self, depot: Path):
        """Mesuré le 28/09/2026 : un SKILL.md dont seule la date change
        suffit à ce que `git status` réécrive .git/index. La lecture doit
        laisser le clone de Carlito octet pour octet."""
        index = depot / ".git" / "index"
        avant = index.read_bytes()
        cible = depot / "skills" / "beta" / "SKILL.md"
        t = cible.stat().st_mtime + 30
        os.utime(cible, (t, t))
        resolver = EccResolver(depot)
        resolver.sync()
        resolver.list_skills()
        assert index.read_bytes() == avant, "la lecture a réécrit .git/index"

    def test_sans_dossier_skills_la_synchro_le_dit(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError, match="skills/"):
            EccResolver(tmp_path / "nulle-part").sync()


class TestLaProvenanceEstLueDuDepot:
    def test_head_version_licence_et_modification_locale(self, depot: Path):
        (depot / "skills" / "beta" / "SKILL.md").write_text(
            "---\nname: beta\ndescription: x\n---\nmodifiée à la main\n"
        )
        resolver = EccResolver(depot)
        resolver.sync()
        head = subprocess.run(
            ["git", "-C", str(depot), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        vues = {s.name: s for s in resolver.list_skills()}
        assert vues["alpha"].commit == head, "le commit doit être HEAD du clone"
        prov_beta = vues["beta"].sidecar_data["provenance"]
        prov_alpha = vues["alpha"].sidecar_data["provenance"]
        assert prov_beta["depot_modifie"] is True, "beta est modifiée localement"
        assert prov_alpha["depot_modifie"] is False, "alpha ne l'est pas"
        assert prov_alpha["version_ecc"] == "9.9.9"
        assert prov_alpha["licence"] == "MIT (licence du dépôt ECC)"
        assert prov_alpha["chemin"] == "skills/alpha/SKILL.md"

    def test_origine_community_garde_sa_provenance(self, depot: Path):
        gamma = {s.name: s for s in EccResolver(depot).list_skills()}["gamma"]
        prov = gamma.sidecar_data["provenance"]
        assert gamma.category == "community"
        assert prov["origine"] == "community"
        assert prov["licence"] == "aucune licence propre (dépôt ECC : MIT)", (
            "une compétence d'auteur tiers n'est pas « sous MIT » : elle est "
            "publiée dans un dépôt MIT"
        )
        assert prov["chemin"] == "skills/gamma-dir/SKILL.md"

    def test_ressources_absentes_et_outils_cites(self, depot: Path):
        vues = {s.name: s for s in EccResolver(depot).list_skills()}
        gamma = vues["gamma"].sidecar_data["provenance"]
        assert gamma["ressources_absentes"] == ["hooks/", "scripts/"], (
            "references/ est copiée ; scripts/ et hooks/ ne le seront jamais"
        )
        alpha = vues["alpha"].sidecar_data["provenance"]
        assert alpha["outils_cites"] == ["Task", "firecrawl_search", "firecrawl_scrape"]
        assert alpha["competences_citees"] == ["beta"]
        assert vues["alpha"].sidecar_data["sections"] == 2, (
            "« ## Executive Summary » dans un bloc de code n'est pas une section"
        )


class TestLesOutilsCitesNeSontPasChaqueMotEnCamelCase:
    def test_la_prose_et_le_code_ne_sont_pas_des_outils(self):
        """L'heuristique de ToolTranslator relevait ValueError, GitHub ou
        UserService comme « outils manquants » : le .source disait faux."""
        corps = (
            "Raise ValueError on GitHub. UserService reads data.\n"
            "Write tests first. Read the plan.\n"
            "`read_csv` is pandas.\n"
        )
        assert cited_tools(corps, {}) == []

    def test_le_champ_tools_du_frontmatter_compte(self):
        assert cited_tools("", {"tools": "Read, Grep, Bash(git:*)"}) == [
            "Read",
            "Grep",
            "Bash",
        ]

    def test_les_titres_dans_un_bloc_de_code_ne_comptent_pas(self):
        corps = "## A\n```markdown\n## B\n```\n### C\n"
        assert [t for _, t, _ in headings(corps)] == ["A", "C"]


def _cfg(tmp_path: Path, **source) -> SimpleNamespace:
    src = SkillSourceConfig(source="ecc", **source)
    return SimpleNamespace(
        skills=SimpleNamespace(
            enabled=True, skills_dir=str(tmp_path / "skills"), sources=[src]
        )
    )


class TestLaListeDAutorisationNeSeDevinePas:
    @pytest.mark.parametrize(
        ("noms", "motif"),
        [
            (["*"], "joker"),
            (["research-*"], "joker"),
            (["deep-research?"], "joker"),
            (["../x"], "nom de compétence"),
            (["Article"], "nom de compétence"),
            ("article-writing", "LISTE"),
            ([3], "pas un nom"),
        ],
    )
    def test_joker_chaine_ou_nom_invalide_refuses(self, noms, motif):
        """« restreindre, jamais élargir » : un motif élargirait la sélection
        au-delà de ce que Carlito a écrit, sans qu'il le voie."""
        with pytest.raises(AllowListError, match=motif):
            allowed_names(SkillSourceConfig(source="ecc", filter={"names": noms}))

    def test_sans_liste_rien_n_est_autorise(self):
        assert allowed_names(SkillSourceConfig(source="ecc")) == []

    def test_seules_les_installees_de_la_liste_sont_servies(self, tmp_path: Path):
        for nom in ("alpha", "beta"):
            _skill(tmp_path / "skills" / "ecc", nom, nom, "# x\n")
        cfg = _cfg(tmp_path, filter={"names": ["alpha", "absente"]})
        assert list(served_skills(cfg)) == ["alpha"], (
            "beta est sur le disque mais hors liste : elle ne doit pas être servie"
        )

    def test_source_coupee_ou_competences_coupees_ne_servent_rien(self, tmp_path):
        _skill(tmp_path / "skills" / "ecc", "alpha", "alpha", "# x\n")
        coupee = _cfg(tmp_path, enabled=False, filter={"names": ["alpha"]})
        assert served_skills(coupee) == {}
        toutes = _cfg(tmp_path, filter={"names": ["alpha"]})
        toutes.skills.enabled = False
        assert served_skills(toutes) == {}

    def test_une_configuration_illisible_ferme_sans_lever(self, tmp_path: Path):
        from unittest.mock import MagicMock

        assert served_skills(MagicMock()) == {}, (
            "la trousse du chat ne doit jamais tomber pour une source mal réglée"
        )
        assert served_skills(_cfg(tmp_path, filter={"names": "*"})) == {}
