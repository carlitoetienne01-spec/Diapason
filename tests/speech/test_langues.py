"""Détection, bascule et prononciation du kreyòl à la voix.

29/09/2026 : la consigne « Answer in {langue} » figeait la réponse, et
Orion, réglé sur le français, avalait les consonnes finales du kreyòl
(« tèt » sans t, « gen » lu « jen »). Ces tests tiennent la langue
dominante, le tour ambigu, et le guide phonétique — sans prétendre
qu'un modèle acoustique kreyòl est installé.
"""

from __future__ import annotations

import pytest

from diapason.speech.langues import (
    CONSIGNE_PERMANENTE,
    GUIDE_PHONETIQUE,
    MemoireLinguistique,
    basculer,
    consigne_anglais,
    consigne_francais,
    consigne_kreyol,
    detecter,
    forme_ecrite,
    forme_orale,
    vitesse,
)
from diapason.speech.realtime.local_voice import LocalVoiceSession


class TestDetection:
    def test_une_phrase_kreyol_est_kreyol(self):
        vu = detecter("Mwen la, sa k ap fèt ?")
        assert vu.code == "ht", "la phrase kreyòl ne doit pas partir en français"
        assert vu.certaine is True

    def test_une_phrase_francaise_reste_francaise(self):
        vu = detecter("Bonjour, comment ça va ?")
        assert vu.code == "fr", "le français courant ne doit pas basculer"
        assert vu.certaine is True

    def test_une_phrase_anglaise_est_anglaise(self):
        vu = detecter("How are you today?")
        assert vu.code == "en"
        assert vu.certaine is True

    def test_la_phrase_mixte_suit_la_langue_dominante(self):
        assert detecter("Mwen byen, sa k ap fèt, merci.").code == "ht"
        assert detecter("Bonjour, je voulais juste dire mèsi.").code == "fr"
        assert detecter("Please tell me how this works, mèsi.").code == "en"

    def test_wi_oui_et_yes_ne_se_confondent_pas(self):
        assert detecter("wi").code == "ht"
        assert detecter("oui").code == "fr"
        assert detecter("yes").code == "en"

    def test_un_mot_court_ambigu_garde_la_memoire(self):
        memoire = MemoireLinguistique("ht")
        vu = detecter("ok", memoire)
        assert vu.code == "ht", "« ok » ne doit pas ramener le français"
        assert vu.certaine is False

    def test_sans_memoire_l_ambigu_reste_francais(self):
        vu = detecter("ok")
        assert vu.code == "fr"
        assert vu.certaine is False

    def test_une_egalite_ne_devine_pas(self):
        vu = detecter("bonjour mèsi", MemoireLinguistique("en"))
        assert vu.certaine is False
        assert vu.code == "en", "l'égalité garde la langue précédente"

    def test_le_o_ouvert_inconnu_compte_pour_le_kreyol(self):
        assert detecter("bò").code == "ht", "ò n'est pas une voyelle française courante"


class TestBascule:
    def test_le_switch_est_immediat_puis_le_court_suit(self):
        memoire = MemoireLinguistique()
        vu, memoire, _ = basculer("Mwen la, mèsi.", memoire)
        assert vu.code == "ht" and vu.certaine
        vu, memoire, consigne = basculer("Bonjour, comment ça va ?", memoire)
        assert vu.code == "fr" and vu.certaine
        assert memoire.courante() == "fr"
        assert "French" in consigne
        vu, memoire, consigne = basculer("ok", memoire)
        assert vu.code == "fr" and not vu.certaine
        assert "French" in consigne
        vu, memoire, consigne = basculer("How are you today?", memoire)
        assert vu.code == "en" and memoire.courante() == "en"
        assert "English" in consigne

    def test_les_consignes_tiennent_les_idiomes_et_interdisent_le_melange(self):
        kreyol = consigne_kreyol()
        for idiome in ("men wi", "sa k ap fèt", "ann avanse", "mwen la"):
            assert idiome in kreyol, idiome
        assert "official orthography" in kreyol
        assert "word for word" in kreyol
        francais = consigne_francais()
        assert "French" in francais
        assert "Kreyòl" in francais
        anglais = consigne_anglais()
        assert "English" in anglais
        assert "Kreyòl" in anglais
        assert "kreyòl" in CONSIGNE_PERMANENTE
        assert "dominant" in CONSIGNE_PERMANENTE


class TestPhonetique:
    def test_le_guide_des_mots_difficiles(self):
        phrase = "tèt jèn kè sè peyi mèsi avni lapòs"
        orale = forme_orale(phrase)
        for grapheme, rendu in GUIDE_PHONETIQUE:
            assert grapheme in phrase
            assert rendu in orale.split(), rendu

    def test_gen_garde_le_g_dur(self):
        orale = forme_orale("pa gen pwoblèm")
        assert "gain" in orale.split(), "« gen » ne doit pas se lire « jen »"
        assert "jen" not in orale.split()
        assert "pwoblème" in orale.split()

    def test_les_idiomes_et_la_question(self):
        assert forme_orale("men wi") == "main oui"
        assert forme_orale("mwen la") == "mouin la"
        assert forme_orale("ann avanse") == "ann avancé"
        assert forme_orale("kijan ou ye") == "kijan ou yé ?"
        assert forme_orale("kijan ou ye.") == "kijan ou yé ?"
        assert forme_orale("Men wi") == "Main oui"
        assert forme_orale("Mèsi, sa k ap fèt ?") == "Mèssi, sa ke ape fète ?"

    def test_les_hesitations_ne_sont_pas_lues(self):
        orale = forme_orale("euh, mwen la…")
        assert "euh" not in orale
        assert "…" not in orale
        assert orale == "mouin la."

    def test_le_clitique_fait_entendre_le_p(self):
        assert "lape" in forme_orale("l ap vini").split()

    def test_le_francais_et_l_anglais_ne_sont_pas_reecrits(self):
        francais = "Je vais à la poste, merci."
        anglais = "Thanks, see you tomorrow."
        assert forme_orale(francais) == francais
        assert forme_orale(anglais) == anglais
        assert forme_ecrite("Je parle le créole haïtien.") == (
            "Je parle le créole haïtien."
        )

    def test_l_orthographe_officielle_corrige_le_kreyol_mal_ecrit(self):
        assert forme_ecrite("mwen pale kreyol") == "mwen pale kreyòl"
        assert forme_ecrite("Mèsi anpil") == "Mèsi anpil"

    def test_une_longue_phrase_ne_coupe_pas_les_mots(self):
        phrase = (
            "Mwen kontan wè ou jodi a, epi n ap pale tou dousman "
            "pou chak mo rive klè jouk nan fen fraz la."
        )
        orale = forme_orale(phrase)
        assert "…" not in orale
        assert "euh" not in orale
        assert "-" not in orale
        assert len(orale.split()) >= 10

    def test_la_vitesse_ne_dechire_pas_le_timbre(self):
        assert vitesse("ht") == 1.0
        assert vitesse("fr") == 1.0
        assert vitesse("en") == 1.0


class TestLaVoix:
    def test_la_langue_libre_porte_la_bascule_dans_le_prompt(self):
        session = LocalVoiceSession(
            stt=lambda _a: "", llm=lambda _m: None, tts=lambda _t: b""
        )
        assert "kreyòl" in session._system_prompt()
        assert "dominant" in session._system_prompt()

    def test_le_code_fr_de_la_config_laisse_la_bascule(self):
        session = LocalVoiceSession(
            language="fr",
            stt=lambda _a: "",
            llm=lambda _m: None,
            tts=lambda _t: b"",
        )
        assert "kreyòl" in session._system_prompt()
        messages = session._turn_messages("Mwen la, sa k ap fèt ?")
        assert any("men wi" in str(m.get("content")) for m in messages)

    def test_francais_dans_la_config_laisse_la_bascule(self):
        session = LocalVoiceSession(
            language="français",
            stt=lambda _a: "",
            llm=lambda _m: None,
            tts=lambda _t: b"",
        )
        assert "kreyòl" in session._system_prompt()
        messages = session._turn_messages("Mwen la, sa k ap fèt ?")
        assert any("men wi" in str(m.get("content")) for m in messages)

    def test_une_consigne_longue_reste_un_verrou(self):
        session = LocalVoiceSession(
            language="réponds uniquement en latin",
            stt=lambda _a: "",
            llm=lambda _m: None,
            tts=lambda _t: b"",
        )
        prompt = session._system_prompt()
        assert "latin" in prompt
        assert "men wi" not in prompt

    def test_le_tour_kreyol_precede_l_utilisateur(self, monkeypatch):
        import diapason.desktop.etat_bureau as eb
        from diapason.desktop.etat_bureau import EtatBureau

        monkeypatch.setattr(
            eb, "_cache", EtatBureau("Safari", ("Safari", "Notes"), 0.0)
        )
        session = LocalVoiceSession(
            stt=lambda _a: "", llm=lambda _m: None, tts=lambda _t: b""
        )
        texte = "Mwen la, sa k ap fèt ?"
        messages = session._turn_messages(texte)
        assert messages[-1] == {"role": "user", "content": texte}
        assert "Safari" in messages[-2]["content"]
        consignes = [
            m["content"]
            for m in messages
            if m["role"] == "system" and "men wi" in m["content"]
        ]
        assert len(consignes) == 1

    def test_une_consigne_longue_n_ajoute_pas_de_consigne_de_bascule(self):
        session = LocalVoiceSession(
            language="réponds uniquement en latin",
            stt=lambda _a: "",
            llm=lambda _m: None,
            tts=lambda _t: b"",
        )
        messages = session._turn_messages("Mwen la, sa k ap fèt ?")
        assert all("men wi" not in str(m.get("content")) for m in messages)

    @pytest.mark.asyncio
    async def test_l_affichage_garde_l_orthographe_et_la_voix_la_phonetique(self):
        recus: list[str] = []
        session = LocalVoiceSession(
            stt=lambda _a: "",
            llm=lambda _m: None,
            tts=lambda texte: recus.append(texte) or b"\x00\x01",
        )
        await session._speak_sentence("Mèsi, sa k ap fèt ?", [])
        assert recus == ["Mèssi, sa ke ape fète ?"]
        evenement = session._queue.get_nowait()
        assert evenement.role == "assistant"
        assert "fèt" in evenement.text
        assert "fète" not in evenement.text
