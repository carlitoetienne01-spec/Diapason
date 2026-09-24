"""Le gardien : dossier du compte, protecteurs locaux, permission de mémoriser.

Conception : ``docs/development/compte-chiffre.md`` §2.10, §2.11 et les
étapes 3 et 3 bis du §6.

Deux étages. Les classes sans marqueur tournent partout, dans la
vérification du dépôt : elles remplacent ``security``, ``tmutil`` et DPAPI
par des doubles. Les classes marquées ``live`` touchent le VRAI trousseau
et le VRAI ``tmutil`` de ce Mac ; elles sont exclues de
``-m "not live and not cloud and not hub"`` parce que la CI tourne sur ce
même Mac, et se lancent à la main avec ``-m live``.
"""

from __future__ import annotations

import os
import secrets
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from diapason.compte import gardien as g
from diapason.security.file_policy import is_sensitive_file

COMPTE = "acct_Q2FybGl0bw-1"
AMK = bytes(range(32))
JETON = b"jeton-de-session-opaque"

POSIX = os.name != "nt"


# ----------------------------------------------------------------------
# Doubles
# ----------------------------------------------------------------------


def _resultat(args, code=0, sortie=b"", erreur=b""):
    return subprocess.CompletedProcess(list(args), code, sortie, erreur)


class FauxSecurity:
    """Un ``/usr/bin/security -i`` en mémoire : lit la commande sur
    l'entrée standard, comme le vrai, et garde la trace des arguments.

    Deux comportements du vrai, mesurés le 24/09/2026, qu'il reproduit :

    - une ligne de plus de 4 095 caractères (saut de ligne exclu) est
      COUPÉE, et la suite s'exécute comme une seconde commande ;
    - ``add-generic-password`` sans ``-U`` refuse un élément qui existe
      déjà (``returned -25299``).
    """

    COUPURE = 4095

    def __init__(self) -> None:
        self.elements: dict[tuple[str, str], str] = {}
        self.appels: list[tuple[list[str], bytes | None]] = []
        self.verrouille = False
        self.falsifier_relecture = False

    @classmethod
    def _lignes(cls, texte: str) -> list[str]:
        lignes = []
        while texte:
            fin = texte.find("\n")
            if 0 <= fin <= cls.COUPURE:
                lignes.append(texte[:fin])
                texte = texte[fin + 1 :]
            else:
                lignes.append(texte[: cls.COUPURE])
                texte = texte[cls.COUPURE :]
        return [ligne for ligne in lignes if ligne.strip()]

    def __call__(self, args, entree):
        self.appels.append((list(args), entree))
        assert list(args) == ["/usr/bin/security", "-i"], args
        resultat = _resultat(args)
        for ligne in self._lignes(entree.decode("ascii")):
            resultat = self._executer(args, ligne)
        return resultat

    def _executer(self, args, ligne):
        mots = shlex.split(ligne)
        verbe, options = mots[0], mots[1:]
        if verbe not in (
            "add-generic-password",
            "find-generic-password",
            "delete-generic-password",
        ):
            erreur = f'security: unknown command "{verbe}"\n{verbe}: returned 1\n'
            return _resultat(args, 1, b"", erreur.encode())
        valeurs = {}
        i = 0
        while i < len(options):
            if options[i] in ("-a", "-s", "-w") and i + 1 < len(options):
                valeurs[options[i]] = options[i + 1]
                i += 2
            else:
                valeurs[options[i]] = True
                i += 1
        cle = (valeurs["-a"], valeurs["-s"])
        if self.verrouille:
            return _resultat(args, 1, b"", f"{verbe}: returned -25308\n".encode())
        if verbe == "add-generic-password":
            if cle in self.elements and "-U" not in valeurs:
                return _resultat(args, 45, b"", f"{verbe}: returned -25299\n".encode())
            self.elements[cle] = valeurs["-w"]
            return _resultat(args)
        if verbe == "find-generic-password":
            if cle not in self.elements:
                return _resultat(
                    args,
                    44,
                    b"",
                    b"security: SecKeychainSearchCopyNext: The specified item "
                    b"could not be found in the keychain.\n"
                    b"find-generic-password: returned -25300\n",
                )
            valeur = self.elements[cle]
            if self.falsifier_relecture:
                valeur = "00" * 32
            return _resultat(args, 0, (valeur + "\n").encode())
        if self.elements.pop(cle, None) is None:
            return _resultat(args, 44, b"", b"x: returned -25300\n")
        return _resultat(args, 0, b"password has been deleted.\n")


class FauxTmutil:
    """``tmutil`` en mémoire : ``[Included]`` tant que ``addexclusion`` n'a
    pas été appelé (ou toujours, si ``exclut`` est faux)."""

    def __init__(
        self, *, exclut: bool = True, absent: bool = False, deja: bool = False
    ) -> None:
        self.exclut = exclut
        self.absent = absent
        self.pose = deja
        self.appels: list[list[str]] = []

    def __call__(self, args, entree):
        self.appels.append(list(args))
        if self.absent:
            raise FileNotFoundError(args[0])
        if args[1] == "addexclusion":
            self.pose = True
            return _resultat(args)
        exclu = self.pose and self.exclut
        etiquette = b"[Excluded]" if exclu else b"[Included]"
        return _resultat(args, 0, etiquette + b"  " + args[2].encode() + b"\n")


def _faux_dpapi():
    """Un DPAPI réversible qui garde trace de l'entropie reçue."""
    vues: list[bytes] = []

    def proteger(donnees: bytes, entropie: bytes) -> bytes:
        vues.append(entropie)
        return b"DPAPI" + entropie + b"|" + bytes(b ^ 0x5A for b in donnees)

    def deproteger(blob: bytes, entropie: bytes) -> bytes:
        vues.append(entropie)
        entete = b"DPAPI" + entropie + b"|"
        if not blob.startswith(entete):
            raise g.ErreurGardien("mauvaise entropie", code="dpapiUnavailable")
        return bytes(b ^ 0x5A for b in blob[len(entete) :])

    return proteger, deproteger, vues


@pytest.fixture
def dossier(tmp_path: Path) -> g.DossierCompte:
    return g.preparer_dossier_compte(tmp_path, plateforme="linux")


# ----------------------------------------------------------------------
# Le dossier du compte
# ----------------------------------------------------------------------


class TestLeDossierDuCompte:
    def test_il_est_cree_en_0700_sous_la_racine(self, tmp_path):
        """§2.10 — ``compte/`` en 0700 : un dossier en 0755 laisserait tout
        compte de la machine lister, voire lire, les fichiers de clé."""
        dossier = g.preparer_dossier_compte(tmp_path, plateforme="linux")
        assert dossier.chemin == tmp_path / "compte", (
            "compte/ directement sous la racine"
        )
        assert dossier.chemin.is_dir(), "le dossier doit exister"
        if POSIX:
            mode = stat.S_IMODE(os.lstat(dossier.chemin).st_mode)
            assert mode == 0o700, f"compte/ doit être en 0700, pas {oct(mode)}"
        assert dossier.exclu_time_machine is None, (
            "hors macOS, l'exclusion Time Machine est sans objet, pas « réussie »"
        )

    @pytest.mark.skipif(not POSIX, reason="bits POSIX")
    def test_un_dossier_elargi_est_resserre(self, tmp_path):
        """§2.10 — un ``compte/`` repris en 0755 (restauration, copie à la
        main) doit revenir en 0700, pas être accepté tel quel."""
        (tmp_path / "compte").mkdir(mode=0o755)
        os.chmod(tmp_path / "compte", 0o755)
        g.preparer_dossier_compte(tmp_path, plateforme="linux")
        mode = stat.S_IMODE(os.lstat(tmp_path / "compte").st_mode)
        assert mode == 0o700, (
            f"le dossier repris doit être resserré, il est {oct(mode)}"
        )

    def test_un_magicmock_est_refuse_et_rien_n_est_ecrit(self, tmp_path, monkeypatch):
        """CLAUDE.md §5 — ``Path(MagicMock())`` écrit « MagicMock/… » dans le
        dossier courant : 42 bases SQLite ont dormi à la racine du dépôt.
        Ici ce serait une clé."""
        monkeypatch.chdir(tmp_path)
        with pytest.raises(g.CheminRefuse):
            g.preparer_dossier_compte(MagicMock(), plateforme="linux")
        assert list(tmp_path.iterdir()) == [], (
            "un double refusé ne doit rien laisser sur le disque"
        )

    @pytest.mark.parametrize("racine", ["", "   ", "relatif/config"])
    def test_une_racine_vide_ou_relative_est_refusee(
        self, racine, tmp_path, monkeypatch
    ):
        """Un chemin relatif se résout contre le dossier courant du serveur
        — le dépôt, sous launchd : refusé avant toute écriture."""
        monkeypatch.chdir(tmp_path)
        with pytest.raises(g.CheminRefuse):
            g.preparer_dossier_compte(racine, plateforme="linux")
        assert list(tmp_path.iterdir()) == [], "rien ne doit être créé"

    def test_une_racine_absente_est_refusee(self, tmp_path):
        """La racine n'est pas créée ici : une racine absente est une
        configuration fausse, pas un dossier à inventer."""
        absente = tmp_path / "nulle-part"
        with pytest.raises(g.CheminRefuse):
            g.preparer_dossier_compte(absente, plateforme="linux")
        assert not absente.exists(), "la racine absente ne doit pas être créée"

    def test_la_racine_du_disque_est_refusee(self):
        """``/compte`` n'est pas le dossier du compte, quoi qu'en dise une
        variable d'environnement vide résolue trop tôt."""
        with pytest.raises(g.CheminRefuse):
            g.preparer_dossier_compte(Path(Path.cwd().anchor), plateforme="linux")

    def test_une_racine_qui_est_un_fichier_est_refusee(self, tmp_path):
        fichier = tmp_path / "config"
        fichier.write_text("x")
        with pytest.raises(g.CheminRefuse):
            g.preparer_dossier_compte(fichier, plateforme="linux")

    @pytest.mark.skipif(not POSIX, reason="liens symboliques POSIX")
    def test_un_compte_qui_est_un_lien_est_refuse(self, tmp_path):
        """§2.10 — un ``compte/`` remplacé par un lien vers un dossier
        partagé ferait écrire la clé là-bas."""
        ailleurs = tmp_path / "ailleurs"
        ailleurs.mkdir()
        racine = tmp_path / "config"
        racine.mkdir()
        (racine / "compte").symlink_to(ailleurs)
        with pytest.raises(g.CheminRefuse):
            g.preparer_dossier_compte(racine, plateforme="linux")
        assert list(ailleurs.iterdir()) == [], "rien ne doit être écrit au bout du lien"


class TestLExclusionTimeMachine:
    def test_sous_macos_l_exclusion_est_posee_puis_relue(self, tmp_path):
        """§2.11 — ``tmutil isexcluded ~/.diapason`` rendait ``[Included]`` :
        la clé partait dans chaque sauvegarde. L'exclusion est posée, puis
        RELUE : c'est ``isexcluded`` qui dit oui, pas le code de retour."""
        faux = FauxTmutil()
        dossier = g.preparer_dossier_compte(
            tmp_path, plateforme="darwin", executer=faux
        )
        assert dossier.exclu_time_machine is True, (
            "l'exclusion confirmée doit être dite"
        )
        compte = str(tmp_path / "compte")
        assert faux.appels == [
            ["/usr/bin/tmutil", "isexcluded", compte],
            ["/usr/bin/tmutil", "addexclusion", compte],
            ["/usr/bin/tmutil", "isexcluded", compte],
        ], "relire, poser sans sudo, relire — sur compte/ lui-même"

    def test_une_exclusion_deja_posee_ne_repaie_pas_onze_secondes(self, tmp_path):
        """§2.10 « au premier usage » — ``addexclusion`` prend 11 s sur ce
        Mac (24/09/2026) ; l'exclusion est collante, on ne la repose pas à
        chaque lancement."""
        faux = FauxTmutil(deja=True)
        dossier = g.preparer_dossier_compte(
            tmp_path, plateforme="darwin", executer=faux
        )
        assert dossier.exclu_time_machine is True, "déjà exclu doit être dit exclu"
        assert [a[1] for a in faux.appels] == ["isexcluded"], (
            "une exclusion déjà posée ne doit pas être reposée"
        )

    def test_une_exclusion_non_confirmee_n_est_pas_dite_reussie(self, tmp_path):
        """§100 — ``addexclusion`` a rendu 0 mais ``isexcluded`` dit
        ``[Included]`` : c'est un échec, et il doit se voir."""
        dossier = g.preparer_dossier_compte(
            tmp_path, plateforme="darwin", executer=FauxTmutil(exclut=False)
        )
        assert dossier.exclu_time_machine is False, "non confirmée = non exclue"

    def test_tmutil_absent_n_empeche_pas_le_dossier(self, tmp_path):
        """Un ``tmutil`` injoignable ne doit ni lever ni prétendre : le
        dossier existe, l'exclusion est dite ratée."""
        dossier = g.preparer_dossier_compte(
            tmp_path, plateforme="darwin", executer=FauxTmutil(absent=True)
        )
        assert dossier.chemin.is_dir(), "le dossier doit exister quand même"
        assert dossier.exclu_time_machine is False, "l'échec doit être dit"


# ----------------------------------------------------------------------
# macOS : le trousseau, par l'entrée standard
# ----------------------------------------------------------------------


class TestLeTrousseauParLEntreeStandard:
    def test_le_secret_passe_par_l_entree_et_jamais_en_argument(self):
        """§2.10 — ``security add-generic-password -w <secret>`` exposerait
        le secret à tout ``ps`` pendant l'appel. Seul ``-i`` est un
        argument ; le secret voyage sur l'entrée standard."""
        faux = FauxSecurity()
        g.ProtecteurTrousseauMac(executer=faux).ranger(COMPTE, g.ELEMENT_AMK, AMK)
        for args, entree in faux.appels:
            assert args == ["/usr/bin/security", "-i"], f"arguments inattendus : {args}"
            assert AMK.hex() not in " ".join(args), (
                "le secret ne doit pas être en argument"
            )
        ecriture = faux.appels[0][1]
        assert AMK.hex().encode() in ecriture, (
            "le secret doit passer par l'entrée standard"
        )

    def test_l_aller_retour_rend_le_secret(self):
        """§2.10 — service « Diapason Compte », compte « <id>/amk »."""
        faux = FauxSecurity()
        protecteur = g.ProtecteurTrousseauMac(executer=faux)
        protecteur.ranger(COMPTE, g.ELEMENT_AMK, AMK)
        assert protecteur.lire(COMPTE, g.ELEMENT_AMK) == AMK, "l'AMK doit revenir"
        assert (f"{COMPTE}/amk", "Diapason Compte") in faux.elements, (
            "le service doit être « Diapason Compte »"
        )

    def test_un_amk_toute_imprimable_revient_intacte(self):
        """``find-generic-password -w`` rend un mot de passe imprimable tel
        quel et un binaire en hexadécimal : le secret est rangé en hexa
        pour que le relu ne dépende pas de ses octets."""
        faux = FauxSecurity()
        protecteur = g.ProtecteurTrousseauMac(executer=faux)
        imprimable = b"A" * 32
        protecteur.ranger(COMPTE, g.ELEMENT_AMK, imprimable)
        assert protecteur.lire(COMPTE, g.ELEMENT_AMK) == imprimable, (
            "une AMK faite d'octets imprimables doit revenir identique"
        )

    def test_rien_de_range_rend_none(self):
        """-25300 : « rien de rangé », qui n'est pas une erreur."""
        protecteur = g.ProtecteurTrousseauMac(executer=FauxSecurity())
        assert protecteur.lire(COMPTE, g.ELEMENT_AMK) is None, "absent doit rendre None"

    def test_un_trousseau_verrouille_leve_au_lieu_de_rendre_none(self):
        """§5 — un trousseau verrouillé (-25308, session SSH) confondu avec
        « jamais mémorisé » ferait croire à l'utilisateur qu'il a décoché
        la case."""
        faux = FauxSecurity()
        faux.verrouille = True
        with pytest.raises(g.ErreurGardien) as exc:
            g.ProtecteurTrousseauMac(executer=faux).lire(COMPTE, g.ELEMENT_AMK)
        assert exc.value.code == "keychainUnavailable", (
            "le code doit dire l'indisponibilité"
        )

    def test_une_ecriture_non_relue_n_est_pas_un_succes(self):
        """§100 — ``security`` a rendu 0 mais le relu diffère : l'écriture
        est un échec, pas un « mémorisé »."""
        faux = FauxSecurity()
        faux.falsifier_relecture = True
        with pytest.raises(g.ErreurGardien):
            g.ProtecteurTrousseauMac(executer=faux).ranger(COMPTE, g.ELEMENT_AMK, AMK)

    @pytest.mark.parametrize(
        "compte",
        ['a" -s "Autre', "a\ndelete-generic-password -s x", "a b", "", "é", "x" * 129],
    )
    def test_un_identifiant_qui_injecterait_une_commande_est_refuse(self, compte):
        """La ligne envoyée à ``security -i`` est analysée : un guillemet ou
        un saut de ligne dans l'accountId y ferait une seconde commande.
        Refusé AVANT tout appel."""
        faux = FauxSecurity()
        with pytest.raises(g.ErreurGardien) as exc:
            g.ProtecteurTrousseauMac(executer=faux).ranger(compte, g.ELEMENT_AMK, AMK)
        assert exc.value.code == "accountIdInvalid", "le code doit nommer l'identifiant"
        assert faux.appels == [], "security ne doit pas avoir été appelé"

    def test_un_service_qui_injecterait_une_commande_est_refuse(self):
        with pytest.raises(g.ErreurGardien):
            g.ProtecteurTrousseauMac('x" -a "y')

    def test_l_erreur_ne_recopie_pas_la_sortie_de_security(self):
        """§2.10 — aucun secret dans un journal : le message d'erreur ne
        garde que le code « returned -N », jamais le reste de stderr."""

        def bavard(args, entree):
            return _resultat(
                args, 1, b"", entree + b"add-generic-password: returned -1\n"
            )

        with pytest.raises(g.ErreurGardien) as exc:
            g.ProtecteurTrousseauMac(executer=bavard).ranger(COMPTE, g.ELEMENT_AMK, AMK)
        assert AMK.hex() not in str(exc.value), (
            "le secret ne doit pas finir dans l'erreur"
        )

    def test_effacer_un_absent_ne_leve_pas(self):
        protecteur = g.ProtecteurTrousseauMac(executer=FauxSecurity())
        protecteur.effacer(COMPTE, g.ELEMENT_SESSION)

    def test_un_element_inconnu_est_refuse(self):
        with pytest.raises(g.ErreurGardien):
            g.ProtecteurTrousseauMac(executer=FauxSecurity()).ranger(
                COMPTE, "autre", AMK
            )

    @pytest.mark.parametrize("secret", ["texte", b"", b"x" * (g._SECRET_MAX_O + 1)])
    def test_un_secret_mal_forme_est_refuse(self, secret):
        """Un ``str`` s'encode chez l'appelant ; vide ou démesuré, c'est une
        erreur d'appel, pas un secret."""
        with pytest.raises(g.ErreurGardien):
            g.ProtecteurTrousseauMac(executer=FauxSecurity()).ranger(
                COMPTE, g.ELEMENT_AMK, secret
            )


# ----------------------------------------------------------------------
# Fichier 0600 dans compte/
# ----------------------------------------------------------------------


class TestLeFichier:
    def test_l_aller_retour_ecrit_un_fichier_0600_dans_compte(self, dossier):
        """§2.10 — ``compte/session.key`` en 0600, et rien d'autre dans le
        dossier (pas de provisoire abandonné)."""
        protecteur = g.ProtecteurFichier(dossier)
        protecteur.ranger(COMPTE, g.ELEMENT_SESSION, JETON)
        assert protecteur.lire(COMPTE, g.ELEMENT_SESSION) == JETON, (
            "le jeton doit revenir"
        )
        assert sorted(p.name for p in dossier.chemin.iterdir()) == ["session.key"], (
            "seul session.key doit exister dans compte/"
        )
        if POSIX:
            mode = stat.S_IMODE(os.lstat(dossier.chemin / "session.key").st_mode)
            assert mode == 0o600, f"le fichier doit être en 0600, pas {oct(mode)}"

    def test_un_autre_compte_ne_relit_pas_le_secret(self, dossier):
        """Un fichier laissé par un autre compte rend None, pas sa clé."""
        protecteur = g.ProtecteurFichier(dossier)
        protecteur.ranger(COMPTE, g.ELEMENT_AMK, AMK)
        assert protecteur.lire("autre-compte", g.ELEMENT_AMK) is None, (
            "le secret d'un autre compte ne doit pas être rendu"
        )

    def test_effacer_supprime_le_fichier(self, dossier):
        protecteur = g.ProtecteurFichier(dossier)
        protecteur.ranger(COMPTE, g.ELEMENT_AMK, AMK)
        protecteur.effacer(COMPTE, g.ELEMENT_AMK)
        assert protecteur.lire(COMPTE, g.ELEMENT_AMK) is None, "effacé doit rendre None"
        assert not (dossier.chemin / "amk.key").exists(), (
            "le fichier doit avoir disparu"
        )

    def test_un_chemin_nu_est_refuse(self, tmp_path):
        """« 0600 dans compte/, jamais ailleurs » : un ``Path`` quelconque
        n'est pas un dossier validé."""
        with pytest.raises(g.CheminRefuse):
            g.ProtecteurFichier(tmp_path)  # type: ignore[arg-type]
        with pytest.raises(g.CheminRefuse):
            g.ProtecteurFichier(MagicMock())  # type: ignore[arg-type]

    @pytest.mark.skipif(not POSIX, reason="liens symboliques POSIX")
    def test_un_dossier_remplace_par_un_lien_apres_coup_est_refuse(self, tmp_path):
        """Le dossier est revalidé à CHAQUE écriture : remplacé par un lien
        entre la préparation et l'écriture, il ne doit rien recevoir."""
        dossier = g.preparer_dossier_compte(tmp_path, plateforme="linux")
        ailleurs = tmp_path / "ailleurs"
        ailleurs.mkdir()
        dossier.chemin.rmdir()
        dossier.chemin.symlink_to(ailleurs)
        with pytest.raises(g.CheminRefuse):
            g.ProtecteurFichier(dossier).ranger(COMPTE, g.ELEMENT_AMK, AMK)
        assert list(ailleurs.iterdir()) == [], "rien ne doit être écrit au bout du lien"

    def test_un_fichier_corrompu_leve(self, dossier):
        (dossier.chemin / "amk.key").write_bytes(b"pas du json")
        with pytest.raises(g.ErreurGardien) as exc:
            g.ProtecteurFichier(dossier).lire(COMPTE, g.ELEMENT_AMK)
        assert exc.value.code == "protectedFileCorrupt", (
            "le code doit dire la corruption"
        )


# ----------------------------------------------------------------------
# La ligne envoyée à security -i (contre-épreuve du 24/09/2026)
# ----------------------------------------------------------------------

COMPTE_LONG = "a" * 128
SERVICE_LONG = "S" * 80


class TestLaLigneDeSecurity:
    def test_la_plus_longue_ligne_legitime_tient_sous_la_borne(self):
        """§2.10 — ``security -i`` coupe une ligne au-delà de 4 095
        caractères (mesuré le 24/09/2026) : un secret de la taille permise,
        avec l'accountId et le service les plus longs, doit tenir sous la
        borne ET revenir identique. Avec l'ancienne borne de 4 Kio, la
        ligne faisait plus de 8 Kio et la fin devenait une commande."""
        faux = FauxSecurity()
        protecteur = g.ProtecteurTrousseauMac(SERVICE_LONG, executer=faux)
        secret = bytes([0xAB]) * g._SECRET_MAX_O
        protecteur.ranger(COMPTE_LONG, g.ELEMENT_SESSION, secret)
        longueur = max(len(entree) for _, entree in faux.appels)
        assert longueur <= g._LIGNE_SECURITY_MAX_O, (
            f"ligne de {longueur} octets, au-delà de la borne"
        )
        assert longueur <= FauxSecurity.COUPURE + 1, (
            "la ligne dépasserait la coupure mesurée de security -i"
        )
        assert protecteur.lire(COMPTE_LONG, g.ELEMENT_SESSION) == secret, (
            "un secret de taille maximale doit revenir identique"
        )

    def test_une_ligne_trop_longue_est_refusee_avant_l_appel(self, monkeypatch):
        """§100 — si la borne du secret régressait, une ligne coupée écraserait
        l'élément valide par un secret tronqué, relu ensuite sans erreur. La
        ligne est donc mesurée AVANT l'appel, et l'élément existant survit."""
        faux = FauxSecurity()
        protecteur = g.ProtecteurTrousseauMac(executer=faux)
        protecteur.ranger(COMPTE, g.ELEMENT_SESSION, JETON)
        appels_avant = len(faux.appels)
        monkeypatch.setattr(g, "_SECRET_MAX_O", 4096)
        with pytest.raises(g.ErreurGardien) as exc:
            protecteur.ranger(COMPTE, g.ELEMENT_SESSION, b"\x01" * 2100)
        assert exc.value.code == "secretInvalid", "le code doit nommer le secret"
        assert len(faux.appels) == appels_avant, "security ne doit pas être appelé"
        assert protecteur.lire(COMPTE, g.ELEMENT_SESSION) == JETON, (
            "l'élément valide ne doit pas avoir été écrasé"
        )

    def test_un_element_faux_apres_ecriture_est_efface(self):
        """§100 — un élément qui ne rend pas ce qu'on y a mis serait relu au
        lancement suivant comme bon : l'échec de la relecture l'efface."""
        faux = FauxSecurity()
        faux.falsifier_relecture = True
        with pytest.raises(g.ErreurGardien):
            g.ProtecteurTrousseauMac(executer=faux).ranger(COMPTE, g.ELEMENT_AMK, AMK)
        assert faux.elements == {}, "l'élément faux doit avoir été effacé"


# ----------------------------------------------------------------------
# Le cycle de vie, pour chaque protecteur
# ----------------------------------------------------------------------


def _protecteurs(dossier: g.DossierCompte) -> dict[str, g.Protecteur]:
    proteger, deproteger, _ = _faux_dpapi()
    return {
        "keychain": g.ProtecteurTrousseauMac(executer=FauxSecurity()),
        "file": g.ProtecteurFichier(dossier),
        "dpapi": g.ProtecteurDpapi(dossier, proteger=proteger, deproteger=deproteger),
        "memory": g.ProtecteurMemoire(),
    }


@pytest.mark.parametrize("nom", ["keychain", "file", "dpapi", "memory"])
class TestLeCycleDeChaqueProtecteur:
    def test_recrire_puis_effacer(self, nom, dossier):
        """§3.7 — chaque reconnexion RÉCRIT le jeton, et ``sessionRevoked``
        efface l'AMK et le jeton. Un écrasement ou un effacement cassé
        laisserait le secret d'hier : c'est le chemin même du §100."""
        protecteur = _protecteurs(dossier)[nom]
        for element in (g.ELEMENT_AMK, g.ELEMENT_SESSION):
            protecteur.ranger(COMPTE, element, b"premier")
            protecteur.ranger(COMPTE, element, b"second")
            assert protecteur.lire(COMPTE, element) == b"second", (
                f"{nom} : la seconde écriture doit remplacer la première"
            )
            protecteur.effacer(COMPTE, element)
            assert protecteur.lire(COMPTE, element) is None, (
                f"{nom} : effacé doit rendre None"
            )
        if nom in ("file", "dpapi"):
            assert list(dossier.chemin.iterdir()) == [], (
                f"{nom} : effacer doit vider compte/"
            )

    def test_un_compte_ne_lit_pas_le_secret_d_un_autre(self, nom, dossier):
        """§2.10 — le secret est rangé sous l'accountId : relu sous un autre,
        il rend None, pas la clé d'un autre compte."""
        protecteur = _protecteurs(dossier)[nom]
        protecteur.ranger("compte-a", g.ELEMENT_AMK, AMK)
        assert protecteur.lire("compte-b", g.ELEMENT_AMK) is None, (
            f"{nom} : un autre compte ne doit rien relire"
        )
        protecteur.effacer("compte-b", g.ELEMENT_AMK)
        if nom in ("keychain", "memory"):
            assert protecteur.lire("compte-a", g.ELEMENT_AMK) == AMK, (
                f"{nom} : effacer un autre compte ne doit pas toucher celui-ci"
            )


# ----------------------------------------------------------------------
# Les provisoires et la concurrence (contre-épreuve du 24/09/2026)
# ----------------------------------------------------------------------


def _vieillir(chemin: Path, secondes: float) -> None:
    passe = time.time() - secondes
    os.utime(chemin, (passe, passe))


class TestLesProvisoires:
    @pytest.mark.parametrize(
        "provisoire", [".99999.amk.key", ".99999.0123456789abcdef.amk.key"]
    )
    def test_effacer_supprime_un_provisoire_abandonne(self, dossier, provisoire):
        """§2.10 — un processus tué entre ``os.open`` et ``os.replace`` laisse
        un provisoire qui porte l'AMK. Décocher « Garder cet appareil
        déverrouillé » doit le faire disparaître aussi."""
        (dossier.chemin / provisoire).write_bytes(b"AMK abandonnee")
        protecteur = g.ProtecteurFichier(dossier)
        protecteur.ranger(COMPTE, g.ELEMENT_AMK, AMK)
        protecteur.effacer(COMPTE, g.ELEMENT_AMK)
        assert list(dossier.chemin.iterdir()) == [], (
            "ni amk.key ni son provisoire ne doivent survivre à effacer()"
        )

    def test_effacer_ne_touche_pas_l_autre_element(self, dossier):
        protecteur = g.ProtecteurFichier(dossier)
        protecteur.ranger(COMPTE, g.ELEMENT_SESSION, JETON)
        (dossier.chemin / ".1.abcd.session.key").write_bytes(b"x")
        protecteur.effacer(COMPTE, g.ELEMENT_AMK)
        assert sorted(p.name for p in dossier.chemin.iterdir()) == [
            ".1.abcd.session.key",
            "session.key",
        ], "effacer l'AMK ne doit rien ôter au jeton"

    def test_la_preparation_purge_les_provisoires_abandonnes(self, tmp_path):
        """Un provisoire de plus de 60 s est abandonné : la préparation le
        supprime. Un provisoire récent (une écriture en cours dans un autre
        processus) et les fichiers définitifs restent."""
        dossier = g.preparer_dossier_compte(tmp_path, plateforme="linux")
        vieux = dossier.chemin / ".4242.00ff.amk.key"
        recent = dossier.chemin / ".4243.00fe.session.key"
        definitif = dossier.chemin / "session.key"
        for chemin in (vieux, recent, definitif):
            chemin.write_bytes(b"x")
        _vieillir(vieux, 3600)
        _vieillir(definitif, 3600)
        g.preparer_dossier_compte(tmp_path, plateforme="linux")
        assert not vieux.exists(), "un provisoire abandonné doit être purgé"
        assert recent.exists(), "un provisoire récent peut être une écriture en cours"
        assert definitif.exists(), "un fichier définitif ne doit jamais être purgé"

    def test_un_echec_d_ecriture_ne_laisse_aucun_provisoire(self, dossier, monkeypatch):
        """§2.10 — si ``os.replace`` échoue, le provisoire qui porte le
        secret est supprimé, et l'erreur est une ErreurGardien, pas une
        OSError brute qui ferait une 500 à l'étape 8."""

        def replace_casse(source, cible):
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(g.os, "replace", replace_casse)
        with pytest.raises(g.ErreurGardien) as exc:
            g.ProtecteurFichier(dossier).ranger(COMPTE, g.ELEMENT_AMK, AMK)
        monkeypatch.undo()
        assert exc.value.code == "protectedFileUnavailable", (
            "le code doit dire l'indisponibilité"
        )
        assert list(dossier.chemin.iterdir()) == [], (
            "aucun provisoire ne doit survivre à l'échec"
        )

    def test_des_ecritures_concurrentes_ne_levent_pas_et_ne_mentent_pas(self, dossier):
        """§100 — les routes ``def`` tournent dans un pool de fils. Avec un
        provisoire commun à tous les fils, 503 écritures sur 900 levaient
        une OSError brute, et l'une pouvait ranger la valeur d'une autre."""
        protecteur = g.ProtecteurFichier(dossier)
        ecrites = {f"valeur-{f}-{i}".encode() for f in range(3) for i in range(150)}
        erreurs: list[BaseException] = []
        lues: list[bytes | None] = []
        fin = threading.Event()

        def ecrire(f: int) -> None:
            for i in range(150):
                try:
                    protecteur.ranger(
                        COMPTE, g.ELEMENT_SESSION, f"valeur-{f}-{i}".encode()
                    )
                except BaseException as exc:  # noqa: BLE001 - on les compte
                    erreurs.append(exc)

        def lire() -> None:
            while not fin.is_set():
                try:
                    lues.append(protecteur.lire(COMPTE, g.ELEMENT_SESSION))
                except BaseException as exc:  # noqa: BLE001 - on les compte
                    erreurs.append(exc)

        lecteur = threading.Thread(target=lire)
        lecteur.start()
        fils = [threading.Thread(target=ecrire, args=(f,)) for f in range(3)]
        for fil in fils:
            fil.start()
        for fil in fils:
            fil.join()
        fin.set()
        lecteur.join()
        assert erreurs == [], f"{len(erreurs)} erreurs, dont {erreurs[:3]!r}"
        assert protecteur.lire(COMPTE, g.ELEMENT_SESSION) in ecrites, (
            "la valeur finale doit être l'une des valeurs écrites"
        )
        assert {v for v in lues if v is not None} <= ecrites, (
            "une lecture ne doit jamais rendre une valeur qui n'a pas été écrite"
        )
        assert [p.name for p in dossier.chemin.iterdir()] == ["session.key"], (
            "aucun provisoire ne doit rester"
        )


class TestLeFichierHorsTimeMachine:
    def test_un_dossier_non_exclu_ne_recoit_pas_le_jeton(self, tmp_path):
        """§2.10 — « ``compte/session.key``, 0600, exclu de Time Machine » :
        si l'exclusion a échoué, le jeton partirait dans chaque sauvegarde.
        L'écriture est refusée, et le code le dit à l'écran (§5)."""
        dossier = g.preparer_dossier_compte(
            tmp_path, plateforme="darwin", executer=FauxTmutil(exclut=False)
        )
        with pytest.raises(g.ErreurGardien) as exc:
            g.ProtecteurFichier(dossier).ranger(COMPTE, g.ELEMENT_SESSION, JETON)
        assert exc.value.code == "backupExclusionFailed", (
            "le code doit nommer l'exclusion ratée"
        )
        assert list(dossier.chemin.iterdir()) == [], "rien ne doit être écrit"


@pytest.mark.skipif(not POSIX, reason="liens symboliques et FIFO POSIX")
class TestUnFichierPlanteALaPlaceDuSecret:
    def test_un_lien_plante_est_refuse_sans_oserror_brute(self, dossier):
        """``compte/`` est en 0700, mais un processus du même utilisateur
        peut y planter un lien : la lecture doit le refuser par une
        CheminRefuse, pas par une OSError (ELOOP) qui ferait une 500."""
        cible = dossier.chemin.parent / "ailleurs"
        cible.write_bytes(b"{}")
        (dossier.chemin / "amk.key").symlink_to(cible)
        with pytest.raises(g.CheminRefuse):
            g.ProtecteurFichier(dossier).lire(COMPTE, g.ELEMENT_AMK)

    def test_une_fifo_ne_bloque_pas_la_lecture(self, dossier):
        """Une FIFO à la place de ``amk.key`` bloquait ``os.open`` pour
        toujours, et la route avec lui : elle doit être refusée tout de
        suite."""
        fifo = dossier.chemin / "amk.key"
        os.mkfifo(fifo)
        resultat: list[BaseException | bytes | None] = []

        def lire() -> None:
            try:
                resultat.append(
                    g.ProtecteurFichier(dossier).lire(COMPTE, g.ELEMENT_AMK)
                )
            except BaseException as exc:  # noqa: BLE001 - on l'examine
                resultat.append(exc)

        fil = threading.Thread(target=lire, daemon=True)
        fil.start()
        fil.join(2)
        try:
            assert not fil.is_alive(), "la lecture d'une FIFO ne doit pas bloquer"
            assert isinstance(resultat[0], g.CheminRefuse), (
                f"une FIFO doit être refusée, pas {resultat[0]!r}"
            )
        finally:
            if fil.is_alive():
                # Débloquer le lecteur : un écrivain ouvre puis referme.
                os.close(os.open(fifo, os.O_WRONLY | os.O_NONBLOCK))
                fil.join(2)


class TestLesGardesDeLaRacine:
    def test_un_dossier_relatif_qui_existe_est_refuse(self, tmp_path, monkeypatch):
        """Sous launchd, le dossier courant est le dépôt : un ``config/``
        relatif qui y existe ne doit pas recevoir ``compte/``."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "config").mkdir()
        with pytest.raises(g.CheminRefuse):
            g.preparer_dossier_compte("config", plateforme="linux")
        assert list((tmp_path / "config").iterdir()) == [], "rien ne doit être créé"

    def test_un_pathlike_etranger_est_refuse_meme_absolu(self, tmp_path):
        """CLAUDE.md §5 — ``MagicMock`` a un ``__fspath__`` : tout objet
        chemin qui n'est ni ``str`` ni ``Path`` est refusé, même s'il rend un
        dossier absolu qui existe."""

        class CheminEtranger:
            def __fspath__(self) -> str:
                return str(tmp_path)

        with pytest.raises(g.CheminRefuse):
            g.preparer_dossier_compte(CheminEtranger(), plateforme="linux")  # type: ignore[arg-type]
        assert list(tmp_path.iterdir()) == [], "rien ne doit être créé"

    def test_un_dossier_hors_de_sa_racine_est_refuse(self, tmp_path):
        """Un ``DossierCompte`` dont le chemin remonte (``…/sous/..``) ne
        désigne pas le ``compte/`` de sa racine : rien n'y est écrit."""
        (tmp_path / "sous").mkdir()
        faux = g.DossierCompte(chemin=tmp_path / "sous" / "..", exclu_time_machine=None)
        with pytest.raises(g.CheminRefuse):
            g.ProtecteurFichier(faux).ranger(COMPTE, g.ELEMENT_AMK, AMK)
        assert sorted(p.name for p in tmp_path.iterdir()) == ["sous"], (
            "rien ne doit être écrit hors de compte/"
        )


class TestLesDelaisDesCommandes:
    @pytest.mark.parametrize(
        ("arguments", "delai"),
        [
            (["/usr/bin/tmutil", "addexclusion", "/x"], 30.0),
            (["/usr/bin/tmutil", "isexcluded", "/x"], 10.0),
            (["/usr/bin/security", "-i"], 10.0),
        ],
    )
    def test_addexclusion_a_trente_secondes_le_reste_dix(
        self, arguments, delai, monkeypatch
    ):
        """24/09/2026 — ``tmutil addexclusion`` prend 11 s sur ce Mac : sous
        un délai de 10 s, l'exclusion était dite ratée à chaque fois."""
        vus: dict[str, object] = {}

        def run(args, **kwargs):
            vus.update(kwargs)
            return _resultat(args)

        monkeypatch.setattr(g.subprocess, "run", run)
        g._executer_systeme(arguments, None)
        assert vus["timeout"] == delai, f"{arguments[:2]} doit avoir {delai} s"
        assert "env" not in vus and "shell" not in vus, "ni env ni shell"


# ----------------------------------------------------------------------
# Windows : DPAPI, logique pure et vrai appel
# ----------------------------------------------------------------------


class TestDpapiLogiquePure:
    def test_l_entropie_est_celle_de_la_conception(self, dossier):
        """§2.10 — entropie ``b"diapason/compte/v1" + accountId`` : une
        autre entropie rendrait les blobs illisibles d'une version à l'autre."""
        proteger, deproteger, vues = _faux_dpapi()
        protecteur = g.ProtecteurDpapi(
            dossier, proteger=proteger, deproteger=deproteger
        )
        protecteur.ranger(COMPTE, g.ELEMENT_AMK, AMK)
        assert protecteur.lire(COMPTE, g.ELEMENT_AMK) == AMK, "l'AMK doit revenir"
        attendu = b"diapason/compte/v1" + COMPTE.encode()
        assert vues == [attendu, attendu], "l'entropie doit être celle du §2.10"

    def test_le_fichier_porte_le_blob_et_jamais_le_clair(self, dossier):
        proteger, deproteger, _ = _faux_dpapi()
        g.ProtecteurDpapi(dossier, proteger=proteger, deproteger=deproteger).ranger(
            COMPTE, g.ELEMENT_AMK, AMK
        )
        contenu = (dossier.chemin / "amk.dpapi.key").read_bytes()
        assert AMK not in contenu and AMK.hex().encode() not in contenu, (
            "le clair ne doit pas être sur le disque"
        )

    @pytest.mark.parametrize(
        ("reussi", "erreur", "attendu"),
        [
            (True, 0, "absent"),
            (False, 1327, "absent"),
            (False, 1326, "present"),
            (False, 1331, "indetermine"),
            (False, 1385, "indetermine"),
            (False, 0, "indetermine"),
        ],
    )
    def test_la_sonde_logonuser_est_interpretee(self, reussi, erreur, attendu):
        """§2.11 — réussir avec un mot de passe vide ou échouer par 1327 :
        pas de mot de passe. 1326 : il y en a un. Le reste : indéterminé."""
        assert g.interpreter_logon(reussi, erreur) == attendu, (
            f"LogonUserW({reussi}, {erreur}) doit donner {attendu}"
        )

    def test_la_memorisation_est_refusee_sur_un_compte_sans_mot_de_passe(self, dossier):
        """§2.11 — DPAPI ne vaut que le mot de passe Windows : sans lui, la
        clé serait lisible par quiconque ouvre la session."""
        proteger, deproteger, _ = _faux_dpapi()
        protecteur = g.ProtecteurDpapi(
            dossier, proteger=proteger, deproteger=deproteger
        )
        assert (
            g.motif_refus_memorisation(
                protecteur, plateforme="win32", sonde_windows=lambda: "absent"
            )
            == "windowsAccountWithoutPassword"
        ), "un compte sans mot de passe doit être refusé, et le dire"
        assert not g.memorisation_permise(
            protecteur, plateforme="win32", sonde_windows=lambda: "indetermine"
        ), "§2.11 — indéterminé, on refuse aussi"
        assert g.memorisation_permise(
            protecteur, plateforme="win32", sonde_windows=lambda: "present"
        ), "avec un mot de passe, la mémorisation est permise"

    def test_le_jeton_de_session_reste_dans_dpapi_meme_sans_memorisation(self, dossier):
        """§2.10 — le jeton va dans le protecteur de l'AMK s'il existe, même
        quand l'AMK n'est pas mémorisée : un compte sans mot de passe garde
        son jeton en DPAPI plutôt qu'en clair."""
        proteger, deproteger, _ = _faux_dpapi()
        protecteur = g.ProtecteurDpapi(
            dossier, proteger=proteger, deproteger=deproteger
        )
        protecteur.ranger(COMPTE, g.ELEMENT_SESSION, JETON)
        assert (dossier.chemin / "session.dpapi.key").exists(), (
            "le jeton doit être rangé"
        )
        assert protecteur.lire(COMPTE, g.ELEMENT_SESSION) == JETON, (
            "le jeton doit revenir"
        )


@pytest.mark.skipif(os.name != "nt", reason="DPAPI n'existe que sous Windows")
class TestDpapiReel:
    def test_l_aller_retour_par_cryptprotectdata(self, dossier):
        """§2.10 — le vrai ``CryptProtectData`` avec l'entropie spécifiée."""
        protecteur = g.ProtecteurDpapi(dossier)
        protecteur.ranger(COMPTE, g.ELEMENT_AMK, AMK)
        assert protecteur.lire(COMPTE, g.ELEMENT_AMK) == AMK, "l'AMK doit revenir"
        contenu = (dossier.chemin / "amk.dpapi.key").read_bytes()
        assert AMK.hex().encode() not in contenu, (
            "le clair ne doit pas être sur le disque"
        )

    def test_une_autre_entropie_ne_dechiffre_pas(self):
        """L'entropie lie le blob au compte : sous une autre, DPAPI refuse."""
        blob = g._proteger_dpapi(AMK, g.ENTROPIE_DPAPI + b"compte-a")
        with pytest.raises(g.ErreurGardien):
            g._deproteger_dpapi(blob, g.ENTROPIE_DPAPI + b"compte-b")

    def test_la_sonde_rend_un_verdict_connu(self):
        """§2.11 — la sonde réelle rend l'un des trois verdicts, jamais autre
        chose ; sur pc-bureau, noter lequel (compte Microsoft, PIN)."""
        assert g.sonder_mot_de_passe_windows() in {"present", "absent", "indetermine"}


# ----------------------------------------------------------------------
# Choix du protecteur et permission de mémoriser
# ----------------------------------------------------------------------


class TestLeChoix:
    def test_chaque_plateforme_a_son_protecteur(self, dossier):
        """§2.10 — trousseau sous macOS, DPAPI sous Windows, fichier sous
        Linux, mémoire faute de dossier. Le ``nom`` est la valeur de
        ``protector`` dans ``/v1/account/status``."""
        noms = {
            p: g.choisir_protecteur(dossier, plateforme=p).nom
            for p in ("darwin", "win32", "linux")
        }
        assert noms == {"darwin": "keychain", "win32": "dpapi", "linux": "file"}, noms
        assert g.choisir_protecteur(None).nom == "memory", "sans dossier : mémoire"

    def test_le_repli_d7_bascule_sur_le_fichier(self, dossier):
        """§6 étape 3 — si la preuve ``ps`` échoue, D7 bascule sur le fichier."""
        protecteur = g.choisir_protecteur(
            dossier, plateforme="darwin", repli_fichier_mac=True
        )
        assert protecteur.nom == "file", "le repli D7 doit donner le fichier"

    def test_la_memoire_ne_permet_jamais_de_memoriser(self):
        """§5 — « Garder cet appareil déverrouillé » avec un protecteur qui
        oublie tout au prochain lancement serait une promesse fausse."""
        memoire = g.ProtecteurMemoire()
        assert g.motif_refus_memorisation(memoire) == "noPersistentProtector", (
            "la mémoire doit refuser"
        )

    def test_le_trousseau_permet_de_memoriser(self):
        protecteur = g.ProtecteurTrousseauMac(executer=FauxSecurity())
        assert g.memorisation_permise(protecteur, plateforme="darwin"), (
            "le trousseau doit permettre la mémorisation"
        )

    def test_le_fichier_sous_linux_ne_memorise_pas_l_amk(self, dossier):
        """§2.10 — Linux : pas de mémorisation ; le fichier n'y garde que le
        jeton de session."""
        assert (
            g.motif_refus_memorisation(g.ProtecteurFichier(dossier), plateforme="linux")
            == "notOnThisPlatform"
        ), "le fichier sous Linux doit refuser la mémorisation"

    def test_le_fichier_sous_macos_exige_l_exclusion_time_machine(self, tmp_path):
        """§2.10 — en repli D7, le fichier n'est admis que s'il est exclu de
        Time Machine : sinon la clé part dans chaque sauvegarde."""
        (tmp_path / "a").mkdir()
        (tmp_path / "b").mkdir()
        exclu = g.preparer_dossier_compte(
            tmp_path / "a", plateforme="darwin", executer=FauxTmutil()
        )
        non_exclu = g.preparer_dossier_compte(
            tmp_path / "b", plateforme="darwin", executer=FauxTmutil(exclut=False)
        )
        assert g.memorisation_permise(
            g.ProtecteurFichier(exclu), plateforme="darwin"
        ), "exclu et confirmé : permis"
        assert (
            g.motif_refus_memorisation(
                g.ProtecteurFichier(non_exclu), plateforme="darwin"
            )
            == "backupExclusionFailed"
        ), "non exclu : refusé, et dit"

    def test_le_jeton_de_session_est_range_dans_le_protecteur_choisi(self, dossier):
        """§2.10 et §3.7 — le jeton de session passe par le MÊME protecteur
        que l'AMK : sous macOS, le trousseau, compte « <id>/session »."""
        faux = FauxSecurity()
        protecteur = g.choisir_protecteur(dossier, plateforme="darwin", executer=faux)
        protecteur.ranger(COMPTE, g.ELEMENT_SESSION, JETON)
        assert (f"{COMPTE}/session", "Diapason Compte") in faux.elements, (
            "le jeton doit être dans le trousseau"
        )
        assert list(dossier.chemin.iterdir()) == [], (
            "sous macOS, le jeton ne doit pas finir dans un fichier"
        )


# ----------------------------------------------------------------------
# Étape 3 bis : la politique de fichiers couvre ce que le gardien écrit
# ----------------------------------------------------------------------


class TestLaPolitiqueDeFichiers:
    @pytest.mark.parametrize(
        "chemin",
        [
            "/Users/x/.diapason/compte/etat.key",
            "C:\\Users\\x\\.diapason\\compte\\etat.key",
            "compte/etat.key",
        ],
    )
    def test_l_etat_du_compte_est_un_fichier_sensible(self, chemin):
        """§6 étape 3 bis et §2.10 — ``file_read`` ne filtre que le nom :
        nommer l'état ``etat.key`` doit suffire à le lui refuser."""
        assert is_sensitive_file(chemin), f"{chemin} doit être refusé par file_read"

    def test_chaque_fichier_que_le_gardien_ecrit_est_sensible(
        self, dossier, monkeypatch
    ):
        """§2.10 — les fichiers de secret ET leur provisoire (le temps d'un
        fsync, il porte le secret) finissent par ``.key``."""
        vus: list[str] = []
        vrai_open = os.open

        def espion(chemin, *args, **kwargs):
            vus.append(os.fspath(chemin))
            return vrai_open(chemin, *args, **kwargs)

        monkeypatch.setattr(g.os, "open", espion)
        proteger, deproteger, _ = _faux_dpapi()
        for protecteur in (
            g.ProtecteurFichier(dossier),
            g.ProtecteurDpapi(dossier, proteger=proteger, deproteger=deproteger),
        ):
            for element in (g.ELEMENT_AMK, g.ELEMENT_SESSION):
                protecteur.ranger(COMPTE, element, AMK)
        monkeypatch.undo()
        ecrits = set(vus) | {str(p) for p in dossier.chemin.iterdir()}
        assert len(ecrits) >= 8, f"quatre définitifs et quatre provisoires : {ecrits}"
        for chemin in ecrits:
            assert is_sensitive_file(chemin), f"{chemin} doit être refusé par file_read"


# ----------------------------------------------------------------------
# macOS réel : trousseau, ps, tmutil (hors vérification du dépôt)
# ----------------------------------------------------------------------

_MAC = sys.platform == "darwin"


def _security(*args: str) -> subprocess.CompletedProcess[bytes]:
    # Aucun secret dans ces arguments : seulement des noms.
    return subprocess.run(
        ["/usr/bin/security", *args], capture_output=True, timeout=10, check=False
    )


@pytest.fixture
def service_essai():
    """Un service unique par exécution, effacé même si le test échoue.

    Le nettoyage est VÉRIFIÉ : un élément resté dans le trousseau de
    Carlito ferait échouer la fixture, pas passer en silence.
    """
    service = f"Diapason Compte Essai {uuid.uuid4().hex[:12]}"
    try:
        yield service
    finally:
        # Par service seul : un test peut ranger sous un autre accountId.
        # Chaque appel efface UN élément ; 10 couvrent largement les 4 rangés.
        for _ in range(10):
            if _security("delete-generic-password", "-s", service).returncode != 0:
                break
        reste = _security("find-generic-password", "-s", service)
        assert reste.returncode != 0, (
            f"le service {service} est resté dans le trousseau"
        )


@pytest.fixture
def racine_essai():
    """Une racine temporaire SOUS le dossier personnel — jamais
    ``~/.diapason``. Pas sous ``/private/tmp`` ni ``/var/folders`` : macOS
    les exclut déjà de Time Machine, et ``[Excluded]`` n'y prouverait rien.
    """
    racine = Path(tempfile.mkdtemp(prefix=".diapason-essai-gardien-", dir=Path.home()))
    try:
        yield racine
    finally:
        shutil.rmtree(racine, ignore_errors=True)
        assert not racine.exists(), f"{racine} doit avoir été effacé"


class _Sonde(threading.Thread):
    """Lit TOUTE la table des processus en boucle, arguments et
    environnement compris (``ps -E``), à la recherche du secret.

    Elle ne prouve rien seule sur ``security`` (voir la preuve ``ps``) :
    elle guette une fuite ailleurs — un autre processus qui recevrait le
    secret en argument ou en variable d'environnement.
    """

    def __init__(self, cherches: list[bytes]) -> None:
        super().__init__(daemon=True)
        self.cherches = cherches
        self.arret = threading.Event()
        self.fuites: list[bytes] = []
        self.echantillons = 0

    def run(self) -> None:
        while not self.arret.is_set():
            sortie = subprocess.run(
                ["/bin/ps", "-axwwE", "-o", "pid=,command="],
                capture_output=True,
                check=False,
            ).stdout
            self.echantillons += 1
            for ligne in sortie.splitlines():
                if any(c in ligne for c in self.cherches):
                    self.fuites.append(ligne)


@pytest.mark.live
@pytest.mark.skipif(not _MAC, reason="trousseau et tmutil de macOS")
class TestLeVraiTrousseauDeCeMac:
    def test_l_aller_retour_et_l_effacement(self, service_essai):
        """§2.10 — ranger, relire, effacer ; après effacement,
        ``security find-generic-password`` ne trouve plus rien."""
        protecteur = g.ProtecteurTrousseauMac(service_essai)
        secret = secrets.token_bytes(32)
        protecteur.ranger(COMPTE, g.ELEMENT_AMK, secret)
        protecteur.ranger(COMPTE, g.ELEMENT_SESSION, JETON)
        assert protecteur.lire(COMPTE, g.ELEMENT_AMK) == secret, "l'AMK doit revenir"
        assert protecteur.lire(COMPTE, g.ELEMENT_SESSION) == JETON, (
            "le jeton doit revenir"
        )
        protecteur.effacer(COMPTE, g.ELEMENT_AMK)
        protecteur.effacer(COMPTE, g.ELEMENT_SESSION)
        assert protecteur.lire(COMPTE, g.ELEMENT_AMK) is None, "effacé doit rendre None"
        reste = _security("find-generic-password", "-s", service_essai)
        assert reste.returncode != 0, (
            "le trousseau ne doit plus rien avoir sous ce service"
        )

    def test_un_secret_de_taille_maximale_revient_identique(self, service_essai):
        """24/09/2026 — ``security -i`` coupait toute ligne de plus de 4 096
        octets : l'ancienne borne de 4 Kio laissait ranger un secret tronqué.
        Le plus grand secret permis, sous l'accountId le plus long, doit
        revenir octet pour octet du VRAI trousseau."""
        protecteur = g.ProtecteurTrousseauMac(service_essai)
        secret = secrets.token_bytes(g._SECRET_MAX_O)
        protecteur.ranger(COMPTE_LONG, g.ELEMENT_SESSION, secret)
        assert protecteur.lire(COMPTE_LONG, g.ELEMENT_SESSION) == secret, (
            "le secret de taille maximale doit revenir identique"
        )

    def test_une_seconde_ecriture_remplace_la_premiere(self, service_essai):
        """§3.7 — chaque reconnexion récrit le jeton : sans ``-U``, le vrai
        ``security`` refuse le doublon (-25299) et l'ancien jeton resterait."""
        protecteur = g.ProtecteurTrousseauMac(service_essai)
        protecteur.ranger(COMPTE, g.ELEMENT_SESSION, b"premier-jeton")
        protecteur.ranger(COMPTE, g.ELEMENT_SESSION, JETON)
        assert protecteur.lire(COMPTE, g.ELEMENT_SESSION) == JETON, (
            "la seconde écriture doit remplacer la première"
        )

    def test_la_sonde_voit_un_secret_passe_en_argument(self):
        """Contre-épreuve : sans elle, une sonde aveugle « prouverait »
        l'absence de fuite. Un marqueur mis en argument DOIT être vu."""
        marqueur = f"marqueur-{uuid.uuid4().hex}"
        sonde = _Sonde([marqueur.encode()])
        processus = subprocess.Popen(
            # « ; true » : sans lui, sh remplace son image par celle de
            # sleep et le marqueur ($0) disparaît de la table.
            ["/bin/sh", "-c", "sleep 2; true", marqueur]
        )
        try:
            sonde.start()
            fin = time.monotonic() + 2
            while not sonde.fuites and time.monotonic() < fin:
                time.sleep(0.05)
        finally:
            sonde.arret.set()
            sonde.join(5)
            processus.kill()
            processus.wait()
        assert sonde.fuites, "la sonde doit voir un marqueur passé en argument"

    def test_le_secret_n_apparait_jamais_dans_ps(self, service_essai):
        """§2.10 et §6 étape 3 — preuve dont dépend D7 : ni les arguments ni
        l'environnement de ``security`` ne portent le secret.

        24/09/2026 : une première sonde lisait ``ps`` en boucle pendant les
        appels ; sur 226 échantillons, elle a vu 216 fois ``(security)`` et
        jamais ses arguments — ``ps`` ne sait plus les lire une fois le
        processus fini et pas encore récolté. Une absence de fuite y était
        donc une absence de regard. Ici, ``security -i`` est RETENU vivant
        après avoir reçu ET exécuté la commande qui porte le secret (on
        n'a pas encore fermé son entrée), et ``ps`` le lit à ce moment-là :
        il doit y voir ``/usr/bin/security -i``, et rien d'autre.
        """
        secret = secrets.token_bytes(32)
        formes = [secret.hex().encode(), secret.hex().upper().encode()]
        lectures: list[bytes] = []

        def executer_retenu(args, entree):
            processus = subprocess.Popen(
                list(args),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                processus.stdin.write(entree)
                processus.stdin.flush()
                # La commande s'exécute en 27 ms ; 300 ms laissent security
                # l'avoir lue et traitée avant qu'on regarde.
                time.sleep(0.3)
                lectures.append(
                    subprocess.run(
                        ["/bin/ps", "-wwE", "-o", "command=", "-p", str(processus.pid)],
                        capture_output=True,
                        check=False,
                    ).stdout
                )
                sortie, erreur = processus.communicate(timeout=10)
            finally:
                if processus.poll() is None:
                    processus.kill()
                    processus.wait()
            return subprocess.CompletedProcess(
                list(args), processus.returncode, sortie, erreur
            )

        sonde = _Sonde(formes)
        sonde.start()
        try:
            protecteur = g.ProtecteurTrousseauMac(
                service_essai, executer=executer_retenu
            )
            protecteur.ranger(COMPTE, g.ELEMENT_AMK, secret)
            assert protecteur.lire(COMPTE, g.ELEMENT_AMK) == secret, "aller-retour"
        finally:
            sonde.arret.set()
            sonde.join(5)
        assert len(lectures) >= 3, "écriture, relecture de contrôle, lecture"
        for lecture in lectures:
            assert lecture.startswith(b"/usr/bin/security -i"), (
                f"ps doit avoir LU les arguments de security vivant : {lecture[:80]!r}"
            )
            assert not any(f in lecture for f in formes), "le secret est apparu dans ps"
        assert sonde.echantillons >= 1, (
            "la sonde de fond doit avoir lu ps au moins une fois"
        )
        assert sonde.fuites == [], "le secret est apparu dans un autre processus"

    def test_compte_est_exclu_de_time_machine(self, racine_essai):
        """§2.10 et §2.11 — ``tmutil isexcluded`` sur ``compte/`` rend
        ``[Excluded]``, alors que sa racine est ``[Included]`` : l'exclusion
        vient bien de nous, pas d'un dossier système déjà exclu."""
        avant = subprocess.run(
            ["/usr/bin/tmutil", "isexcluded", str(racine_essai)],
            capture_output=True,
            check=False,
        ).stdout
        assert b"[Included]" in avant, (
            f"précondition : la racine doit être incluse ({avant!r})"
        )
        dossier = g.preparer_dossier_compte(racine_essai)
        assert dossier.exclu_time_machine is True, "le gardien doit dire l'exclusion"
        apres = subprocess.run(
            ["/usr/bin/tmutil", "isexcluded", str(dossier.chemin)],
            capture_output=True,
            check=False,
        ).stdout
        assert b"[Excluded]" in apres, f"compte/ doit être exclu ({apres!r})"
