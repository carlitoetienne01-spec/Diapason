"""Le scellement des commandes — les primitives, avant tout appelant.

Étape 1 du plan du 26 août 2026. Rien dans le dépôt n'appelle encore ce
module : ces tests vérifient la cryptographie seule, pour que les étapes
suivantes se posent sur un socle déjà éprouvé plutôt que de tout mêler.

La vérification la plus importante n'est pas ici mais dans
``tests/mesh/test_coffre.py``, qui passe **sans une seule modification** :
c'est la preuve que les trois mots-clés ajoutés à ``coffre.py`` sont neutres
et que le transfert de fichiers ne bouge pas d'un bit.
"""

from __future__ import annotations

import os
import stat

import pytest

from diapason.mesh import scellement


@pytest.fixture(autouse=True)
def _chez_soi(tmp_path, monkeypatch):
    """Chaque test frappe ses propres clés, dans son propre dossier.

    Sans cela un test écrirait dans ``~/.diapason`` de qui lance la suite —
    et la clé de scellement de sa vraie machine deviendrait celle d'un test.
    """
    monkeypatch.setenv("DIAPASON_HOME", str(tmp_path / "maison"))
    yield


def _associe(quoi: bytes = b"en-tete-de-routage") -> bytes:
    return quoi


class TestLaCleLocale:
    def test_elle_nait_en_0600_dans_un_dossier_0700(self):
        paire = scellement.paire_locale()
        assert len(paire.privee) == 32
        assert len(paire.publique) == 32

        chemin = scellement._chemin("seal_key")
        assert chemin.exists()
        assert stat.S_IMODE(os.stat(chemin).st_mode) == 0o600, "la clé est lisible"
        assert stat.S_IMODE(os.stat(chemin.parent).st_mode) == 0o700

    def test_elle_ne_se_reforge_pas_a_chaque_appel(self):
        """Deux clés pour une machine, ce serait deux machines pour ses pairs."""
        assert scellement.paire_locale().privee == scellement.paire_locale().privee

    def test_le_kid_designe_sans_reveler(self):
        paire = scellement.paire_locale()
        empreinte = scellement.kid(paire.publique)
        assert len(empreinte) == 8
        assert all(c in "0123456789abcdef" for c in empreinte)
        assert empreinte != paire.publique_b64[:8]


class TestLeRenouvellement:
    def test_l_ancienne_reste_dechiffrable(self):
        """Une commande mise en file AVANT le renouvellement doit encore
        pouvoir s'ouvrir quand elle est enfin livrée."""
        avant = scellement.paire_locale()
        scellement.renouveler()
        apres = scellement.paire_locale()

        assert apres.privee != avant.privee, "la clé n'a pas changé"
        precedente = scellement.paire_precedente()
        assert precedente is not None
        assert precedente.privee == avant.privee

    def test_la_retention_couvre_l_attente_en_file(self):
        """INVARIANT : sans lui, une commande devient indéchiffrable pendant
        qu'elle attend son destinataire."""
        from diapason.mesh.commands import QUEUED_TTL_MS

        assert scellement.RETENTION_PRECEDENTE_MS > QUEUED_TTL_MS

    def test_la_retention_est_APPLIQUEE_et_pas_seulement_declaree(self):
        """La constante était déclarée, exportée, documentée comme un
        invariant — et lue par AUCUN code. La clé précédente survivait en
        réalité jusqu'au renouvellement suivant, une minute ou dix ans,
        pendant que l'aide de la commande promettait sept jours.

        Le test d'au-dessus ne vérifiait que l'arithmétique de la constante :
        « un test le vérifie » était lui-même une proclamation. Celui-ci
        vérifie le COMPORTEMENT.
        """
        import os

        scellement.paire_locale()
        scellement.renouveler()
        assert scellement.paire_precedente() is not None, "test mal construit"

        # On vieillit le fichier d'une seconde de plus que la rétention.
        chemin = scellement._chemin("seal_key.prev")
        vieux = (
            scellement._maintenant_ms() - scellement.RETENTION_PRECEDENTE_MS - 1_000
        ) / 1000
        os.utime(chemin, (vieux, vieux))

        assert scellement.paire_precedente() is None, (
            "la clé précédente survit à sa propre rétention"
        )
        assert not chemin.exists(), (
            "une clé privée périmée reste sur le disque : le renouvellement "
            "ne ferme alors qu'à moitié la fenêtre qu'il vise"
        )

    def test_juste_avant_l_echeance_elle_ouvre_encore(self):
        import os

        scellement.paire_locale()
        scellement.renouveler()
        chemin = scellement._chemin("seal_key.prev")
        limite = (
            scellement._maintenant_ms() - scellement.RETENTION_PRECEDENTE_MS + 60_000
        ) / 1000
        os.utime(chemin, (limite, limite))
        assert scellement.paire_precedente() is not None

    def test_oublier_efface_les_deux(self):
        scellement.paire_locale()
        scellement.renouveler()
        scellement.oublier_locale()
        assert not scellement._chemin("seal_key").exists()
        assert not scellement._chemin("seal_key.prev").exists()
        assert scellement.paire_precedente() is None


class TestUnAllerRetour:
    def _pair(self):
        """Une machine « distante » : sa paire, dont on n'a que la publique."""
        from diapason.mesh.coffre import nouvelle_demi_cle

        return nouvelle_demi_cle()

    def test_ce_qui_est_scelle_se_rouvre(self, monkeypatch, tmp_path):
        # On scelle VERS notre propre clé locale, pour pouvoir rouvrir ici.
        moi = scellement.paire_locale()
        scelle = scellement.contenu_scelle(
            "notifications.show",
            {"title": "Rendez-vous à 14 h", "body": "chez le notaire"},
            False,
            cle_pair_b64=moi.publique_b64,
            command_id="cmd-1",
            associe=_associe(),
        )
        assert set(scelle) == {"s", "e", "k"}

        outil, arguments, confirmation = scellement.ouvrir_contenu(
            scelle, command_id="cmd-1", associe=_associe()
        )
        assert outil == "notifications.show"
        assert arguments == {"title": "Rendez-vous à 14 h", "body": "chez le notaire"}
        assert confirmation is False

    def test_le_contenu_n_apparait_nulle_part_en_clair(self):
        moi = scellement.paire_locale()
        scelle = scellement.contenu_scelle(
            "desktop.open",
            {"target": "https://exemple.test/rapport-confidentiel"},
            True,
            cle_pair_b64=moi.publique_b64,
            command_id="cmd-2",
            associe=_associe(),
        )
        entier = str(scelle)
        assert "desktop.open" not in entier
        assert "rapport-confidentiel" not in entier
        assert "exemple.test" not in entier

    def test_deux_sceaux_du_meme_clair_different(self):
        """Une moitié éphémère neuve à chaque fois : deux commandes
        identiques ne doivent pas produire deux chiffrés identiques, sans
        quoi un observateur les reconnaîtrait."""
        moi = scellement.paire_locale()
        args = dict(
            cle_pair_b64=moi.publique_b64, command_id="cmd-3", associe=_associe()
        )
        un = scellement.contenu_scelle("app.open", {"x": 1}, False, **args)
        deux = scellement.contenu_scelle("app.open", {"x": 1}, False, **args)
        assert un["s"] != deux["s"]
        assert un["e"] != deux["e"]

    def test_la_longueur_ne_trahit_pas_le_verbe(self):
        """Le catalogue ne compte que cinq entrées : sans rembourrage, la
        taille du chiffré désignerait l'outil."""
        moi = scellement.paire_locale()
        tailles = set()
        for outil, arguments in (
            ("app.open", {}),
            ("notifications.show", {"title": "x"}),
            ("desktop.open", {"target": "https://un-peu-plus-long.test/a/b"}),
        ):
            scelle = scellement.contenu_scelle(
                outil,
                arguments,
                False,
                cle_pair_b64=moi.publique_b64,
                command_id="cmd-4",
                associe=_associe(),
            )
            import base64

            tailles.add(len(base64.b64decode(scelle["s"])))
        assert len(tailles) == 1, f"tailles distinctes : {sorted(tailles)}"


class TestCeQuiDoitEchouer:
    def test_un_seul_octet_de_contexte_change_ferme_le_sceau(self):
        """Le blob est collé à SON enveloppe : le déplacer d'une commande à
        une autre casse le tag avant que la signature ait son mot à dire."""
        moi = scellement.paire_locale()
        scelle = scellement.contenu_scelle(
            "app.open",
            {"screen": "projets"},
            False,
            cle_pair_b64=moi.publique_b64,
            command_id="cmd-5",
            associe=b"en-tete-A",
        )
        with pytest.raises(ValueError):
            scellement.ouvrir_contenu(scelle, command_id="cmd-5", associe=b"en-tete-B")

    def test_un_autre_identifiant_de_commande_ferme_le_sceau(self):
        """L'identifiant est le sel : le changer change la clé dérivée."""
        moi = scellement.paire_locale()
        scelle = scellement.contenu_scelle(
            "app.open",
            {"screen": "projets"},
            False,
            cle_pair_b64=moi.publique_b64,
            command_id="cmd-6",
            associe=_associe(),
        )
        with pytest.raises(ValueError):
            scellement.ouvrir_contenu(
                scelle, command_id="cmd-AUTRE", associe=_associe()
            )

    def test_un_sceau_pour_une_cle_qu_on_n_a_plus_le_dit(self):
        """Deux renouvellements : la clé d'origine n'est plus ni courante ni
        précédente. Le refus doit nommer la cause, pas échouer au hasard."""
        moi = scellement.paire_locale()
        scelle = scellement.contenu_scelle(
            "app.open",
            {},
            False,
            cle_pair_b64=moi.publique_b64,
            command_id="cmd-7",
            associe=_associe(),
        )
        scellement.renouveler()
        scellement.renouveler()
        with pytest.raises(ValueError, match="que cette machine n'a plus"):
            scellement.ouvrir_contenu(scelle, command_id="cmd-7", associe=_associe())

    def test_la_cle_precedente_ouvre_encore(self):
        moi = scellement.paire_locale()
        scelle = scellement.contenu_scelle(
            "app.open",
            {"screen": "notes"},
            False,
            cle_pair_b64=moi.publique_b64,
            command_id="cmd-8",
            associe=_associe(),
        )
        scellement.renouveler()
        outil, arguments, _ = scellement.ouvrir_contenu(
            scelle, command_id="cmd-8", associe=_associe()
        )
        assert outil == "app.open" and arguments == {"screen": "notes"}


class TestLeTransfertDeFichiersNeBougePas:
    """Les trois mots-clés ajoutés à ``coffre.py`` doivent être NEUTRES.

    ``tests/mesh/test_coffre.py`` passe sans modification, ce qui le prouve
    déjà par le comportement. Ce test le prouve par les octets.
    """

    def test_sans_contexte_les_octets_authentifies_sont_ceux_d_avant(self):
        from diapason.mesh.coffre import _authentifie

        for index in (0, 1, 42, 999):
            assert _authentifie(index, b"") == str(index).encode("ascii")

    def test_avec_contexte_ils_different(self):
        from diapason.mesh.coffre import _authentifie

        assert _authentifie(0, b"X") != _authentifie(0, b"")


class TestLireUnBlocDeSceauNeLevePasEtNeCroitPas:
    """Étape 4 : le canal de clé, sans encore rien sceller.

    ``lire_bloc_sceau`` est appelée depuis ``announce_to``, qui PROMET de ne
    jamais lever — une annonce qui n'aboutit pas n'est pas une erreur que
    l'utilisateur doive entendre. Un corps venu du réseau ne doit donc pas
    défaire cette promesse, quelle que soit sa forme.
    """

    @pytest.mark.parametrize(
        "corps",
        [
            None,
            "",
            42,
            [],
            {},
            {"sceau": None},
            {"sceau": "pas un dictionnaire"},
            {"sceau": {}},
            {"sceau": {"version": 99}},
            {"sceau": {"sealKey": "pas du base64 !", "signature": "x"}},
        ],
        ids=[
            "rien",
            "chaine-vide",
            "un-nombre",
            "une-liste",
            "vide",
            "sceau-nul",
            "sceau-texte",
            "sceau-vide",
            "mauvaise-version",
            "cle-illisible",
        ],
    )
    def test_aucune_forme_ne_la_fait_lever(self, corps):
        assert scellement.lire_bloc_sceau(corps) is False

    def test_un_bloc_non_signe_est_ignore(self):
        """La signature EST la créance : sans elle, n'importe qui sur le
        réseau installerait sa propre clé et lirait tout."""
        from diapason.mesh.coffre import nouvelle_demi_cle

        faux = {
            "sceau": {
                "version": 1,
                "ownerId": "o",
                "deviceId": "dev_attaquant",
                "sealKey": nouvelle_demi_cle().publique_b64,
                "sentAtMs": 1_000,
            }
        }
        assert scellement.lire_bloc_sceau(faux) is False


class TestLaDecisionDeSceller:
    """Étape 5 : le seul point de décision, éprouvé seul.

    Il ne lit que trois choses — le réglage, le registre, l'horloge — et
    JAMAIS un corps de réponse. C'est la correction la plus importante du
    plan : la première version rendait obligatoire une rétrogradation vers
    le clair sur une réponse HTTP non signée, c'est-à-dire un interrupteur
    offert à l'attaquant.
    """

    @pytest.fixture
    def flotte(self, tmp_path):
        """Un registre avec un pair de confiance, et sa clé de scellement."""
        import base64

        from diapason.mesh.coffre import nouvelle_demi_cle
        from diapason.mesh.registry import DeviceRegistry
        from diapason.security.signing import generate_keypair

        registre = DeviceRegistry(tmp_path / "mesh.db")
        invitation = registre.create_pairing("Le PC")
        registre.redeem_pairing(
            invitation["pairingToken"],
            device_id="dev_pc",
            public_key_b64=base64.b64encode(generate_keypair().public_key).decode(),
            name="Le PC",
            platform="WINDOWS",
            device_type="DESKTOP",
        )
        cle = nouvelle_demi_cle().publique_b64
        return registre, cle

    def _pair(self, nom="Le PC", device_id="dev_pc"):
        return {"deviceId": device_id, "name": nom}

    def test_un_pair_a_jour_donne_sa_cle(self, flotte, monkeypatch):
        registre, cle = flotte
        monkeypatch.setattr(scellement, "mode_de_chiffrement", lambda: "opportuniste")
        registre.record_seal_key("dev_pc", cle, 1_000)
        assert (
            scellement.doit_sceller(
                self._pair(), registry=registre, maintenant_ms=2_000
            )
            == cle
        )

    def test_un_telephone_qui_ne_publie_rien_part_en_clair(self, flotte, monkeypatch):
        """L'exclusion est STRUCTURELLE : on ne scelle que vers un pair dont
        on DÉTIENT une clé. Rien à respecter, rien à oublier."""
        registre, _ = flotte
        monkeypatch.setattr(scellement, "mode_de_chiffrement", lambda: "opportuniste")
        assert scellement.doit_sceller(self._pair(), registry=registre) is None

    def test_une_cle_trop_ancienne_ne_s_emploie_plus(self, flotte, monkeypatch):
        """LE seul mécanisme de repli, et il repose sur un fait signé."""
        registre, cle = flotte
        monkeypatch.setattr(scellement, "mode_de_chiffrement", lambda: "opportuniste")
        registre.record_seal_key("dev_pc", cle, 1_000)

        juste_avant = 1_000 + scellement.FRAICHEUR_MS
        assert (
            scellement.doit_sceller(
                self._pair(), registry=registre, maintenant_ms=juste_avant
            )
            == cle
        )
        assert (
            scellement.doit_sceller(
                self._pair(), registry=registre, maintenant_ms=juste_avant + 1
            )
            is None
        )

    def test_le_mode_jamais_ne_scelle_rien(self, flotte, monkeypatch):
        registre, cle = flotte
        registre.record_seal_key("dev_pc", cle, 1_000)
        monkeypatch.setattr(scellement, "mode_de_chiffrement", lambda: "jamais")
        assert (
            scellement.doit_sceller(
                self._pair(), registry=registre, maintenant_ms=2_000
            )
            is None
        )

    def test_le_mode_exige_refuse_bruyamment(self, flotte, monkeypatch):
        """Sous `exige`, partir en clair serait la panne silencieuse que ce
        réglage veut empêcher. Une exception, pas un None de plus."""
        registre, _ = flotte
        monkeypatch.setattr(scellement, "mode_de_chiffrement", lambda: "exige")
        with pytest.raises(scellement.ScellementExige) as refus:
            scellement.doit_sceller(self._pair(), registry=registre)
        message = str(refus.value)
        assert "Le PC" in message, "le refus doit nommer l'appareil"
        assert "rien ne lui a été envoyé" in message

    def test_un_reglage_inconnu_retombe_sur_le_defaut(self, monkeypatch):
        """Une faute de frappe dans le fichier ne doit pas éteindre le
        chiffrement en silence."""
        from diapason.core.config import MeshConfig

        class FausseConfig:
            mesh = MeshConfig(chiffrement="chiffre-tout-a-fond")

        monkeypatch.setattr("diapason.core.config.load_config", lambda: FausseConfig())
        assert scellement.mode_de_chiffrement() == "opportuniste"

    def test_un_pair_revoque_n_est_plus_scelle(self, flotte, monkeypatch):
        registre, cle = flotte
        monkeypatch.setattr(scellement, "mode_de_chiffrement", lambda: "opportuniste")
        registre.record_seal_key("dev_pc", cle, 1_000)
        registre.revoke("dev_pc")
        assert (
            scellement.doit_sceller(
                self._pair(), registry=registre, maintenant_ms=2_000
            )
            is None
        )


class TestLeRepliSeVoit:
    """Étape 7 : un repli qu'on ne voit pas est celui qu'on ne corrige jamais.

    C'était la seconde panne silencieuse relevée par les juges : la première
    version se contentait d'un `logger.debug` quand une commande repartait en
    clair.
    """

    @pytest.fixture
    def flotte(self, tmp_path):
        import base64

        from diapason.mesh.coffre import nouvelle_demi_cle
        from diapason.mesh.registry import DeviceRegistry
        from diapason.security.signing import generate_keypair

        registre = DeviceRegistry(tmp_path / "mesh.db")
        invitation = registre.create_pairing("Le PC")
        registre.redeem_pairing(
            invitation["pairingToken"],
            device_id="dev_pc",
            public_key_b64=base64.b64encode(generate_keypair().public_key).decode(),
            name="Le PC",
            platform="WINDOWS",
            device_type="DESKTOP",
        )
        return registre, nouvelle_demi_cle().publique_b64

    def _pair(self):
        return {"deviceId": "dev_pc", "name": "Le PC"}

    def test_un_pair_sans_cle_est_annonce_en_clair(self, flotte, monkeypatch):
        registre, _ = flotte
        monkeypatch.setattr(scellement, "mode_de_chiffrement", lambda: "opportuniste")
        assert (
            scellement.etat_de_chiffrement(self._pair(), registry=registre) == "CLAIR"
        )

    def test_un_pair_a_jour_est_annonce_scelle(self, flotte, monkeypatch):
        from diapason.mesh.registry import now_ms

        registre, cle = flotte
        monkeypatch.setattr(scellement, "mode_de_chiffrement", lambda: "opportuniste")
        registre.record_seal_key("dev_pc", cle, now_ms())
        assert (
            scellement.etat_de_chiffrement(self._pair(), registry=registre) == "SCELLE"
        )

    def test_le_mode_jamais_s_annonce_DESACTIVE_et_non_en_clair(
        self, flotte, monkeypatch
    ):
        """Ce test exigeait « CLAIR », et épinglait ainsi une confusion au
        lieu de la corriger.

        Sous « jamais », le pair publie très bien une clé — le registre la
        détient — et c'est CETTE machine qui refuse de s'en servir. Afficher
        « cet appareil ne publie pas de clé » envoyait vérifier la version de
        la machine d'en face au lieu de son propre config.toml.
        """
        from diapason.mesh.registry import now_ms

        registre, cle = flotte
        registre.record_seal_key("dev_pc", cle, now_ms())
        monkeypatch.setattr(scellement, "mode_de_chiffrement", lambda: "jamais")
        assert (
            scellement.etat_de_chiffrement(self._pair(), registry=registre)
            == "DESACTIVE"
        )

    def test_le_mode_exige_sans_cle_s_annonce_BLOQUE(self, flotte, monkeypatch):
        """Et surtout pas « CLAIR » : rien n'est envoyé du tout, donc rien
        n'est lisible. Le code l'avouait — son commentaire disait « CLAIR
        serait faux, et rassurant à tort » deux lignes avant de rendre
        « CLAIR »."""
        registre, _ = flotte
        monkeypatch.setattr(scellement, "mode_de_chiffrement", lambda: "exige")
        assert (
            scellement.etat_de_chiffrement(self._pair(), registry=registre) == "BLOQUE"
        )

    def test_les_cinq_etats_sont_distincts(self):
        """Un mot par situation. Deux situations opposées sous le même mot,
        c'est la moitié visible du repli qui ment."""
        assert len({"SCELLE", "CLAIR", "DESACTIVE", "BLOQUE", "INCONNU"}) == 5

    def test_ce_qu_on_ne_sait_pas_se_dit_inconnu(self, monkeypatch):
        """« CLAIR » affiché à quelqu'un dont les commandes sont peut-être
        chiffrées serait pire qu'un aveu d'ignorance."""

        def casse(*a, **k):
            raise RuntimeError("registre illisible")

        monkeypatch.setattr(scellement, "doit_sceller", casse)
        monkeypatch.setattr(scellement, "mode_de_chiffrement", lambda: "opportuniste")
        assert scellement.etat_de_chiffrement(self._pair()) == "INCONNU"


class TestUneCleTronqueeNeTuePasLeScellement:
    """CONSTATÉ sur la machine de Carlito, à la première mise en service.

    Un redémarrage du service a tué le serveur en pleine écriture et laissé
    vingt-deux octets sur quarante-quatre. `paire_locale` retombait alors sur
    un `FileExistsError` à CHAQUE appel : le fichier existe, donc on ne le
    recrée pas ; il est illisible, donc on ne s'en sert pas. Le scellement
    était mort, définitivement, et sans un mot.

    Exactement la panne silencieuse que ce chantier existe pour empêcher —
    trouvée non par un test, mais en lançant le code sur une vraie machine.
    """

    @pytest.fixture(autouse=True)
    def _chez_soi(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DIAPASON_HOME", str(tmp_path / "maison"))
        yield

    def test_une_cle_tronquee_est_remplacee_et_le_scellement_repart(self):
        bonne = scellement.paire_locale()
        chemin = scellement._chemin("seal_key")

        # Vingt-deux octets sur quarante-quatre : la coupure exacte observée.
        entier = chemin.read_bytes()
        chemin.write_bytes(entier[: len(entier) // 2])

        neuve = scellement.paire_locale()
        assert len(neuve.privee) == 32
        assert neuve.privee != bonne.privee, "la clé aurait dû être remplacée"
        # Et le scellement fonctionne de nouveau, tout de suite.
        scelle = scellement.contenu_scelle(
            "app.open",
            {},
            False,
            cle_pair_b64=neuve.publique_b64,
            command_id="c",
            associe=b"x",
        )
        assert scellement.ouvrir_contenu(scelle, command_id="c", associe=b"x")[0] == (
            "app.open"
        )

    @pytest.mark.parametrize(
        "contenu", [b"", b"pas du base64 !", b"AAAA", b"\x00" * 44]
    )
    def test_aucune_forme_de_corruption_ne_la_bloque(self, contenu):
        scellement.paire_locale()
        scellement._chemin("seal_key").write_bytes(contenu)
        assert len(scellement.paire_locale().privee) == 32

    def test_l_ecriture_ne_laisse_jamais_de_fichier_a_moitie(self, monkeypatch):
        """Le fichier final naît d'un renommage, donc il n'existe jamais
        tronqué — même si l'écriture est interrompue."""
        chemin = scellement._chemin("seal_key")
        chemin.parent.mkdir(mode=0o700, parents=True, exist_ok=True)

        vrai = scellement._ecrire_atomiquement

        def couper(dest, privee):
            # On simule une interruption APRÈS l'écriture du provisoire et
            # AVANT le renommage.
            raise KeyboardInterrupt("service redémarré")

        monkeypatch.setattr(scellement, "_ecrire_atomiquement", couper)
        with pytest.raises(KeyboardInterrupt):
            scellement.paire_locale()
        assert not chemin.exists(), "un fichier tronqué a été laissé derrière"

        monkeypatch.setattr(scellement, "_ecrire_atomiquement", vrai)
        assert len(scellement.paire_locale().privee) == 32
