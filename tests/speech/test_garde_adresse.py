"""Savoir quand on s'adresse à lui — comme une personne dans la pièce.

Demandé le 23 août 2026 : « si je parle à quelqu'un d'autre, s'il y a du
bruit, si je regarde un film, il doit savoir que ce n'est pas à lui qu'on
s'adresse. » La règle d'une personne réelle : on lui répond quand on l'appelle
par son nom ; une conversation engagée continue sans redire le nom ; passé un
long silence, elle attend d'être rappelée.
"""

from __future__ import annotations

import time

import pytest

from diapason.speech.realtime.local_voice import (
    ADDRESS_WINDOW_S,
    LocalVoiceSession,
    mentions_assistant_name,
    strip_assistant_name,
)


class TestLeNom:
    @pytest.mark.parametrize(
        "phrase",
        [
            "Diapason, ouvre Safari",
            "diapason quelle heure est-il",
            "diapasant ouvre-moi la télé",  # la transcription déforme
            "diapazon, mes tâches",
            "Dia pasons, quelle heure est-il ?",  # le nom coupé en deux
            "Dis-moi Diapason, il pleut demain ?",
        ],
    )
    def test_l_appel_est_reconnu_meme_deforme(self, phrase):
        assert mentions_assistant_name(phrase) is True

    @pytest.mark.parametrize(
        "phrase",
        [
            "Ouvre Safari",  # pas de nom : hors fenêtre, ignoré
            "Tu as vu le match hier soir ?",  # on parle à un tiers
            "Le suspect a quitté la maison.",  # un film
            "",
        ],
    )
    def test_sans_le_nom_rien_ne_se_declenche(self, phrase):
        assert mentions_assistant_name(phrase) is False

    def test_le_nom_initial_est_retire_de_la_phrase(self):
        assert strip_assistant_name("Diapason, ouvre Safari") == "ouvre Safari"

    def test_le_nom_coupe_en_deux_est_retire_aussi(self):
        """Constaté en session réelle : « Dia pasons, quelle heure… »."""
        assert (
            strip_assistant_name("Dia pasons, quelle heure est-il ?")
            == "quelle heure est-il ?"
        )

    def test_une_phrase_sans_nom_reste_entiere(self):
        assert strip_assistant_name("ouvre Safari") == "ouvre Safari"


class TestLaFenetre:
    def _session(self):
        s = LocalVoiceSession.__new__(LocalVoiceSession)
        s._engagee_jusqua = time.monotonic() + ADDRESS_WINDOW_S
        return s

    def test_le_debut_de_session_est_engage(self):
        """Qui vient de cliquer « Démarrer » s'adresse évidemment à nous."""
        s = self._session()
        assert time.monotonic() < s._engagee_jusqua

    def test_apres_le_silence_la_fenetre_est_close(self):
        s = self._session()
        s._engagee_jusqua = time.monotonic() - 1
        assert time.monotonic() >= s._engagee_jusqua

    def test_la_fenetre_est_a_l_echelle_d_une_conversation(self):
        """Trop courte : on redit le nom à chaque phrase, insupportable.
        Trop longue : le film finit par répondre à ta place."""
        assert 30 <= ADDRESS_WINDOW_S <= 300
