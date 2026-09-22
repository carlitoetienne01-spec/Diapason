"""Écrit la référence d'API et le script d'installation sur le DISQUE.

22 septembre 2026. Ces deux pages étaient fabriquées en mémoire par
``mkdocs-gen-files`` pendant la construction. Le site est devenu bilingue, et
``mkdocs-static-i18n`` ne voit pas les fichiers virtuels : la référence d'API
disparaissait du site, avec 1 606 avertissements « not found in the
documentation files » — quel que soit l'ordre des deux greffons.

Les fichiers sont donc écrits avant la construction. Ils ne sont pas versionnés
(voir .gitignore) : ils se régénèrent à chaque publication, comme avant.

    .venv/bin/python scripts/gen_reference_docs.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
SRC = RACINE / "src"
REFERENCE = RACINE / "docs" / "api-reference"


def _chemins_de_modules() -> list[tuple[tuple[str, ...], Path]]:
    """(parties du module, chemin de la page) pour chaque module public."""
    sorties: list[tuple[tuple[str, ...], Path]] = []
    for chemin in sorted(SRC.rglob("*.py")):
        parties = chemin.relative_to(SRC).with_suffix("").parts
        page = chemin.relative_to(SRC).with_suffix(".md")
        if parties[-1] == "__init__":
            parties = parties[:-1]
            page = page.with_name("index.md")
        elif parties[-1].startswith("_"):
            continue
        if not parties:
            continue
        sorties.append((parties, page))
    return sorties


def _sommaire(entrees: list[tuple[tuple[str, ...], Path]]) -> str:
    """Le SUMMARY.md que lit literate-nav.

    Un vrai arbre : un paquet apparaît UNE fois, lié à son index.md quand il
    en a un. La première version émettait le nœud puis sa page d'index, et
    « diapason » figurait deux fois de suite dans la navigation (22/09).
    """
    pages: dict[tuple[str, ...], Path] = {p: page for p, page in entrees}
    branches: set[tuple[str, ...]] = set()
    for parties in pages:
        for profondeur in range(1, len(parties)):
            branches.add(parties[:profondeur])

    lignes: list[str] = []

    def descendre(prefixe: tuple[str, ...]) -> None:
        enfants = sorted(
            {
                p[: len(prefixe) + 1]
                for p in {*pages, *branches}
                if p[: len(prefixe)] == prefixe and len(p) > len(prefixe)
            }
        )
        for enfant in enfants:
            marge = "    " * (len(enfant) - 1)
            page = pages.get(enfant)
            nom = enfant[-1]
            if page is not None:
                lignes.append(f"{marge}* [{nom}]({page.as_posix()})")
            else:
                lignes.append(f"{marge}* {nom}")
            descendre(enfant)

    descendre(())
    return "\n".join(lignes) + "\n"


def main() -> int:
    if not SRC.is_dir():
        print(f"✗ {SRC} introuvable", file=sys.stderr)
        return 1

    # Repartir d'un dossier propre : un module supprimé ne doit pas laisser sa
    # page derrière lui.
    if REFERENCE.exists():
        shutil.rmtree(REFERENCE)
    REFERENCE.mkdir(parents=True)

    entrees = _chemins_de_modules()
    for parties, page in entrees:
        destination = REFERENCE / page
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(f"::: {'.'.join(parties)}\n", encoding="utf-8")

    (REFERENCE / "SUMMARY.md").write_text(_sommaire(entrees), encoding="utf-8")

    # Le script d'installation, servi tel quel depuis le site.
    source = RACINE / "scripts" / "install.sh"
    if source.is_file():
        (RACINE / "docs" / "install.sh").write_bytes(source.read_bytes())

    print(f"  {len(entrees)} pages de référence + SUMMARY.md dans docs/api-reference/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
