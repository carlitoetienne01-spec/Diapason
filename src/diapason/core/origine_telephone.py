"""Ce qui est demandé depuis le téléphone, et ce que cela peut faire du Mac.

26/09/2026, phase 2 du plan mobile (docs/development/diapason-mobile.md).
La passerelle du tailnet (``server/passerelle_tailnet.py``) refusait
``/v1/context/*``, ``/v1/screen_share/*`` et ``/v1/actions/*`` au
téléphone — mais elle laissait passer la Discussion, et la trousse du chat
porte ``screen_read_text``, ``screen_describe``, ``screen_snap`` et
``clipboard_read`` SANS confirmation, plus ``open_anything``,
``app_install``, ``file_trash``, ``mail_send`` sous une cloche que le
téléphone peut sonner et approuver lui-même. « Lis mon écran » depuis le
téléphone rendait le texte de l'écran du Mac : le refus des routes était
décoratif, et la décision « aucune action sur le Mac depuis la Discussion
du téléphone avant la phase 6 » contournée.

La route ne suffit pas quand une route permise porte elle-même tous les
pouvoirs. Le plafond descend donc jusqu'à l'exécuteur d'outils, par une
variable de contexte :

- seule la passerelle la pose, autour de l'application qu'elle sert — c'est
  le SOCKET d'arrivée qui dit « téléphone », jamais un en-tête ;
- elle suit la requête là où asyncio et Starlette copient le contexte :
  sous-tâches, ``asyncio.to_thread``, routes ``def`` servies dans un fil,
  générateurs des réponses en flux ;
- ``ToolExecutor.execute`` refuse tout outil absent de
  :data:`OUTILS_DU_TELEPHONE` quand elle est posée. Une liste
  d'AUTORISATION, comme les routes : un outil ajouté demain reste fermé au
  téléphone tant que personne n'a décidé qu'il s'ouvre.

Ce que la variable n'atteint PAS : un ``threading.Thread`` lancé à nu (il
ne copie aucun contexte). Les routes qui confient un agent à un tel fil
(``/v1/managed-agents/*/run`` et voisines) sont donc refusées au téléphone
dans ``server/portee_tailnet.py``, pas seulement filtrées ici.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

__all__ = [
    "OUTILS_DU_TELEPHONE",
    "MOTIF_OUTIL_REFUSE",
    "MOTIF_OPERATION_REFUSEE",
    "depuis_le_telephone",
    "marquer_le_telephone",
    "outil_permis_au_telephone",
]

_DEPUIS_LE_TELEPHONE: ContextVar[bool] = ContextVar(
    "diapason_depuis_le_telephone", default=False
)

# Ce qui lit ou écrit des DONNÉES — tâches, agenda, mémoire, savoir, web — et
# rien qui lise l'écran, le presse-papiers ou l'état du Mac, ni qui y ouvre,
# installe, jette, envoie ou pilote quoi que ce soit (décidé le 25/09/2026 :
# actions sur le Mac depuis la Discussion du téléphone refusées jusqu'à la
# phase 6). Écartés aussi, faute de décision : digest_collect, gmail_search,
# imessage_conversation et messages_status (le courrier et les messages lus
# dans les bases du Mac), find_files (les noms de fichiers du disque),
# notes_write, reminders_write et calendar_add (qui passent par les apps du
# Mac), mesh_devices et mesh_send (le plan de contrôle du maillage, déjà
# refusé en route). La phase 6 les rouvrira un par un.
#
# diapason_app et diapason_app_delete n'y sont pas non plus. Le jour où la
# phase 6 les y mettra pour leurs données, les opérations navigate et
# current_view de diapason_app (piloter la fenêtre du Mac, lire ce qu'elle
# affiche) resteront refusées : l'outil le décide lui-même, opération par
# opération (tools/diapason_app.py, revue de sécurité du 28/09/2026).
OUTILS_DU_TELEPHONE: frozenset[str] = frozenset(
    {
        "current_time",
        "calculator",
        "calendar_query",
        "vie_tasks",
        "vie_workspace",
        "vie_continuity",
        "vie_finances",
        "vie_delete_task",
        "vie_delete_item",
        "vie_delete_continuity",
        "memory_manage",
        "user_profile_manage",
        "knowledge_search",
        "knowledge_get_document",
        "web_search",
        "web_read",
    }
)

MOTIF_OUTIL_REFUSE = (
    "L'outil « {nom} » agit sur le Mac ou lit son écran : il n'est pas "
    "permis depuis le téléphone (phase 6 du plan mobile). Dis-le à "
    "l'utilisateur au lieu d'inventer un résultat."
)

# Le même refus, un cran plus fin : pour un outil permis au téléphone qui
# porte sous un seul nom des données ET une action sur le Mac.
MOTIF_OPERATION_REFUSEE = (
    "L'opération « {operation} » de l'outil « {nom} » n'est pas permise "
    "depuis le téléphone : seules les opérations sur les données de Diapason "
    "le sont, rien qui pilote la fenêtre du Mac ou lise ce qu'elle affiche "
    "(phase 6 du plan mobile). Dis-le à l'utilisateur au lieu d'inventer un "
    "résultat."
)


def depuis_le_telephone() -> bool:
    """Vrai pendant une requête servie par la passerelle du tailnet."""
    return _DEPUIS_LE_TELEPHONE.get()


@contextmanager
def marquer_le_telephone() -> Iterator[None]:
    """À poser par la passerelle SEULE, autour de l'application qu'elle sert."""
    jeton = _DEPUIS_LE_TELEPHONE.set(True)
    try:
        yield
    finally:
        _DEPUIS_LE_TELEPHONE.reset(jeton)


def outil_permis_au_telephone(nom: str) -> bool:
    """*nom* doit déjà être canonique (``nom_canonique``)."""
    return nom in OUTILS_DU_TELEPHONE
