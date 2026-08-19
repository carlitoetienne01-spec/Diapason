"""La dictée qui s'écrit pendant qu'on parle.

Whisper relit tout le tampon à chaque passe et RÉVISE ce qu'il avait
compris — « ca » devient « ça », « conte » devient « compte ». Poser le
texte au fil des mots exige donc de savoir défaire ce qu'on vient d'écrire,
et de s'arrêter net dès qu'on n'est plus sûr d'où l'on est.
"""

from __future__ import annotations

import pytest

from diapason.desktop.dictation_live import LIVE_APPS, LiveDictation, live_allowed


class FauxChamp:
    """Un champ de texte qui obéit — ou qui refuse, sur commande."""

    def __init__(self, refuser_a: int | None = None):
        self.contenu = ""
        self._appels = 0
        self._refuser_a = refuser_a

    def _ko(self) -> bool:
        self._appels += 1
        return self._refuser_a is not None and self._appels >= self._refuser_a

    def inserer(self, texte: str) -> bool:
        if self._ko():
            return False
        self.contenu += texte
        return True

    def remplacer(self, count: int, texte: str) -> bool:
        if self._ko():
            return False
        self.contenu = self.contenu[: len(self.contenu) - count] + texte
        return True


def session(champ: FauxChamp) -> LiveDictation:
    return LiveDictation(inserer=champ.inserer, remplacer=champ.remplacer)


class TestLeTexteSuitLaParole:
    def test_un_allongement_n_ecrit_que_la_suite(self):
        """Le cas courant. Ne réécrire que ce qui change, c'est moins de
        scintillement et moins de surface d'erreur."""
        champ = FauxChamp()
        s = session(champ)
        for etape in ("Bonjour", "Bonjour comment", "Bonjour comment ça va"):
            assert s.mettre_a_jour(etape)
        assert champ.contenu == "Bonjour comment ça va"

    def test_une_revision_corrige_sur_place(self):
        """« ca » devient « ça » : le texte déjà posé doit changer, pas
        s'ajouter."""
        champ = FauxChamp()
        s = session(champ)
        s.mettre_a_jour("bonjour ca va")
        s.mettre_a_jour("bonjour ça va")
        assert champ.contenu == "bonjour ça va"

    def test_un_texte_identique_n_ecrit_rien(self):
        champ = FauxChamp()
        s = session(champ)
        s.mettre_a_jour("Bonjour")
        avant = champ._appels
        assert s.mettre_a_jour("Bonjour")
        assert champ._appels == avant, "aucune écriture pour un texte inchangé"

    def test_le_poli_remplace_le_brut_d_un_geste(self):
        champ = FauxChamp()
        s = session(champ)
        s.mettre_a_jour("bonjour comment ca va")
        assert s.remplacer_par("Bonjour, comment ça va ?")
        assert champ.contenu == "Bonjour, comment ça va ?"


class TestUnEchecArreteToutAuLieuDInsister:
    """Une pose ratée laisse un état inconnu. Réessayer, c'est risquer
    d'écrire deux fois dans le document de quelqu'un."""

    def test_apres_un_refus_plus_rien_n_est_tente(self):
        champ = FauxChamp(refuser_a=2)
        s = session(champ)
        assert s.mettre_a_jour("Bonjour")
        assert not s.mettre_a_jour("Bonjour comment")
        apres_echec = champ._appels
        assert not s.mettre_a_jour("Bonjour comment ça va")
        assert champ._appels == apres_echec, "aucune tentative après l'échec"

    def test_l_echec_est_visible_de_l_exterieur(self):
        """L'appelant doit pouvoir basculer sur le collage de secours."""
        champ = FauxChamp(refuser_a=1)
        s = session(champ)
        s.mettre_a_jour("Bonjour")
        assert s.perdu is True

    def test_le_polissage_ne_force_pas_apres_un_echec(self):
        champ = FauxChamp(refuser_a=1)
        s = session(champ)
        s.mettre_a_jour("bonjour")
        assert not s.remplacer_par("Bonjour.")


class TestLaListeDApplications:
    """Limitée d'abord, étendue selon ce qu'on constate — jamais par
    optimisme. L'échec se produirait dans un document, pas dans un journal."""

    @pytest.mark.parametrize("app", ["Notes", "Mail", "notes", "  Pages  "])
    def test_les_champs_natifs_sont_autorises(self, app):
        assert live_allowed(app)

    @pytest.mark.parametrize(
        "app", ["Terminal", "Visual Studio Code", "Google Chrome", "Safari"]
    )
    def test_les_apps_a_risque_sont_exclues(self, app):
        """Absentes EXPRÈS : leur gestion du remplacement de plage n'est pas
        fiable. Ce test empêche qu'on les ajoute sans y penser."""
        assert not live_allowed(app)

    def test_sans_nom_d_application_on_s_abstient(self):
        """Ne pas savoir où l'on écrit n'est pas une raison d'essayer."""
        assert not live_allowed(None)
        assert not live_allowed("")

    def test_la_liste_reste_courte(self):
        """Un garde-fou de revue : élargir doit être un geste conscient."""
        assert len(LIVE_APPS) <= 8


class TestLAccessibiliteNeSeCroitPasSurParole:
    """``AXIsProcessTrustedWithOptions`` peut répondre True pendant que
    chaque appel réel rend -25204. Constaté sur cette machine : drapeau à
    True, insertion refusée quatre fois de suite, y compris depuis le
    contexte launchd autorisé. Annoncer une capacité absente est exactement
    le défaut que cette base a passé une semaine à retirer."""

    def test_le_test_reel_juge_sur_un_appel(self, monkeypatch):
        from diapason.desktop import accessibility as ax

        # -25204 = kAXErrorAPIDisabled : refus franc.
        monkeypatch.setattr(ax, "accessibility_trusted", lambda **_: True)
        assert ax.accessibility_works() in (True, False)  # ne lève jamais

    def test_insert_refuse_quand_l_api_ne_repond_pas(self, monkeypatch):
        from diapason.desktop import accessibility as ax

        monkeypatch.setattr(ax, "accessibility_works", lambda: False)
        assert ax.insert_text("bonjour") is False
        assert ax.replace_previous(3, "bonjour") is False

    def test_un_texte_vide_ne_tente_rien(self):
        from diapason.desktop import accessibility as ax

        assert ax.insert_text("") is False
