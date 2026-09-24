"""Validation écrite à la main : normalisation, enveloppes, base64, JSON.

Conception : ``docs/development/compte-chiffre.md`` §2.4, §2.5, §3.1 et §3.4.
"""

from __future__ import annotations

import pytest

from diapason.compte import cles, enveloppe
from diapason_comptes import validation as v
from tests.diapason_comptes._outils import amk_mdp, amk_recup, nom_appareil, trousseau

ADRESSES = [
    "simple@exemple.org",
    "  Espaces@Exemple.ORG  ",
    "ｐｌｅｉｎｅ@ｃｈａｓｓｅ.org",
    "école@exemple.org",
    "école@exemple.org",
    "deux@@exemple.org",
    "sans-arobase",
    "a b@exemple.org",
    "@ab",
    "x" * 300 + "@exemple.org",
    "",
]


class TestNormalisation:
    @pytest.mark.parametrize("adresse", ADRESSES)
    def test_le_serveur_normalise_comme_le_client(self, adresse):
        """§2.4, §3.1 — la règle est RECOPIÉE (le service n'importe pas
        ``diapason``) : un écart ferait indexer au serveur une adresse dont le
        client dérive un autre sel, et le compte deviendrait inouvrable."""
        try:
            attendu = cles.normaliser_courriel(adresse)
        except cles.CourrielInvalide:
            attendu = None
        assert v.normaliser_courriel(adresse) == attendu, f"écart sur {adresse!r}"

    def test_padme_est_celui_du_client(self):
        """§2.5 — le VPS vérifie « taille − 66 ∈ Padmé » : s'il arrondissait
        autrement, il refuserait les blobs légitimes."""
        for longueur in range(1, 70_000, 7):
            assert v.padme(longueur) == enveloppe.padme(longueur), f"padme({longueur})"
        assert v.SURCOUT == enveloppe.SURCOUT, "même surcoût de 66 o"


class TestEnveloppes:
    COMPTE = "11111111-2222-4333-8444-555555555555"

    def test_les_enveloppes_du_client_passent_la_forme_du_serveur(self):
        """§3.4 — « vérifie la forme des enveloppes » : ce que le vrai client
        scelle doit passer, sinon aucun compte ne naît."""
        corps = {
            "wrappedMasterKey": v.b64url(amk_mdp(self.COMPTE)),
            "sealedMasterKey": v.b64url(amk_recup(self.COMPTE)),
            "keyring": v.b64url(trousseau(self.COMPTE)),
            "encryptedName": v.b64url(nom_appareil(self.COMPTE, "session")),
        }
        v.enveloppe_amk_mot_de_passe(corps)
        v.enveloppe_amk_recuperation(corps)
        v.enveloppe_trousseau(corps)
        v.enveloppe_nom_appareil(corps)

    @pytest.mark.parametrize(
        ("champ", "retouche"),
        [
            ("wrappedMasterKey", lambda b: b[:1] + b"\x05" + b[2:]),
            ("wrappedMasterKey", lambda b: b[:2] + b"\x00\x00\x00\x01" + b[6:]),
            ("wrappedMasterKey", lambda b: b[:-1]),
            ("keyring", lambda b: b + b"\x00"),
            ("keyring", lambda b: b"\x02" + b[1:]),
            ("sealedMasterKey", lambda b: b + b"\x00"),
        ],
    )
    def test_une_enveloppe_retouchee_est_refusee(self, champ, retouche):
        """§2.5 — mauvais type, époque non nulle, longueur hors Padmé :
        refusés à l'entrée, avant d'être stockés comme un coffre que
        l'appareil suivant ne saurait pas ouvrir."""
        brut = {
            "wrappedMasterKey": amk_mdp(self.COMPTE),
            "sealedMasterKey": amk_recup(self.COMPTE),
            "keyring": trousseau(self.COMPTE),
        }[champ]
        fonction = {
            "wrappedMasterKey": v.enveloppe_amk_mot_de_passe,
            "sealedMasterKey": v.enveloppe_amk_recuperation,
            "keyring": v.enveloppe_trousseau,
        }[champ]
        with pytest.raises(v.ErreurRequete) as refus:
            fonction({champ: v.b64url(retouche(brut))})
        assert refus.value.champ == champ, "le champ fautif est nommé"


class TestConventionsDuFil:
    def test_base64url_strict(self):
        """§3.4 — sans remplissage, et canonique : deux textes ne donnent
        jamais les mêmes octets."""
        assert v.de_b64url("AAA") == b"\x00\x00", "forme canonique"
        assert v.de_b64url("AAB") is None, "bits de queue non nuls refusés"
        assert v.de_b64url("AA==") is None, "remplissage refusé"
        assert v.de_b64url("A+/") is None, "alphabet standard refusé"

    def test_un_entier_est_un_entier(self):
        """§3.4 — ``true`` n'est pas 1 : ``True in {1}`` vaut vrai en Python,
        et ``kdfVersion: true`` passerait pour la version 1."""
        with pytest.raises(v.ErreurRequete):
            v.entier({"n": True}, "n")
        with pytest.raises(v.ErreurRequete):
            v.kdf_version({"kdfVersion": True})

    def test_aucun_flottant_ni_cle_en_double(self):
        """§3.4 — aucun flottant accepté (``1e-07`` contre ``1e-7``, CLAUDE.md
        §4) ; une clé en double validée sur l'une et lue sur l'autre."""
        for texte in (b'{"a": 1.0}', b'{"a": 1e3}', b'{"a": NaN}', b'{"a": 1, "a": 2}'):
            with pytest.raises(v.ErreurRequete) as refus:
                v.lire_json(texte)
            assert refus.value.code == "invalidRequest", f"refus de {texte!r}"
        assert v.lire_json(b"") == {}, "un corps vide vaut {}"


def _poster_en_flux(app, taille: int, *, annoncer: bool) -> tuple[int, int]:
    """POST ``/login`` par morceaux de 16 Kio, directement en ASGI : le
    ``TestClient`` lit tout le corps avant d'appeler l'application, et ne
    montrerait pas ce que le service lit, lui. Rend (statut, octets lus)."""
    import asyncio

    morceau = b" " * 16384
    lus = 0
    statut = 0

    async def recevoir():
        nonlocal lus
        if lus >= taille:
            return {"type": "http.disconnect"}
        lus += len(morceau)
        return {"type": "http.request", "body": morceau, "more_body": lus < taille}

    async def envoyer(message):
        nonlocal statut
        if message["type"] == "http.response.start":
            statut = message["status"]

    en_tetes = [(b"content-type", b"application/json")]
    if annoncer:
        en_tetes.append((b"content-length", str(taille).encode()))
    portee = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/login",
        "raw_path": b"/api/v1/login",
        "query_string": b"",
        "root_path": "",
        "headers": en_tetes,
        "client": ("127.0.0.1", 5000),
        "server": ("127.0.0.1", 8710),
    }
    asyncio.run(app(portee, recevoir, envoyer))
    return statut, lus


class TestBorneDuCorps:
    """§3.9 — nginx borne ``/api/`` à 64 Kio ; le service aussi, parce qu'un
    ``curl`` lancé sur le VPS même ne passe pas par nginx. Jusqu'au
    24/09/2026, la borne n'était vérifiée qu'APRÈS avoir tout lu en mémoire :
    un corps de 300 Mo remplissait le ``MemoryMax=300M`` avant le 413."""

    def test_un_corps_annonce_trop_gros_est_refuse_sans_etre_lu(self, service):
        statut, lus = _poster_en_flux(service.app, 8 * 1024 * 1024, annoncer=True)
        assert statut == 413, "Content-Length au-delà de 64 Kio"
        assert lus == 0, f"{lus} octets lus avant le refus"

    def test_un_corps_en_flux_est_coupe_a_64_kio(self, service):
        statut, lus = _poster_en_flux(service.app, 8 * 1024 * 1024, annoncer=False)
        assert statut == 413, "le flux dépasse 64 Kio"
        assert lus <= v.CORPS_MAX_OCTETS + 16384, (
            f"{lus} octets lus : la lecture s'arrête à la borne"
        )
