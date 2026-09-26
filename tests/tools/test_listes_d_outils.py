"""Le test-fusible des listes d'outils : un nom cité doit exister.

25/09/2026. Six listes nomment des outils par une chaîne, et chacune écarte
en silence un nom que le registre ne connaît pas : ``_chat_tooling`` (au
niveau DEBUG), ``list_voice_tool_ids`` (un filtre), le préchargement de
``trousse_chat`` (une clé absente ne précharge rien), et le prompt vocal, qui
promet au modèle un outil qu'on ne lui donnera pas. Le renommage
``succes_*`` → ``vie_*`` (étape 7 du plan de la phase 1b) touche toutes ces
listes à la fois : une seule oubliée retirait un outil à la voix ou au chat
sans que rien ne le signale.

Le premier passage de ce test a trouvé un cas RÉEL : ``geste_deposer``,
dans la trousse du chat depuis le 25 août 2026, n'était enregistré que par le
chargeur de la voix. Le chat l'écartait donc — sauf si une session vocale
avait eu lieu avant le premier message.

Le contrôle tourne dans un interpréteur NEUF : la fixture autouse de
``tests/conftest.py`` vide le registre avant chaque test, et les modules déjà
importés ne rejouent pas leurs décorateurs. Un processus neuf qui fait
exactement ce que fait le serveur est la seule reproduction fidèle.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_SONDE = r"""
import json, re

import diapason.tools  # ce que fait _chat_tooling, et rien de plus
from diapason.core.registry import ToolRegistry
from diapason.server import trousse_chat
from diapason.server.routes import _TROUSSE_ASSISTANT
from diapason.speech.realtime import oral_prompt
from diapason.speech.realtime import tools as voix


def absents(noms):
    return sorted({n for n in noms if not ToolRegistry.contains(n)})


gras = []
for ligne in oral_prompt.TOOL_ORAL_HINT.splitlines():
    if ligne.startswith("- **"):
        # Seule la tête de la puce nomme des outils : « **draft** » dans une
        # description n'en est pas un.
        gras += re.findall(r"\*\*([a-z_]+)\*\*", ligne.split(" — ")[0])

rapport = {
    "chat": absents(_TROUSSE_ASSISTANT),
    "groupes": absents(n for _, noms in trousse_chat._GROUPES for n in noms),
    "lectures": absents(trousse_chat._LECTURES),
    "prompt_vocal": absents(gras),
    "nombre_gras": len(gras),
}

# La voix charge sa table en plus du paquet : c'est son chemin réel.
voix._ensure_desktop_tools_loaded()
rapport["voix"] = absents(voix.DEFAULT_VOICE_TOOL_IDS)
rapport["prompt_vocal_hors_voix"] = sorted(
    set(gras) - set(voix.DEFAULT_VOICE_TOOL_IDS)
)

# Chaque ligne de la table de chargement doit désigner la classe qui porte
# réellement ce nom : un renommage à moitié (clé neuve, classe ancienne, ou
# module déplacé) serait sinon sauté par `_ensure_desktop_tools_loaded`,
# qui ne le journalise qu'en DEBUG.
table = []
for module, entrees in voix._TOOL_MODULES:
    try:
        mod = __import__(module, fromlist=[a for _, a in entrees])
    except Exception as exc:
        table += [f"{module} : import impossible ({type(exc).__name__})"]
        continue
    for cle, attribut in entrees:
        classe = getattr(mod, attribut, None)
        if classe is None:
            table.append(f"{module}.{attribut} n'existe pas (clé {cle})")
        elif ToolRegistry.get(cle) is not classe:
            table.append(f"{cle} n'est pas enregistré sous {module}.{attribut}")
        elif (nom := classe().spec.name) != cle:
            table.append(f"{module}.{attribut} s'appelle {nom}, pas {cle}")
rapport["table_vocale"] = table
print("RAPPORT=" + json.dumps(rapport))
"""


@pytest.fixture(scope="module")
def rapport(tmp_path_factory) -> dict:
    foyer = tmp_path_factory.mktemp("foyer-fusible")
    racine_src = Path(__file__).resolve().parents[2] / "src"
    env = {
        **os.environ,
        # Le foyer temporaire : importer des outils ne doit rien écrire dans
        # le vrai ~/.diapason.
        "DIAPASON_HOME": str(foyer),
        # Le code de CET arbre, pas celui qu'un venv éditable désigne.
        "PYTHONPATH": os.pathsep.join(
            [str(racine_src), os.environ.get("PYTHONPATH", "")]
        ).rstrip(os.pathsep),
    }
    sortie = subprocess.run(
        [sys.executable, "-c", _SONDE],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert sortie.returncode == 0, f"la sonde a échoué :\n{sortie.stderr[-3000:]}"
    ligne = next(
        (x for x in sortie.stdout.splitlines() if x.startswith("RAPPORT=")), None
    )
    assert ligne, f"la sonde n'a rien rendu :\n{sortie.stdout[-2000:]}"
    return json.loads(ligne.removeprefix("RAPPORT="))


class TestChaqueNomCiteExiste:
    """Un outil retiré d'une liste disparaissait sans un mot."""

    def test_la_trousse_du_chat(self, rapport):
        assert rapport["chat"] == [], (
            f"_TROUSSE_ASSISTANT (server/routes.py) cite {rapport['chat']}, que "
            "`import diapason.tools` n'enregistre pas : le chat les écarte en "
            "silence. Importe leur module dans diapason/tools/__init__.py."
        )

    def test_les_groupes_de_prechargement(self, rapport):
        assert rapport["groupes"] == [], (
            f"_GROUPES (server/trousse_chat.py) précharge {rapport['groupes']}, "
            "qui n'existent pas : la phrase qui les amorce n'amorce plus rien"
        )

    def test_les_lectures(self, rapport):
        assert rapport["lectures"] == [], (
            f"_LECTURES (server/trousse_chat.py) cite {rapport['lectures']}"
        )

    def test_la_liste_de_la_voix(self, rapport):
        assert rapport["voix"] == [], (
            f"DEFAULT_VOICE_TOOL_IDS cite {rapport['voix']}, introuvables même "
            "après le chargeur de la voix : list_voice_tool_ids les filtre sans "
            "rien dire"
        )

    def test_la_table_de_chargement_de_la_voix(self, rapport):
        assert rapport["table_vocale"] == [], (
            "_TOOL_MODULES (speech/realtime/tools.py) :\n  "
            + "\n  ".join(rapport["table_vocale"])
        )

    def test_les_noms_en_gras_du_prompt_vocal(self, rapport):
        assert rapport["prompt_vocal"] == [], (
            f"TOOL_ORAL_HINT promet au modèle {rapport['prompt_vocal']}, qui "
            "n'existent pas"
        )

    def test_le_prompt_vocal_ne_promet_que_des_outils_de_la_voix(self, rapport):
        """Un outil nommé au modèle mais absent de la liste vocale reçoit
        « Tool not allowed in voice mode » — la promesse est pire que
        l'absence."""
        assert rapport["prompt_vocal_hors_voix"] == [], (
            f"TOOL_ORAL_HINT nomme {rapport['prompt_vocal_hors_voix']}, absents "
            "de DEFAULT_VOICE_TOOL_IDS"
        )

    def test_la_sonde_lit_vraiment_le_prompt(self, rapport):
        """Un extracteur qui ne trouve rien rendrait les deux tests précédents
        vrais pour de mauvaises raisons."""
        assert rapport["nombre_gras"] >= 30, (
            f"{rapport['nombre_gras']} noms en gras seulement : le format des "
            "puces de TOOL_ORAL_HINT a changé"
        )
