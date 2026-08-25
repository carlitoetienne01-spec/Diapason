"""Les gestes d'une seconde — chaque outil constate au lieu de proclamer.

Atlas, 24 août 2026 : « monte le son » passait par shell_exec, donc par la
cloche — deux minutes d'attente possibles pour un geste d'une seconde. Et la
régression spotify_play (« the model told the user the music was on while
nothing played ») impose la règle : après la commande, on relit l'état réel.
"""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from diapason.tools.gestes import (
    ClipboardReadTool,
    MediaControlTool,
    ScreenSnapTool,
    SystemVitalsTool,
    VolumeControlTool,
    formater_disque,
    interpreter_etat_lecteur,
    interpreter_volume,
    interpreter_wifi,
    lecteur_en_marche,
)


def _cp(
    stdout: str = "", code: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], code, stdout, stderr)


class TestInterpretes:
    def test_le_volume_se_lit_avec_le_muet(self):
        assert interpreter_volume("62, false") == (62, False)
        assert interpreter_volume("0, true") == (0, True)
        assert interpreter_volume("n'importe quoi") == (None, False)

    def test_l_etat_du_lecteur_se_lit_avec_la_piste(self):
        assert interpreter_etat_lecteur("playing\nPapaoutai — Stromae") == (
            "playing",
            "Papaoutai — Stromae",
        )
        assert interpreter_etat_lecteur("") == ("", "")

    def test_le_wifi_se_lit_ou_dit_ce_qui_reste_constatable(self):
        """macOS caviarde le SSID sans permission Localisation : « connecté »
        vaut mieux qu'un mensonge « pas de réseau » (constaté 24/08/2026)."""
        assert interpreter_wifi("  SSID : MaisonNet\n", "") == "Wi-Fi : MaisonNet"
        assert interpreter_wifi("  SSID : <redacted>\n", "192.168.0.121\n") == (
            "Réseau : connecté"
        )
        assert interpreter_wifi("", "") == "pas de réseau"

    def test_le_disque_parle_en_go_decimaux(self):
        assert formater_disque(210_000_000_000, 494_000_000_000) == (
            "210 Go libres sur 494"
        )


class TestVolume:
    def test_monter_le_son_relit_le_volume_reel(self):
        """Constater, ne pas proclamer : la phrase vient de la RELECTURE."""
        with (
            patch("diapason.tools.gestes.sys.platform", "darwin"),
            patch(
                "diapason.tools.gestes._run",
                side_effect=[_cp(""), _cp("70, false")],
            ) as run,
        ):
            resultat = VolumeControlTool().execute(action="up")
        assert resultat.success
        assert resultat.content == "Volume à 70 %."
        premier = run.call_args_list[0][0][0]
        assert premier[:2] == ["osascript", "-e"] and "+ 10" in premier[2]

    def test_couper_le_son_le_dit(self):
        with (
            patch("diapason.tools.gestes.sys.platform", "darwin"),
            patch(
                "diapason.tools.gestes._run",
                side_effect=[_cp(""), _cp("70, true")],
            ),
        ):
            resultat = VolumeControlTool().execute(action="mute")
        assert resultat.content == "Son coupé."

    def test_set_borne_le_niveau(self):
        with (
            patch("diapason.tools.gestes.sys.platform", "darwin"),
            patch(
                "diapason.tools.gestes._run",
                side_effect=[_cp(""), _cp("100, false")],
            ) as run,
        ):
            VolumeControlTool().execute(action="set", level=250)
        assert "set volume output volume 100" in run.call_args_list[0][0][0][2]

    def test_un_niveau_illisible_est_refuse(self):
        with patch("diapason.tools.gestes.sys.platform", "darwin"):
            resultat = VolumeControlTool().execute(action="set", level="fort")
        assert not resultat.success

    def test_hors_mac_refuse_sans_lever(self):
        with patch("diapason.tools.gestes.sys.platform", "linux"):
            resultat = VolumeControlTool().execute(action="up")
        assert not resultat.success and "macOS" in resultat.content


class TestMediaControl:
    def test_le_lecteur_en_marche_se_constate_par_pgrep(self):
        vus = []

        def runner(cmd, **_kw):
            vus.append(cmd)
            return _cp(code=0 if cmd == ["pgrep", "-x", "Music"] else 1)

        assert lecteur_en_marche(runner) == "Music"
        assert ["pgrep", "-x", "Spotify"] in vus  # Spotify d'abord

    def test_pause_puis_relecture_de_l_etat_reel(self):
        """La régression spotify_play ne se rejoue pas : l'état vient du
        lecteur, pas de la commande."""
        with (
            patch("diapason.tools.gestes.sys.platform", "darwin"),
            patch("diapason.tools.gestes.lecteur_en_marche", return_value="Spotify"),
            patch(
                "diapason.tools.gestes._run",
                side_effect=[_cp(""), _cp("paused\nPapaoutai — Stromae")],
            ) as run,
        ):
            resultat = MediaControlTool().execute(action="pause")
        assert resultat.content == "En pause sur Spotify."
        assert 'tell application "Spotify" to pause' in run.call_args_list[0][0][0][2]

    def test_la_lecture_annonce_la_piste(self):
        with (
            patch("diapason.tools.gestes.sys.platform", "darwin"),
            patch("diapason.tools.gestes.lecteur_en_marche", return_value="Music"),
            patch(
                "diapason.tools.gestes._run",
                side_effect=[_cp(""), _cp("playing\nKompa Love — Harmonik")],
            ),
        ):
            resultat = MediaControlTool().execute(action="play")
        assert resultat.content == "Lecture : Kompa Love — Harmonik (Music)."
        assert resultat.metadata["track"] == "Kompa Love — Harmonik"

    def test_aucun_lecteur_pointe_le_repli_exact(self):
        """Le message d'échec nomme l'appel de repli, écrit POUR le modèle."""
        with (
            patch("diapason.tools.gestes.sys.platform", "darwin"),
            patch("diapason.tools.gestes.lecteur_en_marche", return_value=None),
        ):
            resultat = MediaControlTool().execute(action="playpause")
        assert not resultat.success
        assert "spotify_play" in resultat.content

    def test_aucun_tell_ne_part_sans_lecteur_constate(self):
        """Un tell vers une app éteinte la LANCERAIT : sans lecteur, zéro
        osascript."""
        with (
            patch("diapason.tools.gestes.sys.platform", "darwin"),
            patch("diapason.tools.gestes.lecteur_en_marche", return_value=None),
            patch("diapason.tools.gestes._run") as run,
        ):
            MediaControlTool().execute(action="next")
        run.assert_not_called()


class TestClipboardRead:
    def test_le_texte_copie_revient_tronque_au_besoin(self):
        with (
            patch("diapason.tools.gestes.sys.platform", "darwin"),
            patch("diapason.desktop.clipboard.lire_texte", return_value="x" * 1000),
        ):
            resultat = ClipboardReadTool().execute()
        assert resultat.success and resultat.metadata["truncated"]
        assert "1000 caractères" in resultat.content

    def test_un_presse_papiers_sans_texte_se_dit(self):
        with (
            patch("diapason.tools.gestes.sys.platform", "darwin"),
            patch("diapason.desktop.clipboard.lire_texte", return_value=None),
        ):
            resultat = ClipboardReadTool().execute()
        assert resultat.success and resultat.metadata["empty"]

    def test_pas_de_cloche_c_est_un_arbitrage_assume(self):
        assert ClipboardReadTool().spec.requires_confirmation is False, (
            "Lecture locale tronquée : la cloche tuerait le geste à la voix "
            "(arbitrage documenté dans le spec, 24 août 2026)"
        )


class TestScreenSnap:
    def test_la_capture_part_sur_le_bureau_horodatee(self, tmp_path, monkeypatch):
        source = tmp_path / "brut.png"
        source.write_bytes(b"\x89PNG")
        monkeypatch.setattr("pathlib.Path.home", staticmethod(lambda: tmp_path))
        (tmp_path / "Desktop").mkdir()
        with (
            patch("diapason.tools.gestes.sys.platform", "darwin"),
            patch(
                "diapason.desktop.screen_capture.capture_screen_to_temp",
                return_value=str(source),
            ),
        ):
            resultat = ScreenSnapTool().execute()
        assert resultat.success
        depose = list((tmp_path / "Desktop").glob("Capture Diapason *.png"))
        assert len(depose) == 1
        assert resultat.metadata["path"] == str(depose[0])

    def test_le_refus_screen_recording_remonte_au_modele(self):
        with (
            patch("diapason.tools.gestes.sys.platform", "darwin"),
            patch(
                "diapason.desktop.screen_capture.capture_screen_to_temp",
                side_effect=RuntimeError("Grant Screen Recording to Diapason"),
            ),
        ):
            resultat = ScreenSnapTool().execute()
        assert not resultat.success and "Screen Recording" in resultat.content


class TestSystemVitals:
    def test_les_trois_lectures_en_une_phrase(self):
        pmset = "Now drawing from 'Battery Power'\n -InternalBattery-0 82%; discharging; 4:20 remaining"  # noqa: E501 - sortie réelle de pmset, reproduite telle quelle
        with (
            patch("diapason.tools.gestes.sys.platform", "darwin"),
            patch(
                "diapason.tools.gestes._run",
                side_effect=[
                    _cp(pmset),
                    _cp("  SSID : MaisonNet\n"),
                    _cp("192.168.0.5\n"),
                ],
            ),
        ):
            resultat = SystemVitalsTool().execute()
        assert resultat.success
        assert "Batterie 82 % (en décharge)" in resultat.content
        assert "Wi-Fi : MaisonNet" in resultat.content
        assert "Go libres sur" in resultat.content

    def test_pmset_plante_se_dit_illisible_pas_absent(self):
        """None de lire_batterie confond panne et absence — pas ici."""
        with (
            patch("diapason.tools.gestes.sys.platform", "darwin"),
            patch(
                "diapason.tools.gestes._run",
                side_effect=[_cp("", code=1), _cp(""), _cp("")],
            ),
        ):
            resultat = SystemVitalsTool().execute()
        assert "batterie illisible" in resultat.content
        assert "pas de batterie" not in resultat.content

    def test_un_mac_de_bureau_dit_sur_secteur(self):
        with (
            patch("diapason.tools.gestes.sys.platform", "darwin"),
            patch(
                "diapason.tools.gestes._run",
                side_effect=[_cp("Now drawing from 'AC Power'\n"), _cp(""), _cp("")],
            ),
        ):
            resultat = SystemVitalsTool().execute()
        assert "sur secteur (pas de batterie interne)" in resultat.content


class TestRegistrationEtRegimes:
    def test_les_cinq_gestes_sont_dans_les_deux_trousses(self):
        from diapason.server.routes import _TROUSSE_ASSISTANT
        from diapason.speech.realtime.tools import (
            DEFAULT_VOICE_TOOL_IDS,
            list_voice_tool_ids,
        )

        for outil in (
            "volume_control",
            "media_control",
            "clipboard_read",
            "screen_snap",
            "system_vitals",
        ):
            assert outil in _TROUSSE_ASSISTANT
            assert outil in DEFAULT_VOICE_TOOL_IDS
            # list_voice_tool_ids passe par _TOOL_MODULES après le clear()
            # du conftest : c'est LE piège des outils fantômes à la voix.
            assert outil in list_voice_tool_ids()

    @pytest.mark.parametrize(
        "outil",
        [VolumeControlTool, MediaControlTool, ScreenSnapTool, SystemVitalsTool],
    )
    def test_un_geste_visible_et_reversible_ne_sonne_pas(self, outil):
        assert outil().spec.requires_confirmation is False, (
            "La jurisprudence open_anything : gater un geste d'une seconde "
            "coûte un clic et jusqu'à 45 s à la voix"
        )

    def test_tous_locaux_pour_survivre_a_local_only(self):
        for outil in (
            VolumeControlTool,
            MediaControlTool,
            ClipboardReadTool,
            ScreenSnapTool,
            SystemVitalsTool,
        ):
            assert outil.is_local is True
