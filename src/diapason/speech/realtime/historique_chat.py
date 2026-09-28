"""Le contexte écrit rejoint la voix sans devenir une instruction système."""

from __future__ import annotations


def lire_historique_chat(valeur: object) -> list[dict[str, str]]:
    """Valider les 16 messages que la séance vocale conserve déjà par tour."""
    if valeur is None:
        return []
    if not isinstance(valeur, list) or len(valeur) > 16:
        raise ValueError("L’historique vocal attend au plus 16 messages.")
    resultat = []
    taille = 0
    for message in valeur:
        if not isinstance(message, dict):
            raise ValueError("Message vocal invalide.")
        role, texte = message.get("role"), message.get("content")
        if role not in ("user", "assistant") or not isinstance(texte, str):
            raise ValueError("L’historique accepte seulement des échanges de texte.")
        taille += len(texte.encode("utf-8"))
        # 27/09/2026 : le contexte vient du client authentifié. Un Mio borne
        # la trame sans réduire la fenêtre normale des 16 messages vocaux.
        if taille > 1024 * 1024:
            raise ValueError("L’historique vocal dépasse un Mio.")
        if texte.strip():
            resultat.append({"role": role, "content": texte})
    return resultat
