"""AGENTS.md et CLAUDE.md ne peuvent pas se contredire.

Deux assistants travaillent sur ce dépôt, chacun lisant son propre fichier au
démarrage : Claude Code lit `CLAUDE.md`, Codex lit `AGENTS.md`. Le 26 août
2026 ils portaient le même texte — 195 lignes identiques sur 198 — sans que
rien ne les y oblige.

Deux copies d'un même texte divergent toujours, et celle qui n'est pas
corrigée continue d'instruire quelqu'un. Ce dépôt a déjà payé ce prix
ailleurs : la matrice des capacités niait un travail livré le matin même, et
`docs/deployment/launchd.md` enseignait encore la faille que le plist du même
dépôt interdisait en majuscules.

Ce test est donc un cliquet, pas un rappel : `CLAUDE.md` est la source, et
`AGENTS.md` en découle par `scripts/gen_agents_md.py`.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]


def _generateur():
    chemin = RACINE / "scripts" / "gen_agents_md.py"
    spec = importlib.util.spec_from_file_location("gen_agents_md", chemin)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["gen_agents_md"] = module
    spec.loader.exec_module(module)
    return module


def test_agents_md_est_le_reflet_exact_de_claude_md():
    attendu = _generateur().rendu()
    obtenu = (RACINE / "AGENTS.md").read_text(encoding="utf-8")
    assert obtenu == attendu, (
        "AGENTS.md a dérivé de CLAUDE.md. Régénère-le DANS CE COMMIT :\n"
        "  .venv/bin/python scripts/gen_agents_md.py\n\n"
        "Si la divergence est voulue, elle doit passer par REMPLACEMENTS "
        "dans scripts/gen_agents_md.py — sinon un des deux assistants "
        "travaillera sur des règles périmées sans que rien ne le dise."
    )


def test_le_fichier_engendre_nomme_le_bon_outil():
    """Un fichier généré qui garderait le nom de sa source dirait à Codex
    qu'il lit le fichier de Claude — et l'inverse au premier coup d'œil."""
    agents = (RACINE / "AGENTS.md").read_text(encoding="utf-8")
    claude = (RACINE / "CLAUDE.md").read_text(encoding="utf-8")
    assert agents.startswith("# AGENTS.md")
    assert claude.startswith("# CLAUDE.md")
    assert "session Codex" in agents and "session Claude Code" not in agents
    assert "session Claude Code" in claude and "session Codex" not in claude
