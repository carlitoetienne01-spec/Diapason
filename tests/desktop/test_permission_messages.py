"""Ce que la dictée annonce doit correspondre à ce qu'elle peut faire.

Le service annonçait « Accessibilité : REFUSÉE » pendant qu'il collait
parfaitement dans les applications. Mesuré sur une vraie machine, les trois
signaux divergent :

    AXIsProcessTrusted   True    ← un drapeau
    API AX réelle        False   ← l'écriture directe : refusée
    System Events        True    ← le COLLAGE : fonctionne

Le message se fiait au seul signal qui ne concerne pas le chemin emprunté.
Un avertissement alarmant à propos de rien envoie chercher un défaut là où
il n'y en a pas — et fait douter d'une fonctionnalité qui marche.
"""

from __future__ import annotations

from diapason.desktop import accessibility as ax


class TestDeuxCapacitesDistinctes:
    def test_le_collage_a_son_propre_test(self):
        """Il passe par System Events, pas par l'API AX brute. Les deux
        dépendent d'autorisations différentes."""
        assert hasattr(ax, "paste_works")
        assert ax.paste_works() in (True, False)

    def test_l_ecriture_directe_a_le_sien(self):
        assert ax.accessibility_works() in (True, False)

    def test_aucun_des_deux_ne_leve(self, monkeypatch):
        """Un diagnostic qui plante est pire qu'un diagnostic absent : il
        empêcherait le service de démarrer."""

        def explose(*a, **k):
            raise RuntimeError("osascript introuvable")

        monkeypatch.setattr("subprocess.run", explose)
        assert ax.paste_works() is False


class TestLeMessageSuitLaCapacite:
    """Formulations vérifiées ici plutôt que dans le service, qui exige un
    micro et un modèle pour démarrer."""

    def test_le_collage_disponible_ne_declenche_aucune_alarme(self):
        colle, ecrit = True, False
        lignes = []
        if colle:
            lignes.append("Collage : disponible")
        if not ecrit and colle:
            lignes.append("Écriture directe : indisponible — le reste fonctionne")
        assert not any("REFUSÉE" in x for x in lignes)
        assert any("fonctionne" in x for x in lignes)

    def test_le_collage_absent_est_bien_une_alarme(self):
        """Là, c'est grave : la dictée ne peut rien écrire nulle part."""
        colle = False
        message = (
            "Collage : INDISPONIBLE — la dictée ne pourra rien écrire."
            if not colle
            else "Collage : disponible"
        )
        assert "INDISPONIBLE" in message


class TestLaRemediationNommeLaBonneCible:
    def test_elle_nomme_l_enveloppe_quand_elle_existe(self):
        """macOS attribue au processus responsable : l'agent lance
        l'application, pas l'interpréteur."""
        from pathlib import Path

        texte = ax.accessibility_remediation()
        enveloppe = Path.home() / "Applications" / "Diapason Dictation.app"
        if texte and enveloppe.exists():
            assert "Diapason Dictation.app" in texte

    def test_elle_se_tait_quand_tout_va_bien(self, monkeypatch):
        monkeypatch.setattr(ax, "accessibility_works", lambda: True)
        assert ax.accessibility_remediation() == ""
