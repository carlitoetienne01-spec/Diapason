"""Le cœur du transfert : découper, vérifier, assainir, recoudre.

Spatial Mesh, phase 3 — 25 août 2026. Trois règles nées de vraies erreurs :
jamais tout en mémoire, le nom reçu est une donnée hostile, et rien n'est
visible avant d'être entier.
"""

from __future__ import annotations

import hashlib

import pytest

from diapason.mesh import transfert as tr


class TestNomsHostiles:
    """« ../../.ssh/authorized_keys » est un nom de fichier parfaitement
    valide pour celui qui l'envoie."""

    @pytest.mark.parametrize(
        "brut,attendu",
        [
            ("../../.ssh/authorized_keys", "authorized_keys"),
            ("C:\\Windows\\System32\\evil.dll", "evil.dll"),
            ("..", "fichier"),
            ("...", "fichier"),
            ("", "fichier"),
            (".env", "env"),
            ("photo.jpg", "photo.jpg"),
            ("rapport final.pdf", "rapport final.pdf"),
        ],
    )
    def test_un_nom_ne_devient_jamais_un_chemin(self, brut, attendu):
        assert tr.assainir_nom(brut) == attendu

    def test_les_octets_de_controle_disparaissent(self):
        assert "\x00" not in tr.assainir_nom("photo\x00.jpg")
        assert "\n" not in tr.assainir_nom("photo\n.jpg")

    def test_les_controles_de_direction_ne_deguisent_pas_l_extension(self):
        nom = tr.assainir_nom("rapport\u202egnp.exe")
        assert "\u202e" not in nom
        assert nom == "rapportgnp.exe"

    def test_un_nom_fleuve_garde_son_extension(self):
        nom = tr.assainir_nom("a" * 400 + ".pdf")
        assert len(nom) <= 120 and nom.endswith(".pdf")

    def test_rien_n_est_jamais_ecrase(self, tmp_path):
        (tmp_path / "photo.jpg").write_bytes(b"deja la")
        libre = tr.nom_libre(tmp_path, "photo.jpg")
        assert libre.name == "photo (2).jpg"
        assert (tmp_path / "photo.jpg").read_bytes() == b"deja la"


class TestManifeste:
    def _fichier(self, tmp_path, octets: bytes):
        chemin = tmp_path / "source.bin"
        chemin.write_bytes(octets)
        return chemin

    def test_le_manifeste_decrit_le_fichier_reel(self, tmp_path):
        contenu = b"x" * 3000
        manifeste = tr.decrire_fichier(self._fichier(tmp_path, contenu))
        assert manifeste.taille == 3000
        assert manifeste.hachage == hashlib.sha256(contenu).hexdigest()
        assert manifeste.morceaux == 1

    def test_un_gros_fichier_se_decoupe(self, tmp_path):
        contenu = b"y" * (tr.TAILLE_MORCEAU * 2 + 17)
        manifeste = tr.decrire_fichier(self._fichier(tmp_path, contenu))
        assert manifeste.morceaux == 3

    def test_un_fichier_vide_n_a_aucun_morceau(self, tmp_path):
        manifeste = tr.decrire_fichier(self._fichier(tmp_path, b""))
        assert manifeste.taille == 0 and manifeste.morceaux == 0

    def test_le_manifeste_ne_porte_que_des_entiers(self, tmp_path):
        """Un flottant dans une charge signée s'écrit « 1e-07 » d'un côté et
        « 1e-7 » de l'autre : signatures invalides, sans un mot."""
        brut = tr.decrire_fichier(self._fichier(tmp_path, b"abc")).to_dict()
        assert isinstance(brut["size"], int)
        assert isinstance(brut["chunks"], int)
        assert not any(isinstance(v, float) for v in brut.values())


class TestRefusAvantLePremierOctet:
    def _manifeste(self, **kw):
        base = dict(nom="x.bin", taille=10, hachage="a" * 64, morceaux=1)
        base.update(kw)
        return tr.Manifeste(**base)

    def test_trop_gros_est_refuse_avant_de_remplir_le_disque(self):
        with pytest.raises(tr.RefusDeTransfert, match="limite"):
            tr.verifier_le_manifeste(
                self._manifeste(taille=99, morceaux=1), taille_max=50
            )

    def test_une_empreinte_illisible_est_refusee(self):
        with pytest.raises(tr.RefusDeTransfert, match="[Ee]mpreinte"):
            tr.verifier_le_manifeste(self._manifeste(hachage="pas-du-sha"))

    def test_un_decoupage_incoherent_est_refuse(self):
        """Annoncer un morceau pour dix mégaoctets serait le début d'une
        écriture hors bornes."""
        with pytest.raises(tr.RefusDeTransfert, match="découpage"):
            tr.verifier_le_manifeste(
                self._manifeste(taille=tr.TAILLE_MORCEAU * 5, morceaux=1)
            )


class TestReception:
    def _preparer(self, tmp_path, contenu: bytes):
        source = tmp_path / "src.bin"
        source.write_bytes(contenu)
        manifeste = tr.decrire_fichier(source)
        dossier = tmp_path / "recu"
        reception = tr.ouvrir_reception(manifeste, dossier, session_id="s1")
        return source, manifeste, reception

    def test_un_transfert_complet_arrive_intact(self, tmp_path):
        contenu = bytes(range(256)) * 40
        source, _m, reception = self._preparer(tmp_path, contenu)
        for index, bloc in tr.lire_morceaux(source):
            reception.ecrire(index, bloc)
        cible = reception.finaliser()
        assert cible.read_bytes() == contenu
        assert cible.name == "src.bin"

    def test_rien_n_est_visible_avant_d_etre_entier(self, tmp_path):
        """Un fichier partiel qui porte déjà son nom final sera ouvert par
        quelqu'un, un jour, au milieu d'un transfert."""
        contenu = b"z" * (tr.TAILLE_MORCEAU + 10)
        source, _m, reception = self._preparer(tmp_path, contenu)
        premier = next(tr.lire_morceaux(source))
        reception.ecrire(*premier)
        assert not (reception.dossier / "src.bin").exists()
        assert reception.partiel.name.startswith(".")

    def test_la_reprise_sait_ce_qui_manque(self, tmp_path):
        contenu = b"w" * (tr.TAILLE_MORCEAU * 3)
        source, _m, reception = self._preparer(tmp_path, contenu)
        morceaux = list(tr.lire_morceaux(source))
        reception.ecrire(*morceaux[0])
        reception.ecrire(*morceaux[2])
        assert reception.manquants == [1]
        assert not reception.complet
        reception.ecrire(*morceaux[1])
        assert reception.complet
        assert reception.finaliser().read_bytes() == contenu

    def test_rejouer_un_morceau_est_inoffensif(self, tmp_path):
        contenu = b"v" * 500
        source, _m, reception = self._preparer(tmp_path, contenu)
        morceau = next(tr.lire_morceaux(source))
        reception.ecrire(*morceau)
        reception.ecrire(*morceau)
        assert reception.finaliser().read_bytes() == contenu

    def test_un_morceau_hors_bornes_est_refuse(self, tmp_path):
        _s, _m, reception = self._preparer(tmp_path, b"abc")
        with pytest.raises(tr.RefusDeTransfert, match="hors du fichier"):
            reception.ecrire(9, b"abc")

    def test_un_contenu_altere_ne_devient_jamais_un_fichier(self, tmp_path):
        """L'empreinte est recalculée sur ce qui est SUR LE DISQUE : croire
        le compte des morceaux reviendrait à croire l'émetteur sur parole."""
        contenu = b"honnete" * 100
        source, _m, reception = self._preparer(tmp_path, contenu)
        for index, bloc in tr.lire_morceaux(source):
            reception.ecrire(index, b"altere" + bloc[6:])
        with pytest.raises(tr.RefusDeTransfert, match="empreinte"):
            reception.finaliser()
        assert not (reception.dossier / "src.bin").exists()
        assert not reception.partiel.exists(), "le partiel corrompu est effacé"

    def test_un_transfert_incomplet_ne_se_finalise_pas(self, tmp_path):
        _s, _m, reception = self._preparer(tmp_path, b"q" * (tr.TAILLE_MORCEAU * 2))
        with pytest.raises(tr.RefusDeTransfert, match="incomplet"):
            reception.finaliser()

    def test_le_fichier_recu_n_est_jamais_executable(self, tmp_path):
        contenu = b"#!/bin/sh\necho salut\n"
        source, _m, reception = self._preparer(tmp_path, contenu)
        for index, bloc in tr.lire_morceaux(source):
            reception.ecrire(index, bloc)
        cible = reception.finaliser()
        assert cible.stat().st_mode & 0o111 == 0, "aucun bit exécutable"


class TestDeduplication:
    def test_un_fichier_deja_present_se_reconnait_au_contenu(self, tmp_path):
        """Comparer les noms trompe : deux fichiers de même nom peuvent
        différer, et deux noms différents porter le même contenu."""
        contenu = b"le meme contenu exactement"
        dossier = tmp_path / "recu"
        dossier.mkdir()
        (dossier / "autre-nom.bin").write_bytes(contenu)
        source = tmp_path / "source.bin"
        source.write_bytes(contenu)
        manifeste = tr.decrire_fichier(source)
        assert tr.deja_present(manifeste, dossier).name == "autre-nom.bin"

    def test_un_contenu_different_n_est_pas_confondu(self, tmp_path):
        dossier = tmp_path / "recu"
        dossier.mkdir()
        (dossier / "source.bin").write_bytes(b"autre chose de meme taille!!")
        source = tmp_path / "source.bin"
        source.write_bytes(b"le meme contenu exactement..")
        assert tr.deja_present(tr.decrire_fichier(source), dossier) is None
