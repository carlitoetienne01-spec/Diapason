# L'accès au système

Comment donner à un agent l'accès à la machine où il tourne, et où sont les
vraies limites.

!!! warning
    `shell_exec` lance des commandes arbitraires sous ton compte. Il n'y a ni
    liste d'autorisation, ni liste d'interdiction, ni bac à sable tant que tu
    n'en actives pas un. Un agent qui tient cet outil peut tout ce que tu peux
    faire depuis un terminal.

---

## Commence ici : tu n'as probablement aucun outil activé

Si l'agent te dit qu'il ne peut pas lancer de commandes ni lire de fichiers, ce
n'est en général pas un problème de permissions. C'est qu'aucun outil n'a été
activé au départ.

Les outils viennent de `tools.enabled`, à défaut de `agent.tools`. Les deux sont
vides par défaut, et une valeur vide construit l'agent avec **zéro outil**. Rien
n'est activé par défaut.

Commence par vérifier que tu as bien un fichier de configuration :

```bash
cat ~/.diapason/config.toml
```

S'il n'est pas là, tu as ta réponse. Crée-le :

```toml
[engine]
default = "ollama"

[intelligence]
default_model = "qwen3.5:9b"

[agent]
default_agent = "orchestrator"

[tools]
enabled = ["shell_exec", "file_read", "file_write", "think"]
```

Une version plus complète existe dans
`configs/diapason/examples/full-system-access.toml`.

Vérifie ensuite que la liste s'est bien résolue :

```bash
python -c "from diapason.core.config import load_config; print(load_config().tools.enabled)"
```

---

## Ce que les outils atteignent

| Outil | Portée |
|------|-------|
| `shell_exec` | N'importe quelle commande, sous ton compte. Délai d'attente de 30 s par défaut, 300 s au maximum, sortie plafonnée à 100 Ko par flux. |
| `file_read` | N'importe quel chemin lisible. Plafond de 1 Mo. |
| `file_write` | N'importe quel chemin où l'on peut écrire. Plafond de 10 Mo, peut créer les dossiers parents. |
| `apply_patch` | Applique des diffs unifiés à n'importe quel chemin. |
| `code_interpreter` | Du Python dans un sous-processus, derrière une liste d'interdiction de motifs grossière. |

`file_read` et `file_write` prennent un argument `allowed_dirs` qui les borne à
un ensemble de dossiers, mais aucune clé de configuration ne le remplit. Quand il
est vide, tous les chemins passent. Si tu veux aujourd'hui une prison de système
de fichiers, sers-toi du bac à sable en conteneur plutôt que de compter sur ces
outils pour en tenir une.

### Les noms de fichiers sensibles

`file_read` et `file_write` refusent les noms qui collent à une courte liste de
motifs : `.env`, `*.pem`, `id_rsa`, `credentials.*` et une douzaine d'autres. La
comparaison porte sur le nom du fichier seul, pas sur le chemin ni sur le
contenu, et seuls ces deux outils la consultent. `shell_exec`, `apply_patch` et
`code_interpreter` la sautent complètement : un `cat ~/.ssh/id_rsa` passé par
`shell_exec` fonctionne très bien. Vois-y une protection contre les doigts qui
ripent, pas une frontière de sécurité.

---

## Le comportement de confirmation

`shell_exec`, `git_commit` et `agent_kill` sont marqués `requires_confirmation`.
Ce que cela donne dépend entièrement de la façon dont tu as lancé l'agent :

| Point d'entrée | Comportement |
|-------------|-----------|
| `diapason chat` | Demande avant chaque appel. |
| `diapason ask` | Approuve tout seul. |
| `diapason agent ask` | Approuve tout seul. Passe `--no-yes` si tu veux qu'il demande. |
| Serveur HTTP, app de bureau | Approuve tout seul. Les outils que tu as ajoutés à la trousse d'un agent comptent comme approuvés d'avance. |
| Intégré via `SystemBuilder` | Aucun rappel n'est branché : ces outils échouent en se fermant. |

C'est la dernière ligne qui attrape du monde. Si `shell_exec` rend
« requires confirmation but no confirmation callback is available », c'est que tu
construis l'agent toi-même et qu'il te faut passer un `confirm_callback`.

!!! note "`enforce_tool_confirmation` ne fait rien"
    Le chargeur de configuration accepte `security.enforce_tool_confirmation`,
    mais rien sur le chemin d'exécution des outils ne le lit. La poser ne
    changera le comportement de confirmation nulle part. Fie-toi plutôt au
    tableau ci-dessus.

---

## macOS : l'accès complet au disque

Sur macOS, la vraie frontière est le système d'exploitation, pas la
configuration. L'accès au shell et l'accès ordinaire aux fichiers se mettent à
marcher dès que tu actives les outils. Les données protégées par TCC, non :
Messages, Mail, Photos, l'historique de Safari, Contacts et Calendrier restent
verrouillés, et aucune clé de configuration n'y changera rien.

Donne l'accès complet au disque au processus qui héberge le serveur, quel qu'il
soit. Les processus fils en héritent :

| Comment tu lances Diapason | Donne l'accès à |
|------------------------|-----------------|
| La CLI (`diapason ask`, `diapason chat`) | Ton terminal (Terminal, iTerm, Warp) |
| L'app de bureau | `Diapason.app`, qui lance `diapason serve` sous elle |
| launchd (`deploy/launchd/com.diapason.serve.plist`) | Le binaire `diapason`, comme sa propre entrée |

Réglages Système, puis Confidentialité et sécurité, puis Accès complet au
disque, puis **+**.

Un démon launchd a son propre contexte TCC : donner l'accès au Terminal ne lui
sert à rien. Ajoute `/usr/local/bin/diapason` à part.

Pour vérifier que l'autorisation a bien pris :

```bash
head -c 16 ~/Library/Messages/chat.db >/dev/null 2>&1 \
  && echo "accordé" || echo "refusé"
```

Redémarre le processus hôte après avoir changé le réglage.

### Piloter les apps du Mac

AppleScript passe par `shell_exec` :

```
osascript -e 'tell application "Music" to play'
```

macOS demande l'autorisation d'automatisation une fois par app visée, la
première fois que tu y touches.

---

## Ce que tu ne peux pas faire

Il n'y a pas d'usage général de l'ordinateur : Diapason ne bouge pas le
pointeur, et il n'envoie de frappes clavier que là où tu le lui as demandé (le
collage de la dictée, `paste_to_frontmost`).

Il *peut* regarder, et tu dois savoir exactement jusqu'où :

- **L'état du bureau** — l'app au premier plan, les apps qui tournent, le titre
  de la fenêtre de devant et, quand un navigateur est devant, le titre de son
  onglet actif. Un seul passage AppleScript par System Events, gardé en cache
  quelques secondes, et il voyage dans le contexte du modèle à chaque tour.
- **L'écran lui-même** — `screen_describe` prend une capture et l'envoie à un
  modèle de vision *local*, et seulement après que tu as autorisé la capture.
  C'est éteint tant que tu n'as pas posé `[desktop.vision] enabled = true`.

Les deux restent sur la machine. Un titre de fenêtre peut en dire long (le nom
d'un document, l'objet d'un message) : si c'est plus que ce que tu veux, coupe
`[desktop.vision]` et regarde `[privacy] local_only`.

Les actions `click` et `type` que tu croiseras sont celles de Playwright,
bornées à une page de navigateur et non au bureau.

Une partie de tout ça est atteignable par `shell_exec` si tu apportes
l'outillage toi-même. `screencapture` prendra des captures une fois
l'enregistrement de l'écran accordé, et quelque chose comme `cliclick` bougera
le pointeur. Ça te donne des actions scriptées. Ça ne te donne pas un agent qui
regarde l'écran et trouve tout seul où cliquer.

---

## Restreindre l'accès

L'accès s'élargit et se restreint par `tools.enabled`. Retire des entrées pour
enlever des capacités. Cette liste, c'est tout ce qui est accordé.

Deux contrôles d'isolation supplémentaires existent. Les capacités sont actives
et refusent par défaut ; l'isolation en conteneur, elle, reste un choix de
déploiement explicite :

```toml
[sandbox]
enabled = true          # lance les outils dans un conteneur (sur demande)
runtime = "docker"

[security.capabilities]
enabled = true          # RBAC sur les capacités d'outils déclarées (défaut)
default_deny = true     # les capacités non appariées sont refusées (défaut)
policy_path = "~/.diapason/policy.json"
```

Quand aucun fichier de politique d'administrateur n'est fourni, Diapason
n'accorde que les capacités déclarées par les outils explicitement choisis pour
cet agent. Une politique fournie par un administrateur n'est jamais élargie
automatiquement.

Pour tout ce qui n'est pas de confiance, prends `docker_shell_exec` et
`code_interpreter_docker` plutôt que leurs versions côté hôte.

---

## Voir aussi

- [La sécurité](security.md) — les scanners, le journal d'audit et les garde-fous
- [Les outils](tools.md) — le registre complet
- [L'assistant de code](code-assistant.md) — une installation plus étroite, avec le shell activé
- [Les serveurs MCP externes](mcp-external-servers.md) — les capacités que Diapason ne livre pas
