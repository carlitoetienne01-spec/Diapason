# Le terminal du chat affiche des observations

Intégration du 22 septembre 2026. La démonstration animait un scénario ; le
produit se branche sur les événements existants. La frise « rechercher / lire /
répondre » a été retirée à la demande de Carlito.

Le panneau apparaît dès l'envoi, y compris avant le premier appel d'outil.
Il reste ouvert pendant l'arrivée de la réponse et après la clôture du flux.
Seul « Replier » le ferme ; les nouveaux fragments ne le rouvrent pas.
L'historique chargé ultérieurement commence replié. Le journal suit les
nouvelles lignes tant que l'utilisateur ne remonte pas lui-même.

## Ce que les mesures signifient

- `tool_call_start` ajoute un appel, avec son vrai nom et ses arguments JSON.
  La commande n'invente pas de paramètres de shell (`--limit`, etc.).
- `tool_call_end` confirme la fin. Seul `success: true` donne « Exécuté » ;
  `false` donne « Échec ». Un indicateur absent ne devient pas une réussite.
- `latency` est en **secondes**. Les barres comparent les durées reçues du
  serveur, sans les additionner : des outils peuvent être imbriqués. Une
  barre n'est jamais un pourcentage de progression.
- `result` est un **extrait reçu**, parfois tronqué en amont. Ce n'est pas la
  page entière et sa longueur ne mesure pas le trafic réseau. Chaque ligne
  DATA reprend cet extrait sans inventer d'étapes JOIN, SORT ou DRAW.
- La recherche approfondie fournit `search_call` et `search_result`. Ni durée
  ni nombre de résultats ne sont ajoutés quand ils manquent dans ces événements.
- Une fin de flux sans fin d'outil devient « État non confirmé ». Cela ne prouve
  ni une erreur, ni l'arrêt du travail serveur. Les historiques incomplets
  suivent la même règle. CLOSE indique la fermeture du flux, pas une preuve
  d'exactitude de la réponse.
- Le flux n'a pas d'identifiant d'appel : deux appels homonymes simultanés ne
  peuvent pas être appariés sûrement. Ils restent non confirmés. Le chemin
  courant exécute les outils successivement, avec une lecture automatique
  `web_read` éventuellement imbriquée dans `web_search`.
- « Flux SSE reçu » compte les **octets effectivement lus** dans le corps de
  la réponse HTTP, avant décodage UTF-8, enveloppes SSE comprises. Les points
  sont des tranches d'une seconde depuis l'envoi ; la tranche en cours est
  partielle. Ce n'est ni le débit d'une recherche web, ni celui du modèle.
  Le graphe conserve 30 secondes visibles, les mesures 60 secondes maximum.
  Le compteur total conserve tous les octets. Le graphe se fige à la clôture.
- L'aperçu hexadécimal contient les 16 derniers octets réellement reçus.
  Les temps `t+` et l'ordre du journal sont mesurés côté client à réception.
  Les anciennes discussions sans mesures affichent cette absence explicitement.

Une impulsion décorative accompagne les changements reçus. Elle ne représente
pas un paquet réseau ou une progression. Aucun débit ou code de sortie shell
simulé n'est affiché. « Exécuté » qualifie l'outil, pas l'exactitude factuelle
de sa sortie ou de la réponse du modèle.

## Rendu et animations

Le laser suit le dernier texte déjà rendu ; il ne retape pas la réponse et
ne retarde pas sa livraison. Il reste visible 1,2 seconde après le dernier
fragment, même si celui-ci a clôturé le flux dans le même rendu React. Il est
en dehors du contenu copiable. Le contenu Markdown, les tableaux, les liens
et les formulaires restent ceux du chat.
Les animations sont finies, silencieuses et désactivées avec la préférence
système de réduction des mouvements.

Les couleurs viennent des variables du thème, avec un faisceau ambré pour
Ardéchine comme dans la capture approuvée : son accent noir masquait le laser.
Le terminal utilise la même découpe du verre que le compositeur. Sa largeur
est gérée par des requêtes de conteneur et sa hauteur bornée selon la fenêtre.
Dans le mini-panneau étroit, les mesures secondaires sont allégées.

Vérifications automatisées : `terminalExecution.test.ts` (états et laser),
`receptionTerminal.test.ts` (comptage UTF-8, silence, courbe, chronologie) et
`lib/sse.test.ts` (réception d'un appel avant la réponse finale).
Vérification visuelle sur le vrai ChatArea avec un service SSE local de test :
panneau avant le premier outil, réponse et journal simultanés, laser sur une
réponse en un seul bloc, repli manuel conservé, thèmes et largeur de 340 px.
