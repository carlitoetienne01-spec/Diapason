"""Dix chiffres ne sont pas un numéro de téléphone.

Tous les séparateurs du motif étaient facultatifs, si bien que n'importe
quelle suite de dix chiffres était masquée. Mesuré : demander à Diapason
« 48273 × 91847 » rendait ``[REDACTED:us_phone]`` — l'outil avait
fonctionné, la bonne réponse (4433730231) a été effacée en sortie, et rien
n'indiquait pourquoi. Le calculateur devenait inutilisable au-delà du
milliard, et avec lui tout numéro de commande, horodatage en millisecondes
ou montant en centimes.

Un téléphone doit désormais RESSEMBLER à un téléphone : indicatif ``+1``,
parenthèses autour de l'indicatif régional, ou de vrais séparateurs.
"""

from __future__ import annotations

import pytest

from diapason.security.scanner import PIIScanner


@pytest.fixture
def scanner() -> PIIScanner:
    return PIIScanner()


def masque(scanner: PIIScanner, texte: str) -> bool:
    return any(
        getattr(f, "pattern_name", "") == "us_phone"
        for f in scanner.scan(texte).findings
    )


class TestUnVraiTelephoneEstToujoursProtege:
    """La correction ne doit pas ouvrir une fuite pour gagner en confort."""

    @pytest.mark.parametrize(
        "texte",
        [
            "555-123-4567",
            "555.123.4567",
            "555 123 4567",
            "(555) 123-4567",
            "+1 555 123 4567",
            "+15551234567",
            "Appelle-moi au (438) 555-0199 demain",
        ],
    )
    def test_il_est_detecte(self, scanner, texte):
        assert masque(scanner, texte), texte


class TestUnNombreOrdinaireNEstPlusEfface:
    @pytest.mark.parametrize(
        "texte,quoi",
        [
            ("4433730231", "le résultat de 48273 × 91847"),
            ("Commande 2024081512", "un numéro de commande"),
            ("1755534120", "un horodatage en secondes"),
            ("Le total est 1234567890 centimes", "un montant"),
            ("1099511627776 octets", "une taille en octets"),
        ],
    )
    def test_il_passe(self, scanner, texte, quoi):
        assert not masque(scanner, texte), f"{quoi} : {texte}"

    def test_le_calculateur_redevient_utilisable(self, scanner):
        """L'épreuve exacte qui a révélé le défaut."""
        assert not masque(scanner, str(48273 * 91847))


class TestLesDeuxImplementationsSAccordent:
    """Le scanner a une version Rust ET un repli Python, avec les mêmes
    motifs recopiés des deux côtés. Corriger l'un sans l'autre laisserait le
    défaut vivant partout où l'extension n'est pas compilée — et c'est
    justement le Rust qui tournait ici, donc corriger le Python seul
    n'aurait rien changé du tout."""

    @staticmethod
    def _verdict(scanner: PIIScanner, texte: str) -> bool:
        return any(
            getattr(f, "pattern_name", "") == "us_phone"
            for f in scanner.scan(texte).findings
        )

    @pytest.mark.parametrize(
        "texte,attendu",
        [
            ("4433730231", False),
            ("Commande 2024081512", False),
            ("555-123-4567", True),
            ("(555) 123-4567", True),
            ("+1 555 123 4567", True),
        ],
    )
    def test_les_deux_rendent_le_meme_verdict(self, texte, attendu):
        rust = PIIScanner()
        python = PIIScanner()
        python._rust_impl = None  # force le repli

        assert self._verdict(python, texte) is attendu, f"python : {texte}"
        if rust._rust_impl is not None:
            assert self._verdict(rust, texte) is attendu, f"rust : {texte}"

    def test_l_implementation_rust_est_bien_celle_qui_tourne(self):
        """Sinon le test précédent ne prouve rien de ce qui s'exécute."""
        assert PIIScanner()._rust_impl is not None
