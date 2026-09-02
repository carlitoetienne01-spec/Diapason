"""Où dorment les tirages moissonnés.

Une base par domaine, comme partout ailleurs dans ce projet, et le schéma se
crée à l'ouverture — il n'existe aucune migration ici.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

from diapason.core.paths import get_config_dir
from diapason.loterie.tirages import Tirage

_SCHEMA = """
CREATE TABLE IF NOT EXISTS loterie_tirages (
    jour TEXT PRIMARY KEY,
    numeros TEXT NOT NULL,
    grand_numero INTEGER NOT NULL,
    moissonne_le TEXT NOT NULL
);
"""


class DepotTirages:
    """Les tirages, indexés par leur jour.

    Le JOUR est la clé primaire, et c'est voulu : moissonner deux fois la même
    page ne doit pas créer deux fois le même tirage. Un `INSERT OR REPLACE`
    rend la moisson rejouable sans précaution.
    """

    def __init__(self, chemin: str | Path | None = None) -> None:
        self.chemin = Path(chemin) if chemin else get_config_dir() / "loterie.db"
        self.chemin.parent.mkdir(parents=True, exist_ok=True)
        with self._ouvrir() as conn:
            conn.executescript(_SCHEMA)

    def _ouvrir(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.chemin)
        conn.row_factory = sqlite3.Row
        return conn

    def enregistrer(self, tirages: list[Tirage]) -> int:
        """Poser ces tirages. Rend le nombre de jours NOUVEAUX."""
        if not tirages:
            return 0
        with self._ouvrir() as conn:
            avant = conn.execute(
                "SELECT COUNT(*) AS n FROM loterie_tirages"
            ).fetchone()["n"]
            conn.executemany(
                """INSERT OR REPLACE INTO loterie_tirages
                   (jour, numeros, grand_numero, moissonne_le)
                   VALUES (?,?,?,?)""",
                [
                    (
                        t.jour.isoformat(),
                        ",".join(str(n) for n in t.numeros),
                        t.grand_numero,
                        date.today().isoformat(),
                    )
                    for t in tirages
                ],
            )
            conn.commit()
            apres = conn.execute(
                "SELECT COUNT(*) AS n FROM loterie_tirages"
            ).fetchone()["n"]
        return apres - avant

    def tous(self) -> list[Tirage]:
        """Tous les tirages, du plus ancien au plus récent."""
        with self._ouvrir() as conn:
            lignes = conn.execute(
                "SELECT jour, numeros, grand_numero FROM loterie_tirages ORDER BY jour"
            ).fetchall()
        return [
            Tirage(
                jour=date.fromisoformat(ligne["jour"]),
                numeros=tuple(int(x) for x in ligne["numeros"].split(",")),
                grand_numero=int(ligne["grand_numero"]),
            )
            for ligne in lignes
        ]

    def dernier_jour(self) -> date | None:
        with self._ouvrir() as conn:
            ligne = conn.execute(
                "SELECT MAX(jour) AS j FROM loterie_tirages"
            ).fetchone()
        return date.fromisoformat(ligne["j"]) if ligne and ligne["j"] else None

    def compte(self) -> int:
        with self._ouvrir() as conn:
            return conn.execute("SELECT COUNT(*) AS n FROM loterie_tirages").fetchone()[
                "n"
            ]
