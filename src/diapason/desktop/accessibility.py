"""Small, optional macOS Accessibility adapter.

PyObjC is optional at import time.  When AX is unavailable, callers can fall
back to the clipboard-preserving paste path without weakening permissions.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def accessibility_works() -> bool:
    """Si l'API d'accessibilité RÉPOND, pas si un drapeau dit qu'elle devrait.

    ``accessibility_trusted()`` interroge ``AXIsProcessTrustedWithOptions``,
    qui peut répondre True pendant que chaque appel réel rend -25204
    (kAXErrorAPIDisabled) — constaté ici : drapeau à True, insertion refusée
    quatre fois de suite, y compris depuis le contexte launchd autorisé.

    Le seul test qui ne ment pas est un appel véritable. Il coûte une
    fraction de milliseconde et évite d'annoncer une capacité absente —
    exactement le défaut que cette base a passé une semaine à retirer.
    """
    if sys.platform != "darwin":
        return False
    try:
        from ApplicationServices import (  # type: ignore
            AXUIElementCopyAttributeValue,
            AXUIElementCreateSystemWide,
            kAXFocusedUIElementAttribute,
        )

        err, _ = AXUIElementCopyAttributeValue(
            AXUIElementCreateSystemWide(), kAXFocusedUIElementAttribute, None
        )
        # -25212 (pas d'élément focalisé) signifie que l'API répond : c'est
        # une absence de cible, pas un refus. Seul -25204 est un refus.
        return err in (0, -25212)
    except (ImportError, AttributeError, TypeError, ValueError):
        return False


def accessibility_trusted(*, prompt: bool = False) -> bool:
    if sys.platform != "darwin":
        return False
    try:
        from ApplicationServices import (  # type: ignore
            AXIsProcessTrustedWithOptions,
            kAXTrustedCheckOptionPrompt,
        )

        return bool(
            AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: prompt})
        )
    except (ImportError, AttributeError):
        return False


def _copied_value(result: Any) -> Any:
    """Normalize PyObjC's version-dependent AX copy return shape."""
    if isinstance(result, tuple):
        if len(result) >= 2 and result[0] == 0:
            return result[1]
        return None
    return result


def insert_text(text: str) -> bool:
    """Insert text at the focused UI element using AX selected-text."""
    if not text or not accessibility_works():
        return False
    try:
        from ApplicationServices import (  # type: ignore
            AXUIElementCopyAttributeValue,
            AXUIElementCreateSystemWide,
            AXUIElementSetAttributeValue,
            kAXFocusedUIElementAttribute,
            kAXSelectedTextAttribute,
        )

        system = AXUIElementCreateSystemWide()
        focused = _copied_value(
            AXUIElementCopyAttributeValue(system, kAXFocusedUIElementAttribute, None)
        )
        if focused is None:
            return False
        return (
            AXUIElementSetAttributeValue(focused, kAXSelectedTextAttribute, text) == 0
        )
    except (ImportError, AttributeError, TypeError, ValueError):
        logger.debug("AX text insertion unavailable", exc_info=True)
        return False


def replace_previous(count: int, text: str) -> bool:
    """Remplacer les ``count`` derniers caractères par ``text``.

    C'est la primitive de la dictée progressive : whisper relit tout le
    tampon à chaque passe et peut RÉVISER ce qu'il avait compris — « ca »
    devient « ça », « conte » devient « compte ». Il faut donc pouvoir
    défaire ce qu'on vient d'écrire.

    On sélectionne la plage, puis on l'écrase. Aucune touche Retour arrière
    n'est simulée : une frappe synthétique traverse l'autocomplétion, les
    raccourcis et l'historique d'annulation de l'application, et ce qu'elle
    déclenche là-bas n'est pas prévisible. Déplacer une sélection, si.

    Rend False sans rien tenter quand la plage n'est pas lisible — mieux
    vaut ne pas réviser que réviser au mauvais endroit, dans un document que
    l'utilisateur est en train d'écrire.
    """
    if count <= 0:
        return insert_text(text)
    if not accessibility_works():
        return False
    try:
        from ApplicationServices import (  # type: ignore
            AXUIElementCopyAttributeValue,
            AXUIElementCreateSystemWide,
            AXUIElementSetAttributeValue,
            AXValueCreate,
            AXValueGetValue,
            kAXFocusedUIElementAttribute,
            kAXSelectedTextAttribute,
            kAXSelectedTextRangeAttribute,
            kAXValueCFRangeType,
        )

        system = AXUIElementCreateSystemWide()
        focused = _copied_value(
            AXUIElementCopyAttributeValue(system, kAXFocusedUIElementAttribute, None)
        )
        if focused is None:
            return False

        brut = _copied_value(
            AXUIElementCopyAttributeValue(
                focused, kAXSelectedTextRangeAttribute, None
            )
        )
        if brut is None:
            return False
        ok, plage = AXValueGetValue(brut, kAXValueCFRangeType, None)
        if not ok or plage is None:
            return False

        # Le curseur est à la fin de ce qu'on a inséré ; on remonte de
        # `count`. Si la position ne le permet pas, quelqu'un a déplacé le
        # curseur entre-temps : on s'abstient plutôt que d'écraser son texte.
        debut = plage.location - count
        if debut < 0:
            return False

        nouvelle = AXValueCreate(kAXValueCFRangeType, (debut, count))
        if nouvelle is None:
            return False
        if AXUIElementSetAttributeValue(
            focused, kAXSelectedTextRangeAttribute, nouvelle
        ) != 0:
            return False
        return (
            AXUIElementSetAttributeValue(focused, kAXSelectedTextAttribute, text) == 0
        )
    except (ImportError, AttributeError, TypeError, ValueError):
        logger.debug("AX range replacement unavailable", exc_info=True)
        return False


def accessibility_remediation() -> str:
    """Quoi autoriser, et où — vide si l'API répond déjà.

    Même piège que l'accès complet au disque : macOS attribue l'autorisation
    au binaire RÉSOLU, et le python d'un environnement virtuel est un lien
    symbolique. Autoriser le chemin qu'on a sous les yeux n'accorde donc
    rien, et rien ne le signale.
    """
    if accessibility_works():
        return ""
    lignes = [
        "L'accessibilité est refusée : la dictée ne peut pas écrire "
        "directement dans les applications (le collage prend le relais).",
        "",
        "Réglages Système → Confidentialité et sécurité → Accessibilité → "
        "« + », puis :",
    ]

    # L'enveloppe d'abord quand elle existe. macOS attribue l'autorisation au
    # processus RESPONSABLE, et l'agent launchd lance cette application, pas
    # l'interpréteur : autoriser python n'accorde alors rien, et rien ne le
    # signale. C'est cette enveloppe qui existe pour porter la permission.
    enveloppe = Path.home() / "Applications" / "Diapason Dictation.app"
    if enveloppe.exists():
        lignes += [
            f"  {enveloppe}",
            "",
            "C'est l'application qui lance la dictée : c'est elle que macOS "
            "regarde, pas l'interpréteur qu'elle démarre.",
        ]
    else:
        binaire = Path(sys.executable).resolve()
        lignes.append(f"  {binaire}")
        if binaire != Path(sys.executable):
            lignes.append(
                f"  (et non {sys.executable} : c'est un lien symbolique, "
                "macOS ne regarde que la cible)"
            )

    lignes += ["", "Puis : diapason dictate-service restart"]
    return "\n".join(lignes)


__all__ = [
    "accessibility_remediation",
    "accessibility_trusted",
    "accessibility_works",
    "insert_text",
    "replace_previous",
]
