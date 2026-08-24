"""Les onglets : lister, activer, jamais fermer — et jamais lancer une app.

Atlas, 24 août 2026. La fermeture est ABSENTE du périmètre : irréversible,
et les index se décalent à chaque fermeture. Le tell ne part que vers un
navigateur de la liste blanche, constaté en marche par pgrep.
"""

from __future__ import annotations

import subprocess
from unittest.mock import patch

from diapason.tools.browser_tabs import (
    BrowserTabsTool,
    interpreter_onglets,
    navigateur_en_marche,
)


def _cp(stdout: str = "", code: int = 0, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], code, stdout, stderr)


class TestInterpretation:
    def test_les_lignes_se_lisent_avec_le_separateur(self):
        sortie = "1␟1␟Gmail — Boîte␟https://mail.google.com\n1␟2␟YouTube␟https://youtube.com\n"
        onglets = interpreter_onglets(sortie)
        assert onglets == [
            {"fenetre": 1, "onglet": 1, "titre": "Gmail — Boîte", "url": "https://mail.google.com"},
            {"fenetre": 1, "onglet": 2, "titre": "YouTube", "url": "https://youtube.com"},
        ]

    def test_une_ligne_difforme_se_saute(self):
        assert interpreter_onglets("n'importe quoi\n") == []


class TestGarde:
    def test_aucun_navigateur_pointe_open_anything(self):
        with patch("diapason.tools.browser_tabs.sys.platform", "darwin"), patch(
            "diapason.tools.browser_tabs.navigateur_en_marche", return_value=None
        ), patch("diapason.tools.browser_tabs._run") as run:
            r = BrowserTabsTool().execute(action="list")
        assert not r.success and "open_anything" in r.content
        run.assert_not_called()  # aucun tell ne part sans navigateur constaté

    def test_le_navigateur_se_constate_par_pgrep(self):
        vus = []

        def runner(cmd, **_kw):
            vus.append(cmd)
            return _cp(code=0 if "Brave Browser" in cmd else 1)

        assert navigateur_en_marche(runner) == "Brave Browser"
        assert vus[0] == ["pgrep", "-x", "Safari"]


class TestActions:
    def test_lister_rend_les_index_et_les_titres(self):
        with patch("diapason.tools.browser_tabs.sys.platform", "darwin"), patch(
            "diapason.tools.browser_tabs.navigateur_en_marche",
            return_value="Safari",
        ), patch(
            "diapason.tools.browser_tabs._run",
            return_value=_cp("1␟1␟Gmail␟https://mail.google.com\n"),
        ):
            r = BrowserTabsTool().execute(action="list")
        assert r.success
        assert "[1.1] Gmail" in r.content
        assert r.metadata["tabs"][0]["url"] == "https://mail.google.com"

    def test_activer_constate_l_onglet_devenu_actif(self):
        with patch("diapason.tools.browser_tabs.sys.platform", "darwin"), patch(
            "diapason.tools.browser_tabs.navigateur_en_marche",
            return_value="Safari",
        ), patch(
            "diapason.tools.browser_tabs._run", return_value=_cp("Gmail — Boîte\n")
        ) as run:
            r = BrowserTabsTool().execute(action="activate", window=1, tab=2)
        assert r.success and "Gmail — Boîte" in r.content
        script = run.call_args[0][0][2]
        assert "window 1" in script and "tab 2" in script

    def test_activer_sans_index_renvoie_vers_list(self):
        with patch("diapason.tools.browser_tabs.sys.platform", "darwin"), patch(
            "diapason.tools.browser_tabs.navigateur_en_marche",
            return_value="Safari",
        ):
            r = BrowserTabsTool().execute(action="activate")
        assert not r.success and "list" in r.content

    def test_fermer_n_existe_pas(self):
        spec = BrowserTabsTool().spec
        assert spec.parameters["properties"]["action"]["enum"] == ["list", "activate"]
