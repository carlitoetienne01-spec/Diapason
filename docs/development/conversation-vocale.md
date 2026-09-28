# Essai vocal entre IA — 26 septembre 2026

Dans **Parler**, le bouton **Conversation entre IA — cette session uniquement**
ouvre une séance locale sans reconnaissance du propriétaire. Le bouton habituel
**Commencer à parler** garde le comportement normal. Le choix n'est pas conservé
entre deux séances et ne modifie ni la configuration ni le profil vocal.

Ce mode existe pour les essais au haut-parleur : l'annulation d'écho pouvait
écarter la voix de l'autre application, et le filtre du propriétaire pouvait
refuser une autre voix. Il ne faut pas désactiver ces deux protections dans le
mode normal pour réaliser un essai.

## Limites appliquées dans le serveur

- Aucun outil, y compris les actions vocales rapides et les appels directs à
  l'exécuteur. Les options du client ne peuvent pas rouvrir les outils.
- Aucun contexte du bureau ni mémoire personnelle injectée ; les échanges
  temporaires ne nourrissent pas les traces et la mémoire du propriétaire.
- Aucun message du fil de Discussion (28/09/2026) : ouvert depuis le menu +,
  ce mode recevait les seize derniers messages du propriétaire. Le client ne
  les envoie plus ; la route et `LocalVoiceSession` ignorent `history`.
- Aucune lecture, écriture ou réinitialisation de l'empreinte vocale.
- Fournisseur local uniquement ; mode refusé au téléphone.
- Limites de durée et d'inactivité de `VoiceLiveBridge` conservées.

## Protocole et lecture

La trame `start` contient `conversationOnly: true`. Le serveur confirme avec
`ready` et `conversationOnly: true`. En l'absence de confirmation, le client
ferme le micro sans lui avoir transmis de son : un ancien serveur ne doit pas
ignorer la restriction tout en exécutant des commandes.

Le client demande une capture sans annulation d'écho ni réduction du bruit.
Il suspend l'envoi pendant la lecture de Diapason, puis pendant 300 ms pour
laisser retomber la réverbération. Le serveur écarte également l'audio pendant
tout le tour de réponse (transcription et préparation comprises), puis pendant
la durée estimée de sa propre lecture. Les silences entre deux morceaux ne
rouvrent ainsi pas l'écoute. **Reprendre la parole** reste disponible
au clic ; la reprise vocale automatique est réservée au mode normal.

Les tests de `test_conversation_entre_ia.py`, de la route et de `useVoiceLive`
vérifient ces limites, l'acquittement et le retour au mode normal. L'essai
acoustique au haut-parleur a ensuite été vérifié dans l'application : la
question de Codex sur un exercice quotidien d'anglais a été transcrite et a
reçu une réponse, suivie d'un second échange sur la répétition de phrases.
La transcription comporte encore des erreurs de mots. Une réponse au seul
propriétaire ne constitue pas une preuve de réception de l'autre IA.

## Diagnostic qualité — 27 septembre 2026

L'essai précédent prouve la réception de deux voix, pas la fidélité de la
transcription ni le naturel de la conversation. Mesures du journal réel :
transcription 3,4 à 8,5 s, premier son 4,6 à 9,1 s supplémentaires après
transcription ; plusieurs mots mal reconnus au haut-parleur. Le mode invité
est volontairement en alternance, sans interruption vocale automatique.

Deux défauts corrigés dans le parcours normal et invité :

- Une transcription annulée via `asyncio.to_thread` continuait réellement
  sur le CPU. Les partiels, spéculations et finales pouvaient se concurrencer.
  `TranscriptionSerie` garde le créneau jusqu'à la fin native, même après
  abandon ; une attente annulée n'exécute jamais son ancien enregistrement.
- La couverture de l'ancien texte partiel suivait le lancement du prochain
  calcul. Une phrase ancienne paraissait donc à jour et pouvait raccourcir
  à tort la fin de tour. Le texte possède maintenant sa propre borne audio.

La formulation des réponses distingue également conseil et action sur le
Mac ; une demande d'exercice ne justifie pas de réciter l'absence d'outils.
Ces consignes améliorent le cadrage, sans garantir à elles seules la réponse
produite par le modèle.

Banc local de synthèse (M5, 32 Go, Kokoro, mêmes textes) : quatre phrases
nouvelles demandent 0,28 à 0,57 s sur CPU, contre 0,91 à 1,28 s sur MPS.
Une phrase répétée est plus rapide sur MPS une fois chaude, ce qui ne suffit
pas à justifier un changement de moteur de calcul par défaut. Un rythme de
synthèse à 1,08 est proposé en échantillon, pas activé dans le produit.

Validation : 474 tests voix/routes passent, 7 tests optionnels sont sautés.
Les échantillons synthétiques ne mesurent PAS le taux d'erreurs sur la voix
de Carlito. Il reste à comparer une phrase réelle et sa transcription après
rechargement, puis à juger le timbre et la prosodie à l'écoute. Aucun audio du
micro n'a été enregistré pour ces bancs ni envoyé à un fournisseur distant.

### Échantillons d'un autre moteur, hors application

Le banc isolé `/private/tmp/diapason-essai-voix/mlx-env` utilise MLX Audio
avec `mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-4bit`. Les poids publics
ont été téléchargés explicitement pour cet essai ; la synthèse elle-même
est locale, à partir d'un texte générique et d'une description de voix.
Aucun clonage de voix. Aucune dépendance ajoutée au venv du produit.

Premier échantillon : premier morceau en 4,17 s à froid, total 7,64 s pour
9,84 s d'audio. Second après chargement : premier morceau en 0,25 s, total
2,85 s pour 7,52 s d'audio. Ces chiffres concernent uniquement la synthèse,
PAS le délai d'une conversation complète (micro, STT, modèle, lecture).
L'application conserve Kokoro : le choix d'un timbre et la validation d'une
intégration réellement en flux précèdent tout remplacement.

Sources des capacités examinées :
- https://github.com/QwenLM/Qwen3-TTS
- https://github.com/Blaizzy/mlx-audio
- https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md

Le contrôle de fidélité a rejeté le premier extrait masculin : deux
transcripteurs y relevaient un « ne » absent du texte demandé. Il n'est pas
présenté comme candidat validé. Une seconde génération mesure 0,41 s avant
le premier morceau et 2,89 s au total pour 7,2 s d'audio. Les rendus restent
des démonstrations : un contrôle ASR n'est pas un jugement humain du timbre.

### Choix A/B intégré — 27 septembre 2026

Carlito conserve A et B et choisit **B par défaut**. Les références
synthétiques sont dans `speech/realtime/voix/` ; ce ne sont pas des voix
enregistrées au micro. Qwen3-TTS **Base** conserve leur timbre sur les nouveaux
textes. Le banc VoiceDesign ne sert plus au parcours applicatif.

Installation explicite sur Mac Apple Silicon :
`.venv/bin/python scripts/install-expressive-voices.py`. Elle prépare
`~/.diapason/voices/qwen3/runtime` et un modèle à révision fixée, sans modifier
le venv produit ni la voix par défaut. Aucun téléchargement au démarrage
d'une conversation. Les autres plateformes gardent leur voix classique.

Dans **Parler**, le sélecteur propose B, A et la voix classique. Le choix
passe par la configuration du serveur et reste identique entre les fenêtres.
Il se fait avant la séance : une séance en cours conserve le timbre avec
lequel elle a démarré, même si une autre fenêtre change le défaut.

Le serveur isole MLX dans un processus par séance ; le texte et le PCM
circulent par des tubes locaux. Le moteur produit des morceaux progressivement ;
depuis le diagnostic de continuité ci-dessous, le serveur prépare une phrase
complète avant de transmettre ses morceaux au lecteur.
Une interruption arrête le processus et jette sa sortie ; le tour suivant
redémarre un moteur propre. La fermeture libère aussi le modèle. Les accusés
préenregistrés Kokoro ne sont pas joués avec A/B. Si le moteur choisi manque
ou échoue, l'erreur est visible : aucun remplacement silencieux de timbre.

Mesures réelles sur quatre phrases synthétiques, après préparation : premier
morceau 0,25–0,28 s ; total 1,43–2,90 s pour 3,76–8,16 s d'audio. Le premier
chargement à froid a demandé 20,6 s (séance suivante 1,8 s). Ces mesures ne
sont pas le délai de la conversation complète. Les quatre rendus sont relus
par Whisper large-v3-turbo ; les phrases sont conservées, à la ponctuation
et à une transcription singulier/pluriel homophone près. Le naturel reste
à juger par Carlito en conversation.

Validation du raccordement : 482 tests voix/routes passent, 7 sont sautés ;
40 tests ciblés côté interface et TypeScript passent. Les tests couvrent le
choix durable, le flux avant sa fin, l'annulation du vrai calcul, le refus
d'un format PCM invalide et la conservation du timbre de la séance.

Essai après installation : le vrai WebSocket local accepte le mode sans
outils ni mémoire, transcrit l'audio synthétique envoyé et retourne le texte
assistant ainsi que 25 morceaux PCM. Ce banc n'ouvre pas le micro. Dans
l'application reconstruite, le passage A puis B est vérifié au sélecteur ;
B est laissé sélectionné, micro fermé. Le serveur confirme B par défaut.

### Coupures de la voix B — 27 septembre 2026

Le test au haut-parleur révèle des mots hachés. Un banc sans micro reproduit
le défaut sur 18,56 s de PCM synthétique : 21,20 s de calcul seul, avec
15 ruptures de réserve supérieures à 15 ms. Pendant une génération Ollama,
le même texte demande 43,31 s et produit 38 ruptures, jusqu'à 1,34 s.
Ces durées décrivent la charge de ce banc, pas une vitesse garantie du Mac.
Le lecteur lançait chaque paquet de 480 ms dès réception : quand le calcul
est durablement plus lent que la parole, aucun petit tampon ne suffit.
Un essai de paquets plus longs (1,44 s) réduit les ruptures mais ne les
supprime pas ; ce changement seul n'est donc pas retenu.

Pour A/B, une phrase est maintenant entièrement préparée avant sa lecture,
puis envoyée en paquets bornés sans calcul entre eux. Une annulation ou une
erreur abandonne tous ses morceaux ; une sortie vide est une erreur visible.
La première virgule ne sépare plus artificiellement une proposition en deux
synthèses. Web Audio conserve 60 ms de marge au lancement, sans ajouter un
silence entre les paquets déjà en file. La phrase suivante peut être
préparée pendant la lecture de la précédente.

**Limite explicite :** cette correction privilégie une phrase continue.
Elle peut augmenter l'attente avant les premiers mots ; une machine qui
calcule plus lentement que la lecture peut encore attendre entre deux
phrases. Elle ne prouve ni une conversation sans délai ni le naturel du
timbre. Les erreurs de reconnaissance observées restent un sujet distinct.

Le panneau n'ouvre plus une dictée Apple parallèle pour ses sous-titres :
ses partiels viennent du même flux que les transcriptions finales utilisées
par le modèle. Cela supprime les deux versions concurrentes d'une question,
sans promettre que Whisper ne se trompera plus.

Validation de ce correctif : 486 tests voix/routes passent (7 sautés), puis
12 tests ciblés après ajout du cas de synthèse vide ; 41 tests du lecteur,
du hook et du protocole passent, ainsi que TypeScript. Le bundle a été
reconstruit, signé avec l'identité Apple existante, installé et le serveur
rechargé. L'écoute réelle reste nécessaire pour juger les pauses entre
phrases et le timbre.

Essai réel après relance, au haut-parleur : la demande d'un conseil simple
pour apprendre l'anglais reçoit une réponse pertinente en B. « Diapason »
est encore mal reconnu, mais le reste de la question est conservé. Le
journal confirme deux phrases entièrement préparées : 9,38 s de calcul
pour 5,44 s de son, puis 9,12 s pour 6,96 s. Premier audio 13,46 s après
la transcription (celle-ci a pris 4,01 s). Il subsiste donc une attente
estimée à 3,68 s entre les phrases : la continuité des paquets ne résout
pas le débit insuffisant de la synthèse. Le micro est refermé après ce
seul échange pour éviter une boucle entre assistants. Aucun jugement
subjectif d'écoute n'est déduit de ces mesures.

### Amorce des phrases — 27 septembre 2026

Carlito confirme que les coupures de mots sont corrigées, mais signale les
premiers mots mal reconnus. Le pré-roll conserve déjà 400 ms de son faible ;
le second filtre Silero ne conservait pourtant que 80 ms de marge. Sur une
phrase synthétique disant « Diapason, donne-moi un conseil simple pour
apprendre l'anglais », le décodage commence à 336 ms et rend « D'y a pas
ont ». Une marge de 400 ms conserve l'audio dès 16 ms. Le décodage glouton
reste insuffisant (« Dépasons »), alors que trois hypothèses rendent le nom
correct sans mot-indice ni remplacement après transcription.

Le parcours temps réel passe donc à 400 ms de marge et trois hypothèses,
sans dictionnaire ni contexte précédent. La détection de bruit reste
active. Banc de trois phrases, chacune normale et avec une amorce affaiblie :
six résultats fidèles avec le nouveau réglage. La première phrase passe
de 1,51 à 1,56 s de transcription. Ces phrases synthétiques ne remplacent
pas une mesure sur la voix de Carlito.

Autre défaut indépendant : READY du serveur pouvait afficher « Je t'écoute »
pendant que la permission micro ou le worklet attendait encore. L'affichage
attend désormais le serveur **et** le premier paquet audio non vide capturé.
Aucun son n'est envoyé avant READY ; une fermeture/erreur invalide les
callbacks tardifs. Deux tests exercent les deux ordres d'arrivée.

Validation : 488 tests voix/routes passent, 7 tests optionnels sont sautés ;
43 tests du lecteur, du hook et du protocole ainsi que TypeScript passent.
Un test de frontière Silero vérifie que l'attaque conservée dans le
pré-roll n'est pas coupée une seconde fois.

### Timbre pendant la réponse — 27 septembre 2026

Carlito apprécie A et B mais constate que le timbre change au fil de la
parole, au-delà des variations d'intonation souhaitées. Le moteur conserve
déjà une référence fixe par voix ; les anciens accusés Kokoro sont écartés.
Il reste une différence dans MLX Audio 0.5.6 : le décodage ICL complet
préfixe les codes générés avec ceux de la référence, puis retire sa durée.
Le décodage incrémental `streaming_step` part d'un état vide sans ce préfixe.
Sources du chemin examiné :
[MLX Audio, Qwen3-TTS](https://github.com/Blaizzy/mlx-audio/blob/main/mlx_audio/tts/models/qwen3_tts/qwen3_tts.py)
et [implémentation Qwen](https://github.com/QwenLM/Qwen3-TTS/blob/main/qwen_tts/inference/qwen3_tts_model.py).

Banc local : trois textes, chacun en A et en B, mêmes graines, température
et références, comparés avec les deux décodages. Les six rendus complets
se rapprochent de leur référence selon l'encodeur de locuteur du moteur :
similarité cosinus moyenne B 0,9891 → 0,9924 ; A 0,9875 → 0,9922. Ce sont
des **indicateurs internes**, pas des pourcentages de qualité ni une preuve
que le défaut audible de Carlito est entièrement résolu. Les durées sont
identiques entre modes ; la transcription de contrôle retrouve tous les
mots des six nouveaux rendus. Aucune modification de température, vitesse,
hauteur ou ponctuation n'est utilisée pour aplatir l'intonation.

L'ouvrier utilise désormais le décodage complet, puis découpe le PCM en
trames de 480 ms. La phrase était déjà tamponnée côté serveur : le décodage
incrémental n'avançait donc plus sa lecture. Une sortie vide, non finie,
de mauvaise fréquence ou ayant épuisé le plafond de génération échoue
avant tout envoi ; aucun résultat tronqué n'est présenté comme complet.

Dans le vrai processus corrigé, trois phrases successives donnent :

| Voix | Calcul par phrase | Durée audio par phrase |
|---|---|---|
| B | 1,58 / 2,33 / 3,95 s | 2,96 / 5,44 / 10,16 s |
| A | 1,50 / 2,41 / 4,75 s | 2,64 / 5,28 / 11,60 s |

Le calendrier de lecture simulé ne manque de réserve entre aucune de ces
phrases. Ce banc ne sollicite pas simultanément Ollama ; il ne mesure ni
la latence complète ni les pauses possibles sous une autre charge. Le
décodage complet coûte lui-même environ 0,4–0,9 s de plus sur ces extraits
que le décodage incrémental : c'est un choix de qualité, pas un gain de débit.

Après rechargement, un essai WebSocket avec audio synthétique, sans outils
ni mémoire, reçoit une transcription puis 19 trames (8,96 s de voix).
Transcription 1,57 s ; premier audio 8,28 s après celle-ci, dont 5,20 s de
synthèse d'une première phrase longue. Ce test ne prouve pas une voix rapide.

Pour diminuer cette attente sans rejouer des fragments hachés, la consigne
orale demande une première phrase courte **et utile**, sans accusé creux,
puis un développement si nécessaire. Trois questions génériques comparées
avec la même graine ramènent les premières phrases de 20–24 mots à 11–16.
Leur préparation en B passe respectivement de 3,96 / 3,27 / 2,85 s à
2,29 / 1,95 / 1,98 s. La mesure du premier texte est biaisée à froid au
premier essai et n'est pas utilisée comme promesse de gain complet.
La consigne n'est ni un découpage mécanique ni un plafond de réponse.

Défaut de latence séparé : le préchauffage vocal omettait `num_ctx`, alors
que les tours utilisent la fenêtre de la configuration. Il la transmet
maintenant aussi, pour ne pas chauffer un autre contexte. Cela ne supprime
ni le coût de transcription ni celui des appels d'outils et du modèle.

Validation : 495 tests voix/routes passent, 7 tests optionnels sont sautés.
Les nouveaux cas couvrent la référence A/B sur des phrases successives,
la conservation exacte du PCM, les sorties invalides et la fenêtre du
préchauffage. Après le changement de formulation, les 109 tests concernés
passent également. L'écoute humaine du timbre et la validation de l'amorce sur
la voix réelle de Carlito restent nécessaires.

### Le préchauffage passait devant la voix — 27 septembre 2026

Le second essai après redémarrage révèle une attente de 24,45 s avant le
premier jeton, alors que le pré-remplissage vocal ne prend que 0,61 s.
Au même instant, le préchauffage du chat occupe le moteur pendant 31,08 s.
Le POST vocal direct contournait l'ordonnanceur utilisé par le chat ; ce
dernier croyait le moteur libre pendant l'écoute et lançait sa tâche de fond.

La route protège maintenant la séance locale entière avec la priorité
interactive, de la préparation jusqu'à la fermeture, y compris pendant
que l'utilisateur parle. Les limites d'inactivité et de durée du pont ne
changent pas. Les appels Ollama vocaux et leur propre préchauffage passent
par l'admission commune. Un calcul de fond **déjà lancé** reste non
préemptible ; une attente annulée ne réclame jamais de créneau plus tard.
Le temps de file rejoint les mesures internes du tour.

Trois régressions exercent l'ordonnanceur réel : fond différé pendant
l'écoute puis libéré par arrêt explicite ou déconnexion ; voix passant
devant un fond en attente ; annulation vocale libérant le créneau. Les
116 tests ciblés du routage, de la priorité et du parcours local passent.

Validation finale : 514 tests voix/routes/ordonnanceur passent, 7 sont
sautés. Après rechargement, le même essai vocal synthétique au démarrage
reçoit le premier jeton en 0,58 s et le premier son en 2,54 s après
transcription (1,11 s de transcription). Le préchauffage du chat est
différé pendant la séance. La réponse entière est préparée en 5,64 s.
Cela ne vaut pas pour tous les échanges : dans cet essai, une première
phrase très courte (0,96 s de son) laisse encore environ 2,13 s d'attente
avant la suivante (3,09 s de calcul). La priorité corrige la concurrence
de fond, pas toutes les pauses du moteur local. Deux extraits A/B du vrai
ouvrier corrigé sont présentés à Carlito pour juger le timbre à l'écoute.

### La qualité reste prioritaire — essai réel du 27 septembre 2026

Carlito refuse de diminuer la qualité des réponses pour accélérer la voix.
Conserver le modèle de réponse, le contexte utile, les outils et la précision
de reconnaissance. Un gain isolé de synthèse ne suffit pas : mesurer le
temps jusqu'au premier son et les pauses dans le parcours complet.

Le test utilisateur suivant montre pourquoi le banc invité ne suffit pas :
4,64 puis 6,41 s de transcription, et premier son 17,36 puis 12,11 s
**après transcription**, avec le contexte normal (environ 12 500 jetons).
La question de suivi est correctement transcrite et la réponse conserve
le sujet de l'apprentissage de l'anglais. Cela ne valide ni une latence
conversationnelle ni toutes les prononciations.

Deux pistes ont été mesurées puis écartées, sans modification du moteur :

- Whisper small, mêmes poids, beam 3 et marge 400 ms : quatre séries
  alternées de six extraits français (dont trois amorces faibles).
  Huit fils prennent 0,934 s en moyenne, quatre 1,082 s. Les mots sont
  identiques sur les 24 rendus. Réduire les fils ralentit ce banc.
- Attendre toute la génération du texte avant de commencer la voix B
  accélère la synthèse seule (7,03 vers 4,84 s pour la même première
  phrase), mais pas le premier son : 9,31 contre 9,50 s à chaud avec
  les mêmes mots et la même trousse d'outils. Le premier passage à froid
  prenait 13,78 s ; le comparer au passage suivant aurait créé un faux gain.

Un banc d'ingestion micro simulée (paquets de 20 ms, question de 4,24 s)
produit la transcription finale en 5,82 et 5,87 s depuis le début de
l'envoi. Chaque calcul prend environ 0,76 à 1,02 s. Cette différence avec
les cinq à six secondes du test utilisateur reste à expliquer sous la
charge réelle ; ne pas la présenter comme corrigée. Les bancs n'ont pas
modifié les réglages de l'application ni produit de nouvelle installation.

Le diagnostic distingue désormais la file d'attente de chaque calcul STT
et son exécution native, même lorsque son attente asynchrone est annulée.
Un essai WebSocket synthétique montre 0,70 s de file avant 1,19 s de
décodage spéculatif final, et 1,31 s pour la phase finale du tour.
Ces mesures se chevauchent : ne pas additionner le total de phase et le
calcul qui l'a précédé. Ce banc ne reproduit pas les 5–6 s du vrai micro.

Le décodeur expose aussi le nombre de segments finalement retenus avec
une température de repli. Ce n'est pas le nombre de tentatives effectuées.
Aucune parole ni aucun enregistrement ne sont ajoutés au journal ; les
réglages de précision et les reprises natives restent identiques.
Ces ajouts sont des mesures, pas une nouvelle accélération validée.

Essai au haut-parleur demandé par Carlito : micro ouvert depuis l'interface,
mode temporaire entre IA (sans outils ni mémoire), voix B. La question
prononcée demande trois phrases sur l'apprentissage quotidien de l'anglais.
La transcription finale en déforme le sens ; la réponse hors sujet est
cohérente avec cette mauvaise transcription. L'échange n'est donc pas validé.

Le premier partiel (0,84 s de PCM) prend 3,65 s et retient une température
de repli de 1,0. Le calcul spéculatif final attend ensuite 1,05 s avant
3,12 s de calcul, cette fois avec une température de 0. Le total de la
phase finale STT vaut 3,27 s. Le premier audio arrive encore 10,24 s après
transcription, dont 6,74 s de synthèse. Les reprises ne suffisent donc pas
à expliquer tout le délai, et une température nulle ne garantit pas des
mots corrects. Aucun enregistrement micro n'a été conservé ; seul le
journal de durées est retenu. Micro refermé après la réponse dans l'app.

### Une transcription incomplète pouvait faire perdre l'amorce — 27 septembre

La comparaison de deux déclenchements du premier partiel a reproduit un
défaut de segmentation : sur un passage, le banc ne transmettait que
« Quelle question veux-tu aborder aujourd'hui ? », au lieu de conserver
aussi « Bonjour, je suis prêt. ». La ponctuation de l'ancien partiel
abaissait la pause à 450 ms, alors que la couverture pouvait manquer
jusqu'à 750 ms de parole. La reprise annulait ensuite le premier tour.

Le raccourci exige maintenant la couverture intégrale de la dernière
trame parlée. Un partiel en retard peut toujours annoncer une hésitation
et allonger l'attente, mais ne peut plus la raccourcir. Le test de
régression échoue avant correction (450 ms au lieu des 800 attendues),
puis passe. Un second test traverse une pause de 600 ms et vérifie que
les deux parties restent dans le même tampon final.

Les deux passages natifs corrigés conservent toute la phrase. Ils prennent
5,80 et 6,87 s depuis le début de l'envoi (4,24 s de parole) : ce n'est
pas une accélération démontrée. Retarder uniformément le premier partiel
n'a pas montré de gain ; ce réglage n'est pas modifié. Validation :
507 tests voix/routes/journal passent, 7 optionnels sont sautés. Le modèle,
le contexte de réponse, les paramètres Whisper et les voix A/B ne changent
pas dans cette correction. Les erreurs de mots au haut-parleur et le
délai de la première phrase audio restent ouverts.

### Le cache libre de la voix comprimait la mémoire — 27 septembre

Nouvel essai au haut-parleur après la correction de segmentation : la
demande sur l'anglais reste entière et reçoit trois phrases pertinentes,
mais « dis-moi » est transcrit « 10 mois ». La reconnaissance prend
9,36 s (dont 3,88 s de file), puis le premier audio encore 19,81 s.
Ce passage ne valide donc ni la fidélité des mots ni une conversation rapide.
La fermeture du moteur fait redescendre nettement la mémoire occupée.

Une comparaison contrôlée isole le cache de buffers MLX : mêmes poids,
texte, référence B, graine et décodage complet. Quatre passages alternent
la limite native (environ 32,6 Go) et une limite de 256 Mio. Les quatre
PCM sont identiques à l'octet, pour 6,64 s de son. Avec la limite native,
le cache libre atteint 8,47–8,48 Go et actif + cache 11,30–11,31 Go ;
avec la borne, respectivement 383–384 Mo et 6,89–6,90 Go. La borne est
appliquée lors de l'allocation suivante : ce n'est pas un plafond strict
sur toutes les allocations. Le calcul passe de 6,90 / 8,22 s à
5,98 / 5,55 s sur ce banc, sans changer les échantillons.

L'ouvrier applique désormais cette borne avant le chargement du modèle.
Ni les poids actifs, ni le contexte, ni les paramètres de synthèse ne
sont réduits. Les gains du banc ne valent pas encore mesure de la latence
complète sous toutes les charges ; le décodeur garde un pic actif de 6,63 Go.

Contre-vérification au haut-parleur avec ce réglage chargé : l'interface
confirme l'écoute, puis affiche « Dis à pasant » et « trois phases » pour
« Diapason » et « trois phrases ». Le modèle répond donc en trois étapes
sur l'anglais. Le thème est conservé, mais la consigne n'est pas fidèlement
transcrite. Phase finale STT : 17,02 s ; calcul spéculatif : 4,54 s de file
puis 13,03 s de calcul (ces durées se chevauchent avec la phase finale).
Premier audio : encore 25,90 s après transcription, soit environ 43 s
pour ces deux phases successives. La préparation de toute la réponse
prend 73,15 s après transcription. Le micro est ensuite fermé dans l'app.

Cette mesure sous charge ne démontre **aucune accélération du parcours
réel**, malgré le gain isolé et les PCM identiques du banc. Les processus
d'affichage, de stockage et la machine virtuelle occupent simultanément
le Mac ; cette observation ne suffit pas à leur attribuer la cause. Aucun
n'est arrêté ni reconfiguré pour améliorer artificiellement le résultat.
La transcription fidèle et la réactivité restent non validées. Les
122 tests ciblés du moteur, du parcours et des routes passent ; ils
vérifient le protocole et l'application de la borne avant chargement,
pas la qualité acoustique ni le délai perçu.

### Comparaison d'oreilles et raccordement Metal — 27 septembre

Corpus contrôlé : douze extraits synthétiques (Kokoro, A, B), chacun propre
puis avec amorce atténuée, écho retardé et bruit léger, soit vingt-quatre
fichiers et 304 mots de référence. Le même Silero (400 ms de marge) prépare
les trois moteurs. Le comptage ignore ponctuation, casse et accents ; ce
n'est ni une mesure sur la voix de Carlito ni une garantie sur tout audio.

| Moteur / modèle | Moyenne de décodage | Erreurs de mots |
| --- | ---: | ---: |
| CTranslate2 / small, int8, 3 hypothèses | 2,17 s | 12 / 304 |
| CTranslate2 / large-v3-turbo, int8, 3 hypothèses | 5,90 s | 1 / 304 |
| MLX / large-v3-turbo, float16 | 0,65 s | 0 / 304 |

Les algorithmes ne sont pas identiques : MLX Whisper 0.4.3 ne propose pas
le décodage en faisceau. Sa précision est évaluée ici par les résultats,
pas supposée identique parce que les modèles portent le même nom. Les
reprises de température restent actives sur la vraie transcription.

Le choix `speech.realtime.stt_backend = "mlx-whisper"` utilise un processus
isolé installé explicitement par `scripts/install-mlx-recognition.py`.
Les poids et la configuration ont une révision et des SHA-256 fixés ; aucun
téléchargement au premier mot. Le défaut portable reste `faster-whisper`.
Le processus reçoit uniquement le PCM déjà filtré par un tube local,
applique les mêmes seuils anti-hallucination et ne journalise aucun mot.
La dictée, le modèle de réponse, son contexte et les voix A/B sont inchangés.

Le serveur réel, alimenté par l'enregistrement synthétique de la question
sur l'anglais, conserve les mots dans les deux échanges. La finale arrive
2,85 s après l'audio au premier passage, puis 0,96 s au second ; les
premiers sons arrivent respectivement après 10,96 et 9,72 s. Ces durées
incluent l'envoi en trames temporisées ; les essais au haut-parleur sont
une autre mesure. Les sous-titres provisoires restent révisables et peuvent
contenir une erreur avant la finale correcte.

Le premier partiel payait 5,7 s de préparation malgré les poids chargés.
L'ouvrier chauffe désormais encodeur et décodeur sur du silence synthétique
avant READY ; la limite d'un jeton ne concerne QUE cette chauffe jetée.
Un test vérifie qu'elle ne fuit pas dans les paramètres de la parole réelle.
La file STT privilégie également les finales, puis les spéculations, puis
les partiels EN ATTENTE. Un calcul natif déjà actif reste non préemptible.
Le test échoue avec la file FIFO, puis passe, avec les tests d'annulation
qui garantissent l'absence de calculs natifs concurrents.

La variante TTS 0.6B a aussi été essayée hors produit, avec les mêmes
références A/B et quatre textes identiques au moteur actuel : 2,22–3,19 s
contre 2,01–3,07 s. Aucun gain régulier ne justifie de remplacer les voix.
Ces passages ne constituent pas une validation perceptive du naturel.
Le moteur actuel et B par défaut sont conservés.

Validation : 514 tests voix/routes/journal passent, 7 optionnels sont sautés ;
contrôles Ruff réussis. Installation et activation locales sauvegardées ;
aucun commit ni push de ce chantier partagé. L'essai acoustique et la
latence complète restent les critères de réception, pas ces seuls tests.

Sources des moteurs : [Whisper MLX](https://github.com/ml-explore/mlx-examples/tree/main/whisper),
[Faster Whisper](https://github.com/SYSTRAN/faster-whisper),
[variante TTS comparée](https://huggingface.co/mlx-community/Qwen3-TTS-12Hz-0.6B-Base-4bit).

### Les brouillons trop courts et l'indexation passaient devant la voix

Le dernier essai acoustique ne contenait que 1,74 s d'audio et le nom
« Diapason » : il ne permet pas de juger la transcription de la question
complète. Il révèle néanmoins un défaut : un partiel lancé sur 0,82 s
occupait la reconnaissance 15,69 s, puis la spéculation attendait encore
15,36 s avant son propre calcul. Le microphone a été fermé après ce constat.

Les partiels MLX utilisent maintenant une seule température et un budget
proportionnel à l'audio. Un brouillon qui atteint ce budget ou paraît peu
fiable est jeté ; il ne peut donc pas raccourcir la fin de phrase. Les
transcriptions finales ET spéculatives conservent leur décodage complet,
ses reprises et leurs contrôles de précision. Le transport marque
explicitement le caractère provisoire et les tests vérifient que ces
options ne touchent pas une finale. Deux séries sur des préfixes synthétiques
prennent 1,22–2,12 s par partiel ; les deux finales restent exactes. Cela
ne garantit pas un brouillon fidèle sur un mot encore incomplet.

La contre-vérification dans le serveur reste plus lente : après la fin de
l'enregistrement, finales à 7,23 puis 2,09 s et premiers sons à 22,26 puis
24,50 s. Les mots finaux sont conservés. Le premier partiel prend encore
8,57 s : le préchauffage et le budget ne suffisent pas à garantir un calcul
rapide sous charge. Ces mesures remplacent toute conclusion trop optimiste
tirée du banc isolé.

Pendant ces échanges, quatre synchronisations de connecteurs échouent sur
leur sonde d'embedding après 30 s. L'inspection confirme qu'elles contournaient
l'ordonnanceur d'Ollama : ni la sonde ni le pipeline n'étaient classés comme
travaux de fond, et `OllamaEmbedder` envoyait directement ses requêtes HTTP.
Cela démontre un défaut de coordination, pas que ces appels expliquent à
eux seuls toute la latence mesurée.

La synchronisation porte désormais le contexte de fond DANS son fil, et
chaque calcul d'embedding passe par l'ordonnanceur avant de démarrer son
délai HTTP. Une séance vocale longue ne fait plus expirer l'indexation en
attente ni jeter ses vecteurs. Les embeddings nécessaires à une recherche
interactive restent autorisés, avec leur modèle propre, jamais substitué
par le modèle de dialogue. Un calcul déjà envoyé reste non préemptible.
Les deux régressions échouent avant correction puis passent ; l'échec HTTP
libère aussi le créneau. Validation élargie : **569 tests passent, 7 sont
sautés** (voix, routes, journal, ordonnanceur, pipeline et recherche hybride).

Un décodage audio progressif alimenté par les MÊMES codes, référence A/B
comprise, a été comparé hors produit. Le pic mémoire baisse de 5,89–6,35 Go
à 3,84–4,78 Go, mais le décodage est plus lent et le signal n'est pas
identique (écart maximal 0,05–0,16, rapport signal/écart 30–39 dB). Cette
piste est écartée : aucune modification des voix n'est retenue sur cette
base. Aucun son personnel n'a été enregistré pour ces mesures.

Après rechargement de la correction d'indexation, les deux échanges
synthétiques complets conservent encore la question. La finale arrive
4,87 puis 2,22 s après l'audio ; le premier son après 20,59 puis 21,32 s.
Le modèle produit son premier jeton 1,96 puis 1,35 s après transcription,
mais la première phrase demande encore 11,01 puis 13,73 s de synthèse.
Ces durées TTS chevauchent en partie la génération de la suite du texte :
elles ne s'additionnent pas toutes. Aucune nouvelle erreur d'embedding
n'apparaît pendant ces deux tours. Ce n'est pas une preuve d'accélération
causale à charge identique ; les tests de file établissent la priorité,
la mesure complète établit que l'attente reste trop longue.

**État de réception :** correctifs chargés, modèle et contexte conservés,
A/B inchangées, B par défaut ; pas de validation de fluidité humaine ni
de transcription parfaite au microphone. Les derniers essais serveur
utilisent une phrase synthétique et n'ont pas ouvert le micro. La latence
de synthèse en conditions réelles reste le point principal non résolu.

### 27 septembre — un seul timbre demandé : la voix masculine

Carlito retire explicitement la voix féminine A et la voix classique. Parler
ne propose plus de sélecteur : il affiche « Voix masculine », l'ancien
profil B, et c'est le seul profil rendu disponible. Une configuration ou
une fenêtre ancienne demandant A ou la voix classique est ramenée à B au
démarrage. La route de réglage refuse de réenregistrer un timbre retiré.
Le fichier de référence féminin est supprimé du produit ; le moteur, la
référence masculine, la température et le décodage de B restent inchangés.

Le chemin Kokoro de Parler et ses préchauffages sont retirés, sans toucher
aux autres usages de synthèse du dépôt. Si le moteur masculin n'est pas
installé, Parler le signale indisponible et ne substitue aucune voix.
L'ancien phonémiseur ne conditionne plus la disponibilité de Parler.

Ce retrait est un choix de timbre, pas une accélération mesurée : le
problème de délai documenté plus haut reste ouvert.

Validation de ce retrait : **520 tests passent, 7 sont sautés** sur les
modules vocaux et leurs routes ; **30 tests d'interface passent**, TypeScript
et lint ciblé également. Après rechargement du serveur, la sonde réelle
renvoie uniquement le profil masculin, disponible, par défaut ; ce choix
est sauvegardé dans la configuration. Aucun microphone n'a été ouvert.

Application reconstruite, installée et relancée. Vérification native dans
« Parler » : texte « Voix masculine », aucun sélecteur, bouton « Commencer à
parler » disponible et indication « Ton micro est fermé ».

Carlito nomme ensuite ce timbre **Orion**. Le libellé devient « Voix Orion » ;
le nom de l'assistant reste Diapason. Référence sonore, réglages et identifiant
persistant restent les mêmes : ce changement ne modifie pas le son.

Le nom et la gestion des timbres sont ensuite déplacés, à sa demande, dans
**Réglages → Voix → Voix de Diapason**. « Parler » garde seulement la
conversation. Les choix du réglage proviennent de la liste des voix
installées annoncée par le serveur, avec leurs noms de produit ; Orion est
la seule voix disponible aujourd'hui. Un enregistrement est confirmé par
relecture du défaut côté serveur, pour éviter une réussite seulement locale
à une fenêtre. Aucun timbre supplémentaire n'est créé ni promis.

Après déplacement : TypeScript et **35 tests d'interface/parcours client**
passent. L'application reconstruite et relancée affiche bien Orion dans
Réglages → Voix, « Masculine et posée · Par défaut ». Le sélecteur reste
inactif tant qu'une seule voix est disponible. Contrôle natif également
dans Parler : aucun nom ou choix de timbre, microphone toujours fermé.

### 27 septembre — mémoire du décodeur et contre-mesure de la latence

Le banc natif compare quatre phrases d'Orion en alternance témoin / candidat /
candidat / témoin. Matérialiser la sortie des couches finales du décodeur
avant la couche suivante réduit le pic MLX de **1,17 à 1,40 Go**. Les huit
rendus candidats sont **identiques à l'octet** aux témoins correspondants.
Le contexte complet de la référence, les blocs du décodeur, les poids,
la graine et la température sont conservés. Ce n'est pas le décodage audio
progressif écarté plus haut. Le modèle de dialogue ne change pas non plus.

Le calcul isolé est légèrement plus lent (environ 0,08 à 0,29 s sur les
moyennes par phrase) : on retient une baisse de mémoire, pas une accélération
intrinsèque. Le point d'intégration dépend de MLX Audio 0.5.6, version déjà
fixée par l'installeur. Le banc n'ouvre aucun microphone.

Contre-épreuve sur le vrai serveur, même enregistrement synthétique de
4,25 s et mêmes paramètres de session en conversation seule :

| Ordre | Décodeur | Finale après la fin du son | Premier audio après la fin du son |
|---|---|---:|---:|
| 1 | Témoin | 0,64 s | 7,41 s |
| 2 | Mémoire réduite | 0,78 s | 6,61 s |
| 3 | Mémoire réduite | 0,76 s | 6,60 s |
| 4 | Témoin | 0,78 s | 6,77 s |

Les quatre transcriptions finales conservent les mots de la demande, et les
quatre réponses parlent bien de l'apprentissage quotidien de l'anglais.
Leur texte varie : ces chiffres ne prouvent donc pas un gain causal de vitesse.
La première synthèse reste plus lente sous la charge de la conversation que
sur le banc isolé. Le résultat témoin, déjà plus rapide que les 20–21 s de
l'essai précédent, interdit d'attribuer toute cette différence au candidat.

Le réglage mémoire est raccordé au démarrage de chaque nouvel ouvrier vocal.
Les tests natifs et les logs de comparaison sont conservés dans
`/private/tmp/diapason-essai-voix/` (`etapes-orion-identite.log`,
`parcours-orion-avant.log`, `parcours-orion-sobre.log`,
`parcours-orion-sobre-2.log`, `parcours-orion-standard-2.log` et leurs
compagnons `-mesures.log`).

Validation du raccordement : **114 tests passent** (ouvrier, transport,
annulation, parcours local, étapes et choix du timbre), lint et format ciblés
passent également. Aucun changement d'interface ni de voix n'est requis.

**Réception toujours ouverte :** ces échanges sont synthétiques, ne prouvent
pas la compréhension de la voix réelle de Carlito, et six à sept secondes
restent trop longues pour annoncer une conversation fluide.

### 27 septembre — premiers échantillons avant la fin de la phrase

La boucle ICL de MLX Audio **0.5.6** est reprise, avec sa licence MIT, dans
`speech/realtime/synthese_orion.py`. Elle conserve poids, référence complète,
température, graine, contexte et choix des codes acoustiques. Elle décode les
préfixes avec le décodeur complet ; ce n'est pas `streaming_step`, qui avait
modifié le timbre dans les essais précédents. Le modèle de dialogue et le
texte qu'il produit restent inchangés.

Le premier lot contient 24 codes, soit **1,92 s de son**. La lecture anticipée
n'est autorisée que si le coût estimé du lot suivant reste inférieur à 85 %
de sa durée ET de la réserve déjà accumulée. Si le rythme suivant est bon
mais la réserve trop petite, elle grossit de 24 codes avant une nouvelle
évaluation. Si aucun lot borné ne tient le rythme, toute la phrase est
préparée avant sa lecture. Le premier
pas qui prépare le contexte est un coût unique, pas un coût refacturé à chaque
lot. Les mesures de décision sont journalisées séparément de la durée totale.
Si les codes seuls ne tiennent déjà pas le rythme, le préfixe n'est pas décodé
inutilement : la vitesse est réévaluée 12 codes plus loin. Le retrait de la
référence utilise des entiers : un arrondi flottant pouvait déplacer la
jointure d'un échantillon quand la longueur du préfixe changeait.
L'interruption ferme le vrai générateur, arrête l'ouvrier et abandonne sa suite.
L'historique ne déclare pas une phrase entière prononcée sur une erreur partielle.

**Contre-épreuve longue :** une première version redécodait tous les préfixes
tous les 24 codes. Sur 27,6 s d'audio, elle demandait environ 30 s de calcul et
épuisait la réserve. Le correctif réutilise les blocs terminés de 300 codes,
en conservant exactement les 25 codes de contexte gauche du décodeur original.
L'espacement des décodages augmente avec leur coût, par pas de 12 codes et
au plus 96. Le même texte demande ensuite 18,81–20,09 s de calcul et ne vide
plus la réserve sur les deux essais. Il n'est ni raccourci ni paraphrasé.

Banc final, six textes identiques entre témoin et candidat :

| Durée du son | Phrase entière, témoin | Premier son candidat | Total candidat | Continuité mesurée |
|---:|---:|---:|---:|---|
| 3,20 s | 1,68 s | 1,40 s | 2,43 s | aucun trou |
| 4,48 s | 2,10 s | 1,32 s | 3,52 s | aucun trou |
| 5,52 s | 2,48 s | 1,23 s | 3,81 s | aucun trou |
| 1,84 s | 1,20 s | 1,21 s | 1,21 s | aucun trou |
| 9,20 s | 3,82 s | 1,23 s | 7,05 s | aucun trou |
| 27,60 s | 11,76 s | 1,42 s | 20,09 s | aucun trou |

Les cinq premiers PCM sont identiques à l'octet. Pour la phrase longue,
la durée et les codes sont conservés mais les tailles différentes des
produits matriciels entraînent des arrondis allant jusqu'à **2 niveaux sur
32767**. Il serait donc faux d'annoncer une identité binaire universelle.
Le banc natif opt-in `tests/speech/test_orion_natif.py` garde cette comparaison
reproductible, sans téléchargement, microphone ni diffusion sonore. Ces
comparaisons ne constituent pas un jugement humain de naturel.

**Concurrence avec la réponse :** sur le vrai serveur, le premier préfixe
prenait 2,70 s pendant la génération du texte, puis 1,26 s sur la phrase
suivante. Attendre la fin d'une courte réponse avant de lancer Orion a donné
5,52 s sur un premier essai, mais les versions à attente bornée d'une puis
trois secondes ne tiennent pas ce gain : 7,42 s sur la première, puis
11,56 / 6,04 / 14,22 s sur trois échanges avec la seconde. Ces attentes
artificielles ont été retirées. La première phrase complète peut repartir
immédiatement en synthèse ; c'est la réserve adaptative qui décide du départ
audio. Le texte, le modèle et son contexte ne sont pas réduits.

Une séparation par moteur CPU a également été essayée hors produit : aucune
courte phrase ne se terminait avant la borne de 40 secondes de synthèse.
Elle est écartée.

Les temps changent aussi avec la charge du poste : le contrôle système
constate environ 14,85 Go de swap utilisé et plusieurs applications actives,
sans alerte thermique rapportée. Cela ne prouve pas que le swap explique
à lui seul les délais, et aucun autre programme n'a été fermé pour produire
un chiffre flatteur.

Validation dans le vrai serveur, en conversation seule et sans microphone :

| Version / tour | Finale après la fin du son | Premier audio après la fin du son | Trous de lecture |
|---|---:|---:|---|
| Réserve adaptative, question | 0,64 s | 5,74 s | aucun |
| Réserve adaptative, suite | 0,59 s | 6,18 s | aucun |
| Réserve adaptative, exemple | 0,72 s | 7,87 s | aucun |
| Calculs inutiles écartés, question | 0,76 s | 7,32 s | aucun |
| Calculs inutiles écartés, suite | 0,61 s | 8,99 s | aucun |
| Calculs inutiles écartés, exemple | 0,46 s | 8,97 s | aucun |

Ces trois questions et relances utilisent les mêmes enregistrements, mais
les réponses générées changent. Le gain isolé de synthèse n'est **pas** une
preuve de gain global fiable. La dernière réponse propose aussi un exemple
en français dans une discussion sur l'anglais : conserver les messages de
contexte ne garantit pas que le modèle les suive correctement. Aucun de ces
essais ne suffit à déclarer la qualité conversationnelle ou la fluidité reçue.
Le temps de préparation avant READY (environ 7 s sur ces deux séances) est
rapporté séparément ; il ne doit pas être caché dans le délai de la question.

Limites : un ralentissement imprévisible après le départ du son peut encore
épuiser la réserve. Le gain porte sur l'arrivée des premiers échantillons,
au prix de davantage de calcul total ; il ne garantit pas une conversation
instantanée ni une accélération sous toutes les charges. Le préchauffage
utilise maintenant une phrase assez longue pour exercer ce parcours avant
READY ; il reste distinct du temps de réponse à une question.

### 27 septembre — un brouillon ne doit pas monopoliser la reconnaissance

Une nouvelle séance chargée a révélé **8,16 s** de calcul sur un brouillon,
et **10,42 s** d'attente avant le calcul spéculatif de la phrase entière.
La borne existante de jetons ne borne pas le temps passé par jeton. Sur ce
même essai, le premier audio est arrivé 26,88 s après la fin de l'entrée,
avec un trou de 1,53 s : les essais précédents sans trou ne constituent donc
pas une garantie sous toute charge. L'essai d'une consigne d'amorce de
quatre à sept mots n'apporte pas de gain établi ; retour à huit–douze mots.

Le décodage **provisoire seulement** dispose maintenant d'un budget coopératif
d'une seconde, contrôlé avant chaque pas du décodeur et à son retour. Un
brouillon expiré rend des segments vides, pas une transcription partielle
déclarée finale ni une erreur utilisateur. Les noyaux Metal déjà soumis
finissent avant d'accepter la requête suivante ; un noyau actif n'est pas
interruptible, donc une seconde n'est pas une borne murale absolue.
Le modèle reste chargé. La méthode native est restaurée même sur erreur ;
la finale conserve toutes ses options de décodage et ses reprises.

Le test natif opt-in `test_reconnaissance_mlx_native.py` exerce un abandon
réel, puis retrouve exactement les **19 mots** de sa transcription témoin.
Les deux brouillons non forcés prennent 0,44 et 0,52 s. Le test n'ouvre pas
le microphone et utilise uniquement la référence synthétique livrée.

Après rechargement du serveur, trois échanges sur les mêmes enregistrements :

| Tour | Finale après la fin du son | Premier audio après la fin du son | Trous mesurés |
|---|---:|---:|---|
| Question sur l'anglais | 0,56 s | 8,00 s | aucun |
| Par quoi commencer | 0,46 s | 7,13 s | aucun |
| Exemple de phrase | 0,46 s | 5,42 s | aucun |

Ces résultats valident le chemin rechargé, pas un gain causal de plusieurs
secondes : la charge et le texte des réponses diffèrent. Les réponses restent
sur l'anglais et le dernier exemple est bien en anglais ; la deuxième ajoute
cependant une limitation sur les commandes de l'ordinateur que personne
n'avait demandée. La qualité des réponses n'est donc pas déclarée parfaite.

Le cache du vecteur de timbre a aussi été essayé hors produit : le calcul
initial ne coûte qu'environ **11 ms**, et les huit rendus comparés gardent
le même PCM. Les temps avec/sans cache se recouvrent (2,10–2,14 s sur la
première phrase, 3,03–3,17 s sur la seconde) ; cette modification n'est pas
retenue pour prétendre résoudre une attente de plusieurs secondes.

Les logs reproductibles de cette étape sont `parcours-brouillon-borne.log`,
son compagnon `-mesures.log`, `parcours-amorce-courte.log` et
`cache-timbre.log`, dans le dossier temporaire du banc. **L'objectif de
moins de trois secondes reste non atteint**, et l'essai réel avec la voix
de Carlito reste distinct de ces enregistrements synthétiques.

Validation de cette étape : **542 tests passent**, 7 sont sautés et les deux
bancs natifs opt-in sont exclus de la suite ordinaire. Le nouveau banc natif
de reconnaissance passe séparément ; lint, format ciblé et `git diff --check`
passent. Le serveur a été rechargé avant les trois échanges ci-dessus.

### 27 septembre — le décodeur incrémental ajoutait deux fois le biais

Le flux natif de MLX Audio 0.5.6 ajoutait le report d'une convolution
transposée à la suivante **avec le biais déjà compris dans les deux sorties**.
Sur les codes enregistrés d'Orion, l'écart atteignait 8 498 niveaux PCM16.
Le simple retrait du biais évite le défaut principal, mais additionner deux
sorties arrondies n'est pas strictement le même calcul qu'une convolution.
L'adaptateur `decodeur_orion.py` conserve donc une entrée à gauche et refait
le raccord dans une seule convolution. Les poids, les codes acoustiques,
la référence de timbre et les paramètres de tirage restent inchangés.

La référence complète est décodée avant la parole, sans être émise ; seul
son état peut être réutilisé entre phrases, avec copies des buffers et des
caches. Les frontières du rendu complet restent à 300 codes, avec 25 codes
de contexte à gauche. Une petite queue changeait le noyau numérique : elle
est soit jointe au prochain lot, soit complétée pour le **calcul causal** en
fin de bloc/phrase, puis coupée exactement au nombre d'échantillons réels.
Aucun son artificiel n'est ajouté. Une annulation remet les états à zéro.

Le banc natif court/moyen/long obtient : PCM identique sur 1,84 et 4,48 s de
son, longueur identique et écart maximal de 2 niveaux sur 27,6 s. Démarrage
isolé 1,19 / 0,76 / 0,90 s ; calcul total de la phrase longue 10,61 s.
Le nouveau parcours ne redécode plus tout ce qui a déjà été produit.

Première séance rechargée, mêmes trois enregistrements synthétiques :

| Tour | Transcription finale après entrée | Premier audio après entrée |
|---|---:|---:|
| Question sur l'anglais | 0,67 s | 4,87 s |
| Par quoi commencer | 0,58 s | 4,87 s |
| Exemple de phrase | 0,60 s | 2,90 s |

Aucun manque de réserve sur les deux premiers tours. Le banc sans réserve
initiale trouve 26 ms au raccord entre deux phrases du troisième ; la
lecture de l'application possède déjà 60 ms d'avance de planification.
Ces valeurs d'arrivée n'incluent pas cette avance, ni la latence matérielle
des haut-parleurs. Les réponses varient, donc ce n'est pas une comparaison
causale à texte fixe. **Passer une fois sous trois secondes ne valide pas
cet objectif sur toutes les questions.** La première préparation prend
7,37 s avant READY, toujours rapportée à part.

Essais écartés, hors produit : réserver 3 Gio à la résidence mémoire MLX
ne change pas suffisamment les temps concurrents (4,70–4,93 s contre
4,88–4,92 s pour le même PCM). La synchronisation Metal rapide et les lots
de 128 ou 4 096 opérations ne donnent pas non plus de gain convaincant.
Ces options sont décrites dans la [documentation MLX](https://ml-explore.github.io/mlx/build/html/usage/environment_variables.html)
et n'ont pas été appliquées à l'application ni aux réglages du système.

Logs du banc : `orion-incremental-natif-2.log`,
`parcours-incremental-1.log`, `parcours-incremental-1-mesures.log`,
`residence.log`, `envoi-gpu.log`. Suite vocale : **544 tests passent**, 7
sautés, 2 natifs exclus de la suite ordinaire ; contrôle natif séparé passé.

### 27 septembre — donner le GPU à Orion entre les phrases du modèle

Le préfixe passe à 16 codes (1,28 s de son), avec le même contrôle de
réserve. Le banc natif donne 0,97 / 0,52 / 0,63 s avant le premier PCM,
sans trou ; les rendus courts restent identiques, le long garde sa longueur
et l'écart maximal de deux niveaux PCM16. Une phrase annulée après son
premier fragment ne change pas le rendu de la suivante. Douze codes ont
été essayés puis écartés : le contrôle de fidélité échouait.

Mais les trois échanges complets attendaient encore 6,32 / 4,29 / 3,96 s.
Le modèle qui rédige et Orion qui parle calculaient ensemble sur le GPU.
Leur faire céder le calcul à chaque frontière de phrase accélère Orion :
le flux HTTP est fermé **avant** de livrer la frontière au lecteur, puis
le modèle reprend avec le préfixe assistant exact déjà reçu. Les caractères
après la ponctuation, même reçus dans le même fragment, restent dans ce
préfixe. Le contexte, le modèle et sa fenêtre ne changent pas. Les outils
déjà détectés empêchent cette pause, pour préserver leurs arguments.

Une pause limitée à la première phrase n'était pas suffisante : une
introduction « Dites à voix haute : » démarrait en 1,80 s, mais créait
ensuite 2,82 s de blanc. Orion garde donc les propositions après deux-points
et point-virgule dans la même phrase ; les autres phrases cèdent aussi le
calcul. Huit pauses maximum évitent une boucle pathologique : la dernière
passe finit normalement, et le budget de sortie diminue à chaque fragment.
Les annulations arrêtent le producteur, sa pause et ses rediffusions.

Trois échanges installés, avec le même banc synthétique et son ancien
cadencement (délai après la durée nominale de l'enregistrement) :

| Tour | Transcription finale | Premier PCM | Manque de réserve |
|---|---:|---:|---:|
| Trois phrases sur l'anglais | 0,62 s | 2,72 s | aucun |
| Par quoi commencer | 0,49 s | 2,13 s | aucun |
| Exemple à répéter | 0,49 s | 2,27 s | aucun |

Ce sont des arrivées réseau locales, pas des mesures microphone-haut-parleur.
Le délai matériel et les 60 ms de planification du lecteur restent à ajouter.
La préparation avant READY est séparée ; ces essais n'ouvrent pas le micro
et utilisent la conversation seule, sans outils exécutés ni mémoire personnelle.

Le contrôle natif du modèle compare les récitations, y compris une seule
phrase, et vérifie que l'appel structuré reste exploitable. En réponse
libre, la suite peut être reformulée après préremplissage, même à température
nulle : il serait faux de promettre la même réponse à l'octet. Le test
contrôle aussi la conservation du contexte (anglais, dix minutes), de
l'exemple et de sa traduction, chacun une seule fois. Les réponses libres
du petit modèle restent imparfaites : une réponse de banc a répété un
conseil, une autre inventé une heure. Ce gain de vitesse ne constitue pas
une preuve générale de qualité des réponses.

Preuves : `orion-seize-natif.log`, `parcours-seize.log`,
`parcours-reprise.log`, `parcours-phrase-complete.log`,
`parcours-alterne.log` et leurs mesures, dans le dossier temporaire du banc.
Les tests durables sont `test_decodeur_orion.py`, `test_orion_natif.py`,
`test_reprise_orion.py` et `test_reprise_orion_native.py`.

### 27 septembre — préchauffage attendu et cache partagé avec le chat

La chauffe du modèle partait dans un fil détaché : READY pouvait arriver
alors que le contexte n'était pas prêt. Elle est désormais attendue,
annulable, et utilise le même contexte que la première réponse. Une erreur
ne laisse plus un modèle déclaré prêt à tort au deuxième essai. Fermer
pendant la préparation empêche tout READY tardif. Le repli des modèles qui
refusent les outils reste le même que pendant une réponse.

Dans le mode normal, avec la trousse complète, attendre cette chauffe ne
suffisait pourtant pas : le premier jeton prenait encore 3,3 s, puis la voix
4,8 s après le texte reconnu. Les journaux Ollama montraient une reprise
au point de contrôle récurrent vers 10 251 jetons, suivie d'environ mille
jetons à recalculer. Les essais « même température », « utilisateur vide »
et « Bonjour pendant la chauffe » n'améliorent pas ce délai et sont écartés.

Des lots de 256 déplacent le point réutilisable vers 11 000 jetons et
ramènent le premier jeton à 0,8–1,0 s. Ce nombre limite le **lot de calcul**,
pas la mémoire de conversation : fenêtre, modèle, outils et consignes sont
conservés. Le réglage est commun aux trois chemins du chat, à sa chauffe,
à la chauffe vocale et aux reprises d'Orion, car changer `num_batch`
recharge le runner Ollama. Il ne s'applique qu'à Qwen3.5 sur Apple Silicon,
configuration mesurée ; les autres gardent leurs réglages. Les six chemins
sont exercés par `tests/engine/test_ollama_cache_vocal.py`.

La frontière des phrases accepte maintenant les guillemets fermants :
un exemple anglais cité ne doit pas attendre sa traduction avant d'être
prononcé. Une consigne explicite conserve aussi la langue apprise dans les
exemples, au lieu de donner uniquement leur traduction française.

**Mesures séparées**, sans confondre les périmètres :

- Serveur réel, conversation seule, trois enregistrements cadencés sur
  l'horloge d'envoi : 2,586 / 2,139 / 1,921 s depuis la dernière trame de
  parole au premier PCM ; transcription finale 0,328 / 0,315 / 0,283 s.
  Pas de manque de réserve ; préparation de cette séance 5,731 s.
- Mode normal isolé, vraie reconnaissance, vrai modèle avec sa trousse
  complète et vrai Orion : 2,750 / 2,424 / 2,071 s ; transcription finale
  0,293 / 0,264 / 0,289 s. Aucun manque de réserve sur respectivement
  16,00 / 17,52 / 14,08 s de son. L'identité du locuteur accepté est une
  fixture, la mémoire personnelle et le bureau ne sont pas consultés,
  les outils ne sont pas exécutés. **Ce n'est pas une validation acoustique
  avec la voix de Carlito ni une mesure de ses outils réels.**
- Sur ce dernier banc lancé dans un processus neuf, la préparation a pris
  **65,048 s**, dont 40,512 s de chauffe LLM. Ce coût initial est hors du
  délai par tour et n'est pas masqué. Une séance isolée avec moteurs déjà
  chauds se préparait en 5,612 s. Le chargement à froid reste une limite.

Les 60 ms de planification du lecteur et la latence des périphériques
restent à ajouter aux mesures PCM. La disponibilité d'outils dans le
contexte ne mesure pas le temps d'une recherche ou d'une action. Les
réponses demandant un outil peuvent légitimement attendre son résultat.
L'objectif sous trois secondes est observé sur ces trois échanges prêts,
pas garanti pour toute demande ni sous toute charge.

Preuves temporaires : `parcours-final-orion.log`,
`parcours-final-orion-mesures.log`, `cache-standard.log`, `cache-batch.log`,
`mode-standard-prepare.log`, `mode-standard-batch.log`,
`standard-audio-batch.log`, `tests-batch-orion.log`,
`reprise-native-batch.log`, dans `/private/tmp/diapason-essai-voix/`.
Validation après intégration : **1 064 tests passent**, 7 sautés, 7 tests
live/cloud/hub exclus ; contrôle natif des reprises passé séparément.
Les vérifications de format ciblé, lint ciblé et `git diff --check` passent.

Après rechargement, l'ouverture du WebSocket standard avec **les réglages
et la mémoire par défaut de l'application** atteint READY en 50,812 s.
Aucun micro n'est ouvert, aucune question ni action envoyée, et la séance
est fermée ensuite. Ce contrôle confirme l'installation et la préparation
réelle, tout en confirmant la limite de démarrage à froid ; il ne mesure
pas une réponse standard avec l'identité vocale de Carlito.

Contre-épreuve après ce rechargement : le WebSocket de conversation seule
répond sur les trois mêmes enregistrements en **2,475 / 1,925 / 2,099 s** ;
transcriptions finales en **0,326 / 0,283 / 0,318 s**. Aucun manque de
réserve sur 12,80 / 11,20 / 12,08 s de PCM ; préparation 5,323 s.
`serveur-final-batch.log` et `serveur-final-batch-mesures.log` en gardent
la preuve. Les brouillons partiels restent parfois faux puis sont corrigés
par la phrase complète : la rapidité des sous-titres n'est pas une preuve
d'exactitude de chaque mot provisoire.

Deux réouvertures normales supplémentaires, toujours sans micro ni question,
sont prêtes en **5,249 puis 3,975 s** (`preparation-serveur-reouverture.log`).
Le premier démarrage ne représente donc pas le coût de chaque ouverture.
Le serveur utilise bien la fenêtre personnelle configurée à **32 768 jetons**,
sans modification. Le banc normal isolé ci-dessus employait initialement
le défaut du processus à 16 384 ; une contre-épreuve avec la configuration
réelle le distingue explicitement.

### Réglage final : lots de 128, même contexte de 32 768

La contre-épreuve à 32 768 jetons avec des lots de 256 donne
**3,086 / 2,081 / 2,257 s**. La première phrase est plus longue ; il serait
faux de dire que tous les tours restent sous trois secondes.

Le dernier essai, lots de **128**, réduit le premier jeton de 1,009 à
0,706 s. Les trois départs audio sont **2,354 / 2,138 / 2,231 s**, avec
transcriptions finales en **0,295 / 0,263 / 0,288 s** et aucun manque de
réserve. Les réponses contiennent toujours les trois phrases demandées,
puis un conseil de départ et un exemple anglais. Leur formulation varie :
le gain causal le plus directement comparable est le premier jeton,
non la durée de phrases différentes. Un guillemet non refermé dans une
réponse libre rappelle que la mise en forme du modèle n'est pas parfaite.

La préparation du processus neuf passe de 31,717 à 34,309 s sur ces deux
bancs. **128 est le réglage finalement retenu**, partagé par le chat et
la voix, avec la même restriction à Qwen3.5 sur Apple Silicon. La fenêtre
de contexte reste celle de la configuration ; aucune réduction de modèle,
de trousse ou de précision de reconnaissance n'a été appliquée. Les voix
et les réglages acoustiques d'Orion restent identiques. Les conditions
isolées et les exclusions identité/micro/périphériques décrites plus haut
s'appliquent toujours à cette comparaison.

Preuves : `standard-audio-config.log`, `standard-audio-128.log`.

Version finale rechargée, **lots de 128**, contrôle via le serveur réel en
conversation seule : premiers PCM **2,257 / 2,051 / 2,710 s** ; transcription
finale **0,314 / 0,283 / 0,317 s** ; aucun manque de réserve sur
16,48 / 16,24 / 9,28 s de son. La troisième réponse est un seul long exemple
anglais : elle n'a pas été amputée pour satisfaire un chronomètre.
Preuves : `serveur-final-128.log`, `serveur-final-128-mesures.log`.
Le test natif de restitution et d'appels structurés passe à nouveau
(`reprise-native-128.log`, 15,86 s), ainsi que les 59 tests ciblés du moteur,
du préchauffage et des reprises après le dernier changement numérique
(`tests-reglage-final.log`). Lint, format ciblé et contrôle de diff passent.

Dernière ouverture standard, version finale, mémoire et outils par défaut :
READY en **39,108 s** après le changement de contexte du banc invité vers
le contexte normal (`preparation-finale-128.log`). La séance est ensuite
fermée sans micro ouvert ni question envoyée. Le contexte normal a bien
été préparé ; le démarrage après chargement/changement de contexte reste
explicitement hors de la promesse de latence des tours déjà prêts.

### 28 septembre — un micro qui ne s'ouvre pas dit pourquoi

Au téléphone, « Parler » affichait la phrase des Réglages Système du Mac
pour TOUTE exception du bloc du micro : `useVoiceLive` transformait en
`microphone-denied` aussi bien un refus qu'un `NotReadableError` (la WebView
d'Android sans MODIFY_AUDIO_SETTINGS) ou un AudioContext qui lève après
l'obtention du flux. `lib/echecMicro.ts` classe désormais par étape puis par
nom, et chaque classe a sa phrase, en fr et en en ; au bureau, seul le refus
garde la phrase de macOS. Au téléphone, la page demande à la coquille l'état
de la permission (verbe `micro`) avant de conseiller quoi que ce soit, et
affiche le détail technique sous la phrase. Le contrat, la table des
messages et ce qui reste à voir sur l'appareil :
[`diapason-mobile.md`, §6](diapason-mobile.md#6-le-micro-au-téléphone-28092026).

Rien de ce chantier ne touche la séance elle-même : ni l'ordre
`start` → getUserMedia, ni la logique `serveurPret` / `capturePrete`.
