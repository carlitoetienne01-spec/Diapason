"""Agir DANS une application : chercher, écrire — pas seulement ouvrir.

Demandé de vive voix le 23 août 2026 : « quand je lui demande d'ouvrir
l'App Store, je peux lui demander ensuite de chercher des jeux… des fois mes
mains ne sont pas libres. » Chaque destination utilise son mécanisme natif,
mesuré avant d'être retenu — le pilotage d'interface (⌘F puis frapper) a été
essayé sur l'App Store et il échoue en silence, capture d'écran à l'appui.

Ici, aucun AppleScript ne part vraiment : les doublures capturent les appels.
"""

from __future__ import annotations

import pytest

from diapason.tools import app_actions
from diapason.tools.app_actions import AppSearchTool, NotesWriteTool, _normaliser_app


@pytest.fixture()
def espion(monkeypatch):
    appels: dict[str, list] = {"open": [], "script": []}
    monkeypatch.setattr(
        app_actions, "_ouvrir", lambda url: (appels["open"].append(url), (True, ""))[1]
    )
    monkeypatch.setattr(
        app_actions,
        "_osascript",
        lambda script, *a: (appels["script"].append(a), (True, "ok"))[1],
    )
    return appels


class TestNormalisation:
    """La transcription rend « l'App Store », « apple store », « Notes »…"""

    @pytest.mark.parametrize(
        "parle,attendu",
        [
            ("App Store", "app_store"),
            ("l'App Store", "app_store"),
            ("apple store", "app_store"),
            ("Spotify", "spotify"),
            ("mes notes", "notes"),
            ("Notes", "notes"),
            ("le navigateur", "web"),
            ("Google", "web"),
            ("LinkedIn", None),
        ],
    )
    def test_les_variantes_orales(self, parle, attendu):
        assert _normaliser_app(parle) == attendu


class TestAppSearch:
    def test_app_store_passe_par_son_lien_profond(self, espion):
        """Le ⌘F échouait en silence ; le lien affiche « Résultats pour … »."""
        r = AppSearchTool().execute(app="l'App Store", query="jeux gratuits")
        assert r.success
        assert espion["open"] == [
            "macappstore://search.itunes.apple.com/WebObjects/MZSearch.woa"
            "/wa/search?q=jeux+gratuits"
        ]

    def test_spotify_passe_par_son_uri(self, espion):
        r = AppSearchTool().execute(app="Spotify", query="jazz")
        assert r.success
        assert espion["open"] == ["spotify:search:jazz"]

    def test_une_destination_inconnue_part_sur_le_web_en_le_disant(
        self, espion, monkeypatch
    ):
        """Retourné le 23 août 2026 : le refus sec laissait l'utilisateur sans
        rien — « certaines recherches, il n'arrive pas à les faire ». Le repli
        web agit, et l'honnêteté est sauve : la réponse dit où la recherche
        est réellement partie."""
        from diapason.tools import desktop_tools

        ouverts = []

        def faux_navigateur(url, **kw):
            ouverts.append(url)
            from diapason.tools._stubs import ToolResult

            return ToolResult(tool_name="open_uri", content="", success=True)

        monkeypatch.setattr(desktop_tools, "open_in_browser", faux_navigateur)
        r = AppSearchTool().execute(app="LinkedIn", query="offres python")
        assert r.success is True
        assert "sur le web" in r.content
        assert "LinkedIn" in r.content, "dire OÙ la recherche est partie"
        assert len(ouverts) == 1 and "offres" in ouverts[0]

    def test_sans_quoi_chercher_le_refus_est_franc(self, espion):
        r = AppSearchTool().execute(app="Spotify", query="  ")
        assert r.success is False
        assert espion["open"] == []

    def test_notes_rend_le_compte_et_les_titres(self, monkeypatch):
        monkeypatch.setattr(
            app_actions,
            "_osascript",
            lambda script, *a: (True, "2\nCourses\nIdées cadeaux"),
        )
        r = AppSearchTool().execute(app="Notes", query="courses")
        assert r.success
        assert r.metadata["count"] == 2
        assert r.metadata["titles"] == ["Courses", "Idées cadeaux"]

    def test_notes_sans_resultat_le_dit_sans_échouer(self, monkeypatch):
        monkeypatch.setattr(app_actions, "_osascript", lambda script, *a: (True, "0"))
        r = AppSearchTool().execute(app="Notes", query="licorne")
        assert r.success and "Aucune note" in r.content


class TestNotesWrite:
    def test_le_texte_part_en_argv_jamais_dans_le_script(self, monkeypatch):
        """Un titre contenant « " & quit & " » ne doit jamais devenir du code."""
        recus = []

        def espion(script, *a):
            recus.append((script, a))
            return True, "ok"

        monkeypatch.setattr(app_actions, "_osascript", espion)
        piege = 'x" & do shell script "say pwned" & "'
        NotesWriteTool().execute(action="create", title=piege, text="corps")
        script, args = recus[0]
        assert piege not in script, "le texte utilisateur s'est interpolé dans le code"
        assert args == (piege, "corps")

    def test_ajouter_a_une_note_absente_propose_de_la_creer(self, monkeypatch):
        monkeypatch.setattr(
            app_actions, "_osascript", lambda script, *a: (True, "absent")
        )
        r = NotesWriteTool().execute(action="append", title="Courses", text="lait")
        assert r.success is False
        assert "créer" in r.content

    def test_une_action_inconnue_est_refusee(self):
        r = NotesWriteTool().execute(action="delete", title="X", text="y")
        assert r.success is False


class TestEnchainement:
    """« Ouvre l'App Store » puis « recherche-moi des jeux » — sans redire où."""

    def test_la_recherche_scopee_est_extraite_de_la_phrase(self):
        from diapason.desktop.voice_commands import parse_voice_command

        a = parse_voice_command("Recherche-moi des jeux sur l'App Store")
        assert a.kind == "app_search"
        assert a.target == "des jeux"
        assert (a.extra or {}).get("app") == "App Store"

    def test_une_recherche_sans_destination_reste_du_web(self):
        from diapason.desktop.voice_commands import parse_voice_command

        a = parse_voice_command("Cherche la météo à Montréal")
        assert a.kind == "search"


class TestConstatApresRecherche:
    """La parole suit le constat (Atlas, 24 août 2026) : « résultats à
    l'écran » ne se dit que si l'app est réellement venue devant."""

    def _chercher(self, monkeypatch, devant):
        import diapason.tools.app_actions as m

        monkeypatch.setattr(m, "_ouvrir", lambda _u: (True, ""))
        monkeypatch.setattr(m, "_constater_devant", lambda app, **_k: devant)
        from diapason.tools.app_actions import AppSearchTool

        return AppSearchTool().execute(app="app store", query="solitaire")

    def test_le_constat_positif_se_dit(self, monkeypatch):
        r = self._chercher(monkeypatch, True)
        assert r.success and "à l'écran dans l'App Store" in r.content
        assert r.metadata["verifie"] is True

    def test_l_echec_de_mise_devant_s_avoue(self, monkeypatch):
        r = self._chercher(monkeypatch, False)
        assert r.success  # la recherche EST partie
        assert "n'est pas venue devant" in r.content
        assert r.metadata["verifie"] is False
