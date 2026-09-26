"""Les rappels du téléphone se lisent sur le Mac, dans la forme que le Mac rend.

26/09/2026, phase 3 étape 9 (docs/development/diapason-mobile.md). Après
l'import de sa Life OS, le téléphone planifie ses notifications à partir de
``/v1/vie`` (tâches ouvertes, ``reminderTime`` des habitudes, coches), par un
adaptateur. Sans lui, retirer la Life OS coupait les rappels sans rien dire
(§5) ; mal porté, il rappellerait à la mauvaise heure.

``test/rappels/vie_rappels.json`` (dépôt mobile) est la réponse du Mac à
l'état ``test/rappels/etat_rappels.json`` écrit par le vrai Dart ; le test
Dart ``adaptateur_rappels_test.dart`` exige que l'adaptateur en tire les
mêmes heures que l'ancien ``LifeOsState``. Ici : que ce fichier soit bien ce
que ces routes rendent AUJOURD'HUI — un champ renommé côté Mac le fait
échouer, au lieu de laisser le Dart éprouver une forme périmée. Hors CI, un
dépôt mobile absent est un ÉCHEC, pas un saut.
"""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import re

import pytest

RACINE = pathlib.Path(__file__).resolve().parents[2]
MOBILE = pathlib.Path.home() / "Projets/diapason_mobile"


def _generateur():
    spec = importlib.util.spec_from_file_location(
        "gen_vie_rappels", RACINE / "scripts/gen_vie_rappels.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _en_ci() -> bool:
    return os.environ.get("CI", "").strip().lower() not in ("", "0", "false")


def _lire(relatif: str) -> str:
    chemin = MOBILE / relatif
    try:
        return chemin.read_text(encoding="utf-8")
    except OSError:
        if _en_ci():
            pytest.skip(f"{chemin} absent du runner de CI")
        pytest.fail(
            f"{chemin} introuvable. Le dépôt mobile doit vivre dans {MOBILE} ; "
            "hors CI, son absence n'est pas un saut."
        )


class TestLaReponseDuMacLivreeAuTelephoneEstLaVraie:
    """§5 : un adaptateur éprouvé sur une forme périmée ne prouve rien."""

    def test_le_fichier_livre_est_ce_que_les_routes_rendent(self):
        gen = _generateur()
        etat = json.loads(_lire(gen.ETAT))
        assert _lire(gen.SORTIE) == gen.rendre(etat), (
            "vie_rappels.json ne correspond plus à ce que /v1/vie rend pour "
            "etat_rappels.json : relance scripts/gen_vie_rappels.py et le test "
            "Dart adaptateur_rappels_test.dart, dans le même thème."
        )

    def test_il_porte_les_cas_que_l_adaptateur_doit_tenir(self):
        gen = _generateur()
        reponses = json.loads(_lire(gen.SORTIE))
        taches = reponses["taches"]["corps"]["tasks"]
        habitudes = reponses["habitudes"]["corps"]["habits"]
        assert {t["id"] for t in taches} == {
            "rappel-arrosage",
            "rappel-sans-heure",
            "rappel-soir",
            "rappel-sans-date",
        }, "les tâches ouvertes, et pas la tâche faite (include_done=false)"
        assert {h["reminderTime"] for h in habitudes} == {"07:15", "", "19:00"}, (
            "une heure explicite, une vide (rappel par défaut), une hebdomadaire"
        )
        assert reponses["coches"]["corps"]["logs"], "des coches à relire"

    def test_les_lectures_sont_celles_de_l_adaptateur(self):
        """Les chemins et paramètres sont ceux de ``LecteurDesRappels.lire`` :
        le fichier Dart les cite, un paramètre changé d'un seul côté se voit."""
        gen = _generateur()
        dart = _lire("lib/services/vie/rappels_du_mac.dart")
        for _nom, chemin, requete in gen.LECTURES:
            assert f"'{chemin}'" in dart, f"{chemin} n'est plus lu par l'adaptateur"
            for cle, valeur in requete.items():
                assert f"'{cle}'" in dart, f"le paramètre {cle} manque au Dart"
                # 26/09/2026, contre-épreuve : seuls les NOMS étaient lus ;
                # `'include_done': 'true'` côté Dart laissait ce test vert. Une
                # valeur écrite en dur dans le Dart doit être celle du
                # générateur ; une valeur calculée (`'from': du`) ne se lit
                # pas ici, et le banc live_rappels.dart la montre.
                litterales = re.findall(rf"'{re.escape(cle)}':\s*'([^']*)'", dart)
                assert all(v == valeur for v in litterales), (
                    f"{cle} vaut {litterales} dans le Dart et {valeur!r} dans "
                    "le générateur : les rappels ne liraient pas ce que le "
                    "fichier commun prouve"
                )
                if cle == "include_done":
                    assert litterales == [valeur], (
                        "include_done doit être écrit en dur, et égal au générateur"
                    )
