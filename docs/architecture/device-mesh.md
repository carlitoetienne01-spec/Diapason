# Le maillage d'appareils

Le maillage d'appareils laisse les appareils d'un même propriétaire agir l'un pour l'autre : *« ouvre mes tâches sur mon PC »*, tapé sur un portable, ouvre un écran sur le poste de bureau, et un rappel créé sur un Mac apparaît sur un téléphone.

C'est une **flotte d'un seul propriétaire**. Pas de serveur, pas de compte, aucune notion de partage entre personnes. Chaque appareil détient les mêmes données privées et la même autorité ; le maillage ne fait que porter l'intention de l'un à l'autre.

---

## Le modèle de confiance

Un appareil est dans la flotte ou il n'y est pas. Il n'existe pas d'appartenance partielle.

| Notion | Ce qu'elle veut dire |
|---|---|
| **Identifiant de propriétaire** | Nomme la flotte. Frappé une seule fois, propagé par l'appairage. Une commande qui porte un autre identifiant de propriétaire est refusée sans plus d'examen. |
| **Identifiant d'appareil** | `sha256(public_key)[:24]`, préfixé `dev_`. Dérivé, jamais affirmé — un appareil ne peut pas choisir son propre nom, au sens du protocole. |
| **Niveau de confiance** | `TRUSTED` une fois l'invitation consommée ; `REVOKED` après que l'utilisateur l'a retiré. La révocation est terminale : le seul retour en arrière est d'oublier entièrement l'appareil et de l'appairer à nouveau. |
| **Capacités** | Ce qu'on a le droit de lui demander. Toujours l'**intersection** de ce qu'il déclare et de ce que le plafond de sa plateforme autorise (`capabilities.py`), jamais l'union. |

L'appairage est mutuel et de courte durée. L'hôte frappe une invitation à usage unique (10 minutes) ; l'appareil qui rejoint la consomme avec sa clé publique, et reçoit dans la même réponse l'identité et l'adresse de l'hôte. Les deux côtés détiennent désormais la clé publique de l'autre, et c'est le seul justificatif dont le maillage se serve ensuite.

### Le plafond de la plateforme

`PLATFORM_CAPABILITIES`, dans `capabilities.py`, répond à la question « qu'est-ce que cette classe d'appareils pourrait honorer, ne serait-ce qu'en principe ». iOS, iPadOS et Android excluent l'automatisation de l'hôte et `desktop.open` ; `WEB` est client seulement ; une plateforme non reconnue retombe sur un plancher en lecture seule.

L'accès au système de fichiers n'est pas une question de plafond. Aucun verbe de ce vocabulaire ne l'accorde, sur aucune plateforme — `filesystem.workspace.read` / `.write` ont été retirés le 25 août 2026, sans qu'aucun client les ait jamais déclarés — et `FORBIDDEN_PARAMETER_NAMES`, dans `tools.py`, refuse structurellement un paramètre `path`. Le *transfert* de fichiers est un sous-système à part (`/v1/mesh/files`), avec sa propre session, gardé par une offre signée et un jeton de session plutôt que par une capacité.

C'est vérifié à chaque endroit où un appareil pourrait tenter d'élargir son propre droit — l'appairage, une déclaration explicite, une balise de présence, une relève — parce qu'un contrôle qui n'existe qu'à un seul de ces endroits est un contrôle que les autres finiront par contourner.

---

## Ce qu'on peut commander

Le catalogue distant est fermé et court (`tools.py`) :

| Outil | Effet | Politique hors ligne |
|---|---|---|
| `app.navigate` | Ouvre un écran désigné par une route `success://` | `REQUIRE_ONLINE` |
| `app.show_resource` | Affiche une tâche, un projet, une note ou une habitude | `QUEUE_UNTIL_EXPIRATION` |
| `app.open` | Met l'application au premier plan | `REQUIRE_ONLINE` |
| `notifications.show` | Affiche une notification | `QUEUE_UNTIL_EXPIRATION` |
| `desktop.open` | Ouvre une app, une URL, un fichier ou une recherche sur l'**ordinateur** visé | `REQUIRE_ONLINE` |

`desktop.open` est le seul verbe qui sort de l'application pour piloter le
**bureau**, et le seul dont la cible n'a pas de bornes. Deux conséquences,
tranchées toutes les deux le 25 août 2026 : il déclare `requires_confirmation`,
si bien que le récepteur refuse une enveloppe qui n'atteste pas l'accord de
l'utilisateur — c'est ce qui fait enfin du contrôle n° 10 de `verify_command` un
contrôle vivant plutôt qu'un contrôle documenté ; et il n'est **pas proposé au
modèle** (`_HORS_PORTEE_DU_MODELE` dans `tools/mesh_tools.py`), parce qu'une
phrase ne doit pas donner plus de pouvoir sur une machine lointaine que la même
phrase n'en donne ici.

Chaque outil déclare des paramètres typés, et un garde structurel refuse tout outil dont les paramètres portent un nom de passe-plat — `command`, `path`, `url`, `sql`, `script`, `eval` et les autres :

```python
FORBIDDEN_PARAMETER_NAMES = frozenset({
    "action", "command", "method", "code", "script",
    "sql", "query", "exec", "eval", "path", "url", "shell",
})
```

Ce qui compte n'est pas que les quatre outils d'aujourd'hui soient sûrs. C'est que le *prochain* outil ne puisse pas être, en douce, un shell déguisé.

---

## L'enveloppe de commande

Chaque commande est une enveloppe signée en Ed25519. `verify_command()` enchaîne onze contrôles dans un ordre voulu :

1. la version du protocole
2. le propriétaire — la même flotte
3. la destination — c'est bien à nous qu'elle s'adresse
4. l'origine — un appareil qu'on connaît, à qui on fait confiance, et dont on détient une clé
5. l'expiration, avec une tolérance d'horloge bornée dans les deux sens
6. la signature, sur l'enveloppe moins elle-même
7. l'outil existe dans le catalogue
8. les arguments correspondent à la forme déclarée par l'outil
9. les capacités — ce que **cet** appareil-ci peut honorer
10. la confirmation — un outil à conséquences ne tourne pas sans confirmation
11. **le nonce dépensé, en dernier**

L'ordre porte un sens. Les contrôles structurels, qui ne coûtent rien, passent en premier : une commande mal adressée n'atteint ainsi jamais la cryptographie. Le nonce est dépensé **en dernier** pour qu'une commande rejetée pour n'importe quelle autre raison ne brûle pas un nonce dont l'expéditeur légitime a encore besoin.

`NonceStore.spend()` se sert d'une insertion en `PRIMARY KEY` comme test atomique — deux livraisons concurrentes de la même commande ne peuvent pas réussir toutes les deux, puisqu'une seule insertion peut gagner.

---

## Deux transports

Le maillage doit atteindre deux sortes d'appareils très différentes, et une seule forme ne convient pas aux deux.

### La poussée — les ordinateurs

Une machine dont l'adresse est joignable est appelée directement : l'expéditeur POSTe l'enveloppe signée vers `POST /v1/mesh/commands/deliver`. C'est la latence la plus basse, et l'expéditeur apprend l'issue dans le même aller-retour.

L'adresse est apprise de l'appareil lui-même, et c'est une promesse : `local_address()` rapporte là où le processus écoute *réellement*, jamais une supposition tirée de la configuration. Un serveur lié à la boucle locale annonce la boucle locale, même si une adresse du réseau local aurait l'air plus utile — les pairs qui ne sont pas sur cette machine ne peuvent véritablement pas l'atteindre, et leur dire autre chose envoie des commandes dans le vide et les fait déclarer livrées.

### La relève — les téléphones et les tablettes

Succès Flutter tourne sur des appareils qu'on ne peut pas appeler : pas d'adresse stable, un NAT d'opérateur en travers du chemin, et un système d'exploitation qui suspend l'application dès que l'utilisateur regarde ailleurs. Le sens s'inverse. C'est l'appareil qui demande :

```
POST /v1/mesh/commands/poll   → { commands: [...enveloppes signées...] }
POST /v1/mesh/commands/ack    → ce qu'il en a fait
```

Deux conséquences en découlent, plutôt que d'y avoir été mises :

- **La relève est le battement de cœur.** Un appareil qui demande ses commandes a prouvé qu'il est éveillé mieux qu'aucune balise ne saurait le faire : la même requête enregistre donc la présence.
- **Une commande mise en attente n'est pas une commande ratée.** Un téléphone qui relève toutes les quelques secondes la ramasse en quelques secondes, donc `« elle n'a pas été effectuée »` serait un mensonge.

Un appareil est traité en mode relève quand il nous l'a *dit* en relevant (`transport == "pull"`), jamais par déduction depuis l'absence d'adresse — un poste de bureau qui ne s'est simplement pas encore annoncé n'a pas d'adresse non plus, et lui ne viendra jamais chercher quoi que ce soit.

---

## La présence

La présence est **dérivée, jamais rangée comme un état**. `presence_of()` lit l'horodatage de dernière vue et rend l'un de quatre états :

| État | Âge du dernier contact |
|---|---|
| `ONLINE` | ≤ 45 s |
| `IDLE` | ≤ 5 min |
| `BACKGROUND` | ≤ 30 min |
| `OFFLINE` | au-delà, ou révoqué |

Un appareil révoqué est `OFFLINE`, si récemment qu'on l'ait vu.

Les appareils s'annoncent avec le même justificatif que celui qui leur sert à commander — une signature Ed25519 — parce qu'un appareil qui rejoint la flotte ne détient jamais la clé d'API de cette machine. Le rejeu est arrêté par la **monotonie** plutôt que par des nonces : une balise doit être strictement plus récente que la dernière acceptée. Un battement de cœur toutes les quinze secondes frapperait 5 760 nonces par appareil et par jour pour protéger un message dont tout le contenu est « je suis toujours là » ; un seul entier par appareil refuse la même attaque pour rien.

---

## Le contrat d'honnêteté

La règle pour laquelle tout le système existe :

> Une commande qui n'a fait que se mettre en attente ne doit jamais être annoncée comme faite.

Chaque statut terminal porte une phrase française vraie de ce statut-là et d'aucun autre, et `dispatch.py` est délibérément le seul endroit qui décide de ce qu'on dit à l'utilisateur.

| Situation | Ce que l'utilisateur lit |
|---|---|
| Livrée et exécutée | *« C'est fait. »* |
| Appareil endormi, l'outil le veut éveillé | *« … est hors ligne : cette action demande un appareil actif, elle n'a pas été effectuée. »* |
| Appareil éveillé mais injoignable sur le réseau | *« … n'a pas pu être joint : … »* |
| Appareil endormi, l'outil peut attendre | *« … est hors ligne : la commande est en attente et partira dès son retour. »* |
| Appareil en relève, éveillé | *« C'est prêt pour … : l'appareil le récupérera dans quelques secondes. »* |
| Appareil en relève, endormi | *« … : l'appareil le récupérera à son réveil. »* |

Ces distinctions ne sont pas décoratives. « Hors ligne » et « injoignable » appellent de l'utilisateur deux choses différentes — attendre, ou aller vérifier le réseau — et s'entendre dire la mauvaise, c'est perdre son temps sur la mauvaise machine.

---

## La frontière de sécurité

### Les routes hors du mur de la clé d'API

Cinq routes sont joignables sans la clé d'API locale, parce que l'appareil qui les appelle ne l'a jamais eue :

| Route | Justificatif |
|---|---|
| `POST /v1/mesh/pairings/redeem` | l'invitation à usage unique |
| `POST /v1/mesh/commands/deliver` | signature Ed25519 sur l'enveloppe |
| `POST /v1/mesh/presence` | signature Ed25519 sur la balise |
| `POST /v1/mesh/commands/poll` | signature Ed25519 sur la relève |
| `POST /v1/mesh/commands/ack` | signature Ed25519 sur les résultats |

Une signature prouve plus qu'un secret partagé ne le ferait : elle dit *quel* appareil, et elle lie le contenu exact. Les sept contrôles communs aux quatre dernières vivent au même endroit (`signed.py`), pour qu'il n'y ait qu'une seule copie à réussir.

### L'exemption du mode local seul

Le mode `local_only` de Diapason est en échec fermé : rien ne quitte la machine. Le maillage tient une exemption, documentée, et ses deux moitiés sont exigées :

```python
if (device or {}).get("trustLevel") != "TRUSTED":
    raise LocalOnlyError(...)
if not address_is_private(address):
    raise LocalOnlyError(...)
```

Un appareil appairé et de confiance, à une adresse privée, c'est l'autre ordinateur de l'utilisateur, pas « ailleurs ». Tout ce qui manque l'une ou l'autre moitié est refusé exactement comme avant. `mesh/transport.py` et `mesh/beacon.py` sont listés dans `tests/privacy/outbound_manifest.txt`, et le test à cliquet échoue dans les deux sens si cela cesse d'être vrai.

### Ce que l'assistant peut faire

L'assistant de discussion voit deux outils, séparés à dessein : `mesh_devices` ne fait que regarder, `mesh_send` agit. Tous les deux sont entrés dans `_TROUSSE_ASSISTANT` le 25 août 2026 — jusque-là, ce paragraphe décrivait une intention, pas le code : les outils étaient enregistrés et remis à personne, si bien que « ouvre mes tâches sur mon PC » n'avait aucun chemin du tout. Un test garde maintenant leur présence, en miroir de celui qui garde leur absence dans la voix.

`mesh_send` déclare `risk: "outward_action"`. Il n'est **pas** dans la liste d'autorisation de la voix en direct (`speech/realtime/tools.py`), parce que ce chemin-là exécute ses outils directement plutôt que par `ToolExecutor`, où vit le système d'approbation. Un test-fusible impose cela, et dit quand se supprimer lui-même.

---

## Les limites connues

- **Le serveur se lie à `127.0.0.1` par défaut**, donc le maillage ne franchit pas encore les machines sans que l'utilisateur ouvre l'interface réseau. C'est une décision de sécurité, et elle lui appartient.
- **`execute_voice_tool` court-circuite `ToolExecutor`**, et donc les approbations. Il faut corriger cela avant d'exposer le moindre outil `remote.*` au chemin de la voix.
- **La file d'attente de la boîte de réception vit en mémoire, dans le processus**, plafonnée à 16 entrées. Un redémarrage du backend perd tout ce qui attendait d'être ramassé par le shell du bureau.
- **Rejoindre est à sens unique dans l'interface.** L'hôte peut frapper une
  invitation depuis la page Appareils ; rien là-bas n'en consomme une. Le chemin
  de l'invité vit dans la CLI (`diapason mesh join <address> <code>`) et dans
  `mesh/join.py`. Avant le 25 août 2026, il n'existait pas du tout dans ce
  dépôt, et c'est pourquoi les seuls pairs appairés avaient été créés par le
  client Flutter.
- **Il n'y a pas de transfert de fichiers.** C'est un maillage de *commandes* :
  des enveloppes signées, sans état, de courte vie. Un transfert reprenable
  demande un cycle de vie de session que ni `commands.py` ni `queue.py` ne
  porte — et il ne faut pas le boulonner sur l'enveloppe de commande, puisque
  ajouter un champ signé casse tous les téléphones déjà sur le terrain.
- **Les enveloppes sont signées, pas chiffrées.** Sur un réseau local de
  confiance, cela suffit ; cela cesse de suffire le jour où un relais existe.

---

## Les fichiers

| Module | Responsabilité |
|---|---|
| `identity.py` | les clés, l'identifiant d'appareil, les octets canoniques, la signature des enveloppes |
| `registry.py` | les appareils appairés, les invitations, la confiance, la révocation |
| `capabilities.py` | le plafond de la plateforme |
| `presence.py` | la présence dérivée |
| `commands.py` | l'enveloppe, ses onze contrôles, les nonces |
| `tools.py` | le catalogue distant, fermé |
| `queue.py` | la file d'attente durable des commandes |
| `transport.py` | la livraison sur le réseau local, et l'exemption du mode local seul |
| `beacon.py` | la présence sortante et entrante |
| `pull.py` | la relève et l'accusé de réception, pour les appareils qui viennent chercher |
| `signed.py` | les sept contrôles partagés par les requêtes signées par un appareil |
| `dispatch.py` | l'envoi, et ce qu'on dit à l'utilisateur |
| `executor.py` | l'exécution ici d'une commande vérifiée |
| `resolver.py` | *« sur mon PC »* → un identifiant d'appareil, ou une question |
| `routes.py` | la surface HTTP |
