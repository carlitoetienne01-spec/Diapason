"""Les images jointes à un message du chat (§5 : rien ne passe sans être vu).

22/09/2026 : le serveur transmettait déjà les images à Ollama et qwen3.5:9b
annonce « vision », mais le modèle Pydantic qui reçoit les requêtes n'avait
aucun champ pour elles — le navigateur ne pouvait rien envoyer.
"""

import base64

import pytest

from diapason.server.models import ChatMessage
from diapason.server.pieces_jointes import (
    NOMBRE_MAX,
    TAILLE_MAX,
    PieceJointeRefusee,
    format_de,
    normaliser,
    normaliser_toutes,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 40
GIF = b"GIF89a" + b"\x00" * 40
WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 30


def en_base64(octets: bytes) -> str:
    return base64.b64encode(octets).decode()


class TestLeFormatSeLitDansLesOctets:
    """L'en-tête « data:image/png » qu'envoie le client est une déclaration,
    pas une preuve : c'est un champ de texte qu'il écrit lui-même."""

    @pytest.mark.parametrize(
        ("octets", "attendu"),
        [
            (PNG, "image/png"),
            (JPEG, "image/jpeg"),
            (GIF, "image/gif"),
            (WEBP, "image/webp"),
        ],
    )
    def test_les_formats_que_les_modeles_de_vision_lisent(self, octets, attendu):
        assert format_de(octets) == attendu

    @pytest.mark.parametrize(
        "octets",
        [
            b"%PDF-1.7\n%\xe2\xe3\xcf\xd3",  # un PDF déguisé en image
            b"<svg xmlns='http://www.w3.org/2000/svg'>",  # SVG : du script
            b"MZ\x90\x00",  # un exécutable Windows
            b"",
        ],
    )
    def test_ce_qui_n_est_pas_une_image_n_en_est_pas_une(self, octets):
        assert format_de(octets) is None

    def test_un_pdf_annonce_comme_png_est_refuse(self):
        """Le mensonge est dans l'en-tête ; les octets, eux, disent PDF."""
        menteur = "data:image/png;base64," + en_base64(b"%PDF-1.7\n")
        with pytest.raises(PieceJointeRefusee, match="Format non reconnu"):
            normaliser(menteur)


class TestCeQuiEstAccepte:
    def test_l_entete_data_est_retiree(self):
        """FileReader.readAsDataURL rend « data:image/png;base64,… » ;
        Ollama veut le base64 nu."""
        nu = en_base64(PNG)
        assert normaliser(f"data:image/png;base64,{nu}") == nu
        assert normaliser(nu) == nu, "sans en-tête, c'est déjà bon"

    def test_les_espaces_autour_ne_genent_pas(self):
        nu = en_base64(PNG)
        assert normaliser(f"  {nu}  ") == nu

    def test_trois_images_passent(self):
        images = [en_base64(PNG), en_base64(JPEG), en_base64(GIF)]
        assert normaliser_toutes(images) == images

    def test_aucune_image_rend_none(self):
        assert normaliser_toutes(None) is None
        assert normaliser_toutes([]) is None, (
            "une liste vide n'est pas une image vide : le message est du texte"
        )


class TestCeQuiEstRefuse:
    def test_une_image_vide(self):
        with pytest.raises(PieceJointeRefusee, match="vide"):
            normaliser("")

    def test_du_base64_invalide(self):
        with pytest.raises(PieceJointeRefusee, match="pas du base64"):
            normaliser("ceci n'est pas du base64 !!!")

    def test_trop_lourde(self):
        """Une photo d'iPhone fait 12 Mo, 16 une fois encodée : on transporte
        des octets que le modèle redimensionne de toute façon."""
        enorme = PNG + b"\x00" * (TAILLE_MAX + 1)
        with pytest.raises(PieceJointeRefusee, match="trop lourde"):
            normaliser(en_base64(enorme))

    def test_trop_nombreuses(self):
        """Chaque image coûte des centaines de jetons au 9b, qui a 32 Ko."""
        with pytest.raises(PieceJointeRefusee, match=f"maximum {NOMBRE_MAX}"):
            normaliser_toutes([en_base64(PNG)] * (NOMBRE_MAX + 1))

    def test_une_seule_refusee_refuse_le_message(self):
        """Livrer les deux autres en silence ferait croire que la troisième
        a été vue (§5)."""
        with pytest.raises(PieceJointeRefusee, match="Format non reconnu"):
            normaliser_toutes([en_base64(PNG), en_base64(b"%PDF-1.7\n")])

    def test_le_refus_dit_ce_qui_est_refuse(self):
        """« Une erreur est survenue » n'apprend rien à qui vient de glisser
        une photo."""
        with pytest.raises(PieceJointeRefusee) as erreur:
            normaliser(en_base64(PNG + b"\x00" * (TAILLE_MAX + 1)))
        message = str(erreur.value)
        assert "Mo" in message and "maximum" in message


class TestLeChampArriveJusquAuModele:
    def test_chat_message_accepte_des_images(self):
        """Le trou était exactement là : le tuyau allait du serveur à Ollama,
        pas du navigateur au serveur."""
        m = ChatMessage(role="user", content="c'est quoi ?", images=[en_base64(PNG)])
        assert m.images and len(m.images) == 1

    def test_un_message_sans_images_reste_sans_images(self):
        assert ChatMessage(role="user", content="bonjour").images is None

    def test_la_conversion_valide_et_transmet(self):
        from diapason.core.types import Role
        from diapason.server.routes import _to_messages

        nu = en_base64(JPEG)
        (message,) = _to_messages(
            [
                ChatMessage(
                    role="user",
                    content="regarde",
                    images=[f"data:image/jpeg;base64,{nu}"],
                )
            ]
        )
        assert message.role == Role.USER
        assert message.images == [nu], "l'en-tête data: est retirée en chemin"

    def test_la_conversion_refuse_ce_qui_n_est_pas_une_image(self):
        from diapason.server.routes import _to_messages

        with pytest.raises(PieceJointeRefusee):
            _to_messages(
                [ChatMessage(role="user", content="x", images=[en_base64(b"%PDF-1.7")])]
            )


class TestLeCheminQuiPorteLesImages:
    """22/09/2026 : sans flux, `agent.run()` prend une CHAÎNE — le dernier
    message était réduit à son texte et ses images tombaient par terre. Le
    modèle répondait « je n'ai pas accès à l'image » à qui venait de lui en
    joindre une, et rien ne disait qu'elle avait été jetée."""

    def _requete(self, avec_images):
        from diapason.server.models import ChatCompletionRequest

        message = {"role": "user", "content": "regarde"}
        if avec_images:
            message["images"] = [en_base64(PNG)]
        return ChatCompletionRequest(model="m", messages=[ChatMessage(**message)])

    def test_un_message_avec_images_evite_l_agent(self):
        """Même garde que pour les outils fournis par le client : `agent.run()`
        les ignore aussi, et le silence de ce détournement a produit #414."""
        req = self._requete(avec_images=True)
        assert any(getattr(m, "images", None) for m in req.messages), (
            "c'est ce test-là que fait le routage dans chat_completions"
        )

    def test_un_message_sans_image_reste_sur_le_chemin_de_l_agent(self):
        req = self._requete(avec_images=False)
        assert not any(getattr(m, "images", None) for m in req.messages)

    def test_le_moteur_transmet_les_images_a_ollama(self):
        """La plomberie d'engine/_base.py — « Vision: forward base64 images
        to the engine » — sur un vrai Message."""
        from diapason.core.types import Message, Role
        from diapason.engine._base import messages_to_dicts

        nu = en_base64(PNG)
        sortie = messages_to_dicts(
            [Message(role=Role.USER, content="regarde", images=[nu])]
        )
        assert sortie[0]["images"] == [nu]

    def test_un_message_sans_image_n_ajoute_pas_le_champ(self):
        from diapason.core.types import Message, Role
        from diapason.engine._base import messages_to_dicts

        sortie = messages_to_dicts([Message(role=Role.USER, content="bonjour")])
        assert "images" not in sortie[0], (
            "un champ vide sur chaque message de texte coûterait pour rien"
        )
