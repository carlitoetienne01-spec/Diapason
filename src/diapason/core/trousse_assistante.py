"""La trousse unique du chat et de la voix.

29/09/2026 : deux listes vivaient côte à côte. Un outil du chat
(``mesh_devices``) manquait à la voix, et un geste de la voix
(``focus_app``, le partage d'écran) manquait au clavier.

Appelants : ``server/routes.py`` (``_chat_tooling``) et
``speech/realtime/tools.py`` (``list_voice_tool_ids``). Pas de route
nouvelle, pas de champ sur le fil.

``mesh_send`` choisit une action ouverte et un appareil d'après une
phrase transcrite : aucune confirmation ne dé-entend un mot mal pris.
``handoff_continue`` envoie l'écran courant sans cloche. Les deux
restent au chat.
"""

from __future__ import annotations

TROUSSE_ASSISTANTE: tuple[str, ...] = (
    "study",
    "current_time",
    "calendar_query",
    "vie_tasks",
    "vie_workspace",
    "vie_continuity",
    "vie_finances",
    "diapason_app",
    "diapason_app_delete",
    "vie_delete_task",
    "vie_delete_item",
    # memory_manage écrit dans ~/.diapason/MEMORY.md, que le constructeur de
    # prompt relit à chaque session : c'est le seul circuit de mémoire qui
    # boucle réellement. memory_search, memory_store et retrieval visent un
    # magasin vectoriel désactivé ([memory] enabled = false) et ne savent que
    # répondre « No memory backend configured » — trois outils qui coûtent du
    # préremplissage pour ne rendre que des échecs.
    "memory_manage",
    "user_profile_manage",
    # Le savoir personnel (Obsidian, Apple Notes, documents ingérés) était
    # indexé ET embarqué dans knowledge.db — mais seul le mode recherche
    # profonde y avait accès. Le chat le lit désormais aussi (23 août 2026).
    "knowledge_search",
    # Le dernier kilomètre (25/08/2026) : l'extrait de 300 caractères
    # remonte au document ENTIER — le corps complet est déjà dans l'index.
    "knowledge_get_document",
    # « J'ai reçu quoi ? » en direct — mails non lus, messages, agenda —
    # au lieu de réserver ce talent au brief du matin (Atlas, 24/08/2026).
    "digest_collect",
    "web_search",
    # 21/09/2026 : cinq extraits sur « premier ministre du Canada », aucun ne
    # nommait le titulaire ; la page du poste le dit. Lire une page entière
    # (texte principal, titre, date) est un outil, pas un tour de passe-passe
    # « une URL dans la requête » : le modèle peut le demander, et le code le
    # fait seul pour un titulaire (agentic_stream._lire_la_page).
    "web_read",
    "find_files",
    "open_anything",
    "app_search",
    "app_install",
    "notes_write",
    "reminders_write",
    "calendar_add",
    # Le chat rattrape la voix (Atlas, 24 août 2026) : musique, mails et
    # messages marchent aussi au clavier. Les envois passent par la cloche
    # d'approbation, comme partout.
    "spotify_play",
    "mail_compose",
    "messages_compose",
    "mail_send",
    "messages_send",
    # Le constat d'envoi (Atlas, 24/08/2026) : « c'est parti ? » se lit dans
    # chat.db au lieu de se deviner.
    "messages_status",
    # Les mains des connecteurs (Atlas, 25/08/2026) : chercher TOUT
    # l'historique Gmail en direct, archiver et corbeille sous cloche,
    # lire une conversation Messages. Les specs fantômes s'incarnent.
    "gmail_search",
    "mail_archive",
    "mail_trash",
    "imessage_conversation",
    # LA MAIN SUR LE MAILLAGE (Spatial Mesh, phase 0, 25/08/2026). Quatre
    # mille lignes de maillage vivaient sans poignée : les deux outils
    # étaient enregistrés et distribués à personne, et la documentation
    # affirmait pourtant que « le modèle voit deux outils ». « Ouvre mes
    # tâches sur mon PC » n'avait aucun chemin. L'absence côté VOIX reste
    # délibérée — mais plus pour la raison qu'on lisait ici : la voix passe
    # par ToolExecutor depuis le 22 août, donc par la cloche. La vraie
    # raison est que `mesh_send` choisit une action dans une énumération
    # ouverte et un appareil d'après une phrase TRANSCRITE, et qu'aucune
    # confirmation ne dé-entend un mot mal transcrit (test_voice_boundary).
    "mesh_devices",
    "mesh_send",
    # « Continue ce projet sur mon téléphone » (handoff, 25/08/2026) : part
    # de ce que l'interface affiche, au lieu d'exiger un identifiant que le
    # modèle n'a aucun moyen de connaître.
    "handoff_continue",
    # Et « envoie ÇA » — ce que la main tient (25/08/2026). Celui-ci est à
    # la voix aussi : il ne choisit ni l'objet (c'est la main) ni l'action
    # (elle découle du type), et devant une question en attente il tranche
    # dans une liste fermée que le serveur a mesurée.
    "geste_deposer",
    "screen_describe",
    # Le texte EXACT (OCR natif Apple) — zéro paraphrase, zéro Ollama
    # (Atlas, 24/08/2026).
    "screen_read_text",
    # Retrouver un onglet, ranger un fichier vers la corbeille — le
    # rangement passe par la cloche (Atlas, 24/08/2026).
    "browser_tabs",
    "file_trash",
    "calculator",
    # Les gestes d'une seconde (Atlas, 24 août 2026) : monter le son ou
    # mettre pause passait par shell_exec, donc par la cloche — un clic et
    # deux minutes d'attente pour un geste visible et réversible.
    "volume_control",
    "media_control",
    "clipboard_read",
    "screen_snap",
    "system_vitals",
    # 29/09/2026 : la voix les avait, le clavier non. Même pouvoir des
    # deux côtés ; la suppression passe par la cloche.
    "open_uri",
    "focus_app",
    "open_browser_on_monitor",
    "run_voice_command",
    "screen_share_start",
    "screen_share_stop",
    "screen_share_status",
    "vie_delete_continuity",
)

# Une transcription ne choisit pas une cible ouverte, et n'envoie pas
# l'écran sans cloche.
EXCLUS_DE_LA_VOIX: tuple[str, ...] = ("mesh_send", "handoff_continue")


def trousse_de_la_voix() -> tuple[str, ...]:
    exclus = set(EXCLUS_DE_LA_VOIX)
    return tuple(nom for nom in TROUSSE_ASSISTANTE if nom not in exclus)
