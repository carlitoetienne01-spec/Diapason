# Les actions éclair

Diapason exécute les commandes de bureau explicites et réversibles avant
d'aller chercher en mémoire et avant l'inférence du modèle. Le client de bureau
y consent avec `action_mode: "auto"` ; l'API compatible OpenAI, elle, garde les
actions sur la machine hôte désactivées par défaut.

## Les commandes prises en charge

- ouvrir une application, une URL ou une recherche web, ou lui donner le focus ;
- préparer un brouillon de courriel ou de message, sans l'envoyer ;
- écrire ou coller dans une application nommée, ou dans celle du premier plan ;
- produire le contenu demandé, puis l'insérer dans une application nommée ;
- déclencher les intentions média déjà en place, comme les recherches YouTube
  et Spotify.

Sur macOS, l'insertion de texte passe d'abord par l'API d'accessibilité, puis se
rabat sur un collage qui restaure ensuite tout le presse-papiers. Diapason
vérifie que l'application demandée est bien passée au premier plan, et n'appuie
jamais sur Entrée après avoir inséré du texte.

## La frontière de sécurité

Envoyer, supprimer, acheter ou payer, installer ou désinstaller, administrer,
redémarrer le système : aucune de ces opérations n'emprunte le chemin éclair.
Elles restent dans la chaîne de l'agent, avec contrôle des capacités et
confirmation. La saisie automatique de texte exclut par ailleurs Terminal, iTerm
et System Settings.

La configuration vit sous `[desktop.lightning]`. Couper `allow_type` ou
`allow_external_drafts` réduit encore la surface autorisée. Les métriques de
`GET /v1/actions/metrics` ne contiennent jamais de prompts, de texte saisi,
d'URL, de chemins ni d'applications visées.

Par défaut, les actions sur la machine hôte n'acceptent que les clients en
boucle locale, même quand une requête pose `action_mode: "auto"`. Ne pose
`allow_remote = true` que si l'API est solidement authentifiée et que le
pilotage du bureau à distance est voulu.

## Les performances

Ollama reçoit `keep_alive = "30m"` et est préchargé en arrière-plan. L'index des
applications macOS est gardé en cache pendant cinq minutes. Lance le banc
d'essai du routeur avec :

```bash
uv run python scripts/bench_lightning.py
```
