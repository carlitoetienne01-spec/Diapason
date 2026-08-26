#!/usr/bin/env python
"""Engendre AGENTS.md à partir de CLAUDE.md.

26 août 2026. Deux assistants travaillent sur ce dépôt et chacun lit son
propre fichier au démarrage : Claude Code lit `CLAUDE.md`, Codex lit
`AGENTS.md`. Les deux disaient exactement la même chose — 195 lignes
identiques sur 198, mêmes huit sections — et ne différaient que par leur
titre, l'outil nommé à la deuxième ligne, et la signature du pied de page.

Deux copies d'un même texte finissent toujours par diverger, et ce dépôt en
a déjà payé le prix ailleurs : la matrice des capacités niait un travail
livré le matin même, `docs/deployment/launchd.md` enseignait encore la faille
que le plist du même dépôt interdisait en majuscules. Une session qui corrige
un des deux fichiers ne pense pas à l'autre — et l'autre continue d'instruire
quelqu'un.

D'où ce script plutôt qu'une promesse : `CLAUDE.md` est la source, `AGENTS.md`
en découle, et `tests/test_agents_md.py` refuse qu'ils s'écartent.

Usage : .venv/bin/python scripts/gen_agents_md.py
"""

from __future__ import annotations

from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
SOURCE = RACINE / "CLAUDE.md"
SORTIE = RACINE / "AGENTS.md"

# Les seules différences légitimes entre les deux fichiers. Toute autre
# divergence est une dérive, et le test la refuse.
REMPLACEMENTS: tuple[tuple[str, str], ...] = (
    (
        "# CLAUDE.md — ce qu'une session doit savoir avant d'écrire une ligne",
        "# AGENTS.md — ce qu'une session doit savoir avant d'écrire une ligne",
    ),
    (
        "Ce fichier est lu automatiquement au début de chaque session Claude Code dans",
        "Ce fichier est lu automatiquement au début de chaque session Codex dans",
    ),
    (
        "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>",
        "Co-Authored-By: Codex Opus 5 <noreply@anthropic.com>",
    ),
)


def rendu() -> str:
    """Le contenu qu'AGENTS.md doit avoir, tiré de CLAUDE.md."""
    texte = SOURCE.read_text(encoding="utf-8")
    for depuis, vers in REMPLACEMENTS:
        if depuis not in texte:
            raise SystemExit(
                f"CLAUDE.md ne contient plus :\n  {depuis}\n\n"
                "Le script ne sait plus quoi remplacer. Mets à jour "
                "REMPLACEMENTS dans scripts/gen_agents_md.py."
            )
        texte = texte.replace(depuis, vers)
    return texte


def main() -> None:
    SORTIE.write_text(rendu(), encoding="utf-8")
    print(f"AGENTS.md engendré depuis CLAUDE.md → {SORTIE}")


if __name__ == "__main__":
    main()
