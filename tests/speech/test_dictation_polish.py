"""La dictée corrige l'écriture, pas le propos.

Trois défauts empilés empêchaient toute correction d'atteindre le texte
collé, chacun silencieux :

1. La dictée de bureau — celle qu'on utilise vraiment — n'appelait pas
   ``polish_pipeline`` du tout, seulement le dictionnaire.
2. ``llm_polish_text`` dépaquetait mal ``get_engine``, qui rend
   ``(nom, moteur)`` : il gardait le tuple, sans ``engine_id`` ni
   ``is_cloud``.
3. Le garde local-only, voyant un moteur non identifié, appliquait sa règle
   « un moteur inconnu n'est pas local » et refusait — correctement. Le
   polissage était donc mort par une erreur de dépaquetage, et le refus
   parfaitement expliqué dans un journal que personne ne lisait.
"""

from __future__ import annotations

import pytest

from diapason.cli.dictate_cmd import _correction_fidele


class TestUneCorrectionNeReecritPasLaPhrase:
    """Le prompt interdit d'inventer, mais un prompt est un vœu. Sur une
    phrase mal transcrite, un petit modèle résume, complète, ou répond à la
    question au lieu de la corriger."""

    def test_les_accents_et_la_ponctuation_passent(self):
        assert _correction_fidele("bonjour comment ca va", "Bonjour, comment ça va ?")

    def test_une_reponse_a_la_place_d_une_correction_est_ecartee(self):
        """Le cas qui fait mal : le modèle répond au lieu de corriger."""
        assert not _correction_fidele(
            "quelle heure est-il",
            "Il est actuellement 14 h 32, heure de l'Est. Souhaitez-vous "
            "que je programme un rappel pour plus tard dans la journée ?",
        )

    def test_un_resume_est_ecarte(self):
        assert not _correction_fidele(
            "je voudrais savoir si le rapport dont on a parlé hier soir "
            "pendant la réunion est prêt pour demain matin",
            "Rapport prêt ?",
        )

    def test_une_correction_vide_est_ecartee(self):
        """Perdre le texte est le pire résultat possible."""
        assert not _correction_fidele("bonjour comment ca va", "")
        assert not _correction_fidele("bonjour comment ca va", "   ")

    def test_un_brut_vide_accepte_ce_qui_vient(self):
        assert _correction_fidele("", "Bonjour.")

    @pytest.mark.parametrize(
        "brut,corrige",
        [
            ("ca va", "Ça va ?"),
            ("le rapport est pret", "Le rapport est prêt."),
            ("envoie moi le fichier", "Envoie-moi le fichier."),
        ],
    )
    def test_les_corrections_ordinaires_passent(self, brut, corrige):
        assert _correction_fidele(brut, corrige)


class TestLeDepaquetageDuMoteur:
    """``get_engine`` rend ``(nom, moteur)``. Garder le tuple donnait un objet
    sans ``engine_id`` ni ``is_cloud``, que le garde local-only classait
    « distant » — et refusait, correctement."""

    def test_un_couple_est_depaquete(self):
        from diapason.speech.llm_polish import _unwrap_engine

        class Moteur:
            engine_id = "ollama"

        m = Moteur()
        assert _unwrap_engine(("ollama", m)) is m

    def test_un_moteur_nu_passe_tel_quel(self):
        from diapason.speech.llm_polish import _unwrap_engine

        class Moteur:
            engine_id = "ollama"

        m = Moteur()
        assert _unwrap_engine(m) is m

    def test_un_couple_vide_ne_donne_rien(self):
        from diapason.speech.llm_polish import _unwrap_engine

        assert _unwrap_engine(()) is None
        assert _unwrap_engine(None) is None

    def test_un_moteur_non_identifie_reste_refuse(self):
        """La règle fail-closed qui a rendu le défaut visible : elle ne doit
        pas être assouplie pour faire passer le polissage."""
        from diapason.core.local_mode import engine_is_local

        class Inconnu:
            pass

        assert engine_is_local(Inconnu()) is False
        assert engine_is_local(None) is False


class TestHomophonesDeCommande:
    """« mets de la musique » → « mais de la musique » chez TOUS les modèles
    Whisper (mesuré le 23 août 2026). En tête d'ordre, « mais » + article est
    le verbe ; ailleurs, la conjonction reste intouchée."""

    def test_le_mais_de_tete_redevient_mets(self):
        from diapason.speech.dictate_polish import reparer_homophones_de_commande

        assert reparer_homophones_de_commande("mais de la musique") == "mets de la musique"
        assert reparer_homophones_de_commande("Mais de la musique.") == "Mets de la musique."
        assert (
            reparer_homophones_de_commande("Diapason, mais de la musique")
            == "Diapason, mets de la musique"
        )
        assert reparer_homophones_de_commande("mais du jazz") == "mets du jazz"

    def test_la_vraie_conjonction_reste_intouchee(self):
        from diapason.speech.dictate_polish import reparer_homophones_de_commande

        for phrase in (
            "je veux bien, mais la musique est trop forte",
            "mais pourquoi tu dis ça",
            "il pleut mais on sort",
        ):
            assert reparer_homophones_de_commande(phrase) == phrase

    def test_la_dictee_passe_par_la_reparation(self):
        from diapason.speech.dictate_polish import polish_dictation

        assert polish_dictation("mais de la musique") == "Mets de la musique."
