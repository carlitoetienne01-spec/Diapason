"""Les écrans qu'une route du maillage peut nommer, tenus d'accord dans trois langues.

25/09/2026. Trois tables disent quels écrans une route `success://…` ouvre :
``PATHS`` dans ``frontend/src/features/mesh/routes.ts`` (la fenêtre du
bureau), ``_views`` dans ``lib/services/mesh/mesh_routes.dart`` (le
téléphone) et ``MESH_ROUTE_KINDS`` dans ``mesh/executor.py`` (le récepteur
Python, qui répond à l'émetteur AVANT que la fenêtre n'ouvre quoi que ce
soit). Rien ne les liait : une clé ajoutée d'un côté seulement donnait
« Écran ouvert » en Python et rien à l'écran, ou l'inverse — UNSUPPORTED pour
un écran que la fenêtre sait ouvrir.

Ces tests lisent les deux fichiers sources tels quels : pas de copie à tenir
à jour, qui dériverait à son tour.
"""

from __future__ import annotations

import os
import pathlib
import re

import pytest

from diapason.mesh.executor import _MESH_ROUTE, MESH_ROUTE_KINDS

RACINE = pathlib.Path(__file__).resolve().parents[2]
ROUTES_TS = RACINE / "frontend/src/features/mesh/routes.ts"

# Le dépôt Flutter, à côté — le même chemin, et la même règle, que
# test_succes_client_contract.py : hors CI, son absence est un ÉCHEC.
MOBILE = pathlib.Path.home() / "Projets/diapason_mobile"
MESH_ROUTES_DART = MOBILE / "lib/services/mesh/mesh_routes.dart"


def _en_ci() -> bool:
    return os.environ.get("CI", "").strip().lower() not in ("", "0", "false")


def _source_dart() -> str:
    """Le fichier Dart — ou un échec qui le dit.

    Seule la CI a le droit de s'en passer : le runner n'a que Diapason.
    Ailleurs, un saut maquillerait « contrat non vérifié » en « contrat
    respecté ».
    """
    try:
        return MESH_ROUTES_DART.read_text(encoding="utf-8")
    except OSError:
        if _en_ci():
            pytest.skip(f"{MESH_ROUTES_DART} absent du runner de CI")
        pytest.fail(
            f"{MESH_ROUTES_DART} introuvable ou illisible. Le dépôt mobile doit "
            f"vivre dans {MOBILE} ; hors CI, son absence n'est pas un saut."
        )


def _bloc(source: str, ouverture: str) -> str:
    """Le corps d'un littéral de table, de son ouverture à la première `};`."""
    debut = source.find(ouverture)
    assert debut >= 0, f"« {ouverture} » introuvable : la table a changé de forme"
    fin = source.find("};", debut)
    assert fin > debut, f"fin de « {ouverture} » introuvable"
    return source[debut + len(ouverture) : fin]


def cles_ts(source: str) -> set[str]:
    return set(
        re.findall(
            r"^\s*([a-z]+)\s*:",
            _bloc(source, "const PATHS: Record<string, string> = {"),
            re.M,
        )
    )


def cles_dart(source: str) -> set[str]:
    return set(
        re.findall(
            r"^\s*'([a-z]+)'\s*:", _bloc(source, "const _views = <String, int>{"), re.M
        )
    )


def _schemas(motif: str) -> set[str]:
    """`{success}` pour `^success://…`, `{success, vie}` pour
    `^(?:success|vie)://…` : l'alternative qui précède le premier `:`."""
    tete = re.match(r"\^?(?:\(\?:([a-z|]+)\)|([a-z]+)):", motif, re.I)
    assert tete, f"schéma illisible dans le motif « {motif} »"
    return set((tete.group(1) or tete.group(2)).lower().split("|"))


def motif_ts(source: str) -> str:
    return re.search(r"const SUCCESS_ROUTE = /(.+)/i;", source).group(1)


def motif_dart(source: str) -> str:
    return re.search(r"r'(\^[^']+)'", _bloc_regex_dart(source)).group(1)


def _bloc_regex_dart(source: str) -> str:
    debut = source.find("final _pattern = RegExp(")
    assert debut >= 0, "le motif Dart a changé de forme"
    return source[debut : source.find(");", debut)]


class TestLesTroisTablesDisentLesMemesEcrans:
    """§100 : le récepteur Python répond à l'émetteur au nom de la fenêtre."""

    def test_la_table_du_bureau_est_celle_de_python(self):
        ts = cles_ts(ROUTES_TS.read_text(encoding="utf-8"))
        assert ts == set(MESH_ROUTE_KINDS), (
            "routes.ts (PATHS) et mesh/executor.py (MESH_ROUTE_KINDS) divergent :\n"
            f"  seulement dans routes.ts : {sorted(ts - MESH_ROUTE_KINDS)}\n"
            f"  seulement en Python : {sorted(MESH_ROUTE_KINDS - ts)}\n"
            "Python annoncerait « Écran ouvert » pour un écran que la fenêtre "
            "n'ouvre pas, ou refuserait un écran qu'elle sait ouvrir."
        )

    def test_la_table_du_telephone_est_celle_de_python(self):
        dart = cles_dart(_source_dart())
        assert dart == set(MESH_ROUTE_KINDS), (
            "mesh_routes.dart (_views) et mesh/executor.py divergent :\n"
            f"  seulement en Dart : {sorted(dart - MESH_ROUTE_KINDS)}\n"
            f"  seulement en Python : {sorted(MESH_ROUTE_KINDS - dart)}"
        )

    def test_les_trois_acceptent_les_memes_schemas(self):
        """L'étape 12 fera accepter `vie://` aux trois récepteurs à la fois ;
        un seul en retard donnerait « route inconnue » d'un côté seulement."""
        python = _schemas(_MESH_ROUTE.pattern)
        ts = _schemas(motif_ts(ROUTES_TS.read_text(encoding="utf-8")))
        dart = _schemas(motif_dart(_source_dart()))
        assert python == ts == dart, (
            f"schémas acceptés — Python : {sorted(python)}, TypeScript : "
            f"{sorted(ts)}, Dart : {sorted(dart)}"
        )


class TestLaLectureDesSourcesNeSeTaitPas:
    """Un extracteur qui ne trouve rien rendrait les tests ci-dessus vrais
    pour de mauvaises raisons — ou faux sans dire pourquoi."""

    def test_l_extracteur_ts_trouve_les_cinq_ecrans(self):
        assert len(cles_ts(ROUTES_TS.read_text(encoding="utf-8"))) == 5, (
            "cinq écrans attendus dans PATHS : today, tasks, projects, habits, notes"
        )

    def test_une_cle_retiree_de_routes_ts_se_voit(self):
        source = ROUTES_TS.read_text(encoding="utf-8")
        # `notes:` figure aussi dans SELECTABLE ; celle de PATHS mène à un chemin.
        amputee = re.sub(r"^\s*notes:\s*'/.*\n", "", source, count=1, flags=re.M)
        assert amputee != source, "la ligne « notes: » de PATHS a changé de forme"
        assert cles_ts(amputee) != set(MESH_ROUTE_KINDS), (
            "retirer « notes » de routes.ts doit faire diverger les tables"
        )

    def test_une_cle_retiree_du_dart_se_voit(self):
        source = _source_dart()
        amputee = re.sub(r"^\s*'notes':.*\n", "", source, count=1, flags=re.M)
        assert amputee != source, "la ligne « 'notes': » de _views a changé de forme"
        assert cles_dart(amputee) != set(MESH_ROUTE_KINDS)

    def test_les_schemas_se_lisent_aussi_sous_leur_forme_a_venir(self):
        assert _schemas(r"^(?:success|vie)://([a-z]+)") == {"success", "vie"}
        assert _schemas(r"^success:\/\/([a-z]+)") == {"success"}
