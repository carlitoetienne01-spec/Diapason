"""Le banc qui manquait : deux Diapason, un vrai socket, une vraie commande.

Spatial Mesh, 25 août 2026. ``mesh/transport.py`` n'était exercé de bout en
bout par AUCUN test : tous les tests de dispatch injectent
``transport=lambda c, d: {...}``. Ce qui était couvert, c'était la décision
d'envoyer — jamais la livraison. Le chemin réel — signature, POST httpx,
onze vérifications côté récepteur, exécution, accusé — ne tournait que sur
la machine de Carlito, à la main.

Ici, tout est vrai : deux processus, deux identités Ed25519 distinctes,
deux bases, un jumelage par invitation à usage unique, et une commande
signée qui traverse la boucle locale.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

_NOEUD = Path(__file__).parent / "_noeud_de_banc.py"


@pytest.fixture(autouse=True, scope="module")
def _aucun_noeud_ne_survit():
    """Le filet : même si un test tombe en plein vol, rien ne reste debout."""
    yield
    import signal

    restants = subprocess.run(
        ["pgrep", "-f", "_noeud_de_banc"], capture_output=True, text=True
    ).stdout.split()
    for pid in restants:
        try:
            os.kill(int(pid), signal.SIGKILL)
        except (ProcessLookupError, ValueError):
            pass


_DEMARRAGE_MAX_S = 40.0


def _port_libre() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _une_cle_publique() -> str:
    """Une clé d'identité Ed25519, pour un appareil de test."""
    import base64

    from diapason.security.signing import generate_keypair

    return base64.b64encode(generate_keypair().public_key).decode("ascii")


def _http(
    url: str, corps: dict | None = None, cle: str = "", methode: str = ""
) -> dict:
    donnees = json.dumps(corps).encode() if corps is not None else None
    requete = urllib.request.Request(url, data=donnees, method=methode or None)
    requete.add_header("Content-Type", "application/json")
    if cle:
        requete.add_header("Authorization", f"Bearer {cle}")
    try:
        with urllib.request.urlopen(requete, timeout=10) as reponse:
            return json.loads(reponse.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return {"_status": exc.code, "_detail": exc.read().decode("utf-8", "replace")}
    except (urllib.error.URLError, OSError) as exc:
        # Le socket n'écoute pas ENCORE : la boucle d'attente doit pouvoir
        # réessayer plutôt que de faire tomber le test au premier essai.
        return {"_erreur": str(exc)}


class _Noeud:
    """Un Diapason qui tourne pour de vrai, et qu'on peut interroger."""

    def __init__(self, foyer: Path, cle: str) -> None:
        self.foyer = foyer
        self.cle = cle
        self.port = _port_libre()
        self.base = f"http://127.0.0.1:{self.port}"
        self.device_id = ""
        self._proc: subprocess.Popen | None = None

    def demarrer(self) -> None:
        env = dict(os.environ, DIAPASON_HOME=str(self.foyer), PYTHONUNBUFFERED="1")
        self._proc = subprocess.Popen(
            [sys.executable, str(_NOEUD), str(self.foyer), str(self.port), self.cle],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        # « PRÊT <id> » puis l'attente que le socket accepte vraiment.
        ligne = self._proc.stdout.readline() if self._proc.stdout else ""
        if not ligne.startswith("PRÊT "):
            self.arreter()
            pytest.skip(f"nœud de banc non démarré : {ligne!r}")
        self.device_id = ligne.split(" ", 1)[1].strip()
        limite = time.monotonic() + _DEMARRAGE_MAX_S
        while time.monotonic() < limite:
            if self._proc.poll() is not None:
                pytest.skip("le nœud de banc s'est arrêté au démarrage")
            reponse = _http(f"{self.base}/v1/mesh/me", cle=self.cle)
            if reponse.get("deviceId"):
                return
            time.sleep(0.2)
        self.arreter()
        erreurs = ""
        if self._proc is not None and self._proc.stderr is not None:
            erreurs = (self._proc.stderr.read() or "")[-400:]
        pytest.skip(f"le nœud de banc n'a jamais répondu : {erreurs}")

    def arreter(self) -> None:
        """Tuer le nœud, et s'assurer qu'il est MORT.

        Constaté le 25 août 2026 : deux nœuds de banc tournaient encore huit
        heures après leur test, tenant leurs ports et prêtant à confusion
        avec les serveurs de l'application. terminate() suivi d'un wait qui
        expire laissait le processus vivant, et personne ne le revérifiait.
        On attend le décès, on force, puis on VÉRIFIE.
        """
        proc = self._proc
        self._proc = None
        if proc is None or proc.poll() is not None:
            return
        for arret in (proc.terminate, proc.kill):
            arret()
            try:
                proc.wait(timeout=5)
                break
            except subprocess.TimeoutExpired:
                continue
        # Les tuyaux aussi : un stdout jamais fermé retient un descripteur.
        for tuyau in (proc.stdout, proc.stderr):
            try:
                if tuyau is not None:
                    tuyau.close()
            except Exception:  # noqa: BLE001
                pass
        assert proc.poll() is not None, "un nœud de banc a survécu à son test"


@pytest.fixture()
def hote(tmp_path):
    """Le nœud qui accueille : il émet l'invitation et reçoit la commande."""
    noeud = _Noeud(tmp_path / "hote", "cle-hote-de-banc")
    noeud.demarrer()
    yield noeud
    noeud.arreter()


class TestDeuxProcessusSeParlent:
    """Le chemin complet, sans un seul substitut."""

    def test_jumelage_puis_commande_reellement_livree(
        self, hote, tmp_path, monkeypatch
    ):
        # ── 1. l'hôte émet une invitation ────────────────────────────────
        invitation = _http(
            f"{hote.base}/v1/mesh/pairings",
            {"deviceName": "Invité de banc"},
            cle=hote.cle,
        )
        jeton = invitation.get("pairingToken")
        assert jeton, f"invitation refusée : {invitation}"

        # ── 2. l'invité rejoint (CE processus, son propre foyer) ─────────
        monkeypatch.setenv("DIAPASON_HOME", str(tmp_path / "invite"))
        from diapason.mesh.identity import device_identity, owner_id
        from diapason.mesh.join import join_fleet

        moi = device_identity()
        flotte_avant = owner_id()
        assert moi.device_id != hote.device_id, "deux identités distinctes"

        jumelage = join_fleet(hote.base, jeton, my_address="")

        assert owner_id() == jumelage.owner_id != flotte_avant, (
            "l'invité doit adopter la flotte de l'hôte"
        )

        # Le trou corrigé le 25/08/2026 : sans capacités, tout envoi serait
        # refusé « ne peut pas faire cela » par dispatch_command.
        from diapason.mesh.registry import DeviceRegistry

        inscrit = DeviceRegistry().get(jumelage.host_device_id)
        assert "notifications.show" in (inscrit.get("capabilities") or []), (
            "la réponse du jumelage doit porter les capacités de l'hôte"
        )

        # ── 3. une VRAIE commande signée traverse le socket ──────────────
        from diapason.mesh.dispatch import dispatch_command

        resultat = dispatch_command(
            target_device_id=jumelage.host_device_id,
            tool="notifications.show",
            arguments={"title": "Banc", "body": "La commande a traversé."},
            # PAS de transport= : c'est tout l'objet de ce test.
        )
        assert resultat["status"] == "SUCCESS", (
            f"la livraison réelle a échoué : {resultat}"
        )

        # ── 4. et elle est ARRIVÉE : l'hôte la porte dans sa boîte ───────
        boite = _http(f"{hote.base}/v1/mesh/inbox", cle=hote.cle)
        entrees = boite.get("pending") or boite.get("entries") or []
        assert entrees, f"rien n'est arrivé chez l'hôte : {boite}"
        recue = json.dumps(entrees, ensure_ascii=False)
        assert "La commande a traversé." in recue
        assert resultat["commandId"] in recue, "le même identifiant des deux côtés"

    def test_une_commande_rejouee_ne_s_execute_qu_une_fois(
        self, hote, tmp_path, monkeypatch
    ):
        """L'anti-rejeu sur un vrai socket : le nonce est dépensé en base,
        pas dans une variable de test."""
        invitation = _http(
            f"{hote.base}/v1/mesh/pairings",
            {"deviceName": "Rejoueur"},
            cle=hote.cle,
        )
        monkeypatch.setenv("DIAPASON_HOME", str(tmp_path / "rejoueur"))
        from diapason.mesh.commands import build_command, sign_command
        from diapason.mesh.join import join_fleet
        from diapason.mesh.transport import deliver

        jumelage = join_fleet(hote.base, invitation["pairingToken"], my_address="")
        cible = {
            "deviceId": jumelage.host_device_id,
            "address": jumelage.host_address,
            "trustLevel": "TRUSTED",
        }
        from diapason.mesh.identity import device_identity, owner_id

        commande = sign_command(
            build_command(
                owner_id=owner_id(),
                origin_device_id=device_identity().device_id,
                target_device_id=jumelage.host_device_id,
                tool="notifications.show",
                arguments={"title": "Rejeu", "body": "une seule fois"},
            )
        )
        premier = deliver(commande, cible)
        second = deliver(commande, cible)

        assert premier.get("status") == "SUCCESS"
        assert second.get("status") != "SUCCESS", (
            f"le rejeu aurait dû être refusé : {second}"
        )


class TestUnFichierTraverse:
    """Le transfert, de bout en bout, sur un vrai socket.

    Spatial Mesh, phase 3 — 25 août 2026. Deux processus, deux identités,
    une session chiffrée, un fichier qui arrive intact et vérifié.
    """

    def _jumeler(self, hote, tmp_path, monkeypatch, nom):
        invitation = _http(
            f"{hote.base}/v1/mesh/pairings", {"deviceName": nom}, cle=hote.cle
        )
        assert invitation.get("pairingToken"), f"invitation refusée : {invitation}"
        monkeypatch.setenv("DIAPASON_HOME", str(tmp_path / nom))
        from diapason.mesh.join import join_fleet

        return join_fleet(hote.base, invitation["pairingToken"], my_address="")

    def test_un_fichier_arrive_intact_et_chiffre(self, hote, tmp_path, monkeypatch):
        import hashlib

        jumelage = self._jumeler(hote, tmp_path, monkeypatch, "envoyeur")

        # Un fichier de plusieurs morceaux, avec du contenu reconnaissable.
        from diapason.mesh.transfert import TAILLE_MORCEAU

        # Au moins trois morceaux : la reprise et l ordre ne se testent pas sur un seul.
        contenu = (b"CONTENU CONFIDENTIEL " * 120_000)[: TAILLE_MORCEAU * 2 + 4242]
        source = tmp_path / "rapport secret.bin"
        source.write_bytes(contenu)

        from diapason.mesh.envoi_fichier import envoyer_fichier
        from diapason.mesh.registry import DeviceRegistry

        cible = DeviceRegistry().get(jumelage.host_device_id)
        resultat = envoyer_fichier(source, cible)

        assert resultat.statut == "COMPLETE", resultat.message
        assert resultat.morceaux == 3
        recu = Path(resultat.chemin_distant)
        assert recu.exists(), "le fichier doit exister chez le récepteur"
        assert recu.read_bytes() == contenu
        assert (
            hashlib.sha256(recu.read_bytes()).hexdigest()
            == hashlib.sha256(contenu).hexdigest()
        )
        # Le nom est assaini et rien n'est exécutable.
        assert recu.name == "rapport secret.bin"
        assert recu.stat().st_mode & 0o111 == 0

    def test_le_meme_fichier_ne_repart_pas_deux_fois(self, hote, tmp_path, monkeypatch):
        """Déduplication par CONTENU (§45) : le second envoi ne transfère
        aucun octet."""
        jumelage = self._jumeler(hote, tmp_path, monkeypatch, "dedup")
        source = tmp_path / "doc.txt"
        source.write_bytes(b"un contenu unique et reconnaissable")

        from diapason.mesh.envoi_fichier import envoyer_fichier
        from diapason.mesh.registry import DeviceRegistry

        cible = DeviceRegistry().get(jumelage.host_device_id)
        premier = envoyer_fichier(source, cible)
        assert premier.statut == "COMPLETE"

        # Même contenu, autre nom : la déduplication compare les empreintes.
        autre = tmp_path / "copie-du-doc.txt"
        autre.write_bytes(source.read_bytes())
        second = envoyer_fichier(autre, cible)
        assert second.statut == "ALREADY_PRESENT"
        assert second.morceaux == 0, "aucun octet ne doit repartir"

    def test_un_inconnu_ne_peut_rien_deposer(self, hote, tmp_path, monkeypatch):
        """L'offre est signée : un appareil non appairé est refusé avant
        d'avoir envoyé le moindre octet."""
        monkeypatch.setenv("DIAPASON_HOME", str(tmp_path / "intrus"))
        import time as _t

        from diapason.mesh.files_routes import _CHAMPS_SIGNES
        from diapason.mesh.identity import device_identity, owner_id
        from diapason.mesh.signed import sign_payload

        offre = sign_payload(
            {
                "version": 1,
                "ownerId": owner_id(),
                "deviceId": device_identity().device_id,
                "sentAtMs": int(_t.time() * 1000),
                "sessionNonce": "n",
                "manifest": {
                    "name": "cheval.bin",
                    "size": 4,
                    "sha256": "a" * 64,
                    "chunks": 1,
                },
                "ephemeralPublicKey": "A" * 44,
            },
            _CHAMPS_SIGNES,
        )
        reponse = _http(f"{hote.base}/v1/mesh/files/offer", offre)
        assert reponse.get("_status") == 403, f"un inconnu doit être refusé : {reponse}"

    def test_un_jeton_de_session_faux_ne_depose_rien(self, hote, tmp_path, monkeypatch):
        """La signature garde la porte, le jeton garde le couloir."""
        self._jumeler(hote, tmp_path, monkeypatch, "jeton")
        source = tmp_path / "petit.txt"
        source.write_bytes(b"court")

        import time as _t

        from diapason.mesh.coffre import nouvelle_demi_cle
        from diapason.mesh.envoi_fichier import _champs
        from diapason.mesh.identity import device_identity, owner_id
        from diapason.mesh.signed import sign_payload
        from diapason.mesh.transfert import decrire_fichier

        demi = nouvelle_demi_cle()
        offre = sign_payload(
            {
                "version": 1,
                "ownerId": owner_id(),
                "deviceId": device_identity().device_id,
                "sentAtMs": int(_t.time() * 1000),
                "sessionNonce": "n2",
                "manifest": decrire_fichier(source).to_dict(),
                "ephemeralPublicKey": demi.publique_b64,
            },
            _champs(),
        )
        accord = _http(f"{hote.base}/v1/mesh/files/offer", offre)
        session = accord.get("sessionId")
        assert session, f"offre refusée : {accord}"

        import urllib.request

        requete = urllib.request.Request(
            f"{hote.base}/v1/mesh/files/{session}/chunk?index=0",
            data=b"n'importe quoi",
            method="POST",
        )
        requete.add_header("X-Transfer-Token", "jeton-invente")
        requete.add_header("Content-Type", "application/octet-stream")
        try:
            urllib.request.urlopen(requete, timeout=10)
            raise AssertionError("un jeton inventé ne doit rien déposer")
        except urllib.error.HTTPError as exc:
            assert exc.code == 403


class TestUnIntercepteurNeLitPasLeFichier:
    """La réponse à l'offre porte la moitié de clé dont la session est tirée.

    Elle n'était PAS signée, et l'émetteur en dérivait la clé sur parole
    (`envoi_fichier.py`). Quiconque se plaçait entre les deux appareils —
    un point d'accès complaisant, une usurpation ARP — n'avait qu'à
    substituer sa propre moitié : il partageait alors la clé avec
    l'émetteur et lisait le contenu de CHAQUE fichier transféré. Tout le
    chiffrement de `coffre.py` reposait sur un octet que personne n'avait
    signé.

    Inoffensif tant que la route n'écoutait que sur la loopback ; elle a
    été ouverte au réseau le 26 août 2026, et corrigée le même jour.
    """

    def _jumeler(self, hote, tmp_path, monkeypatch, nom):
        invitation = _http(
            f"{hote.base}/v1/mesh/pairings", {"deviceName": nom}, cle=hote.cle
        )
        assert invitation.get("pairingToken"), f"invitation refusée : {invitation}"
        monkeypatch.setenv("DIAPASON_HOME", str(tmp_path / nom))
        from diapason.mesh.join import join_fleet

        return join_fleet(hote.base, invitation["pairingToken"], my_address="")

    def test_une_moitie_de_cle_substituee_est_refusee(
        self, hote, tmp_path, monkeypatch
    ):
        from diapason.mesh.coffre import nouvelle_demi_cle
        from diapason.mesh.envoi_fichier import (
            EnvoiRefuse,
            _poster,
            envoyer_fichier,
        )
        from diapason.mesh.registry import DeviceRegistry

        jumelage = self._jumeler(hote, tmp_path, monkeypatch, "intercepte")
        source = tmp_path / "secret.bin"
        source.write_bytes(b"CE QUE PERSONNE D'AUTRE NE DOIT LIRE " * 500)

        celle_de_l_attaquant = nouvelle_demi_cle()

        def intercepter(url, corps, jeton):
            reponse = _poster(url, corps, jeton)
            if url.endswith("/files/offer"):
                # L'attaquant laisse tout passer et ne change QUE la moitié
                # de clé : c'est la substitution la plus discrète possible,
                # et jusqu'au 26 août 2026 elle suffisait.
                reponse = dict(reponse)
                reponse["ephemeralPublicKey"] = celle_de_l_attaquant.publique_b64
            return reponse

        cible = DeviceRegistry().get(jumelage.host_device_id)
        with pytest.raises(EnvoiRefuse) as refus:
            envoyer_fichier(source, cible, poster=intercepter)
        assert "transfert refusée" in str(refus.value), str(refus.value)

    def test_une_reponse_deja_present_forgee_ne_fait_pas_croire_a_un_envoi(
        self, hote, tmp_path, monkeypatch
    ):
        """Sans signature sur `status`, un intercepteur répondait « déjà
        là » et l'émetteur croyait son fichier arrivé sans qu'un seul octet
        soit parti."""
        from diapason.mesh.envoi_fichier import EnvoiRefuse, envoyer_fichier
        from diapason.mesh.registry import DeviceRegistry

        jumelage = self._jumeler(hote, tmp_path, monkeypatch, "menteur")
        source = tmp_path / "rapport.bin"
        source.write_bytes(b"x" * 4096)

        def mentir(url, corps, jeton):
            return {
                "status": "ALREADY_PRESENT",
                "path": "/tmp/rien",
                "userSafeMessage": "Déjà là — rien à envoyer.",
            }

        cible = DeviceRegistry().get(jumelage.host_device_id)
        with pytest.raises(EnvoiRefuse):
            envoyer_fichier(source, cible, poster=mentir)


class TestLesClesDeScellementSEchangent:
    """Étape 4 du plan du 26 août 2026 — sur deux VRAIS processus.

    La clé de scellement voyage dans des corps de réponse qui circulent
    déjà : celui de la présence, celui du jumelage. Aucune route neuve,
    aucun tour de réseau ajouté. Rien ne scelle encore quoi que ce soit —
    ces tests vérifient seulement que les clés arrivent.
    """

    def _jumeler(self, hote, tmp_path, monkeypatch, nom):
        invitation = _http(
            f"{hote.base}/v1/mesh/pairings", {"deviceName": nom}, cle=hote.cle
        )
        assert invitation.get("pairingToken"), f"invitation refusée : {invitation}"
        monkeypatch.setenv("DIAPASON_HOME", str(tmp_path / nom))
        from diapason.mesh.join import join_fleet

        return join_fleet(hote.base, invitation["pairingToken"], my_address="")

    def test_le_jumelage_transporte_les_deux_cles(self, hote, tmp_path, monkeypatch):
        """Dès le jumelage, chacun peut sceller vers l'autre — sans attendre
        une première annonce."""
        from diapason.mesh.registry import DeviceRegistry
        from diapason.mesh.scellement import paire_locale

        jumelage = self._jumeler(hote, tmp_path, monkeypatch, "invite")

        # Côté invité : la clé de l'hôte est arrivée dans la réponse.
        retenue = DeviceRegistry().seal_key_of(jumelage.host_device_id)
        assert retenue is not None, "l'invité n'a pas retenu la clé de l'hôte"
        cle, vue = retenue
        assert len(cle) == 44 and vue > 0

        # Et elle n'est pas la nôtre : deux machines, deux clés.
        assert cle != paire_locale().publique_b64

    def test_une_annonce_de_presence_apporte_la_cle(self, hote, tmp_path, monkeypatch):
        """Le chemin qui compte en régime établi : les deux machines
        s'annoncent toutes les quinze secondes, donc la couverture est
        symétrique sans un seul tour ajouté."""
        from diapason.mesh.beacon import announce_to
        from diapason.mesh.registry import DeviceRegistry

        jumelage = self._jumeler(hote, tmp_path, monkeypatch, "annonceur")
        registre = DeviceRegistry()

        # On oublie ce que le jumelage a apporté, pour isoler le canal.
        registre.forget_seal_key(jumelage.host_device_id)
        assert registre.seal_key_of(jumelage.host_device_id) is None

        assert announce_to(registre.get(jumelage.host_device_id)) is True
        assert registre.seal_key_of(jumelage.host_device_id) is not None, (
            "la clé n'est pas venue avec la réponse de présence"
        )

    def test_un_client_qui_ne_publie_rien_s_appaire_comme_avant(self, hote):
        """LE test qui garde le téléphone : le client figé n'envoie pas de
        clé, et tout doit se passer exactement comme avant."""
        invitation = _http(
            f"{hote.base}/v1/mesh/pairings",
            {"deviceName": "Vieux client"},
            cle=hote.cle,
        )
        reponse = _http(
            f"{hote.base}/v1/mesh/pairings/redeem",
            {
                "pairingToken": invitation["pairingToken"],
                "deviceId": "dev_client_fige",
                "publicKey": _une_cle_publique(),
                "name": "Vieux client",
                "platform": "ANDROID",
                "deviceType": "PHONE",
                "capabilities": ["app.navigate"],
            },
        )
        assert reponse.get("device", {}).get("deviceId") == "dev_client_fige"
        hote_dit = reponse.get("host") or {}
        for champ in ("deviceId", "publicKey", "ownerId", "address", "capabilities"):
            assert champ in hote_dit, f"le jumelage a perdu « {champ} »"


class TestUneCommandeScelleeTraverse:
    """Étape 6, sur deux VRAIS processus : le maillage chiffre pour de bon.

    C'est ici que le comportement change. Les étapes 1 à 5 ont posé la
    cryptographie, le registre, la forme sur le fil et la décision ; celle-ci
    les branche.
    """

    def _jumeler(self, hote, tmp_path, monkeypatch, nom):
        invitation = _http(
            f"{hote.base}/v1/mesh/pairings", {"deviceName": nom}, cle=hote.cle
        )
        assert invitation.get("pairingToken"), f"invitation refusée : {invitation}"
        monkeypatch.setenv("DIAPASON_HOME", str(tmp_path / nom))
        from diapason.mesh.join import join_fleet

        return join_fleet(hote.base, invitation["pairingToken"], my_address="")

    def test_le_contenu_ne_traverse_plus_en_clair(self, hote, tmp_path, monkeypatch):
        """Ce que verrait quelqu'un qui écoute le Wi-Fi."""
        from diapason.mesh.dispatch import dispatch_command
        from diapason.mesh.queue import CommandQueue
        from diapason.mesh.registry import DeviceRegistry
        from diapason.mesh.scellement import SENTINELLE

        jumelage = self._jumeler(hote, tmp_path, monkeypatch, "chiffreur")
        registre = DeviceRegistry()
        assert registre.seal_key_of(jumelage.host_device_id) is not None, (
            "le jumelage aurait dû apporter la clé de l'hôte"
        )

        vu_sur_le_fil = {}

        def espion(commande, appareil):
            from diapason.mesh.transport import deliver

            vu_sur_le_fil.update(commande.to_dict())
            return deliver(commande, appareil)

        issue = dispatch_command(
            target_device_id=jumelage.host_device_id,
            tool="notifications.show",
            arguments={"title": "Rendez-vous chez le notaire", "body": "14 h"},
            registry=registre,
            queue=CommandQueue(),
            transport=espion,
        )
        assert issue["status"] == "SUCCESS", issue

        assert vu_sur_le_fil["tool"] == SENTINELLE
        entier = str(vu_sur_le_fil)
        assert "notifications.show" not in entier
        assert "notaire" not in entier, "le titre a traversé en clair"
        assert set(vu_sur_le_fil["arguments"]) == {"s", "e", "k"}

    def test_le_destinataire_l_ouvre_et_l_execute(self, hote, tmp_path, monkeypatch):
        """Le sceau ne sert à rien si le pair n'en fait rien."""
        from diapason.mesh.dispatch import dispatch_command
        from diapason.mesh.queue import CommandQueue
        from diapason.mesh.registry import DeviceRegistry

        jumelage = self._jumeler(hote, tmp_path, monkeypatch, "executeur")
        issue = dispatch_command(
            target_device_id=jumelage.host_device_id,
            tool="app.navigate",
            arguments={"route": "success://projects/secret"},
            registry=DeviceRegistry(),
            queue=CommandQueue(),
        )
        assert issue["status"] == "SUCCESS", issue
        assert "n'existe pas" not in str(issue.get("userSafeMessage") or "")

    def test_une_commande_claire_passe_toujours(self, hote, tmp_path, monkeypatch):
        """Le chemin du téléphone : sans clé publiée, rien ne change."""
        from diapason.mesh.dispatch import dispatch_command
        from diapason.mesh.queue import CommandQueue
        from diapason.mesh.registry import DeviceRegistry
        from diapason.mesh.scellement import SENTINELLE

        jumelage = self._jumeler(hote, tmp_path, monkeypatch, "en-clair")
        registre = DeviceRegistry()
        registre.forget_seal_key(jumelage.host_device_id)

        vu = {}

        def espion(commande, appareil):
            from diapason.mesh.transport import deliver

            vu.update(commande.to_dict())
            return deliver(commande, appareil)

        issue = dispatch_command(
            target_device_id=jumelage.host_device_id,
            tool="app.navigate",
            arguments={"route": "success://projects/x"},
            registry=registre,
            queue=CommandQueue(),
            transport=espion,
        )
        assert issue["status"] == "SUCCESS", issue
        assert vu["tool"] == "app.navigate" and vu["tool"] != SENTINELLE
