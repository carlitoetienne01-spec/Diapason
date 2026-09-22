# Modèle de menaces

## Périmètre

Diapason est un assistant local d'abord qui peut lire des fichiers, exécuter du
code, accéder au réseau, appeler des modèles externes et envoyer des messages
quand les outils correspondants sont activés. Les biens à protéger sont tes
données, tes identifiants, tes fichiers locaux, le contexte du modèle,
l'intégrité de l'audit et le contrôle de la machine.

## Frontières de confiance

| Frontière | Entrée non fiable | Contrôle exigé |
|---|---|---|
| Navigateur/bureau → API locale | Requêtes, WebSockets | Authentification Bearer, liste d'autorisation CORS, limite de débit |
| Prompt/modèle → exécuteur d'outils | Nom de l'outil et arguments | Liste d'autorisation par nom exact, capacités, confirmation, délai d'attente |
| Appareil → réseau/cloud | Prompts, fichiers, audio, captures d'écran | Verrou « local seulement », contrôles SSRF, balayage des secrets et données personnelles à la frontière |
| Exécution → système de fichiers/processus | Chemins et commandes | Politique des fichiers sensibles, contrôle de capacité, confirmation, bac à sable là où il est configuré |
| Exécution → journaux/traces | Résultats et métadonnées | Caviardage avant écriture, preuves de sécurité hachées, fichiers lisibles du seul propriétaire |
| WebView du bureau → hôte natif | Commandes Tauri | Surface de commandes étroite et manifeste de capacités ; aucune permission du plugin shell |

## Principales menaces et parades

- **Injection de prompt et usage d'outil par délégué abusé (confused deputy) :**
  les outils sont bornés à l'ensemble configuré, les octrois de capacité portent
  sur des noms d'outils exacts, et les outils sensibles demandent une
  approbation.
- **Exfiltration d'identifiants ou de données personnelles :** le mode « local
  seulement » bloque par défaut les chemins distants ; les charges sortantes et
  le trafic vers les modèles sont balayés puis caviardés ou bloqués selon le
  profil.
- **Accès non authentifié à l'API locale :** chaque démarrage du serveur résout
  une clé explicite ou en crée une de 256 bits, lisible du seul propriétaire ;
  les routes de données HTTP et WebSocket la vérifient.
- **Abus et épuisement des ressources :** seaux à jetons au niveau de l'API et
  par outil, délais d'attente sur les outils, limites de taille de requête là où
  les routes en définissent, et concurrence bornée.
- **SSRF et accès dangereux aux fichiers :** les destinations d'URL et les
  chemins sensibles sont vérifiés avant tout accès.
- **Fuite de secrets par l'observabilité :** les entrées d'audit enregistrent
  des empreintes et des longueurs plutôt que les valeurs trouvées ; les
  événements d'outil caviardent arguments et résultats.
- **Élargissement des privilèges sur le bureau natif :** la WebView n'a aucune
  permission générique d'exécution shell, ni spawn, stdin, kill ou open.
- **Compromission de la chaîne d'approvisionnement :** les fichiers de
  verrouillage sont suivis en dépôt ; la CI doit passer les contrôles de
  dépendances, de secrets, de licences et de provenance avant une publication.

## Profils de sécurité

- `personal` (par défaut) : serveur sur la boucle locale, confidentialité
  « local seulement », caviardage, 60 requêtes par minute avec une rafale de 10,
  approbation exigée pour les outils sensibles.
- `shared` : serveur sur la boucle locale avec la même application des règles ;
  les administrateurs doivent fournir une politique de capacités explicite quand
  plusieurs personnes l'utilisent.
- `server` : mode blocage, 30 requêtes par minute avec une rafale de 5. Une
  exposition hors de la boucle locale exige du TLS sur un proxy inverse et un
  secret géré.

## Risques résiduels

La sortie du modèle n'est pas fiable, la détection par expressions régulières ne
reconnaît pas tous les secrets, l'exécution de code en local hérite des droits
de l'utilisateur de la machine tant que le bac à sable n'est pas activé, et une
dépendance compromise s'exécute dans le même processus. L'approbation d'une
version exige donc qu'aucun constat de gravité High/Critical ne soit connu, plus
une revue indépendante pour les déploiements exposés à Internet ou à fort enjeu.
