"""Les écrans qu'une route du maillage peut nommer, tenus d'accord dans trois langues.

25/09/2026. Trois tables disent quels écrans une route `success://…` ouvre :
``PATHS`` dans ``frontend/src/features/mesh/routes.ts`` (la fenêtre du
bureau), ``_chemins`` dans ``lib/services/mesh/mesh_routes.dart`` (le
téléphone ; ``_views`` jusqu'au 26/09/2026, quand la coquille a remplacé la
Life OS native) et ``MESH_ROUTE_KINDS`` dans ``mesh/executor.py`` (le récepteur
Python, qui répond à l'émetteur AVANT que la fenêtre n'ouvre quoi que ce
soit). Rien ne les liait : une clé ajoutée d'un côté seulement donnait
« Écran ouvert » en Python et rien à l'écran, ou l'inverse — UNSUPPORTED pour
un écran que la fenêtre sait ouvrir.

Ces tests lisent les deux fichiers sources tels quels : pas de copie à tenir
à jour, qui dériverait à son tour.

26/09/2026, phase 3 étape 9 : au téléphone, c'est la coquille qui traduit la
route en CHEMIN React avant de demander l'écran au bundle (verbe
« naviguer »). Les clés ne suffisent plus à tenir les tables d'accord : un
chemin mal porté ferait acquitter une navigation vers une page qui n'affiche
pas la cible. D'où ``vecteurs_routes.json``, écrit à la main à côté de
``routes.ts`` et copié à l'identique dans le dépôt mobile : vitest et
``flutter test`` le lisent contre leur table, et ce fichier exige les deux
copies égales et le récepteur Python d'accord sur ce qui est refusé.
"""

from __future__ import annotations

import json
import os
import pathlib
import re

import pytest

from diapason.mesh.executor import _MESH_ROUTE, MESH_ROUTE_KINDS, parse_mesh_route

RACINE = pathlib.Path(__file__).resolve().parents[2]
ROUTES_TS = RACINE / "frontend/src/features/mesh/routes.ts"
VECTEURS = RACINE / "frontend/src/features/mesh/vecteurs_routes.json"

# Le dépôt Flutter, à côté — le même chemin, et la même règle, que
# test_succes_client_contract.py : hors CI, son absence est un ÉCHEC.
MOBILE = pathlib.Path.home() / "Projets/diapason_mobile"
MESH_ROUTES_DART = MOBILE / "lib/services/mesh/mesh_routes.dart"
VECTEURS_DART = MOBILE / "test/mesh/vecteurs_routes.json"


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


_TABLE_DART = "const _chemins = <String, String>{"


def cles_dart(source: str) -> set[str]:
    return set(chemins_dart(source))


def chemins_dart(source: str) -> dict[str, str]:
    return dict(
        re.findall(r"^\s*'([a-z]+)'\s*:\s*'([^']+)'", _bloc(source, _TABLE_DART), re.M)
    )


def chemins_ts(source: str) -> dict[str, str]:
    bloc = _bloc(source, "const PATHS: Record<string, string> = {")
    brut = dict(re.findall(r"^\s*([a-z]+)\s*:\s*([^,\n]+),", bloc, re.M))
    # `today: MESH_ROUTE_TODAY` : la constante, résolue dans le même fichier.
    constantes = dict(re.findall(r"export const ([A-Z_]+) = '([^']+)';", source))
    return {
        cle: constantes.get(valeur.strip(), valeur.strip().strip("'"))
        for cle, valeur in brut.items()
    }


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
            "mesh_routes.dart (_chemins) et mesh/executor.py divergent :\n"
            f"  seulement en Dart : {sorted(dart - MESH_ROUTE_KINDS)}\n"
            f"  seulement en Python : {sorted(MESH_ROUTE_KINDS - dart)}"
        )

    def test_les_trois_acceptent_les_memes_schemas(self):
        """L'étape 12 (25/09/2026) fait accepter `vie://` aux trois récepteurs
        à la fois ; un seul en retard donnerait « route inconnue » d'un côté
        seulement."""
        python = _schemas(_MESH_ROUTE.pattern)
        ts = _schemas(motif_ts(ROUTES_TS.read_text(encoding="utf-8")))
        dart = _schemas(motif_dart(_source_dart()))
        assert python == ts == dart, (
            f"schémas acceptés — Python : {sorted(python)}, TypeScript : "
            f"{sorted(ts)}, Dart : {sorted(dart)}"
        )

    def test_les_deux_schemas_restent_acceptes(self):
        """Tant qu'un émetteur peut encore écrire `success://` (le téléphone,
        une app de bureau non reconstruite) et qu'un autre écrit déjà
        `vie://`, retirer l'un des deux d'un récepteur — même des trois à la
        fois, ce que le test précédent laisserait passer — rendrait
        UNSUPPORTED à une route que l'émetteur croit valide."""
        assert _schemas(_MESH_ROUTE.pattern) == {"success", "vie"}, (
            "le récepteur Python doit accepter success:// ET vie:// (plan 1b, "
            "étape 12) ; diapason:// reste exclu"
        )


def _corps_canonique(motif: str) -> str:
    """Le motif sans ses ancres ni l'échappement de `/` propre au littéral
    JavaScript : `fullmatch` en Python vaut `^…$` ailleurs."""
    corps = motif.replace("\\/", "/")
    if corps.startswith("^"):
        corps = corps[1:]
    if corps.endswith("$"):
        corps = corps[:-1]
    return corps


def drapeaux_ts(source: str) -> str:
    return re.search(r"const SUCCESS_ROUTE = /.+/([a-z]*);", source).group(1)


class TestLesTroisMotifsSontLeMeme:
    """25/09/2026 : le test des schémas ne comparait que l'alternative avant
    `:`. Contre-épreuve : un Dart sans `caseSensitive: false` (D3), ou dont
    le chemin s'élargit à `([a-z_0-9]+)` (D4), laissait tout vert — alors que
    le commentaire d'executor.py promet le même motif « character for
    character ». Flutter ne tourne pas dans la CI de Diapason : ce test est le
    seul à voir le Dart depuis ici."""

    def test_le_corps_du_motif_est_identique_dans_les_trois_langues(self):
        python = _corps_canonique(_MESH_ROUTE.pattern)
        ts = _corps_canonique(motif_ts(ROUTES_TS.read_text(encoding="utf-8")))
        dart = _corps_canonique(motif_dart(_source_dart()))
        assert python == ts == dart, (
            f"motifs divergents —\n  Python : {python}\n  TypeScript : {ts}\n"
            f"  Dart : {dart}"
        )

    def test_les_trois_ignorent_la_casse_sans_repli_unicode(self):
        """Insensible à la casse partout (`VIE://tasks` s'ouvre), mais sans
        repli Unicode : `ſuccess://` ne doit valoir `success://` nulle part.
        JavaScript `/iu` et Dart `unicode: true` replieraient ſ en s."""
        drapeaux = _MESH_ROUTE.flags
        assert drapeaux & re.I and drapeaux & re.ASCII, (
            "Python : re.I | re.ASCII attendus"
        )
        assert drapeaux_ts(ROUTES_TS.read_text(encoding="utf-8")) == "i", (
            "routes.ts : le drapeau /i seul (ni u, ni v)"
        )
        dart = _bloc_regex_dart(_source_dart())
        assert re.search(r"caseSensitive:\s*false", dart), (
            "mesh_routes.dart : caseSensitive: false manque — VIE://tasks y "
            "serait refusé, accepté ailleurs"
        )
        assert "unicode:" not in dart, "mesh_routes.dart : pas de repli Unicode"


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
        assert amputee != source, "la ligne « 'notes': » de _chemins a changé de forme"
        assert cles_dart(amputee) != set(MESH_ROUTE_KINDS)

    def test_la_normalisation_ne_confond_que_les_ecritures_equivalentes(self):
        assert _corps_canonique(r"^a:\/\/b$") == _corps_canonique("a://b")
        assert _corps_canonique(r"^a://([a-z]+)$") != _corps_canonique(
            r"^a://([a-z_0-9]+)$"
        ), "un chemin élargi doit rester visible"

    def test_les_schemas_se_lisent_aussi_sous_leur_forme_a_venir(self):
        assert _schemas(r"^(?:success|vie)://([a-z]+)") == {"success", "vie"}
        assert _schemas(r"^success:\/\/([a-z]+)") == {"success"}


def _vecteurs() -> dict:
    return json.loads(VECTEURS.read_text(encoding="utf-8"))


def _vecteurs_dart() -> str:
    """La copie du dépôt mobile — ou un échec qui le dit (même règle que la
    source Dart : hors CI, son absence n'est pas un saut)."""
    try:
        return VECTEURS_DART.read_text(encoding="utf-8")
    except OSError:
        if _en_ci():
            pytest.skip(f"{VECTEURS_DART} absent du runner de CI")
        pytest.fail(
            f"{VECTEURS_DART} introuvable. Copie-le depuis {VECTEURS} : les "
            "deux fichiers doivent être identiques."
        )


class TestLesVecteursCommunsDesRoutes:
    """§100, phase 3 étape 9 : la coquille acquitte SUCCESS à l'appareil qui a
    demandé l'écran ; elle doit ouvrir LE chemin que la fenêtre ouvrirait."""

    def test_la_copie_du_telephone_est_identique(self):
        assert _vecteurs_dart() == VECTEURS.read_text(encoding="utf-8"), (
            f"{VECTEURS_DART} diffère de {VECTEURS} : recopie-le, à l'octet "
            "près, dans le même thème que le changement qui l'a causé."
        )

    def test_le_recepteur_python_refuse_ce_que_les_deux_autres_refusent(self):
        for v in _vecteurs()["vecteurs"]:
            refusee = parse_mesh_route(v["route"]) is None
            assert refusee == (v["path"] is None), (
                f"{v['route']!r} : Python la dit "
                f"{'refusée' if refusee else 'acceptée'}, les vecteurs "
                f"{'refusée' if v['path'] is None else 'vers ' + v['path']}"
            )

    def test_le_dart_et_routes_ts_donnent_les_memes_chemins(self):
        ts = chemins_ts(ROUTES_TS.read_text(encoding="utf-8"))
        dart = chemins_dart(_source_dart())
        assert ts == dart, f"chemins divergents —\n  routes.ts : {ts}\n  Dart : {dart}"
        assert set(ts.values()) == {
            v["path"] for v in _vecteurs()["vecteurs"] if v["path"]
        }, "chaque écran de la table doit figurer dans les vecteurs"

    def test_l_extracteur_des_chemins_ne_se_tait_pas(self):
        ts = chemins_ts(ROUTES_TS.read_text(encoding="utf-8"))
        assert ts.get("today") == "/vie/planner", (
            "MESH_ROUTE_TODAY doit être résolue, pas lue comme un nom"
        )
        assert len(ts) == 5
