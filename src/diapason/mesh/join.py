"""Rejoindre une flotte — le côté INVITÉ du jumelage, qui manquait.

Spatial Mesh, phase 0, 25 août 2026. La route ``POST /v1/mesh/pairings/
redeem`` existait, était ouverte hors clé d'API, et était testée. Mais
AUCUN client de ce dépôt ne l'appelait : l'interface sait créer une
invitation, pas en consommer une, et il n'y avait pas de commande. Le
côté hôte était complet, le côté invité absent — ce qui avait appairé les
appareils présents en base était le client Flutter, hors dépôt.

Pire, et c'est le vrai défaut : ``adopt_owner_id()`` n'avait AUCUN
appelant. Or ``owner_id()`` frappe un identifiant aléatoire local au
premier appel, et ``signed.py`` refuse toute enveloppe dont l'``ownerId``
diffère du nôtre — AVANT même de regarder la signature. Deux Diapason qui
s'appairaient obtenaient donc TRUSTED des deux côtés, puis se refusaient
mutuellement chaque balise, chaque relève et chaque commande, avec « vient
d'un autre ensemble d'appareils ». La réponse du redeem porte pourtant
l'``ownerId`` de l'hôte depuis toujours : le protocole le transmettait,
personne ne le lisait.

Les tests masquaient le défaut en injectant le même propriétaire des deux
côtés. C'est pourquoi le maillage marchait avec le téléphone — le client
Dart, lui, adopte l'identité de flotte — et jamais entre deux ordinateurs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DELAI_S = 15.0


class JoinError(RuntimeError):
    """Le jumelage n'a pas abouti — le message est destiné à l'utilisateur."""


@dataclass(frozen=True, slots=True)
class Jumelage:
    """Ce qu'on a appris de l'hôte en le rejoignant."""

    owner_id: str
    host_device_id: str
    host_name: str
    host_address: str
    granted_capabilities: tuple[str, ...]


def _base_propre(url: str) -> str:
    """L'adresse de l'hôte, normalisée — et refusée si elle sent le piège."""
    from urllib.parse import urlparse

    brut = (url or "").strip().rstrip("/")
    if not brut:
        raise JoinError("Il me faut l'adresse de l'ordinateur à rejoindre.")
    if "://" not in brut:
        brut = f"http://{brut}"
    parsed = urlparse(brut)
    if parsed.scheme not in ("http", "https"):
        raise JoinError("L'adresse doit commencer par http:// ou https://.")
    if not parsed.hostname:
        raise JoinError("Cette adresse n'a pas de nom d'hôte lisible.")
    if parsed.username or parsed.password:
        raise JoinError("N'inclus pas d'identifiants dans l'adresse.")
    return brut


def join_fleet(
    host_url: str,
    pairing_token: str,
    *,
    my_address: Optional[str] = None,
    poster: Any = None,
) -> Jumelage:
    """Consommer une invitation et ADOPTER l'identité de flotte de l'hôte.

    L'ordre compte : on adopte l'``ownerId`` AVANT d'enregistrer l'hôte
    dans notre registre. Un appareil enregistré sous un propriétaire qui
    n'est pas le nôtre serait un pair qu'on refuserait à chaque échange —
    exactement le défaut que cette fonction corrige.
    """
    base = _base_propre(host_url)
    jeton = (pairing_token or "").strip()
    if not jeton:
        raise JoinError("Il me faut le code d'invitation affiché sur l'hôte.")

    from diapason.mesh.capabilities import local_capabilities
    from diapason.mesh.identity import adopt_owner_id, device_identity

    moi = device_identity()
    if my_address is None:
        from diapason.mesh.beacon import local_address

        my_address = local_address()

    # deviceType n'est pas porté par l'identité : un Mac de bureau et un
    # portable partagent la plateforme MACOS. On dit LAPTOP faute de mieux
    # plutôt que d'inventer une détection — l'utilisateur renomme et
    # requalifie depuis la page Appareils.
    corps = {
        "pairingToken": jeton,
        "deviceId": moi.device_id,
        "publicKey": moi.public_key_b64,
        "name": moi.name,
        "platform": moi.platform,
        "deviceType": "LAPTOP",
        "capabilities": sorted(local_capabilities()),
        "appVersion": _version_app(),
        "address": my_address or "",
    }
    # Notre clé de scellement, pour que l'hôte puisse nous sceller dès la
    # première commande plutôt que d'attendre notre première annonce. Non
    # signée ici, exactement comme `publicKey` ne l'est pas : ce champ hérite
    # de la confiance du jeton d'invitation, ni plus ni moins. Le jumelage
    # lui-même passe en clair — c'est une faiblesse connue du maillage,
    # écrite dans docs/spatial-mesh/, et ce canal en hérite.
    try:
        from diapason.mesh.scellement import paire_locale

        corps["sealKey"] = paire_locale().publique_b64
    except Exception:  # noqa: BLE001 - un jumelage ne doit pas échouer pour cela
        logger.debug("clé de scellement non jointe au jumelage", exc_info=True)

    reponse = (poster or _poster)(f"{base}/v1/mesh/pairings/redeem", corps)
    hote = reponse.get("host") or {}
    owner = str(hote.get("ownerId") or "").strip()
    if not owner:
        raise JoinError(
            "L'hôte n'a pas renvoyé son identité de flotte — version trop "
            "ancienne ? Mets-le à jour avant de réessayer."
        )

    # LE geste qui manquait — et sa condition, constatée avant d'agir.
    # Un appareil qui n'a AUCUN pair de confiance porte un identifiant de
    # flotte qu'il s'est donné tout seul et que personne ne connaît : le
    # remplacer ne fait perdre personne. Dès qu'il a un pair, changer de
    # flotte les perdrait tous — refus, et l'utilisateur tranche.
    solitaire = _sans_aucun_pair()
    try:
        adopt_owner_id(owner, remplacer_si_solitaire=solitaire)
    except ValueError as exc:
        raise JoinError(str(exc)) from exc

    # L'hôte entre dans NOTRE registre : le jumelage est mutuel, sinon on
    # saurait lui répondre sans savoir le reconnaître.
    depuis = reponse.get("device") or {}
    accordees = tuple(depuis.get("capabilities") or ())
    adresse_hote = str(hote.get("address") or base)
    try:
        from diapason.mesh.registry import DeviceRegistry

        DeviceRegistry().enrol_host(
            device_id=str(hote.get("deviceId") or ""),
            public_key_b64=str(hote.get("publicKey") or ""),
            name=str(hote.get("name") or "Hôte"),
            platform=str(hote.get("platform") or "UNKNOWN"),
            device_type=str(hote.get("deviceType") or "DESKTOP"),
            declared_capabilities=list(hote.get("capabilities") or ()),
            address=adresse_hote,
        )
    except Exception as exc:  # noqa: BLE001 - l'adoption a réussi, c'est l'essentiel
        logger.warning("hôte non enregistré localement : %s", exc, exc_info=True)

    # Et la sienne, s'il en a publié une. Rangée APRÈS `enrol_host`, qui
    # remet justement cette colonne à NULL : l'inverse effacerait ce qu'on
    # vient d'écrire.
    cle_hote = str(hote.get("sealKey") or "")
    if cle_hote:
        try:
            import time as _time

            from diapason.mesh.registry import DeviceRegistry

            DeviceRegistry().record_seal_key(
                str(hote.get("deviceId") or ""),
                cle_hote,
                int(_time.time() * 1000),
            )
        except Exception:  # noqa: BLE001
            logger.debug("clé de scellement de l'hôte non retenue", exc_info=True)

    return Jumelage(
        owner_id=owner,
        host_device_id=str(hote.get("deviceId") or ""),
        host_name=str(hote.get("name") or "Hôte"),
        host_address=adresse_hote,
        granted_capabilities=accordees,
    )


def _sans_aucun_pair() -> bool:
    """Cet appareil est-il seul au monde ? Constaté, jamais supposé.

    Un registre illisible rend False : dans le doute, on refuse de changer
    de flotte plutôt que de risquer d'en orpheliner une.
    """
    try:
        from diapason.mesh.registry import DeviceRegistry

        return not DeviceRegistry().list_devices()
    except Exception:  # noqa: BLE001 - le doute profite à la flotte existante
        logger.warning("registre illisible : adoption refusée", exc_info=True)
        return False


def _version_app() -> str:
    try:
        from diapason import __version__

        return str(__version__)[:40]
    except Exception:  # noqa: BLE001 - une version illisible n'empêche pas de rejoindre
        return ""


def _poster(url: str, corps: dict) -> dict:
    """Le POST réel. Séparé pour que les tests n'ouvrent aucune socket."""
    import httpx

    from diapason.core.local_mode import LocalOnlyError, local_only
    from diapason.mesh.transport import address_is_private

    # LE JUMELAGE EST LE SEUL GESTE DU MAILLAGE QUI NE PEUT PAS S'APPUYER SUR
    # LA CONFIANCE — c'est lui qui la crée.
    #
    # Partout ailleurs, `assert_may_reach_device` porte l'exemption étroite du
    # maillage au mode local : un pair APPAIRÉ, joignable sur une adresse
    # PRIVÉE, peut être commandé même sous `local_only`. Ici, la moitié
    # « appairé » n'existe pas encore, et le code appelait donc le garde
    # générique — celui du nuage — qui refusait tout.
    #
    # Conséquence constatée le 26 août 2026, sur une installation Windows
    # neuve où `local_only` vaut `true` par défaut : impossible de jumeler
    # deux machines du même réseau. Et le refus conseillait « Set local_only
    # = false to allow cloud engines », c'est-à-dire d'ouvrir l'accès au nuage
    # pour joindre un ordinateur à trois mètres. Un conseil qui affaiblit un
    # garde-fou pour une raison qui ne le concerne pas.
    #
    # L'autre moitié de l'exemption, elle, s'applique pleinement : l'adresse
    # est privée ou elle ne l'est pas. On la garde, et on garde le refus pour
    # tout ce qui sort du réseau local — jumeler par Internet est exactement
    # ce que `local_only` doit empêcher.
    if local_only() and not address_is_private(url):
        raise LocalOnlyError(
            "Le mode local-only est actif et cette adresse n'est pas sur le "
            f"réseau local : rien n'a été envoyé à {url}. Jumelez deux "
            "machines du même réseau, ou mettez local_only = false dans "
            "~/.diapason/config.toml si vous voulez vraiment jumeler par "
            "Internet."
        )
    try:
        reponse = httpx.post(url, json=corps, timeout=_DELAI_S)
    except httpx.HTTPError as exc:
        raise JoinError(
            f"Impossible de joindre {url} — l'ordinateur est-il allumé et "
            f"Diapason lancé ? ({str(exc)[:80]})"
        ) from exc
    if reponse.status_code == 404:
        raise JoinError("Cette adresse répond, mais pas au maillage : vérifie le port.")
    if reponse.status_code >= 400:
        detail = ""
        try:
            detail = str((reponse.json() or {}).get("detail") or "")
        except Exception:  # noqa: BLE001
            detail = reponse.text[:120]
        raise JoinError(detail or f"L'hôte a refusé (HTTP {reponse.status_code}).")
    return reponse.json()


__all__ = ["JoinError", "Jumelage", "join_fleet"]
