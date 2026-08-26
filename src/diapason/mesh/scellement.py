"""Sceller ce qu'une commande DIT, sans toucher à ce qui la route.

26 août 2026. Les enveloppes de commande étaient signées mais pas chiffrées :
personne ne pouvait en fabriquer une sans la clé privée, mais quiconque était
sur le même Wi-Fi lisait le verbe et ses arguments — titres de notification,
adresses ouvertes, noms de fichiers. Sur la loopback c'était sans objet ; le
maillage a été ouvert au réseau le jour même.

**Aucun champ nouveau sur le fil.** Le triplet ``tool`` / ``arguments`` /
``requiresConfirmation`` est remplacé par une sentinelle et un blob, dans les
champs qui existent déjà. C'est tout le mécanisme, et ce n'est pas un
raffinement : un champ ajouté au niveau supérieur ne serait pas reproduit par
``RemoteCommand.from_dict``, qui lit une liste fixe de clés — le récepteur
réémettrait donc une enveloppe amputée et la signature tomberait. Ici il n'y a
rien à arracher.

**Une SECONDE paire X25519 statique, jamais une conversion.** L'en-tête de
``coffre.py`` refuse de convertir Ed25519 → X25519, pour deux raisons qui
tiennent : la conversion n'existe pas dans ``cryptography``, l'écrire serait
de l'arithmétique de corps à la main — la cryptographie maison qu'interdit le
§40 ; et détourner une clé de signature pour de l'accord de clé se paie. On ne
convertit rien : on génère. Une clé, un usage.

**Statique et non éphémère, et c'est un prix assumé.** Une commande est
POUSSÉE : un pair endormi ne peut pas fournir de moitié éphémère, et une
commande attend jusqu'à ``QUEUED_TTL_MS`` (six heures) dans la file. Un design
éphémère laisserait donc partir en clair, en silence, précisément le chemin qui
compte. Le prix : plus de confidentialité persistante côté destinataire — qui
archive le trafic puis vole ``seal_key`` déchiffre rétroactivement. Atténué
côté émetteur, dont la moitié reste éphémère, et relativisé par le fait que ce
voleur tient aussi la clé Ed25519 et la base du maillage.

**Sceller PUIS signer.** La signature reste la créance et doit rester
vérifiable SANS la clé de déchiffrement : un pair révoqué, une enveloppe
expirée ou mal adressée sont refusés sur l'identité avant qu'un octet de
chiffré ne soit touché — un inconnu du réseau ne peut pas nous faire calculer
un X25519 par paquet.

Ce que ce module NE protège pas est écrit dans ``docs/spatial-mesh/``, et la
première ligne de cette liste mérite d'être répétée ici : **le client mobile
ne publie aucune clé**, donc rien ne lui est scellé. L'exclusion est
structurelle — on ne scelle que vers un pair dont on DÉTIENT une clé fraîche —
et non une règle qu'il faudrait penser à respecter.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# La sentinelle qui remplace le verbe. Elle n'entre JAMAIS dans le catalogue
# des outils distants ni dans les capacités déclarées : c'est une marque de
# transport, pas un verbe qu'un appareil pourrait exécuter.
SENTINELLE = "mesh.sealed"

SCEAU_VERSION = 1
_CHAMPS_SCEAU = ("version", "ownerId", "deviceId", "sealKey", "sentAtMs")

# La clé d'un pair vue il y a plus longtemps que cela n'est plus employée.
# C'est le SEUL mécanisme de repli : on ne démote jamais sur un corps de
# réponse, qui n'est pas signé et qu'un attaquant forge à volonté. Il doit
# donc supprimer les publications sept jours durant, pas une fois — une usure,
# pas un interrupteur.
FRAICHEUR_MS = 7 * 24 * 3600 * 1000

# L'ancienne clé reste déchiffrable après un renouvellement. INVARIANT : cette
# durée doit dépasser QUEUED_TTL_MS (six heures), sans quoi une commande mise
# en file avant le renouvellement deviendrait indéchiffrable pendant qu'elle
# attend. Un test le vérifie.
RETENTION_PRECEDENTE_MS = FRAICHEUR_MS

# Le clair est complété jusqu'au multiple supérieur. Sans cela, la longueur
# trahit le verbe : le catalogue ne compte que cinq entrées.
PALIER_REMBOURRAGE = 256

_INFO_COMMANDE = b"diapason-mesh-command-v1"
_FICHIER_CLE = "seal_key"
_FICHIER_PRECEDENT = "seal_key.prev"


def _chemin(nom: str):
    from diapason.mesh.identity import identity_dir

    return identity_dir() / nom


def _lire(nom: str):
    """La paire rangée sous *nom*, ou None. Ne crée rien."""
    from diapason.mesh.identity import _read_private_key

    chemin = _chemin(nom)
    if not chemin.exists():
        return None
    try:
        privee = _read_private_key(chemin)
    except Exception:  # noqa: BLE001 - clé illisible = clé absente
        logger.warning("clé de scellement illisible : %s", chemin.name)
        return None
    return _paire_depuis(privee)


def _paire_depuis(privee: bytes):
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    from diapason.mesh.coffre import DemiCle

    publique = (
        X25519PrivateKey.from_private_bytes(privee)
        .public_key()
        .public_bytes(Encoding.Raw, PublicFormat.Raw)
    )
    return DemiCle(privee=privee, publique=publique)


def paire_locale():
    """La paire de scellement de CETTE machine, créée au premier appel.

    Écrite par le chemin durci d'``identity`` — dossier 0700, fichier 0600,
    ``O_EXCL``, ``O_NOFOLLOW`` — et non par une copie de ce durcissement :
    deux copies divergent.
    """
    from diapason.mesh.coffre import nouvelle_demi_cle
    from diapason.mesh.identity import _write_private_key, identity_dir

    existante = _lire(_FICHIER_CLE)
    if existante is not None:
        return existante

    dossier = identity_dir()
    dossier.mkdir(mode=0o700, parents=True, exist_ok=True)
    neuve = nouvelle_demi_cle()
    try:
        _write_private_key(_chemin(_FICHIER_CLE), neuve.privee)
    except FileExistsError:
        # Une autre session l'a écrite entre notre lecture et notre écriture.
        # La sienne fait foi : deux clés pour une machine, ce serait deux
        # machines pour ses pairs.
        relue = _lire(_FICHIER_CLE)
        if relue is None:
            raise
        return relue
    return neuve


def paire_precedente():
    """La paire d'avant un renouvellement, tant qu'elle est conservée."""
    return _lire(_FICHIER_PRECEDENT)


def kid(publique: bytes) -> str:
    """Huit hexadécimaux qui désignent une clé sans la révéler.

    Le destinataire s'en sert pour choisir entre sa clé courante et la
    précédente, sans essayer les deux à l'aveugle.
    """
    import hashlib

    return hashlib.sha256(publique).hexdigest()[:8]


def renouveler() -> None:
    """Frapper une clé neuve, en gardant la précédente déchiffrable.

    Geste EXPLICITE, jamais automatique : une rotation périodique n'achèterait
    rien qu'une clé statique n'ait déjà perdu, et créerait une panne différée —
    un ``kid`` périmé refusé des heures après coup.
    """
    from diapason.mesh.identity import _write_private_key

    courante = _chemin(_FICHIER_CLE)
    precedente = _chemin(_FICHIER_PRECEDENT)
    if courante.exists():
        # DÉPLACER avant d'écrire : `_write_private_key` utilise O_EXCL et
        # refuserait un fichier déjà là.
        precedente.unlink(missing_ok=True)
        courante.replace(precedente)
    from diapason.mesh.coffre import nouvelle_demi_cle

    _write_private_key(courante, nouvelle_demi_cle().privee)


def oublier_locale() -> None:
    """Effacer les deux clés. Le prochain appel en frappera une neuve."""
    _chemin(_FICHIER_CLE).unlink(missing_ok=True)
    _chemin(_FICHIER_PRECEDENT).unlink(missing_ok=True)


# ── publier sa clé, et lire celle des autres ────────────────────────────


def bloc_sceau() -> dict[str, Any]:
    """La clé publique de cette machine, signée par son identité.

    Ce bloc s'attache à des corps de RÉPONSE qui circulent déjà — celui de
    ``/v1/mesh/presence``, celui du jumelage — plutôt qu'à une route neuve.
    Une route de plus coûterait une porte au mur du réseau, un seau de
    limitation, une régénération d'instantané de contrat, et rendrait faux
    trois commentaires qui comptent les neuf portes. Un corps de réponse ne
    coûte rien de tout cela.

    Il n'est JAMAIS servi à un inconnu : la route qui le porte refuse en 403
    avant de répondre quoi que ce soit. Ce dépôt vient de colmater une fuite
    d'identifiant sur une route ouverte — la remarque n'est pas théorique.
    """
    from diapason.mesh.identity import device_identity, owner_id
    from diapason.mesh.signed import sign_payload

    return sign_payload(
        {
            "version": SCEAU_VERSION,
            "ownerId": owner_id(),
            "deviceId": device_identity().device_id,
            "sealKey": paire_locale().publique_b64,
            "sentAtMs": _maintenant_ms(),
        },
        _CHAMPS_SCEAU,
    )


def _maintenant_ms() -> int:
    import time

    return int(time.time() * 1000)


def lire_bloc_sceau(
    corps: Any, *, registry: Any = None, pair_attendu: str = ""
) -> bool:
    """Enregistrer la clé qu'un pair vient de publier. NE LÈVE JAMAIS.

    Appelée depuis ``announce_to``, qui promet de ne jamais lever : une
    annonce qui n'aboutit pas n'est pas une erreur que l'utilisateur doive
    entendre. Un corps malformé ne doit donc pas remonter d'ici.

    Le contrôle qui compte : la clé est rangée sous le device_id que
    ``verify_payload`` RETOURNE, et l'on vérifie qu'il vaut bien celui qu'on
    interrogeait. Sans cela, un sceau capté chez A et recollé dans une
    réponse de B écrirait la clé de A dans la ligne de B — et l'on scellerait
    ensuite vers A ce qui était destiné à B.
    """
    try:
        from diapason.mesh.identity import device_identity, owner_id
        from diapason.mesh.registry import DeviceRegistry
        from diapason.mesh.signed import SignedRejected, verify_payload

        if not isinstance(corps, dict):
            return False
        bloc = corps.get("sceau")
        if not isinstance(bloc, dict):
            return False

        registre = registry if registry is not None else DeviceRegistry()
        try:
            signataire = verify_payload(
                bloc,
                fields=_CHAMPS_SCEAU,
                version=SCEAU_VERSION,
                registry=registre,
                local_owner_id=owner_id(),
                local_device_id=device_identity().device_id,
                now_ms=_maintenant_ms(),
                subject="publication de clé",
            )
        except SignedRejected as exc:
            logger.debug("bloc de sceau refusé : %s", exc)
            return False

        if pair_attendu and signataire != pair_attendu:
            logger.warning(
                "bloc de sceau signé par %s dans une réponse de %s : ignoré",
                signataire,
                pair_attendu,
            )
            return False

        return bool(
            registre.record_seal_key(
                signataire,
                str(bloc.get("sealKey") or ""),
                int(bloc.get("sentAtMs") or 0),
            )
        )
    except Exception:  # noqa: BLE001 - cette fonction ne lève jamais
        logger.debug("bloc de sceau illisible", exc_info=True)
        return False


# ── faut-il sceller, et vers quelle clé ? ───────────────────────────────


class ScellementExige(RuntimeError):
    """Le réglage exige le chiffrement et ce pair n'a pas de clé fraîche.

    Une exception plutôt qu'un ``None`` de plus : sous ``exige``, partir en
    clair serait exactement la panne silencieuse que ce réglage veut
    empêcher. L'appelant doit avoir à s'en occuper, pas à y penser.
    """


def mode_de_chiffrement() -> str:
    """Ce que la configuration demande. « opportuniste » à défaut."""
    try:
        from diapason.core.config import load_config

        mode = str(load_config().mesh.chiffrement or "").strip().lower()
    except Exception:  # noqa: BLE001 - une config illisible ne casse pas le maillage
        return "opportuniste"
    return mode if mode in {"opportuniste", "exige", "jamais"} else "opportuniste"


def doit_sceller(
    device: Any, *, registry: Any = None, maintenant_ms: int | None = None
) -> str | None:
    """La clé vers laquelle sceller — ou None pour partir en clair.

    LE point de décision, et le seul. Il ne lit QUE trois choses : le
    réglage, le registre, et l'horloge. Jamais un corps de réponse.

    C'est la correction la plus importante du plan. La première version
    rendait obligatoire une rétrogradation vers le clair quand le pair
    répondait « je ne connais pas cet outil » — mais cette réponse est un
    corps HTTP NON SIGNÉ. Un paquet forgé suffisait alors à éteindre le
    chiffrement, commande par commande, et de façon persistante. Un
    chiffrement qu'un attaquant coupe à volonté est pire que pas de
    chiffrement, parce qu'on croit l'avoir.

    Le seul repli est donc l'expiration d'un fait SIGNÉ : la clé d'un pair
    vue il y a plus de ``FRAICHEUR_MS`` ne s'emploie plus. Un attaquant qui
    supprime les publications doit tenir sept jours, pas une seconde — une
    usure, pas un interrupteur. Et le repli se voit, au lieu de se taire.
    """
    mode = mode_de_chiffrement()
    if mode == "jamais":
        return None

    from diapason.mesh.registry import DeviceRegistry

    registre = registry if registry is not None else DeviceRegistry()
    device_id = str(
        (device.get("deviceId") if isinstance(device, dict) else device) or ""
    )
    retenue = registre.seal_key_of(device_id) if device_id else None

    if retenue is not None:
        cle, vue_a = retenue
        instant = _maintenant_ms() if maintenant_ms is None else int(maintenant_ms)
        if instant - vue_a <= FRAICHEUR_MS:
            return cle

    if mode == "exige":
        nom = device.get("name") if isinstance(device, dict) else device_id
        raise ScellementExige(
            f"Le chiffrement des commandes est exigé et « {nom} » ne publie "
            "pas de clé de scellement (téléphone, ou version antérieure de "
            "Diapason) : rien ne lui a été envoyé."
        )
    return None


# ── le scellement lui-même ──────────────────────────────────────────────


def _rembourrer(clair: bytes) -> bytes:
    """Compléter par des zéros jusqu'au palier supérieur.

    Sûr et sans champ de longueur : ``json.dumps`` échappe tout caractère de
    contrôle, donc les octets sérialisés ne contiennent jamais ``0x00`` et
    ``rstrip`` ne peut pas manger de contenu.
    """
    reste = len(clair) % PALIER_REMBOURRAGE
    return clair + b"\x00" * (PALIER_REMBOURRAGE - reste)


def _derembourrer(clair: bytes) -> bytes:
    return clair.rstrip(b"\x00")


def contenu_scelle(
    tool: str,
    arguments: dict[str, Any],
    requires_confirmation: bool,
    *,
    cle_pair_b64: str,
    command_id: str,
    associe: bytes,
) -> dict[str, str]:
    """Le triplet, chiffré vers un pair, prêt à occuper ``arguments``.

    Le sel de dérivation est ``command_id`` — neuf à chaque commande — donc la
    clé AES est neuve elle aussi, ce qui rend sûr le nonce constant de
    ``coffre``. Deux garanties indépendantes de fraîcheur : le sel ET la
    moitié éphémère.
    """
    from diapason.mesh.coffre import cle_de_session, nouvelle_demi_cle, sceller
    from diapason.mesh.identity import canonical_bytes

    demi = nouvelle_demi_cle()
    cle = cle_de_session(demi, cle_pair_b64, command_id, info=_INFO_COMMANDE)
    clair = canonical_bytes(
        {"t": tool, "a": arguments, "c": bool(requires_confirmation)}
    )
    blob = sceller(cle, 0, _rembourrer(clair), associe=associe)

    import base64

    return {
        "s": base64.b64encode(blob).decode("ascii"),
        "e": demi.publique_b64,
        "k": kid(_cle_publique_pair(cle_pair_b64)),
    }


def _cle_publique_pair(b64: str) -> bytes:
    import base64

    return base64.b64decode(b64, validate=True)


def ouvrir_contenu(
    scelle: dict[str, Any], *, command_id: str, associe: bytes
) -> tuple[str, dict[str, Any], bool]:
    """Rouvrir un triplet scellé, avec la clé courante ou la précédente.

    Le ``kid`` désigne laquelle : sans lui, il faudrait les essayer à
    l'aveugle et un échec ne dirait pas s'il vient de la clé ou du contenu.
    """
    import base64
    import json

    from diapason.mesh.coffre import cle_de_session, desceller

    if not isinstance(scelle, dict):
        raise ValueError("Contenu scellé illisible.")
    demande = str(scelle.get("k") or "")
    demi = None
    for candidate in (paire_locale(), paire_precedente()):
        if candidate is not None and kid(candidate.publique) == demande:
            demi = candidate
            break
    if demi is None:
        raise ValueError(
            "Cette commande est scellée pour une clé que cette machine n'a plus."
        )

    try:
        blob = base64.b64decode(str(scelle.get("s") or ""), validate=True)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("Contenu scellé illisible.") from exc

    cle = cle_de_session(
        demi, str(scelle.get("e") or ""), command_id, info=_INFO_COMMANDE
    )
    clair = _derembourrer(desceller(cle, 0, blob, associe=associe))
    charge = json.loads(clair.decode("utf-8"))
    if not isinstance(charge, dict):
        raise ValueError("Contenu scellé illisible.")
    outil = str(charge.get("t") or "")
    arguments = charge.get("a")
    if not outil or not isinstance(arguments, dict):
        raise ValueError("Contenu scellé incomplet.")
    return outil, arguments, bool(charge.get("c"))


__all__ = [
    "FRAICHEUR_MS",
    "ScellementExige",
    "bloc_sceau",
    "doit_sceller",
    "mode_de_chiffrement",
    "lire_bloc_sceau",
    "PALIER_REMBOURRAGE",
    "RETENTION_PRECEDENTE_MS",
    "SCEAU_VERSION",
    "SENTINELLE",
    "contenu_scelle",
    "kid",
    "oublier_locale",
    "ouvrir_contenu",
    "paire_locale",
    "paire_precedente",
    "renouveler",
]
