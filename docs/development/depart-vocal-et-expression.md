# Départ vocal et expression d’Orion

27 septembre 2026. **Activé dans l’application installée** après la demande
explicite de Carlito de mettre ces changements dans l’application ouverte.
La reconstruction et l’installation signée ont réussi, Diapason a été
relancé et le serveur local rechargé.

## Fermer une séance à la voix

Quelques formules reconnues, avec leurs variantes de ponctuation, accents,
politesse et tutoiement/vouvoiement :

- « Merci Diapason, ce sera tout. »
- « Diapason, tu peux disposer. »
- « Diapason, j’en ai fini avec toi. »
- « On s’arrête là pour aujourd’hui, Diapason. »
- « Diapason, je n’ai plus besoin de toi pour le moment. »
- « À bientôt, Diapason. »
- « Diapason, termine la conversation et coupe le micro. »

Le serveur vérifie l’adresse et l’identité comme pour une autre demande.
Une voix trop brève pour être identifiée peut encore nécessiter quelques
mots supplémentaires. Le mode temporaire entre IA conserve ses règles.

La reconnaissance de départ porte sur la phrase entière, avant de retirer
le nom Diapason. Une question, une citation ou une négation ne déclenche
pas la fermeture. « Stop », « attends » et « c’est bon » restent de simples
interruptions. Les formulations inconnues ne sont pas devinées par un
second appel au modèle.

Le serveur émet `closing` avec `reason: "farewell"`. Le client arrête les
pistes du micro et la capture, bloque toute reprise, puis joue le bref
« À bientôt. » produit par le même moteur Orion. Le serveur émet les
transcriptions et le dernier PCM avant `closed`, puis libère la séance.
Le client laisse finir les paquets reçus avant de refermer le contrôle vocal.
La fenêtre séparée se ferme également ; l’application et le chat restent.
Les deux messages suivent la sauvegarde habituelle du fil.

Une synthèse impossible ne bloque pas le départ : plafond serveur de huit
secondes pour cette seule formule. Côté client, douze secondes bornent la
fermeture si le dernier événement ou la fin de lecture manque ; le micro
est déjà éteint. X et Échap restent immédiats, sans attendre la formule.

## Expression mesurée

La consigne vocale autorise une interjection pertinente (« ah », « oh »,
« eh bien ») et une onomatopée qui illustre un son (« toc-toc », « boum »).
Elle demande de ne pas en mettre à chaque tour, de ne pas répéter une
amorce, de ne pas modifier une citation et de ne pas simuler des rires,
soupirs ou émotions humaines. Aucun ajout aléatoire au texte, aucun effet
sonore ajouté au PCM, aucun changement de référence vocale.

Ce sont des consignes de rédaction ; elles ne prouvent pas à elles seules
que chaque réponse du modèle les suivra. Le naturel des sons non verbaux
reste à juger à l’écoute d’Orion après activation.

## Annoncer une recherche

Pour `web_search` et `web_read`, une courte annonce est possible après
400 ms d’appel encore en cours. Un appel rapide n’en reçoit aucune. Les
phrases varient entre les tours et ne doublent pas une explication déjà
prononcée dans la réponse. Aucun compte à rebours ni résultat anticipé.
Un budget épuisé ou un exécuteur absent ne produit pas d’annonce.

L’appel s’exécute pendant la synthèse de l’annonce. Une annonce commencée
va au bout : annuler Orion au milieu de ce calcul tuerait son ouvrier et
imposerait un rechargement avant la vraie réponse. Une opération qui finit
pendant cette courte phrase peut donc attendre la fin de sa préparation.
L’interruption volontaire annule toujours le tour. Le moteur, le timbre,
le contexte et la qualité demandée à la réponse restent les mêmes.

## Vérifications

La vérification élargie voix, routes vocales, profil et contrat tailnet
compte 695 tests réussis, sept cas optionnels sautés et trois tests live
exclus. Le contrôle final du départ, des annonces et des interruptions
passe ses 157 tests, dont les trois cas supplémentaires sur les apostrophes
et « attends ». Le dossier de configuration était
temporaire, sans toucher au profil réel. Les tests couvrent notamment les
faux départs, le verrou d’identité, l’ordre micro/audio/fermeture, une panne
de synthèse, X pendant la préparation et la fermeture effective du pont.

TypeScript et les 25 tests de traduction passent. Les 64 tests frontend
ciblés couvrent la capture, le
lecteur, la conservation des messages, la synchronisation et la fin vocale,
y compris une permission micro tardive et un lecteur qui ne termine pas.
Les tests des annonces contrôlent leur absence pour un appel rapide ou
refusé, leur variation, leur ordre après l’appel et leur annulation.

Aucune nouvelle mesure de latence de conversation complète ni validation
de prosodie réelle n’est revendiquée par ces tests.

Contrôle après activation : la santé vocale annonce le moteur local prêt
avec Orion ; un vrai échange WebSocket reçoit une formule de départ saisie
par le banc, puis émet `closing`, les deux transcriptions finales, 1,04 s de
PCM et `closed` avec le motif `farewell`. La préparation de cette séance
d’essai a pris 8,5 s. Aucun micro n’a été ouvert, aucun son joué et les outils
étaient désactivés pour ce contrôle. L’interface native relancée a été lue :
le chat est présent et propose de démarrer la conversation vocale.

L’écoute des interjections et onomatopées en conversation réelle reste à
valider avec Carlito ; leur intégration ne garantit pas à elle seule leur
prosodie.
