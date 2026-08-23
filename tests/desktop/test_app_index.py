"""Le nom PARLÉ doit trouver l'application SUR DISQUE.

macOS affiche des noms français dans le Finder mais range les applications
sous leur nom anglais — « Musique » est Music.app, « Réglages Système » est
System Settings.app — et ``open -a`` n'accepte que le nom sur disque.
Constaté le 23 août 2026 : « ouvre-moi Apple TV » échouait (l'application
s'appelle TV.app), et tout nom français échouait avec elle. L'assistant est
parlé en français ; sans cette résolution, la moitié du Mac lui était fermée.
"""

from __future__ import annotations

import pytest

from diapason.desktop.app_index import MacAppIndex

# (nom sur disque, nom affiché en français lu dans le bundle — ou None)
_INSTALLEES = (
    ("TV", None),
    ("Music", "Musique"),
    ("System Settings", "Réglages Système"),
    ("Calendar", "Calendrier"),
    ("Maps", "Plans"),
    ("Preview", "Aperçu"),
    ("Podcasts", "Podcasts"),
    ("VoiceMemos", "Dictaphone"),
    ("Phone", "Téléphone"),
    ("Terminal", None),
    ("QuickTime Player", None),
    ("Safari", None),
    ("Photo Booth", None),
    ("Visual Studio Code", None),
    ("Chess", "Échecs"),
    ("Activity Monitor", "Moniteur d’activité"),
    ("Finder", None),
)


@pytest.fixture()
def index(monkeypatch):
    idx = MacAppIndex()
    monkeypatch.setattr(idx, "_scan", staticmethod(lambda: _INSTALLEES))
    return idx


@pytest.mark.parametrize(
    "parle,attendu",
    [
        ("Apple TV", "TV"),
        ("apple tv", "TV"),
        ("télé", "TV"),
        ("Musique", "Music"),
        ("Apple Music", "Music"),
        ("Réglages", "System Settings"),
        ("réglages système", "System Settings"),
        ("préférences système", "System Settings"),
        ("Calendrier", "Calendar"),
        ("Plans", "Maps"),
        ("Aperçu", "Preview"),
        ("Balados", "Podcasts"),
    ],
)
def test_le_nom_francais_trouve_l_application(index, parle, attendu):
    assert index.resolve(parle) == attendu


def test_l_alias_retrouve_un_nom_de_fichier_colle(index):
    """« Voice Memos » est VoiceMemos.app sur disque : l'alias doit recoller."""
    assert index.resolve("Dictaphone") == "VoiceMemos"


def test_un_mot_au_milieu_d_un_autre_ne_mord_pas(index):
    """« phone » vit au milieu de « dictaphone » : l'inclusion brute rendait
    Phone.app pour le Dictaphone."""
    assert index.resolve("dictaphone") != "Phone"


def test_le_nom_exact_gagne_toujours(index):
    assert index.resolve("Safari") == "Safari"
    assert index.resolve("Photo Booth") == "Photo Booth"


def test_le_nom_partiel_trouve_le_plus_court(index):
    assert index.resolve("QuickTime") == "QuickTime Player"
    assert index.resolve("visual studio") == "Visual Studio Code"


def test_un_inconnu_est_rendu_tel_quel_pour_launch_services(index):
    """Launch Services connaît des applications hors des dossiers balayés."""
    assert index.resolve("Blender") == "Blender"


def test_le_suffixe_app_est_toléré(index):
    assert index.resolve("Musique.app") == "Music"


class TestLookupStrict:
    """``lookup`` dit si l'application est RÉELLEMENT installée.

    ``resolve`` rend le nom brut quand rien ne correspond — utile pour Launch
    Services, mais inutilisable pour décider « l'installé gagne sur le web » :
    il fallait un verdict franc. C'est lui qui fait passer « Ouvre ChatGPT »
    par l'application installée plutôt que par chatgpt.com dans un onglet.
    """

    def test_un_installe_est_trouve(self, index):
        assert index.lookup("Apple TV") == "TV"

    def test_un_absent_rend_none_et_non_le_nom_brut(self, index):
        assert index.lookup("Blender") is None
        assert index.resolve("Blender") == "Blender"


class TestCommandesVocales:
    """Le routage parlé : l'installé en chemin rapide, le web en repli."""

    @pytest.fixture(autouse=True)
    def _index_fige(self, monkeypatch):
        from diapason.desktop.app_index import APP_INDEX

        monkeypatch.setattr(
            APP_INDEX,
            "_scan",
            staticmethod(
                lambda: (
                    ("Mail", None),
                    ("ChatGPT", None),
                    ("Xcode", None),
                    ("TV", None),
                )
            ),
        )
        APP_INDEX.refresh()
        yield
        APP_INDEX.refresh()

    def test_ouvre_chatgpt_prend_l_application_pas_le_site(self):
        """Constaté le 23 août 2026 : « ChatGPT ne s'ouvre pas » — le raccourci
        web chatgpt.com passait avant l'application installée."""
        from diapason.desktop.voice_commands import parse_voice_command

        a = parse_voice_command("ouvre chatgpt")
        assert (a.kind, a.target) == ("focus_app", "ChatGPT")

    def test_le_de_de_l_application_ne_survit_pas(self):
        """« l'application DE ChatGPT » donnait la cible « de ChatGPT »."""
        from diapason.desktop.voice_commands import parse_voice_command

        a = parse_voice_command("ouvre l'application de ChatGPT")
        assert (a.kind, a.target) == ("focus_app", "ChatGPT")

    def test_toute_application_installee_part_en_chemin_rapide(self):
        """Xcode n'est dans aucune table écrite à la main : l'index suffit."""
        from diapason.desktop.voice_commands import parse_voice_command

        a = parse_voice_command("ouvre xcode")
        assert (a.kind, a.target) == ("focus_app", "Xcode")

    def test_un_site_sans_application_reste_du_web(self):
        from diapason.desktop.voice_commands import parse_voice_command

        a = parse_voice_command("ouvre youtube")
        assert a.kind == "open_uri"
        assert "youtube" in a.target

class TestNomsAffiches:
    """Le nom FRANÇAIS que le Finder montre — « Échecs » est Chess.app.

    Mesuré le 23 août 2026 : vingt-trois noms affichés sur quatre-vingt-sept
    étaient injoignables — un quart du Mac. Une table écrite à la main ne
    gagne jamais cette course ; le bundle porte le nom, on le lit.
    """

    def test_le_nom_affiche_trouve_l_application(self, index):
        assert index.lookup("Échecs") == "Chess"
        assert index.lookup("échecs") == "Chess"

    def test_l_apostrophe_typographique_rencontre_la_droite(self, index):
        """macOS écrit « Moniteur d'activité » avec ' ; la voix dicte '."""
        assert index.lookup("moniteur d'activité") == "Activity Monitor"

    def test_l_article_parle_tombe_naturellement(self, index):
        assert index.lookup("le Finder") == "Finder"

    def test_apres_l_audit_complet_le_vrai_disque_repond(self):
        """Sur la machine réelle : les cas rapportés comme injoignables."""
        from diapason.desktop.app_index import APP_INDEX

        APP_INDEX.refresh()
        for parle, attendu in (
            ("le dictionnaire", "Dictionary"),
            ("les raccourcis", "Shortcuts"),
            ("aide-mémoire", "Stickies"),
        ):
            assert APP_INDEX.lookup(parle) == attendu


class TestEtageFlou:
    """La transcription déforme les noms ; le flou rattrape, sans deviner.

    Mesuré le 23 août 2026 : neuf déformations réalistes sur quatorze
    rataient — « safary », « cursore », « gitub desktop », « x-code »…
    """

    @pytest.mark.parametrize(
        "deforme,attendu",
        [
            ("safary", "Safari"),
            ("x-code", None),  # absent de ce faux index — voir plus bas
            ("photo bout", "Photo Booth"),
        ],
    )
    def test_les_deformations_realistes(self, index, deforme, attendu):
        assert index.lookup(deforme) == attendu

    def test_deux_candidats_proches_font_refuser(self, monkeypatch):
        """Ouvrir la mauvaise application est pire qu'avouer ne pas savoir."""
        idx = MacAppIndex()
        monkeypatch.setattr(
            idx, "_scan", staticmethod(lambda: (("Slack", None), ("Slick", None)))
        )
        assert idx.lookup("slock") is None

    def test_un_nom_court_n_est_jamais_devine(self, index):
        """Sous cinq caractères, le flou ferait n'importe quoi."""
        assert index.lookup("tvv") is None
