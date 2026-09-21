# Diagnostic et plan d’optimisation de Diapason

19 septembre 2026 — Mac de Carlito, branche `main`, HEAD `0d4c3d6`, avec les
corrections locales de copie enrichie et de réponses longues encore non commitées.

**Statut : lots 1 à 7 traités localement le 19 septembre 2026, dans le périmètre détaillé ci-dessous.** Le diagnostic
initial ci-dessous est conservé ; les bilans suivent cette introduction.
Les étapes restantes ne sont pas présentées comme livrées. Les essais n’ont
pas enregistré de nouveaux messages dans les discussions.

## Suite du 20 septembre 2026 — ce que les lots n'avaient pas vu

Deux tours réels du matin, télémétrie des messages et journal d'Ollama :

| Tour | Modèle | Total | Premier texte | Passages Ollama |
|---|---|---:|---:|---|
| « Qui est le président actuel d'Haïti ? » | qwen3.8:27b-mlx | 56,6 s | 47,5 s | 37,4 s (décide `web_search`) + 18,0 s |
| « Que veut dire "Self Aware" en français ? » | qwen3.8:27b-mlx | 89,4 s | **88,3 s** | 53,2 s + 36,2 s |
| « Ouvre moi Youtube et joue la musique Self Away » | voie éclair, sans modèle | 1,2 s | 1,1 s | aucun |

Trois causes, trois réponses, dans l'ordre des commits :

1. **La relecture du lot 3 se déclenchait sur une traduction.** Le premier
   passage avait répondu juste, sans outil ; la règle l'a retenu et rejoué
   avec les 44 schémas — préfixe différent, contexte entièrement retraité.
   Elle s'était armée parce que la demande précédente parlait de musique et
   qu'un `web_search` traînait trois échanges plus haut. Trois règles
   remplacent « trousse réduite = relecture » (`trousse_chat.py`) : seule
   une demande **reconnue** (un mot d'une famille, hors mots de temps seuls)
   ou une réponse autonome (explique, traduis, que veut dire…) diffère les
   schémas — une demande inconnue, même courte après une action, garde les
   44 ; la relecture n'est armée que si la demande courante parle de données
   à LIRE (tâches, notes, agenda, web, mails, messages, écran, fichiers,
   onglets, appareils — les mots, pas les outils amorcés : « ouvre » et
   « onglets » amorcent le même outil) ; un suivi court n'hérite du sujet que
   s'il interroge ou enchaîne et que le tour précédent a réellement lu.
2. **Le 27b ne tient pas sur ce Mac.** 18 à 26 Go résidents pour 32 Go, 10,5
   libres au chargement (journal d'Ollama 10:54:14) ; la première passe après
   chargement a duré 1 min 38 s. Le classificateur marquait ces questions
   « trivial » (0,06) mais ne changeait que le budget de jetons — ses motifs
   sont anglais, en français presque tout est trivial. `server/tour_leger.py`
   envoie un tour léger sur `[intelligence].light_model` quand il est
   configuré et qu'Ollama le liste (relu toutes les 60 s) : une ou deux
   lignes, sans image, code, calcul, quantité, verbe de production en tête
   (rédige, prépare, code-moi, fais-moi…) ni raisonnement (pourquoi, résous,
   démontre). Une suite (« Continue », « Plus long », trois mots ou moins)
   garde le poids du tour qu'elle prolonge, de proche en proche. Le modèle
   choisi garde le reste ; chaque fragment porte le modèle réel et le bilan
   un bloc `routing` ; le pied de la réponse affiche « léger ← lourd », et
   plus aucun modèle sur la voie éclair. Limite mesurée : deux modèles ne
   cohabitent pas quand le lourd occupe la mémoire (le préchauffage du
   sélecteur est défait par le premier tour léger) ; le remède de fond reste
   le 9b comme modèle du quotidien.
3. **La mémoire suit le tour, jamais l'inverse.** Aucun modèle n'est chargé
   pour extraire un souvenir : après un tour léger l'extraction tourne sur
   le léger, après un tour lourd sur le lourd (`extraction_model` reste
   vide). Un 27b résident n'est pas évincé pour 200 jetons de souvenir.

Deux corrections de mesure : la ligne `chat_performance` n'atteignait jamais
`serve.err.log` (logger au niveau WARNING ; elle parle en INFO désormais), et
le pied de chaque réponse affichait le modèle du sélecteur, pas celui qui
avait répondu.

### La trousse stable — 20 septembre, après-midi

La trousse adaptative du lot 3 changeait de forme à chaque tour (catalogue +
familles reconnues, ou les 45 schémas pour une demande inconnue). Or Ollama
rend les schémas en tête du prompt et ne réutilise que le préfixe identique :
chaque changement de trousse remettait tout le préremplissage à froid. Banc
de cinq tours sur le 9b, même conversation, mesuré par `chat_performance` —
`promptEvalMs` de la première passe, puis premier texte reçu :

| Tour | Trousse adaptative (lot 3) | Trousse stable |
|---|---:|---:|
| « Quelles sont mes tâches aujourd'hui ? » (appel `succes_tasks`) | 9,1 s → 15,6 s | 2,4 s → 6,4 s |
| « Quelle est la capitale du Pérou ? » | 24,4 s → 24,9 s | 2,7 s → 3,2 s |
| « Et mes notes ? » | 8,4 s + relecture 2,9 s → 14,1 s | 2,7 s → 4,2 s |
| « Quelle est la capitale du Chili ? » | 2,9 s → 3,4 s | 3,0 s → 3,4 s |
| « Quelles sont mes tâches en retard ? » | 9,0 s + relecture 2,8 s → 13,0 s | 2,7 s → 4,3 s |
| **Somme des premiers textes** | **71,0 s** | **21,5 s** |

Avec la trousse adaptative, quatre tours sur cinq partaient à froid ; le seul
tour chaud avait la même trousse que celui du Pérou. Avec la trousse stable,
le préfixe (identité + 45 schémas, 10 112 jetons rapportés par Ollama) est le
même pour tous les tours et toutes les conversations : il ne se paie qu'au
chargement du modèle (≈ 24 s sur le 9b), et le premier tour du banc l'a
trouvé encore en cache. `[agent] trousse_adaptative = true` rend l'ancienne
trousse ; par défaut la trousse est stable et la relecture avant affichage
n'est plus armée — elle n'aurait rien à élargir. Limite connue, non
mesurée : un 9b qui affirme « aucune tâche » sans lire malgré les 45
schémas n'est rattrapé par rien, comme avant le 19 septembre ; le seul
indice favorable est ce banc, où `succes_tasks` a bien été appelé.

Ce que ce banc ne mesure pas : le premier tour après un vrai chargement du
modèle (≈ 7 s de chargement + 24 s de préremplissage), et les conversations
qui débordent la fenêtre de 16 384 jetons — 10 112 sont pris par le préfixe,
il en reste environ 6 000 pour l'historique. Au-delà, Ollama écarte les
messages les plus anciens mais garde toujours les messages système et le
dernier message : le préfixe reste en cache, l'historique conservé glisse et
se retraite (quelques secondes par tour). Si le préfixe et le dernier message
dépassent à eux seuls la fenêtre (un document de 25 000 caractères collé),
le runner coupe au jeton en ne gardant que quatre jetons de tête : identité
et premiers schémas disparaissent sans un mot. Élargir `DIAPASON_NUM_CTX` à
32 768 pour le 9b coûterait environ 2,4 Go de cache KV de plus ; à mesurer
avant de le poser.

Deux compléments mesurés le même après-midi :

- **Le préfixe reste chaud entre deux questions.** Le cache meurt avec le
  runner (`keep_alive` 30 min) ; `server/prechauffage.py` rejoue le préfixe
  exact du bureau (identité, 45 schémas, celui des questions, « Bonjour »,
  un jeton) toutes les dix minutes, par l'admission de fond — un tour
  interactif le fait attendre. Preuve dans le journal de llama-server, 20
  septembre à 19:39 : préchauffage 27,7 s (points de contrôle créés à
  9 848 et 10 868 jetons), puis première question du bureau quatre secondes
  plus tard « sim = 0.946 (10104/10678) … restored context checkpoint
  (pos 9848) » : **2,44 s** au lieu de 25. La ligne `prefixe_chauffe … en
  N s` du journal du serveur dit si le tour de dix minutes a trouvé le
  préfixe en cache (~0,3 s) ou l'a recalculé. En passant : le préchargement
  du modèle au démarrage (`_prewarm_local_model`) n'avait jamais envoyé un
  seul `/api/generate` sur ce Mac — son déballage s'arrêtait sur le
  GuardrailsEngine, qui relaie `engine_id` sans avoir d'hôte ; il partage
  désormais le déballage du préchauffage.
- **Pourquoi la forme du préfixe doit être exacte.** Le 9b est hybride
  (couches SSM + attention) ; llama-server ne peut reprendre qu'à un point de
  contrôle, créé au plus tôt vers 8 192 jetons et au début du dernier lot de
  1 024. Un préfixe commun de 8 116 jetons (le bureau avec 46 schémas contre
  un appel API avec 45) ne sert à rien : « checking checkpoint with [9615]
  against 8116 » → tout est recalculé, et les points de contrôle de l'autre
  prompt sont effacés. Même trousse, même ordre, même schéma des questions :
  c'est à ce prix que le point de contrôle tient.
- **Un « Merci ! » garde la trousse.** Dispensé de schémas, un salut partait
  de l'identité seule et retraitait tout l'historique : 4,2 s de
  préremplissage pour 1 843 jetons, contre 2,7 s pour la question outillée
  suivante (10 292 jetons) dont le préfixe était en cache. Tous les tours du
  bureau passent désormais par la même trousse. Sur ce banc, le tour outillé
  qui suivait le « Merci ! » est resté chaud : llama-server conserve le
  préfixe outillé même après un prompt sans outils.

### La fenêtre de contexte à 32 768 — 20 septembre, soir

`[intelligence] num_ctx = 32768` dans `config.toml` (nouvelle clé, câblée
sur `DIAPASON_NUM_CTX` que l'environnement peut encore imposer pour un
appel ponctuel). Mesures sur le 9b, même Mac :

| | 16 384 | 32 768 |
|---|---:|---:|
| Cache KV alloué par llama-server (8 couches d'attention sur 32) | 512 Mio | 1 024 Mio |
| Modèle résident selon `/api/ps` | 5,62 Gio | 6,18 Gio |
| Chargement du runner | 2,8 s | 2,8 s |
| Préremplissage du préfixe à froid (10 640 jetons) | 25,6 s (416 jetons/s) | 25,2 s (423 jetons/s) |
| Tours courts, préfixe chaud (premier texte) | 3,2 – 3,5 s | 3,2 – 5,7 s |
| Conversation de 17 300 jetons, tours suivants | *tronquée* | 3,3 – 3,5 s, `truncated = 0` |

Le coût est de 512 Mio ; la vitesse de préremplissage ne bouge pas. Sur une
conversation amorcée à 17 300 jetons (quatorze échanges synthétiques d'un
paragraphe, sans contenu personnel), le premier tour paie l'historique une
fois (21,9 s), puis llama-server reprend au point de contrôle (« restored
context checkpoint (pos 16325) », 903 jetons retraités) : 3,5 s et 3,3 s.
À 16 384, ces prompts auraient dépassé la fenêtre : Ollama aurait écarté les
messages les plus anciens à chaque tour, le début conservé aurait glissé et
tout l'historique aurait été retraité — raisonnement, pas mesure, la fenêtre
ne se règle pas par requête.

### Vite, mais faux — 20 septembre, 22:30

Dans le mini-panneau : « Qui est le président actuel du Canada ? » →
« Justin Trudeau, 23e Premier ministre, depuis 2015 », en 5,1 s, sans appel
d'outil. Le 9b avait `web_search` et la règle « ce qui est récent » dans son
identité ; il a répondu de tête parce qu'il croyait savoir. La vitesse ne
sert à rien si la réponse date. `server/actualite.py` :

- une question de fait sur un titulaire, une valeur ou une date (« qui est
  le premier ministre », « quel est le prix », « dis-moi qui… »), ou un
  marqueur de temps joint à un tel sujet (« la météo à Ottawa aujourd'hui »),
  hors données personnelles, définitions, productions et histoire ancienne,
  reçoit une consigne AU TOUR COURANT — là où le 9b obéit — : appelle
  `web_search`, réponds d'après les résultats en datant l'information, sinon
  dis que tu n'as pas pu vérifier ;
- la réponse est retenue tant qu'une recherche n'a pas RENDU quelque chose
  (`current_time`, un `web_search` vide ou en échec ne comptent pas) ; un
  premier passage sans appel vaut une relance ferme, une seule ; un second
  refus, ou une recherche vide, fait partir la réponse avec « ⚠︎ Non vérifié
  en ligne » ou « ⚠︎ La recherche web n'a rien donné » en tête (§100) ; un
  silence devient « Je n'ai pas pu vérifier cette information en ligne » ;
  une demande de précision (« quel billet ? ») suit le chemin des questions.

Même question, même 9b, après : appel `web_search("président actuel du
Canada 2026")`, résultats lus, « Le Canada n'a pas de président, mais un
Premier ministre. En septembre 2026, c'est Mark Carney qui occupe ce poste.
Il a succédé à Justin Trudeau en avril 2025. » — premier texte à 11,6 s,
total 13,2 s (1,2 s de préparation après relance du serveur, 4,4 s pour le
passage qui décide l'appel, 1,5 s de recherche, 5,7 s pour le passage qui
rédige). Avant : 5,1 s, faux. Le prix d'une question d'actualité est donc
un passage de plus et la recherche ; sur une question ordinaire rien ne
change. Limites : la reconnaissance est lexicale (une question d'actualité
sans forme interrogative ni marqueur passe encore de tête) ; rien ne relit
la réponse finale — un modèle qui lit les résultats et n'en tient pas
compte, ou invente une source, n'est pas rattrapé ; la voix et le chemin
non diffusé n'ont pas cette garde.

### Le socle des recherches véridiques — 20 septembre, nuit

L'outil cherchait avec les réglages par défaut de `ddgs` : région
`us-en`, aucune fraîcheur, pas de vertical actualités, cinq extraits sans
date, moteur tiré au hasard. Sondé le soir même : le moteur `duckduckgo`
(texte) refusait la région `ca-fr` (« No results found »), `brave`
répondait ; les trois moteurs d'actualités rendaient des dates. Quatre
pièces, sans clé API ni réseau en plus :

1. **Résultats datés, régionaux, nommés** (`tools/web_search.py`) : région
   `ca-fr` par défaut (`DIAPASON_SEARCH_REGION`), paramètres `recency` et
   `news`, chaîne fixe de moteurs (brave, duckduckgo, yahoo, mojeek ; pour
   les journaux duckduckgo, bing, yahoo) où un moteur muet cède au suivant,
   filtres relâchés plan par plan, seconde page sous trois résultats,
   dédoublonnage par URL canonique. Chaque résultat sort numéroté
   « [N] Titre — média · date » ; le moteur qui a répondu est dans la carte.
2. **Fraîcheur décidée par le code** (`actualite.py`) : une question
   d'actualité reçoit `recency=year` (une semaine pour ce qui se périme en
   jours : météo, scores, cours) et `news` pour ce qui fait l'actualité ;
   le modèle peut préciser, jamais relâcher.
3. **Sources cliquables** : la consigne demande de citer par numéro ; un
   événement SSE `sources` porte la liste ; les pastilles `[N]` (déjà là
   pour Deep Research) et une ligne « 1 · ledevoir.com · 18 sept. 2026 »
   sous la bulle rendent chaque affirmation vérifiable d'un clic. Une
   seconde recherche continue la numérotation.
4. **Contrôle a posteriori** : années, valeurs (« 5 % », « 250 $ », « 18 °C »)
   et noms propres de la réponse sont cherchés dans les sources et la
   question ; ce qui n'y est pas arrive par un événement SSE `verification`
   et s'affiche sous la bulle — « ⚠︎ Non retrouvé dans les sources : Justin
   Trudeau ». Un événement, pas un jeton : dans le texte, il se copiait et
   le modèle le relisait au tour suivant. Un signal, pas un verdict : l'année
   du jour (elle vient du contexte MAINTENANT), les têtes de phrase
   (« Actuellement Mark Carney ») et les mots de la question ne comptent
   pas ; seules les questions d'actualité, qui ont reçu la consigne de s'en
   tenir aux sources, sont contrôlées.

Mesuré, 9b, préfixe chaud : « Qui est le président actuel du Canada ? » →
`web_search("président actuel du Canada 2026", recency=year)`, cinq
sources Wikipédia numérotées, « Le Canada n'a pas de président. Le chef de
l'État est le gouverneur général, tandis que le chef du gouvernement est le
premier ministre [1][5]. En septembre 2026, c'est Mark Carney qui occupe le
poste [3]. » ; « Qui est le premier ministre du Canada ? » 11,4 s de premier
texte, 14,1 s au total ; une question stable 3,8 s. « Quel temps fait-il
aujourd'hui à Ottawa ? » → vertical actualités, cinq articles datés, aucune
donnée météo dedans, et le modèle le dit : « La recherche n'a pas retourné
de données météo pour Ottawa. » — honnête ; une source météo (palier pro)
reste à brancher. Coût d'une recherche sans résultat, après la revue du
20/09 : un budget de 12 s pour toute la chaîne (`BUDGET_S`), 5 s par
moteur, un moteur qui lève est écarté pour tous les plans — avant : quatre
moteurs × trois plans + pages 2, jusqu'à quinze appels (60–75 s) qu'un
exécuteur à 30 s tranchait sans un mot. Zéro moteur joint est une panne
(`success=False`, « aucun moteur n'a répondu »), des moteurs qui répondent
vide sont un vide. La carte décrit chaque plan qui a répondu (moteur,
catégorie, filtres, nombre) au lieu de prêter les filtres d'un plan au
moteur d'un autre ; le modèle ne peut que resserrer `recency`/`news`,
jamais les relâcher ; une page vue par deux recherches garde sa première
pastille ; les dates se lisent dans le fuseau du poste. Limites : les
résultats « texte » de ddgs n'ont pas de date, seuls les journaux en
portent ; `recency=year` filtre la date de la page, pas celle du fait — une
page de référence stable peut passer derrière trois pages fraîches ; le
contrôle a posteriori ignore les mots seuls et les flexions ; brave ne lit
que le pays de `ca-fr`, la langue n'atteint que les moteurs de secours.

Ce que le 9b hybride (couches SSM + attention) ajoute : chaque tour
retraite ce qui suit le dernier point de contrôle utilisable, environ 700 à
1 000 jetons (contexte frais + dernier échange), d'où le plancher de 2,7 à
3,0 s. Sur huit tours de 180 à 220 jetons de réponse chacun (historique de
10 254 à 11 750 jetons), le préremplissage est passé de 2,9 à 3,3 s : la
croissance existe mais reste lente à cette échelle.

## Lot 1 — contexte stable, réactivité et mesures

Livré :

- L’heure, l’état du bureau et les souvenirs recherchés rejoignent la demande
  courante, après les échanges précédents. L’identité et les instructions du
  client restent présentes. L’historique enregistré n’est ni tronqué ni réécrit.
- La recherche mémoire, la préparation de l’identité et l’initialisation de la
  trousse s’exécutent hors de la boucle du serveur. L’initialisation de la
  trousse est sérialisée ; les conversations ne le sont pas. La vérification
  de santé n’immobilise plus la boucle en attendant le moteur.
- Le flux possède un identifiant de requête et une mesure propre, indépendante
  des autres fenêtres : préparation, mémoire, cadrage, premier fragment natif,
  premier texte émis, durée totale et compteurs/durées Ollama de chaque passe.
  Ces mesures sont disponibles dans `telemetry.performance` à la fin du flux
  et dans le journal du serveur, sans contenu des discussions. La première
  émission du serveur n’est pas confondue avec l’affichage effectif à l’écran.
- Les appels d’outils déjà présents dans un historique conservent leurs
  arguments et identifiants lors de la conversion. L’ajout de mémoire conserve
  les objets du client et ne sépare pas un appel de son résultat.
- La fermeture ou l’annulation du lecteur ferme aussi la source du flux.

Comparaison sur l’historique d’Anglais, cette fois avec l’identité configurée,
mais sans les schémas d’outils : 7 530 jetons de contexte rapportés par Ollama.

| Placement des informations fraîches | Premier appel | Deuxième appel, date actualisée |
|---|---:|---:|
| Avant l’historique, ancien comportement | 17,36 s | 17,37 s |
| Près de la demande, nouveau comportement | 18,01 s | **2,77 s** |

Le deuxième appel réduit l’attente d’environ **84 % dans cet essai contrôlé**.
Le premier appel après changement de disposition reste coûteux. Le journal
du moteur confirme une reprise à un point de calcul conservé, avec 1 024
jetons réellement retraités dans le dernier essai. Ce résultat ne promet pas
le même gain à froid, avec un autre modèle ou avec des requêtes concurrentes.

Après rechargement du serveur, une requête réelle a confirmé la transmission
des mesures et une réponse de santé en **18,61 ms pendant la génération**.
Sur ce « Bonjour », le premier fragment natif arrive à 5,40 s, le premier texte
émis à 6,42 s et le flux finit à 6,43 s. L’amélioration de contexte ne supprime
donc pas tous les autres coûts.

Point supplémentaire identifié à la fin du lot 1, **traité au lot 2 ci-dessous** :
`GuardrailsEngine.stream_full` conservait les morceaux jusqu’à la fin pour
examiner le contenu, contrairement au flux texte simple qui utilisait déjà
une retenue de fin. Sur les longs tours outillés, cette attente pouvait masquer
la génération progressive. La correction devait préserver les contrôles, les données
sensibles et les appels d’outils lors de la diffusion progressive.

Vérifications : **168 tests ciblés réussis**, lint et formatage des fichiers
modifiés conformes. La campagne élargie a donné 1 365 réussites et 9 sauts ;
ses deux échecs de tests sur sockets ont disparu avec l’autorisation d’ouvrir
les ports de test locaux (9 tests réseau réussis). Trois autres échecs ont
été reproduits avec les routes de HEAD, avant ce lot : métriques vides dans
un dossier de test neuf, doublure Granola inopérante, chemin de persona qui
ignore le dossier de test configuré. La suite élargie n’est donc pas annoncée
entièrement verte. Les nouvelles écritures de test sont isolées dans `/tmp`.

[Mesures du lot 1, sans contenu utilisateur](mesures-performances-2026-09-19-lot1.json).
Les routes Succès asynchrones, l’ordonnancement des modèles, la sélection des
outils et les optimisations de rendu restent dans les lots suivants.

## Lot 2 — diffusion progressive et fermeture des flux

Livré et activé sur le serveur local :

- Le flux riche utilisé par la discussion peut envoyer du texte déjà vérifié
  pendant la rédaction. Le flux simple utilise les mêmes frontières sûres.
  Une courte retenue couvre les motifs de taille bornée ; les mots/adresses
  non terminés et les affectations secrètes encore ouvertes restent retenus.
  Une longue clé ou une valeur sur plusieurs lignes ne peut plus être
  partiellement envoyée par l’ancienne retenue fixe du flux simple.
- Une détection suspend la diffusion du reste jusqu’au contrôle complet.
  Le mode **BLOCK** reste intégralement tamponné, sans texte ni outil partiel.
  Les scanners personnalisés restent aussi tamponnés : on ne suppose pas
  leurs motifs bornés. Les modes WARN/REDACT conservent leur sens ; aucun
  contrôle n’a été désactivé dans la configuration.
- Les fragments d’appels d’outils, résultats, blocs, compteurs et motif d’arrêt
  sont conservés une fois, dans leur ordre ; ils attendent le contrôle final.
  Un flux configuré sans contrôle de sortie n’attend plus inutilement la fin.
- Les couches serveur, reprise longue, boucle d’outils, routage de modèles,
  instrumentation et moteur transmettent explicitement la fermeture. Les
  tests vérifient la fermeture de la connexion HTTP à Ollama, y compris
  lorsqu’on arrête juste après le premier texte, sans attendre le nettoyage
  automatique de Python. Aucun nouvel appel de continuation n’est lancé.
  Cela ne prouve pas une préemption immédiate de tout calcul GPU interne.
- La zone déjà diffusée n’est plus réanalysée à chaque jeton. Si une très
  longue séquence reste ambiguë, l’espacement des contrôles augmente pour
  éviter de rescanner tout son préfixe à chaque petit fragment.

### Mesures réelles

Même question courte, même modèle et plafond de 192 jetons, un schéma d’outil
explicite. Aucun outil demandé par le modèle dans ces deux essais.

| Mesure | Avant | Après |
|---|---:|---:|
| Premier fragment natif | 5,90 s | 3,74 s |
| Premier texte reçu par le client HTTP | 12,95 s | **5,50 s** |
| Attente entre fragment natif et première émission serveur | 7,04 s | **1,76 s** |
| Fin reçue par le client | 12,98 s | 9,48 s |
| Jetons de réponse | 160 | 130 |

Le texte est désormais reçu pendant la génération. Le traitement du contexte
et la longueur de sortie diffèrent aussi : cette comparaison n’isole pas
l’effet du lot sur la durée totale, ne donne pas un p95 et ne mesure pas
l’affichage à l’écran. Les tests à fournisseur suspendu prouvent séparément
que le début peut sortir avant la fin et que son contenu reste exact.

Un troisième essai emprunte **le parcours habituel du bureau**, sans outils
explicitement fournis, plafond de 128 jetons. Premier texte natif à **23,98 s**,
premier texte reçu à **25,55 s**, fin à **29,64 s**. Ollama rapporte **10 231
jetons de contexte**, dont le traitement dure **23,88 s** ; la préparation
serveur dure 41 ms. L’attente de diffusion n’est plus que 1,57 s, mais le coût
du contexte et de la trousse automatique reste élevé. Ce résultat n’est pas
masqué par le cas plus rapide à un seul schéma. Il motive la sélection des
outils et les mesures de réutilisation du contexte au lot suivant ; aucun
outil n’a été retiré arbitrairement dans ce lot.

Vérification : **1 423 tests ciblés réussis**, lint et formatage conformes.
La suite couvre sécurité, moteurs, télémétrie et parcours du chat,
avec variantes Rust/Python, fragments de 1/17/173 caractères, secrets longs,
valeurs multilignes, outils, BLOCK, scanner personnalisé, fermeture et
annulation. Les essais unitaires utilisent un dossier temporaire. Les trois
échecs préexistants de la campagne élargie du lot 1 restent distincts ; ils
ne sont pas déclarés corrigés ici.

[Mesures du lot 2, sans contenu des discussions](mesures-performances-2026-09-19-lot2.json).

## Lot 3 — trousse adaptée au tour, avec accès et contrôles conservés

Livré :

- Une grande trousse peut présenter un catalogue court et les schémas détaillés
  des outils probablement utiles au tour. Les petites trousses restent
  inchangées ; le catalogue n’est employé que s’il est réellement moins lourd.
  Les schémas préchargés/chargés gardent tous leurs paramètres et contraintes.
- Une explication ou une production autonome reconnue évite de faire lire
  d’emblée tous les paramètres. Les tâches, notes, projets, agenda, etc.
  préchargent leur famille. Les mots-clés sont des indices de préchargement,
  jamais des permissions. Les outils récents et le contexte d’un suivi court
  participent à ce choix ; l’historique utilisateur n’est pas tronqué.
- Tous les noms autorisés restent dans le catalogue. Le modèle peut charger
  un schéma manquant sans exécuter une action. Deux découvertes au plus, puis
  repli aux schémas complets ; elles ne consomment pas les trois tours d’actions.
  Un appel direct à un outil connu reste soumis au même exécuteur. Aucun nom
  absent de la trousse configurée ne peut atteindre cet exécuteur.
- **Une demande non reconnue garde les schémas complets.** Ce choix vient d’un
  essai raté du prototype : « J’ai reçu quoi ? » avec catalogue seul produisait
  une absence de messages inventée. Cette variante n’a pas été activée.
- Pour une demande de données utilisant la trousse réduite, une réponse sans
  aucun appel d’outil, après un arrêt normal, est retenue avant affichage et
  rejouée une seule fois avec les schémas complets. L’affirmation non vérifiée
  n’est pas ajoutée à l’historique de travail. Aucun repli sur arrêt de sécurité,
  coupure ou motif d’arrêt absent. Une découverte qui tourne en boucle finit
  par une explication de l’échec, sans faux succès.
- Les confirmations, contrôles de capacités et validations demeurent dans
  `ToolExecutor`. Les outils explicitement fournis par un client et la voix
  conservent leurs chemins précédents. Fenêtre principale et mini-panneau
  bénéficient du même parcours du chat.
- Chaque inférence rapporte désormais `toolSchemaCount` et
  `toolSchemaCharacters`, uniquement des compteurs. Une seule définition peut
  être le catalogue : ce chiffre ne signifie pas que les autres capacités
  ont été retirées. Aucun schéma, argument ou contenu privé n’est ajouté aux
  mesures.

### Mesures sur le parcours normal du bureau

Même question sur la croissance des arbres, même modèle déjà résident,
`temperature=0`, plafond de 128 jetons. L’essai « avant » est celui du lot 2,
avec la trousse complète. Le premier passage « après » suit un rechargement du
serveur ; la répétition peut réutiliser le contexte du précédent appel.

| Mesure | Avant, lot 2 | Après, premier passage | Après, répétition |
|---|---:|---:|---:|
| Premier texte reçu par le client HTTP | 25,55 s | **9,26 s** | **2,68 s** |
| Premier fragment natif | 23,98 s | 7,79 s | 1,17 s |
| Traitement du contexte rapporté par Ollama | 23,88 s | 6,53 s | 1,10 s |
| Fin reçue | 29,64 s | 13,16 s | 6,67 s |
| Contexte rapporté | 10 231 jetons | **3 441 jetons** | 3 441 jetons |
| Réponse produite | 122 jetons | 119 jetons | 119 jetons |

Le premier texte arrive environ 64 % plus tôt au premier passage de cet
essai. La répétition bénéficie aussi du contexte déjà calculé ; ces gains ne
s’additionnent pas. Un échantillon par cas n’est ni une moyenne représentative
ni un p95, et la réception HTTP n’est pas le rendu à l’écran. Les demandes
inconnues et les replis peuvent encore coûter la trousse entière. La rédaction
elle-même reste proportionnelle à la longueur demandée.

### Vérification de la qualité

Le modèle réel a été essayé avec des outils doublés, sans lecture ni mutation
des données personnelles :

- Demande de tâches pour demain : `succes_tasks(action="list", date="demain")`,
  puis restitution du titre de test reçu. Trois schémas au premier appel.
- Demande de titres des notes : `succes_workspace(action="list_notes")`, puis
  restitution du titre provenant de la liste structurée de test. Deux schémas.
  Une première doublure, limitée à une phrase sans liste, n’avait pas permis
  une restitution fiable ; le banc a été corrigé pour suivre le format réel.
- Vérification des éléments reçus aujourd’hui : appel `digest_collect`, puis
  reprise de l’identifiant renvoyé par le banc ; aucun connecteur réel exécuté.
- Formulation inconnue « J’ai reçu quoi ? » : les 44 schémas du banc sont
  conservés ; tentative de lecture Messages. Le banc refusant ce connecteur,
  le modèle a signalé une absence d’accès, sans prétendre à une lecture réussie.

La suite automatisée vérifie en plus : schémas complets identiques après
chargement, isolement entre fenêtres, historique et suivi court, configurations
personnalisées, collision du nom interne, refus de confirmation sans effet,
outils inconnus rejetés, budgets bornés, absence de contournement d’un arrêt de
sécurité, absence inventée retenue avant affichage et annulation du fournisseur.
**1 451 tests ciblés réussis** sur les domaines sécurité, moteurs, télémétrie
et chat ; contrôles de style conformes. Les limites de la campagne élargie du
lot 1 ne sont pas effacées par cette campagne ciblée.

[Mesures du lot 3, sans contenu des discussions](mesures-performances-2026-09-19-lot3.json).
Restent notamment l’ordonnancement des générations concurrentes et du travail
de fond, le rendu/sauvegarde des discussions et l’allègement des réponses de
listes Succès. Aucun hébergement distant, changement de modèle par défaut ni
publication GitHub n’a été effectué pour ce lot.

## Lot 4 — priorité aux discussions face à la mémoire en attente

Livré et activé après rechargement du serveur :

- Les clients `OllamaEngine` d’un même serveur, dans le même processus,
  partagent une admission. Une extraction mémoire en attente laisse passer
  les appels interactifs ; les questions entre elles gardent le parallélisme
  configuré dans Ollama. Les clients `localhost`, `127.0.0.1` et `::1` du même
  port partagent la même coordination.
- Le tour de chat est protégé jusqu’à la fermeture du flux, y compris le temps
  passé dans les outils et les reprises de réponse. Le chemin non diffusé
  garde cette protection dans son fil de travail. La mémoire attend aussi
  **deux secondes de calme** après le dernier tour/appel interactif, pour
  laisser passer un suivi immédiat. Ce délai ne s’applique pas aux questions.
- Le préchargement cède également le passage. Un modèle explicitement demandé
  pour préchargement reste celui réellement chargé et annoncé.
- Lorsque le modèle d’extraction est laissé automatique, la mémoire reprend
  le dernier modèle utilisé avec succès par un appel interactif sur ce serveur,
  au lieu du modèle fixé au démarrage du service. Un modèle mémoire configuré
  explicitement reste respecté. Le bilan de télémétrie utilise le modèle
  effectivement retourné par le fournisseur.
- La file mémoire reste bornée à **256 échanges**. Les doublons strictement
  identiques encore en attente/en cours sont regroupés ; des textes ou des
  réponses différents ne sont pas fusionnés. Une fois terminé, un échange
  identique peut être soumis de nouveau. Les souvenirs différés sont extraits
  et enregistrés après la discussion.
- Annuler un flux retire son attente et ferme le transport. Aucun fil d’attente
  abandonné ne peut obtenir le moteur plus tard. Arrêter le service retire les
  extractions qui attendent encore leur admission ; une extraction déjà envoyée
  peut se terminer. Redémarrer trop tôt ne crée pas un second ouvrier parallèle.
- `inferenceQueueMs` mesure l’attente **interne à Diapason** pour chaque réponse.
  Elle ne mesure pas la file interne d’Ollama. Un délai d’admission dépassé est
  signalé comme un moteur occupé, sans faux diagnostic de connexion inaccessible.

### Essai de concurrence reproductible dans les tests

Le banc utilise le vrai moteur Python et l’extracteur, avec un fournisseur HTTP
simulé qui possède un seul créneau : extraction de 300 ms, réponse de 50 ms,
question posée après une pause d’outil de 40 ms. Trois paires alternent admission
ancienne et nouvelle. Médianes du premier fragment : **319,73 ms avant**, puis
**55,79 ms après**. Les six extractions produisent le souvenir attendu. Après
correction, les traces montrent question puis mémoire ; avant, mémoire puis
question. Le délai de calme de deux secondes est payé par la mémoire.

**Ces nombres valident ce scénario de concurrence, pas la vitesse du GPU ni
un gain général de l’application.** Les tests couvrent aussi l’extraction déjà
commencée : elle finit avant de libérer le moteur. Aucune préemption fictive.

### Vérification sur le serveur réel

Serveur rechargé, contrôle de santé **HTTP 200**, puis deux réponses complètes
sans appel d’outil ni message enregistré dans l’historique. Au moment de l’essai,
`qwen3.5:9b` et `gemma3:4b` sont tous deux résidents. Le second correspond au
modèle de vision configuré ; sa présence seule ne prouve ni une inférence active
ni quel processus l’a chargé. Aucun modèle n’a été déchargé pour arranger le banc.

| Mesure | Premier passage | Répétition |
|---|---:|---:|
| Premier texte reçu par HTTP | 10,09 s | 3,77 s |
| Fin de réponse reçue | 14,41 s | 8,12 s |
| Attente interne mesurée | 0,003 ms | 0,012 ms |
| Traitement du contexte natif | 7,31 s | 2,29 s |
| Contexte / réponse rapportés | 3 426 / 130 jetons | 3 426 / 130 jetons |

Il n’y avait pas d’attente d’admission notable sur ces deux appels. Ce n’est
pas une comparaison avant/après du lot 4 : le lot 3 avait un seul modèle
résident et un contexte différent. Le test réel valide le raccord et la mesure,
pas une nouvelle accélération chiffrée de la discussion sans concurrence.

**1 632 tests ciblés réussis, 14 sautés et 4 désélectionnés**, sur sécurité,
moteurs, télémétrie, mémoire et parcours du chat/préchargement. Style et diff
vérifiés. Les échecs préexistants de la campagne générale du lot 1 ne sont pas
présentés comme corrigés par cette campagne ciblée.

[Mesures et traces du lot 4](mesures-performances-2026-09-19-lot4.json).

Limites conservées : une génération déjà envoyée n’est pas interrompue ; les
appels d’autres processus à Ollama et les appels directs hors `OllamaEngine`
ne sont pas ordonnancés ici. Seuls mémoire et préchargement ont reçu le statut
de fond dans ce lot : les autres agents et travaux périodiques, dont la vision,
restent à classifier. La file mémoire était et demeure en mémoire vive et au
mieux en cas de saturation/arrêt ; aucune persistance de file n’est promise.
Les discussions stockées et les faits déjà enregistrés ne sont pas supprimés.

La prochaine priorité est le rendu et les sauvegardes du chat dans les deux
fenêtres, puis l’allègement des lectures des modules. Aucun changement de
modèle principal, hébergement distant, reconstruction de l’interface ou push
GitHub n’est nécessaire à cette activation du serveur.

## Lot 5 — rendu du chat, points de reprise et synchronisation

Livré dans l'interface, app reconstruite et relancée localement. Le bundle
servi au mini-panneau a été rafraîchi dans la même installation :

- La copie de travail des conversations reste en mémoire. Une modification
  copie uniquement le fil et le message concernés ; les autres messages
  conservent leur identité. `React.memo` peut alors éviter de réanalyser tous
  les anciens tableaux et blocs de code à chaque publication.
- Le premier texte apparaît immédiatement. Les rafales suivantes sont
  regroupées sur 80 ms, y compris la progression utilisée par l'interface.
  Le chronomètre ne fait plus rendre toute la discussion ni son compositeur.
  Un dernier fragment isolé n'attend plus le jeton suivant pour apparaître.
- Pendant la rédaction, l'historique est sauvegardé à intervalles fixes de
  1 000 ms, à la fin et au changement de visibilité. Les métadonnées sont
  enregistrées immédiatement. Un échec du stockage ne remplace plus le texte
  récent par une ancienne copie avant l'envoi au serveur.
- La vérification audio secondaire ne retient plus le dernier texte ni le
  bouton Envoyer. Un audio tardif est rattaché à son message exact, seulement
  si le texte du digest correspond ; une suppression n'est pas annulée par
  son arrivée. L'annulation du flux garde la main jusqu'à sa vraie fermeture,
  sans laisser l'ancien `finally` réinitialiser un nouvel envoi.
- Les événements SSE conservent leur nom lorsqu'ils arrivent en plusieurs
  lectures réseau. Finir ou quitter le consommateur annule le lecteur réseau.
- Les GET de synchronisation simultanés partagent leur requête. Les vues
  cachées ne font plus de GET périodiques, mais réessaient les écritures en
  attente. La réouverture, le retour du réseau et la fin d'un flux relancent
  les actions nécessaires. Une discussion consultée reste synchronisée même
  si une autre reçoit encore une réponse.
- Export et import lisent la copie récente. Une suppression vide aussi le
  cache et les messages affichés. Les règles de fusion Python/TypeScript et
  le contrat HTTP n'ont pas changé.

### Mesure contrôlée dans WebKit

Banc synthétique : 40 anciens messages, dont 20 tableaux de 25 lignes, puis
100 publications d'une réponse. L'ancien chemin parse et réécrit l'historique
à chaque publication et rend les bulles sans mémorisation. Le nouveau utilise
le vrai store modifié et les bulles mémorisées. Les deux utilisent le même
composant de bulle et les mêmes textes.

| Passage | p95 du travail JS de publication avant | Après | Écritures locales avant → après |
|---|---:|---:|---:|
| 1, largeur 1 000 px | 39 ms | 6 ms | 100 → 3 |
| 2, largeur 1 000 px | 32 ms | 6 ms | 100 → 3 |
| 3, largeur 340 px | 32 ms | 5 ms | 100 → 3 |

Les deux premières paires utilisent une fenêtre transparente ; la troisième
une fenêtre visible. Mesures de **React en développement dans WKWebView**,
avec `flushSync` et `Profiler`, pas du bundle de production ni de chaque image
composée par le GPU. `performance.now()` est arrondi par WebKit : une valeur
de 0 ms indique une durée sous sa résolution, jamais un coût nul. Ces petits
échantillons ne constituent pas un p95 d'usage représentatif. Ils isolent une
baisse du travail JavaScript ; ils ne mesurent pas le temps de génération du
modèle. La réponse courante et les points de reprise gardent un coût.

### Vérifications

- **931 tests de l'interface réussis**, dont sauvegarde différée, quota plein,
  reprise réseau, réponse PUT ancienne, suppression pendant un PUT, curseur
  retenu pendant un flux, rafraîchissement de l'autre fil, fin et annulation
  SSE. Les 10 cas du contrat commun de fusion restent conformes.
- Vraie `ChatArea`/`InputArea` dans WKWebView visible : tableau synthétique de
  100 lignes intact à 1 000 et 340 px, thèmes sombre et Terminal phosphore,
  aucun débordement horizontal de page ni erreur JavaScript. Le compositeur
  est disponible malgré un digest secondaire volontairement bloqué. Arrêt
  après un texte partiel, puis nouvel envoi complet de 100 lignes réussis.
- Deux processus WKWebView avec stockages éphémères et origines distinctes,
  contre les **vraies routes de conversations et SQLite temporaire** : envoi
  dans les deux sens, panne réseau simulée, écriture concurrente pendant un
  flux, convergence vers trois messages sans doublon et texte complet, puis
  suppression propagée et vues vidées. Aucun message ni base personnelle
  utilisés par ces bancs.

Un arrêt brutal peut perdre le texte depuis le dernier point de reprise réel,
notamment si la WebView suspend ses minuteurs. La synchronisation n'est pas
annoncée réussie sans réponse serveur. Windows/WebView2, le coût graphique du
Liquid Glass, les notes paginées et la consommation au repos restent à mesurer.

[Mesures du lot 5](mesures-performances-2026-09-19-lot5.json).
L'allègement des listes Succès et des autres travaux de fond reste au lot 6.

## Lot 6 — listes légères, lectures ordonnées et sondes suspendues

Application reconstruite, installée avec sa signature stable et relancée.
Le serveur répond en HTTP 200 ; les interfaces embarquée et servie au mini-panneau
sont identiques. Activation locale uniquement, sans publication GitHub.

Changements vérifiés sur le serveur et dans le vrai moteur WebKit du Mac :

- La liste des tâches passe de **1 405 SELECT pour 702 tâches à deux SELECT**
  groupés dans le même instantané SQLite. Les champs, carnets, rangs et arbres
  de sous-tâches restent complets ; aucune tâche terminée n’est retirée du
  contrat. Un test compare le résultat groupé aux lectures détaillées.
- Les 55 routes de `succes/routes.py` qui étaient asynchrones sans aucun
  `await` passent dans le pool de travail de Starlette. Une lecture SQLite ou
  un échange réseau lent n’immobilise plus la boucle qui sert le chat. La
  création initiale du store est protégée contre les appels concurrents.
- Les cartables de Notes et les notes rattachées à Projets lisent des résumés
  sans HTML. Le document complet est demandé à l’ouverture ; tant qu’il n’est
  pas arrivé, aucun éditeur vide ne peut écraser son contenu. L’ancien endpoint
  complet reste disponible. Deux routes ajoutées portent le contrat à 100.
- Les GET simultanés identiques partagent leur réception, avec une copie par
  consommateur. Serveur, authentification et recherche les distinguent. Les
  écritures invalident ces lectures à leur départ et à leur fin. Les anciennes
  réponses de recherche sont ignorées dès la frappe, avant le délai de recherche.
- Les projets, récurrences et états de synchronisation ne retardent plus les
  tâches. Les kits ne retardent plus les projets. L’ordre « matérialiser les
  récurrences, puis relire les tâches » du Planificateur est conservé.
- Une écriture dont la réponse réseau est perdue n’est plus automatiquement
  rejouée : elle pouvait créer des doublons. Les réessais bornés des GET restent
  présents. Les sauvegardes de notes sont ordonnées, lisent le brouillon récent
  à leur départ et ne remplacent pas une frappe faite pendant leur attente.
- Les sondes du panneau système sont authentifiées, mutualisées et annulées
  quand la vue est cachée. Elles reprennent au retour. Une sonde déjà fermée
  au remontage StrictMode ne démarre pas une requête inutile.

### Mesures locales, trois lectures par route

| Route / résultat | Avant | Après |
|---|---:|---:|
| Charge utile des cartables | 1 101 391 octets | **5 799 octets**, −99,47 % |
| Liste des tâches, durées successives | 62,25 / 17,56 / 14,64 ms | 58,49 / 11,74 / 10,15 ms |
| Charge utile des tâches | 840 823 octets | 840 823 octets, contenus préservés |

Le résumé des notes n’accélère **pas** la seule réponse HTTP : analyser leur
HTML côté serveur prend environ 23 ms ici, contre environ 3 à 4 ms pour rendre
la liste complète. Le gain porte sur le transfert, la mise en cache et le
travail de l’interface, qui ne transporte plus tous les documents pour dessiner
les cartables. Le compteur « ≈ pages » est une estimation textuelle, distincte
du nombre de pages réellement mesuré dans l’éditeur.

Trois appels par route ne constituent pas un p95. Le premier appel de chaque
série comprend des effets de mise en route non isolés ; il n’est pas présenté
comme un lancement à froid contrôlé. Les gains des lots ne s’additionnent pas.

### Vérifications

- **944 tests frontend dans 79 fichiers** et TypeScript passent. **250 tests
  Succès et contrats** passent dans un dossier de données temporaire. Lint,
  formatage Python des fichiers modifiés et instantané des 100 routes conformes.
- WKWebView visible, données synthétiques : les sept tâches sont déjà là au
  contrôle après 150 ms alors que projets et récurrences attendent 2 500 ms.
- Recherches revenant dans l’ordre inverse et clics rapides sur deux cartables :
  le dernier choix reste affiché, sans apparition d’un éditeur vide.
- Saisie pendant une sauvegarde retardée de 800 ms : l’ancien retour ne remplace
  pas le nouveau texte ; les deux écritures arrivent dans l’ordre. Une panne
  503 garde la note ouverte et modifiée ; le réessai enregistre son texte.
- Notes à 340 px en Terminal phosphore : document et tableau présents, sans
  débordement horizontal de page ni erreur JavaScript. Projets et Planificateur
  se montent aussi à cette largeur sans erreur ; le jour montre ses sept tâches.
  Ces essais n’équivalent pas à un audit graphique exhaustif de tous les menus.

Une première exécution Vitest a été interrompue par une longue suspension du
Mac et des délais de travailleurs expirés. La reprise sous prévention de veille,
avec quatre travailleurs, passe sans changement des seuils des tests.

Les mesures de consommation au repos, le coût graphique du bundle de production,
WebView2 et une campagne de charge SQLite restent à faire. La suspension des
sondes est prouvée fonctionnellement, sans prétendre à un gain énergétique chiffré.

[Mesures et vérifications du lot 6](mesures-performances-2026-09-19-lot6.json).

## Lot 7 — validation globale et coût des relectures sous charge

**Activé localement** : serveur rechargé, app reconstruite avec signature stable
puis relancée ; le mini-panneau reçoit le même bundle. Aucun push GitHub.

Le compteur estimatif des notes était encore recalculé intégralement à chaque
lecture. Il utilise maintenant un cache borné de **256 résultats**, indexé sur
l’empreinte SHA-256 du contenu et la capacité du format choisi. Le cache ne
conserve aucun HTML. Renommer une note ne reparcourt pas son document ; modifier
son texte ou son format relance le calcul, même si sa date n’a pas changé. Les
métadonnées, classements et rattachements restent lus à chaque requête.

### Lectures sur le serveur local

Deux campagnes identiques : 40 lectures par route après chauffe, d’abord en
séquence, puis quatre lecteurs concurrents, avec une sonde de santé indépendante.
Le p95 est le rang entier supérieur des 40 valeurs de ce banc.

| Périmètre | p95 avant le cache des compteurs | p95 après |
|---|---:|---:|
| Notes, séquentiel | 24,14 ms | **2,97 ms** |
| Notes, quatre lecteurs | 30,31 ms | **10,81 ms** |
| Tâches, quatre lecteurs | 100,89 ms | **51,44 ms** |
| Projets, quatre lecteurs | 29,07 ms | **9,46 ms** |

Les 240 lectures métier de chaque campagne retenue réussissent sans erreur.
Pendant la charge, les 17 sondes de santé de la campagne finale restent sous
17,38 ms. Ce nombre d’échantillons est modeste : il ne prouve ni une borne
absolue ni un p95 de l’usage quotidien. Le poste n’était pas réservé au banc,
et les autres programmes n’ont pas été arrêtés.

Un premier protocole faisait partager à la sonde les quatre connexions occupées
par les lecteurs : elle attendait côté client et semblait prendre 1,2 seconde.
Cette mesure est **écartée**, pas présentée comme un blocage du serveur. Les
deux campagnes comparées utilisent la connexion indépendante corrigée.

### Activité au repos et voyants

Une observation de 30 secondes sans interaction de mesure avec Diapason donne
**1,77 % d’un cœur CPU pour le serveur** et **1,20 % pour le processus natif de
l’app**, avec une mémoire résidente stable à cette échelle. Elle exclut les
processus WebKit XPC, le GPU et Ollama : ce n’est ni la consommation complète
de Diapason ni une comparaison énergétique avant/après. Une fenêtre aussi
courte ne suffit pas à exclure une fuite mémoire.

Les voyants de santé et d’activité des agents utilisent désormais le même
contrôleur que le panneau système : requête unique en cours, suspension quand
le document est caché, reprise à son retour. Dans WKWebView, avec les vrais
composants sous StrictMode et un réseau artificiel :

- pendant 31 secondes de visibilité cachée simulée, **aucun appel supplémentaire**
  de santé, d’agents, d’énergie ou de statistiques ;
- le retour simultané de visibilité, focus et reprise du panneau déclenche
  **une seule lecture par ressource**, sans erreur JavaScript ;
- les approbations continuent leurs six contrôles pendant la même période.
  Les rappels et la sécurité ne sont pas mis en pause par cette optimisation.

Le drapeau de visibilité est simulé dans le banc ; ce résultat ne garantit pas
que macOS considère chaque fenêtre simplement recouverte comme « cachée ».
L’annulation HTTP et le rejet des réponses tardives sont effectifs ; un appel
natif Tauri déjà lancé peut terminer et son résultat abandonné est ignoré.

### Vérification complète et dépendances

La campagne complète a d’abord donné 10 026 tests Python réussis et 40 sauts.
Les tests de sockets avaient besoin de l’autorisation réseau locale. Sept autres
cas dépendaient à tort du vrai dossier personnel, d’une recherche web réelle
ou d’une doublure Granola remplacée au rechargement du registre. Leurs fixtures
sont maintenant isolées ; les assertions métier n’ont pas été affaiblies.
Après la correction du cache des pages, les 251 tests Succès et contrats passent.
Un test de vision utilisait aussi la capture du bureau comme image supposée
sans main. Son résultat dépendait de ce qui était affiché. Il utilise désormais
un PNG déterministe de 640 × 400, avec le vrai framework Vision et le même seuil
de temps de traitement ; aucune capture d’écran ni modification du détecteur.
La **dernière suite complète donne 10 027 réussites et 40 sauts** en 59,64 s.
Les **944 tests frontend**, **421 tests Rust du workspace** et **58 tests Tauri**
passent aussi ; le test d’amorçage réel Tauri reste explicitement ignoré ici.
Le formatage/lint des 1 662 fichiers Python, TypeScript et l’identité sont conformes.

L’audit a identifié des correctifs GitPython 3.1.60 et vLLM 0.28.0. Le verrou
est mis à jour avec leurs dépendances nécessaires ; ces deux options sont
absentes du venv du Mac et aucune synchronisation du venv n’a été faite.
L’audit repasse sans vulnérabilité connue, avec les exclusions préexistantes
du dépôt conservées, sans en ajouter. Sources :
[publication GitPython](https://github.com/gitpython-developers/GitPython/releases/tag/3.1.60)
et [avis officiel vLLM](https://github.com/vllm-project/vllm/security/advisories/GHSA-3c86-2m5g-59q7).
Le fonctionnement GPU de cette version optionnelle de vLLM n’est pas validé sur ce Mac.

`pc-bureau` est **hors ligne** au contrôle GitHub : aucun résultat Mac n’est
présenté comme une validation Windows. Restent également le profil GPU/WebKit
de production, un vrai lancement à froid et une campagne longue de qualité et
de débit du modèle. Aucun hébergement distant ni changement de modèle par défaut.

[Mesures brutes et limites du lot 7](mesures-performances-2026-09-19-lot7.json).

## Conclusion initiale

Le premier investissement doit porter sur le chemin local de la conversation.
Le GPU fonctionne déjà. Deux causes d’attente ressortent des mesures : relire
un long contexte lorsque son début change, et attendre qu’une autre génération
libère la place ou qu’un modèle soit rechargé. Le rendu et le stockage du chat
font aussi du travail évitable, identifié dans le code mais pas encore chiffré
dans les WebViews. Les lectures Succès sont rapides dans les essais réalisés.

Un VPS pour héberger le site de téléchargement n’agit pas sur ces coûts. Le
choix éventuel d’une machine d’inférence distante doit venir après une
comparaison à modèle, contexte, quantité et qualité équivalents.

## Mesures et limites

Machine relevée : MacBook Air M5, 32 Go. Modèle de l’essai : `qwen3.5:9b`,
6 031 262 349 octets résidents, entièrement sur GPU, contexte de 16 384 jetons.
Le modèle était déjà chargé : ce n’est pas une mesure de premier démarrage.

### Génération locale

Appels directs à Ollama, séquentiels, `think=false`, température 0, graine 42,
sortie plafonnée à 32 jetons. Le protocole court évite de confondre l’attente
initiale avec le temps nécessaire pour rédiger plusieurs centaines de lignes.

| Essai | Premier texte | Durée totale | Traitement du contexte | Débit de génération |
|---|---:|---:|---:|---:|
| Question courte | 0,399 s | 1,984 s | 0,371 s | 18,3 jetons/s |
| Même question, entrée identique | 0,094 s | 1,673 s | 0,082 s | 18,4 jetons/s |
| Historique « Anglais », nouveau préfixe | 15,873 s | 16,694 s | 15,857 s | 17,1 jetons/s |
| Exactement la même entrée | 0,116 s | 0,903 s | 0,099 s | 17,8 jetons/s |
| Une seconde changée dans la date du préfixe | 16,252 s | 17,023 s | 16,213 s | 18,2 jetons/s |
| Répétition de la dernière entrée, avec concurrence extérieure | délai dépassé | 100 s | non disponible | non disponible |

L’historique contient 24 messages et 17 300 caractères. Les trois essais
terminés avec cet historique ont reçu un contexte de 5 910 jetons selon Ollama.
Ils ajoutent une petite consigne et une question courte ; ils **n’incluent pas**
la trousse d’outils, les fichiers de personnalité et la recherche mémoire de
l’application. Ils isolent le coût du contexte ; ce n’est pas un benchmark
complet de l’interface. Le nombre d’échantillons ne permet pas de donner un p95.

Le journal Ollama explique la concurrence du dernier essai : à 14:28:13,
chargement de `qwen3.8:27b-mlx` pour une autre requête ; contexte de 10 748
jetons ; décision d’éviction liée à la mémoire à 14:28:18 ; arrêt de ce runner
à 14:29:47 puis rechargement du 9b en environ 2,77 s. La requête de mesure a
atteint sa limite à 14:29:53. L’application à l’origine de l’autre requête
n’a pas été identifiée. Cet essai ne prouve pas un blocage intrinsèque du 9b.

La différence 16 s / 0,12 s démontre la valeur de la réutilisation du contexte
dans cette situation, **pas** une promesse de répondre à toute question en
0,12 s. Ajouter un nouveau tour, changer d’outils, changer de conversation ou
charger un autre modèle peut demander de nouveaux calculs. À environ 18
jetons/s, produire 1 000 jetons représente déjà environ 56 s de génération,
hors préparation : extrapolation indicative, dépendante du contenu et du modèle.

### Lectures de l’application

Trois lectures successives par route, client HTTP local ; elles comprennent la
réception du corps, mais ni son rendu React ni les ponts Tauri/WebKit.

| Lecture | Médiane | Étendue | Corps reçu |
|---|---:|---:|---:|
| Santé | 15,79 ms | 12,48–18,52 ms | 15 octets |
| Tâches, terminées incluses | 19,20 ms | 16,41–56,60 ms | 840 823 octets |
| Notes | 4,78 ms | 4,21–7,14 ms | 965 671 octets |
| Projets | 1,98 ms | 1,75–2,94 ms | 3 361 octets |
| Tableau de bord | 14,57 ms | 12,32–15,80 ms | 4 488 octets |

Ces résultats ne révèlent pas une base SQLite lente au repos. Les corps des
notes et tâches sont toutefois volumineux pour afficher une liste ou cinq
cartes. Une pagination uniquement visuelle ne réduit pas le transfert.

## Diagnostic du code

« Confirmé » signifie observé dans les mesures ou établi par la lecture du
code. L’importance en millisecondes reste à mesurer quand elle n’est pas donnée.

| Priorité | Constat | État et conséquence | Intervention |
|---|---|---|---|
| P0 | Date à la seconde et contexte du bureau placés avant l’historique | Confirmé dans `server/routes.py`, `_now_anchor` et `_ensure_identity_prompt`. Un préfixe variable peut faire recalculer le contexte qui suit ; coût démontré par l’essai contrôlé. | Garder un préfixe stable ; placer les informations fraîches au plus près du tour courant, avec leur autorité et leur fuseau explicites. Mesurer aussi les changements de mémoire et de schémas d’outils. |
| P0 | Modèles concurrents et évictions | Concurrence et rechargement observés pendant l’essai. Le runner du 9b est lancé avec `-np 1`. | Mesurer l’attente ; coordonner les demandes internes et les travaux de fond ; éviter les changements automatiques inutiles. Ne pas augmenter aveuglément le parallélisme. |
| P0 | Travail bloquant dans des routes asynchrones | `health` appelle directement un client HTTP synchrone ; l’injection mémoire est synchrone ; `succes/routes.py` contient 55 routes `async` sans `await`, dont les lectures et écritures SQLite. Un blocage local peut retarder d’autres requêtes. | Déplacer les opérations bloquantes dans des fils adaptés, après vérification des connexions et transactions ; tester la réactivité sous contention. Une route sans `await` n’est pas à elle seule une mesure de lenteur. |
| P0 | Mesure incomplète du flux | Le moteur ne transmet pas les durées Ollama dans ses morceaux de flux ; la fin du chemin de chat ordinaire émet `stop`. La reprise longue ne restitue pas tous les compteurs cumulés. | Chronométrer chaque phase par requête ; conserver les motifs d’arrêt et agréger toutes les passes. Adapter le client aux fins autres que `stop`. |
| P1 | Tout l’historique est envoyé | Confirmé dans `Chat/InputArea.tsx`. Aucun budget de contexte spécifique à ce chemin n’est visible avant l’envoi. | Conserver l’historique intégral au stockage, sélectionner un contexte de travail pertinent, réserver la place de la sortie et des résultats d’outils. Résumer avec provenance lorsque nécessaire. |
| P1 | Trousse très large sur les demandes ordinaires | 45 noms dans la trousse par défaut, aucun remplacement configuré. Le filtre retire les outils seulement pour des salutations/acquiescements. Le nombre réellement disponible et son coût en jetons doivent être instrumentés. | Utiliser les outils adaptés au besoin, avec une voie d’élargissement. Une demande sur les tâches, l’agenda, les fichiers ou le Web doit toujours pouvoir consulter ses sources réelles. |
| P1 | Travaux d’IA supplémentaires | Mémoire automatique activée : extraction en arrière-plan avec le modèle par défaut, jusqu’à 512 jetons. Réflexion activée avec `qwen3:14b` : brouillon jusqu’à 700 jetons puis réponse, seulement sur les chemins et demandes éligibles sans outils. | Donner la priorité à la conversation ; reporter/regrouper les extractions ; réserver la double passe à un bénéfice mesuré. Ces mécanismes ne sont pas la cause démontrée de chaque attente. |
| P1 | Réponses longues : plusieurs coûts ajoutés récemment | Jusqu’à trois passes, amorce retenue jusqu’à 2 048 caractères ou détection d’une liste/table, possible régénération d’un refus technique. Ces garde-fous améliorent la complétude mais peuvent retarder le premier texte. | Réduire la rétention, annoncer honnêtement l’avancement, reprendre uniquement sur une preuve d’incomplétude, borner temps et budget. Valider les données produites, pas seulement le nombre de lignes. |
| P1 | Réécriture du stockage pendant le flux | `updateLastAssistant` relit/parcourt puis sérialise toutes les conversations dans `localStorage`, jusqu’à une fois toutes les 80 ms. Deux conversations, 38 messages et environ 27,7 Ko de messages côté serveur aujourd’hui : coût actuel non chronométré, croissance certaine du travail avec l’historique. | Garder l’état courant en mémoire, écrire uniquement les changements à une cadence distincte de l’affichage, assurer la sauvegarde finale et la reprise après incident. Préserver la fusion serveur/mini-panneau. |
| P1 | Rendu du chat très sollicité | État modifié à chaque fragment et chronomètre toutes les 100 ms ; `ChatArea` rend toute la liste ; `MessageBubble` n’est pas mémorisé ; Markdown, coloration et mathématiques reparcourent les réponses. Le défilement lit la hauteur puis déplace la vue. | Regrouper les fragments, isoler le chronomètre, stabiliser les objets/messages inchangés, mémoriser les réponses terminées, regrouper les mesures de mise en page. Profiler avant une virtualisation. |
| P2 | Listes lourdes et chargements couplés | Corps complets des notes/carnets transférés. Tâches attend aussi projets et gabarits via `Promise.all`. Le cache existant ne coordonne pas les requêtes déjà en vol. | Résumés pour les listes et détails à l’ouverture ; afficher les données essentielles dès réception ; mutualiser les lectures et ignorer les réponses périmées. Maintenir les comptes et filtres exacts. |
| P2 | Réessais trop généraux | Le client Succès peut répéter jusqu’à quatre fois toute méthode après une erreur réseau, et attend aussi sur 429 ; annulation non distinguée. Une mutation peut avoir réussi avant la perte de réponse. | Réessais limités aux cas sûrs, respect immédiat des annulations, identifiants d’opération pour les mutations qui nécessitent une reprise. |
| P2 | Travail permanent de l’interface | Synchronisation des discussions toutes les 10 s, autres sondes à 3/5/30 s ; certains minuteurs ne sont pas suspendus lorsque la vue est cachée. Rail natif sondé toutes les 0,03 s. | Adapter les travaux à la visibilité et à l’activité, sans perdre les écritures ni le retour à jour. Le sondage natif reste nécessaire au survol d’un panneau non activant : pas de remplacement naïf par `mouseenter`. |
| P2 | Liquid Glass et notes longues | Le masque du verre recalcule les géométries à chaque scroll/resize ; plusieurs observateurs peuvent déclencher des mesures. La pagination des notes utilise déjà une animation différée, mais mesure le DOM. Coût graphique non profilé ici. | Mutualiser les mesures par image, exclure les surfaces hors champ si utile, mesurer les longues tâches et la mémoire. Conserver couleurs, flous, caret, sélection, annulation et responsivité. |

## Ce qui est déjà optimisé

- Le modèle de l’essai utilise le GPU ; le préchargement existe et la rétention
  du modèle est configurée à 30 minutes. Cela ne protège pas d’une éviction.
- Le chat diffuse déjà progressivement et désactive la réflexion interne du
  modèle par défaut (`think=false`). La double passe applicative est distincte.
- Les pages Succès disposent déjà d’un cache mémoire/disque et conservent les
  données visibles pendant la relecture. Le premier chargement n’attend plus
  artificiellement le délai de recherche de 180 ms.
- Le cache est borné, les écritures sont différées, les requêtes de recherche
  ne s’accumulent pas sur disque. Son empreinte de build invalide toutefois les
  entrées à chaque reconstruction ; passer à une version de schéma explicite
  est une amélioration possible, avec validation des anciens formats.
- Plusieurs pages sont déjà chargées à la demande. Les outils du chat sont
  exécutés dans des fils et les connexions SQLite utilisent WAL.
- Le masque du verre n’utilise plus une nouvelle image SVG à chaque scroll.
  La pagination des notes et les reflets ont déjà certains regroupements par
  image. Il faut prolonger ces choix, pas réintroduire le scintillement corrigé.

## Plan d’exécution

### 1. Établir les mesures fiables et protéger la réactivité

Ajouter un identifiant de requête et des durées : préparation, recherche mémoire,
attente du moteur, chargement, lecture du contexte, premier fragment moteur,
premier texte visible, génération, outils et reprises. Ne journaliser ni clés
ni contenu privé. Le serveur ne connaît pas directement toute l’attente interne
d’Ollama : présenter les valeurs mesurées et les estimations séparément.

Sortir de la boucle principale les appels réellement bloquants identifiés ;
annuler les requêtes abandonnées et distinguer une fin normale d’une coupure.
Premier livrable : tableau avant/après et tests de réactivité sous charge.

### 2. Réduire le temps avant le premier mot

Réorganiser le contexte pour préserver son préfixe stable. Garder date, heure,
état du bureau et mémoire à jour, sans recopier des blocs volatils en tête.
Fixer un budget partagé entrée/sortie/outils plutôt que seulement augmenter
`max_tokens`. Tester une suite de vrais tours consécutifs et deux discussions
alternées, pas uniquement la répétition artificielle d’un même appel.

Introduire une sélection prudente des outils, avec élargissement possible et
vérification des demandes ambiguës. Les consignes de sécurité et la politique
d’approbation restent celles de l’exécuteur. Aucune action n’est inventée.

### 3. Organiser l’usage du modèle

Donner une priorité explicite aux demandes interactives et placer l’extraction
mémoire après elles, avec file bornée et fusion des travaux compatibles. Ne
pas promettre d’interrompre proprement une génération déjà exécutée dans un
fil sans construire et tester son mécanisme d’annulation.

Éviter les changements de modèle déclenchés par des tâches accessoires.
Comparer les modèles installés sur les mêmes cas avant toute modification
du défaut. Les demandes d’autres programmes à Ollama restent hors de la file
interne de Diapason : détecter cette concurrence et la signaler honnêtement.

### 4. Produire de longues réponses sans gaspiller

Séparer préparation de données et présentation quand le résultat demandé est
très structuré. Afficher progressivement ce qui est validé. Réviser le tampon
initial et la stratégie de reprise ; cumuler correctement les compteurs et
réserver le contexte nécessaire à chaque suite. Respecter le nombre demandé
lorsqu’il est factuellement possible, sans fabriquer des entrées.

Les tests synthétiques vérifient quantité, doublons, ordre, coupure et annulation.
Un tableau de verbes exige en plus un contrôle de qualité des formes : compter
400 lignes ne valide pas 400 verbes corrects. Ne pas présenter une nouvelle
limite arbitraire de 50 ou 100 entrées comme une amélioration de vitesse.

### 5. Fluidifier la fenêtre et le mini-panneau

Découpler réception, rendu et sauvegarde des messages. Préserver l’identité des
messages inchangés avant d’ajouter la mémorisation React. Ne pas faire analyser
à nouveau toutes les anciennes réponses à chaque tic du chronomètre. Sauvegarder
à la fin, au changement de visibilité et lors de la fermeture, avec reprise
des écritures en échec. Tester simultanément les deux vues et la déconnexion.

Profiler les tableaux longs, les notes paginées et le Liquid Glass dans le
vrai WebKit ; vérifier aussi WebView2 sur Windows. Toute optimisation doit
conserver sélection, copier-coller enrichi, recherche et navigation vers un
message, saisie fluide et fidélité des thèmes.

### 6. Alléger les modules et le travail en arrière-plan

Ajouter des lectures de résumés et des détails ciblés, compatibles avec les
clients existants. Un nouvel endpoint implique son instantané de contrat.
Maintenir un cache validé et versionné, les invalidations après mutation,
l’ordre manuel, les comptes des tâches terminées et les pastilles du calendrier.

Mutualiser les requêtes en cours, empêcher une ancienne recherche d’écraser
la suivante, découpler les données secondaires et borner les réessais sûrs.
Suspendre les sondes inutiles hors écran, relire au retour au premier plan.
Optimiser les couches graphiques à partir de profils, sans retirer le style.

### 7. Valider puis comparer une solution distante si nécessaire

Après chaque lot, rejouer les mêmes scénarios et publier les mesures. Lancer
les contrôles complets du dépôt avant une publication. Une mise en ligne ou un
changement global de modèle ne fait pas partie de ce diagnostic.

Si le débit local reste insuffisant pour les longues productions, comparer une
instance GPU ou une API avec le même jeu d’essai : attente, débit, exactitude,
coût réel et données transmises. Un VPS CPU n’est pas un substitut mesuré à ce GPU.

## Critères de réussite

| Scénario | Vérification attendue |
|---|---|
| Question courte, modèle chaud | Premier texte visible visé sous 2 s au p95 dans un test contrôlé sans concurrence extérieure ; mesurer avant de promettre. |
| Discussion longue | Réduction mesurée du temps de préparation et du premier mot ; les informations utiles et les références restent accessibles. |
| Nouveau tour pendant une extraction mémoire | Priorité à l’interaction et attente expliquée ; aucune disparition de mémoire ou de message. |
| Deux vues, deux discussions | Aucun mélange, aucun remplacement de message ; annuler l’une n’annule pas l’autre. |
| Outils | Lecture réelle pour les données personnelles et actuelles ; aucune action répétée lors d’une reprise de texte. |
| Long tableau | Ordre, contenu, nombre d’entrées, unicité et export vérifiés ; réponse partielle explicitement identifiée. |
| Succès sous charge | Lectures visées sous 100 ms au p95 sur le jeu actuel ; objectif distinct du temps d’affichage dans la WebView. |
| Retour sur une page en cache | Contenu utile visé sous 100 ms ; relecture discrète et cache invalidé correctement après une modification. |
| Défilement et saisie | Mesurer le budget d’image selon l’écran ; viser l’absence de longues tâches > 50 ms dans les parcours usuels, sans scintillement. |
| Repos | CPU, GPU, mémoire et sondes comparés pendant une période stable ; pas d’augmentation continue de mémoire. |
| Windows et Mac | Vérifications natives de saisie, redimensionnement, thèmes, menus, copie et mini-panneau ; pas de déduction à partir d’un seul navigateur. |

## Périmètre restant à mesurer

Les lots 5 et 6 apportent un profil JavaScript contrôlé et des vérifications
des listes dans WebKit. Restent
le rendu de production et son coût graphique, WebView2, la consommation au
repos, le lancement à froid, un p95 représentatif et la saturation de SQLite.
Le lot 3 mesure le nombre de schémas envoyés dans une vraie requête Diapason.
Les gains des différents lots ne doivent pas être additionnés : les essais
ne mesurent ni le même périmètre ni toujours les mêmes conditions.

Les essais en cours de session ayant partagé Ollama avec une autre requête,
les comparaisons finales devront prévoir une fenêtre de mesure sans concurrence
extérieure, puis une seconde campagne avec concurrence volontaire.

## Sources locales

- [Mesures brutes sans contenu des discussions](mesures-performances-2026-09-19.json).
- [Routes et préparation du chat](../../src/diapason/server/routes.py).
- [Moteur Ollama](../../src/diapason/engine/ollama.py).
- [Reprises longues](../../src/diapason/server/reponses_longues.py).
- [Envoi et réception du chat](../../frontend/src/components/Chat/InputArea.tsx).
- [État et sauvegarde des conversations](../../frontend/src/lib/store.ts).
- [Rendu des messages](../../frontend/src/components/Chat/MessageBubble.tsx).
- [Cache Succès existant](../../frontend/src/features/succes/cacheSucces.ts).
- [Client des requêtes Succès](../../frontend/src/features/succes/api.ts).
- [Géométries du verre](../../frontend/src/components/Chat/verreTexture.ts).
- [Convention de synchronisation des discussions](conversations-sync.md).
- [Convention du mini-panneau](mini-panneau-responsive.md).
