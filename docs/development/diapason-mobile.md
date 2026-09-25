# Diapason mobile — Succès devient Diapason

Décidé le 25/09/2026 par Carlito, question par question. Ce document est le
point d'entrée du chantier : ce qui a été décidé, pourquoi, ce qu'on a trouvé
en regardant, et dans quel ordre on avance. Ce qui est fait y est **barré**,
pas effacé.

## 1. Ce qu'on a trouvé avant de décider

L'inventaire du 25/09/2026, fait en lecture seule sur les deux dépôts, a
contredit la documentation sur quatre points :

1. **Il existait deux Succès aux données séparées.** L'app Flutter
   synchronisait sa Life OS avec le site PHP (`carlitoportfolio.com/
   lifeos-api.php`, blob `lifeos_v1` de 13 clés) et son assistant « L'Entité »
   passait par `assistant-api.php`. Le Succès du bureau vit dans
   `~/.diapason/succes.db`, derrière 100 routes `/v1/succes`. Le Dart n'en
   appelait **aucune**, alors que `docs/succes-client-mobile.md` disait
   « 73 routes, ce que l'application mobile appelle ».
2. **Le lien téléphone ↔ Mac était probablement rompu depuis fin août.** Le
   Dart vise le port 8000 par défaut ; depuis le 26 août (49d45ae), 8000
   n'écoute plus que 127.0.0.1 et le réseau local n'a que les 9 portes du
   maillage sur 8001. Le téléphone a été vu pour la dernière fois le 18 août.
3. **La télécommande était refusée depuis le 25 août** (921acb9) : elle envoie
   `desktop.open` sans confirmation, que le contrôle n°10 exige désormais.
4. **Hors de la maison, rien ne marchait**, et `app_config.dart` portait en
   clair un mot de passe admin et un jeton de synchronisation.

Et un ordre de grandeur : le bureau pèse ~85 000 lignes de React. Tout
réécrire en Dart aurait pris des mois et laissé deux copies à maintenir.

## 2. Les décisions

| Sujet | Décision |
|---|---|
| Architecture | **Hybride** : coquille Flutter native (notifications, appairage, caméra, micro, verrou) + le vrai bundle React dans une WebView. Précédent : le mini-panneau charge déjà ce bundle à 340 px. |
| Réseau | **Partout via Tailscale** (Mac et téléphone). Le téléphone prouve son identité par une **clé d'appareil délivrée à l'appairage, révocable** — jamais par une copie de la clé d'API locale, secret partagé et extractible. |
| Données | Celles du Mac. **Import unique** des 13 clés Life OS du site PHP, puis l'app n'utilise plus le PHP. |
| Renommage | **Absolument tout.** Nom affiché « Diapason », identifiant `com.diapason.mobile` (variante `com.diapason.mobile.dev`, « Diapason dev »), paquet Dart `diapason_mobile`. Dans Diapason, le domaine interne `succes` devient **`vie`** : `/v1/vie`, `src/diapason/vie/`, `~/.diapason/vie.db`, `frontend/src/features/vie/`. À l'écran, le groupe de navigation « Succès » s'intitule **« Diapason »**. |
| Dossier | `~/Desktop/Porfolio/Succes` déménage vers **`~/Projets/diapason_mobile`**. |
| Logo | Icône : la tuile noire (`assets/branding/diapason-icon-1024.png`), identique au Dock. Écran de lancement et premier plan de l'icône adaptative Android : le diapason seul (`assets/branding/diapason-logo-source.png`) sur fond noir. |
| L'Entité | Remplacée par la Discussion Diapason. |
| Thème | Nocturne, neumorphisme et écrans de démo disparaissent ; les 7 apparences du bureau. |
| Plateformes | Android d'abord ; les squelettes web, macOS, Windows et Linux de l'app Flutter sont retirés. |
| Voix | Celle du Mac (Whisper + Kokoro, micro du téléphone par WebSocket), armée à la main, coupée seule (§78). |
| Fonctions propres au Mac | Pilotées à distance depuis le téléphone, jamais exécutées dessus. |
| Ajouts mobiles | Appareil photo → piles de photos ; « Partager vers Diapason » ; notifications (rappels, approbations) ; verrou biométrique. |
| Nettoyage | Firebase retiré ; secrets en clair retirés. |
| Portfolio | Outil personnel : pas de mode démo. Sans Mac joignable, l'app le dit. |

## 3. L'ordre

### Phase 1 — Fondations

**1a. Côté mobile** (ne touche Diapason que pour les chemins) — **fait le
25/09/2026**, onze commits de `9bcd5a2` à `2bb080b` dans `diapason_mobile` :

- ~~déménager le dépôt vers `~/Projets/diapason_mobile` et corriger les chemins
  codés en dur dans Diapason (`scripts/gen_canonical_vectors.py`,
  `tests/contract/test_succes_client_contract.py`,
  `tests/contract/test_mesh_client_contract.py`) ; le test des vecteurs
  **échoue** si le dépôt manque hors CI, au lieu de se sauter en silence~~ ;
- ~~identifiant, paquet Dart, libellés, logo, écran de lancement~~ ;
- ~~retirer Firebase (son `google-services.json` ne déclare que l'ancien
  identifiant : le garder casserait la construction), les secrets en clair
  (sortis vers un fichier local non suivi, lu à la construction : la
  synchronisation PHP doit survivre jusqu'à l'import de la phase 3, sinon ce
  que le téléphone écrit entre-temps serait perdu), les trois démos, le code
  mort et les plateformes inutiles~~.

Ce que la phase 1a a appris, et qui reste vrai :

- **Les secrets quittent le dépôt, pas l'APK.** Ils sont dans
  `config/secrets.json` (ignoré), compilés dans chaque construction faite par
  `tool/flutter_avec_secrets.sh`, et présents dans les 15 commits de
  `cfc5869` à `88a92b6`. Seule une **rotation côté site** les protège ; à
  faire une fois l'import de la phase 3 passé.
- **Sans jeton, l'app envoyait quand même tout l'état au site** en cochant une
  habitude, en affichant « tes données ne partent pas ». La garde vit
  désormais dans `NetClient._send`, avant tout envoi ; un jeton refusé
  (401/403) arrête la synchronisation et le dit, au lieu de rendre l'app
  muette.
- **`_bootstrapFromServer` remplace l'état local par celui du site.** Ce qui a
  été écrit pendant une synchronisation non configurée ou refusée est écrasé
  au premier lancement qui a le bon jeton. Non corrigé : ce code part en
  phase 3.
- Gradle hors de `flutter` exige
  `JAVA_HOME="/Applications/Android Studio.app/Contents/jbr/Contents/Home"`.
  Les variantes release et profile demandent des artefacts absents du cache
  hors ligne ; un `flutter build` sans `--no-pub` interroge pub.dev.

L'Entité et Nocturne restent jusqu'à la phase 3 : les retirer avant que la
Discussion Diapason n'arrive laisserait le téléphone sans assistant.

**Changer l'identifiant crée une AUTRE app.** L'ancienne « Succès » et la
nouvelle « Diapason » coexistent sur le téléphone ; l'appairage est à refaire,
et l'ancien « Mon téléphone » est à oublier depuis la page Appareils.
**Avant de désinstaller l'ancienne, s'assurer qu'elle a synchronisé avec le
site PHP.**

**1b. Côté Diapason : `succes` → `vie`** (après que le point 5 des comptes est
commité, parce qu'il touche `server/app.py`). Ce que l'inventaire a relevé et
qui ne doit pas casser en silence :

- le fichier `~/.diapason/succes.db` se renomme au démarrage, avec ses
  `-wal`/`-shm`, jamais pendant qu'une connexion est ouverte ;
- les **identifiants d'outils** `succes_*` sont enregistrés dans des agents
  sauvegardés : un agent dont la liste cite un outil disparu en perd un, sans
  erreur. Il faut des alias ou une migration de ces listes ;
- le schéma `success://` voyage dans des commandes **signées** (`app.navigate`)
  et est codé en dur dans `executor.py`, `mesh_tools.py`, `gestes_routes.py`,
  `features/mesh/routes.ts` et le Dart : période où les deux sont acceptés.
  `diapason://` est déjà le lien profond OAuth de Tauri : vérifier qu'une
  route de navigation n'y est jamais confondue ;
- les routes `/v1/succes/sync/pair` et `/exchange` servent la synchro entre
  instances Diapason : un pair plus ancien (pc-bureau) les appelle encore ;
- les clés `localStorage` et les routes React `/succes/*`, la réglette
  (`lib.rs`, `reglette.html`) ;
- l'instantané `tests/contract/succes_api_surface.json` et son générateur ;
- CLAUDE.md (§1, §4) puis AGENTS.md, la mémoire, `docs/succes-client-mobile.md`.

### Phase 2 — Joindre le Mac

Tailscale sur le Mac et le téléphone (**installation faite par Carlito**).
Le serveur accepte l'app complète sur l'interface Tailscale, et seulement
avec une clé d'appareil ; CORS, CSP et `Permissions-Policy: microphone`
s'ouvrent pour l'origine de la WebView et elle seule. Réparer l'appairage
(port) et la télécommande (confirmation côté Mac : la phrase vient du
récepteur, §100).

### Phase 3 — La WebView

Le bundle est **servi par le Mac** plutôt qu'embarqué : il reste ainsi à la
version exacte du serveur qui lui répond. La Discussion remplace l'Entité ;
les pages de vie arrivent avec l'import PHP (les 13 clés, pas seulement
tâches et projets comme `/import/legacy` aujourd'hui) ; les commandes Tauri
dont les pages dépendent deviennent des routes, ou leur absence se dit.
Nocturne disparaît ; la coquille suit l'apparence choisie dans la WebView.

### Phase 4 — La voix

### Phase 5 — Photo, partage, notifications, verrou

### Phase 6 — Télécommande des fonctions du Mac
