"""Envoyer ce que la MAIN tient — le geste, terminé à la voix.

Spatial Mesh, gestes — 25 août 2026. Fermer le poing retient ce que l'écran
affiche (`desktop/presse_papiers_spatial.py`) ; ouvrir la main le dépose. Mais
quand plusieurs appareils sont capables, le serveur POSE la question « vers
lequel ? » — et jusqu'ici la seule façon d'y répondre était de cliquer.

Cet outil est la réponse parlée. Il ne connaît QUE la main.

**Pourquoi un outil de plus, et pas `handoff_continue` élargi.** Deux
référents dans un même outil, c'est « je ne sais plus lequel des deux tu
veux ». Et aucun ne prime naturellement : la main peut être vide, et l'écran
peut avoir changé depuis la saisie. Un outil, un référent. `handoff_continue`
part de l'écran ; celui-ci part de la main, et rien d'autre.

**Ce qu'il ne prend pas en paramètre**, et c'est le point : aucun identifiant
de ressource. Le référent est la main, pas le modèle. Un outil qui accepterait
« envoie le projet p1 » laisserait le modèle inventer ce qu'il envoie, ce que
le geste existe précisément pour éviter.

**Répondre à une question, jamais en ouvrir une seconde.** Si le serveur
attend déjà un choix, cet outil tranche AVEC LES MÊMES CANDIDATS mesurés par
le serveur, et réutilise le jeton comme clé d'idempotence. Sans cela, un clic
à l'écran et une réponse à la voix enverraient deux fois.
"""

from __future__ import annotations

from typing import Any

from diapason.core.registry import ToolRegistry
from diapason.tools._stubs import BaseTool, ToolResult, ToolSpec
from diapason.tools.mesh_tools import MeshSendTool


def _rendre(succes: bool, contenu: str, metadata: dict[str, Any]) -> ToolResult:
    return ToolResult(
        tool_name="geste_deposer",
        success=succes,
        content=contenu,
        metadata=metadata,
    )


@ToolRegistry.register("geste_deposer")
class GesteDeposerTool(BaseTool):
    """Envoyer vers un appareil ce que la main tient."""

    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="geste_deposer",
            description=(
                "Send whatever the user is currently HOLDING with a hand gesture "
                "to one of their paired devices. The thing to send is not chosen "
                "here — it is whatever the user grabbed by closing their fist, and "
                "it appears in the context as 'Dans la main (geste) : …'. Use this "
                "when the user says something like 'envoie ça sur mon téléphone' or "
                "answers a pending 'vers lequel ?' question. If their hand is empty, "
                "this says so instead of sending anything."
            ),
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "device_phrase": {
                        "type": "string",
                        "description": (
                            "How the user named the device — 'mon téléphone', "
                            "'l'iPad'. Refused if it matches several devices."
                        ),
                    },
                    "device_id": {
                        "type": "string",
                        "description": (
                            "Target device id, as returned by mesh_devices. "
                            "Alternative to device_phrase."
                        ),
                    },
                },
                "required": [],
            },
            category="mesh",
            # Même risque que mesh_send : cela change ce qui s'affiche sur un
            # écran près duquel l'utilisateur n'est peut-être pas. La cloche
            # s'applique, au chat comme à la voix.
            metadata={"risk": "outward_action", "reversible": True},
        )

    # Empruntés à MeshSendTool, comme handoff_continue : « mon téléphone »
    # doit désigner le même appareil quel que soit l'outil qui l'entend,
    # sinon deux outils sont deux vérités pour une même phrase.
    #
    # `registry` se résout paresseusement sur `self._registry`, que le
    # `__init__` de MeshSendTool pose et que celui-ci n'a pas : l'attribut de
    # classe le fournit, comme dans handoff_continue.
    _registry = None
    registry = MeshSendTool.registry
    _target = MeshSendTool._target

    def execute(self, **params: Any) -> ToolResult:
        from diapason.desktop.presse_papiers_spatial import tenu
        from diapason.server import gestes_routes as gr

        objet = tenu()
        if objet is None:
            # L'outil, LUI, dit la main vide — parce qu'on l'a appelé. Le
            # contexte, lui, se tait dans ce cas : la dissymétrie est voulue.
            return _rendre(
                False,
                "Ta main est vide : ferme le poing sur ce que tu veux envoyer, "
                "puis redis-le-moi.",
                {"status": "NOTHING_HELD"},
            )

        phrase = str(params.get("device_phrase") or "").strip()
        identifiant = str(params.get("device_id") or "").strip()

        attente = gr.choix_en_attente()
        if attente is not None:
            return self._repondre_a_la_question(attente, phrase, identifiant)
        return self._deposer_librement(objet, phrase, identifiant)

    # ── répondre à une question déjà posée ──────────────────────────────
    def _repondre_a_la_question(
        self, attente: dict, phrase: str, identifiant: str
    ) -> ToolResult:
        """Trancher entre les candidats QUE LE SERVEUR a mesurés.

        Le modèle choisit parmi une liste fermée, il ne désigne pas une
        destination. C'est ce qui rend ce chemin plus sûr que `mesh_send` à
        la voix : une transcription approximative ne peut pas inventer un
        appareil qui n'était pas proposé — au pire elle ne correspond à
        aucun, et on repose la question.
        """
        from diapason.server import gestes_routes as gr

        candidats = list(attente["candidats"])
        cible = _choisir(candidats, phrase, identifiant)
        if cible is None:
            noms = ", ".join(c["name"] for c in candidats)
            return _rendre(
                False,
                f"« {attente['objet'].titre} » attend toujours : vers lequel — "
                f"{noms} ?",
                {"status": "AMBIGUOUS", "candidates": [c["name"] for c in candidats]},
            )
        resultat = gr.repondre_au_choix(attente, cible)
        return _rendre(
            bool(resultat.get("done")),
            str(resultat.get("message") or ""),
            {k: v for k, v in resultat.items() if k != "object"},
        )

    # ── aucun choix en attente : on résout comme les autres outils ───────
    def _deposer_librement(
        self, objet: Any, phrase: str, identifiant: str
    ) -> ToolResult:
        from diapason.mesh.identity import device_identity
        from diapason.server import gestes_routes as gr
        from diapason.tools.mesh_tools import _Unresolved

        try:
            # La MÊME résolution que mesh_send et handoff_continue : deux
            # outils qui répondraient différemment à « mon téléphone »
            # seraient deux vérités pour une phrase.
            cible_id = self._target(
                {"device_phrase": phrase, "device_id": identifiant},
                device_identity().device_id,
            )
        except _Unresolved as exc:
            return _rendre(False, str(exc), {"status": "AMBIGUOUS"})

        appareil = self.registry.find(cible_id) or {
            "deviceId": cible_id,
            "name": cible_id,
        }
        resultat = gr.envoyer_ce_qui_est_tenu(objet, appareil)
        return _rendre(
            bool(resultat.get("done")),
            str(resultat.get("message") or ""),
            {k: v for k, v in resultat.items() if k != "object"},
        )


def _choisir(candidats: list[dict], phrase: str, identifiant: str) -> Any:
    """Le candidat désigné, ou None — jamais un choix par défaut.

    Un seul candidat ne suffit PAS à trancher tout seul : si le serveur a
    posé la question, c'est qu'il y en avait plusieurs. Ne rien reconnaître
    rend None, et la question se repose.
    """
    if identifiant:
        for c in candidats:
            if c["deviceId"] == identifiant:
                return c
    if not phrase:
        return None
    from diapason.mesh.resolver import _fold

    voulu = _fold(phrase)
    exacts = [c for c in candidats if _fold(c["name"]) == voulu]
    if len(exacts) == 1:
        return exacts[0]
    partiels = [c for c in candidats if voulu and voulu in _fold(c["name"])]
    return partiels[0] if len(partiels) == 1 else None


__all__ = ["GesteDeposerTool"]
