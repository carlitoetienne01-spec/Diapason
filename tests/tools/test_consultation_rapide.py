"""§5/§100 : un compte direct reste sourcé, jamais une approximation de filtre."""

import pytest

from diapason.tools.consultation_rapide import compte_demande


class TestCompteDirect:
    @pytest.mark.parametrize(
        "question, debut, fin",
        [
            (
                "Combien de tâches ai-je sur toute l’année 2026, "
                "et combien restent à terminer ?",
                "2026-01-01",
                "2026-12-31",
            ),
            (
                "Combien de tâches ai-je le 27 septembre 2026 ? "
                "Donne le total, les terminées et celles qui restent.",
                "2026-09-27",
                "2026-09-27",
            ),
            (
                "Combien de tâches ai-je du 2026-10-01 au 2027-02-02 inclus ?",
                "2026-10-01",
                "2027-02-02",
            ),
            (
                "Combien de tâches ai-je du 28 septembre 2026 "
                "au 4 octobre 2026 inclus ?",
                "2026-09-28",
                "2026-10-04",
            ),
        ],
    )
    def test_periode_exacte(self, question, debut, fin):
        """§100 : le filtre entier est connu avant d'éviter l'inférence."""
        assert compte_demande(question) == {
            "action": "count",
            "startDate": debut,
            "endDate": fin,
        }

    @pytest.mark.parametrize(
        "question",
        [
            "Combien de tâches ai-je pour le projet Anglais cette semaine ?",
            "Combien de tâches ai-je aujourd'hui et supprime les anciennes ?",
            "Combien de tâches ai-je cette semaine par rapport à la dernière ?",
            "Combien de tâches terminées ai-je aujourd'hui ?",
            "Combien de tâches ai-je du 2026-10-20 au 2026-10-01 ?",
            "Combien de tâches ai-je le 40 septembre 2026 ?",
            "Pourquoi ai-je tant de tâches ?",
        ],
    )
    def test_demande_complexe_ou_invalide_reste_au_modele(self, question):
        """§34 : ne jamais jeter un critère ni deviner une période ambiguë."""
        assert compte_demande(question) is None, "tous les critères doivent rester"

    def test_action_lit_le_magasin_reel(self, tmp_path, monkeypatch):
        """§100 : aucun nombre n'est fabriqué par le raccourci."""
        from diapason.desktop.voice_commands import (
            execute_voice_action,
            parse_voice_command,
        )
        from diapason.tools.vie_tasks import VieTasksTool
        from diapason.vie.store import VieStore

        monkeypatch.setenv("DIAPASON_HOME", str(tmp_path))
        magasin = VieStore(tmp_path / "vie.db")
        magasin.create_task({"title": "Terminée", "date": "2026-10-01", "done": True})
        magasin.create_task({"title": "À faire", "date": "2026-10-02"})
        monkeypatch.setattr(VieTasksTool, "_store", property(lambda _: magasin))
        resultat = execute_voice_action(
            parse_voice_command("Combien de tâches ai-je en 2026 ?")
        )
        assert resultat["success"] and resultat["verified"], "lecture effectuée"
        assert (
            "2 tâches" in resultat["detail"]
            and "1 terminée et 1 restante" in resultat["detail"]
        )
