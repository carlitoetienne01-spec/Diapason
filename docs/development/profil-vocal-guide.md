# Reconnaissance du propriétaire : profil guidé et phrases courtes

27 septembre 2026. **Implémentation testée et activée** lors de la mise à jour
autorisée ensuite par Carlito pour intégrer les ajouts vocaux à l’application
ouverte. L’application est reconstruite et relancée, le serveur rechargé.
L’ancien profil n’a pas été remplacé : son nouvel enregistrement reste guidé
par Carlito, avec validation explicite.

## Défaut observé

Deux tours transcrits de 1,70 et 1,88 seconde étaient ensuite refusés par
l’identité vocale (similarités 0,30 et 0,32 ; seuil 0,45). Le profil comportait
cinq captures apprises automatiquement pendant le dialogue. À l’inverse,
l’ancienne extraction impossible, y compris moins d’une seconde de son,
rendait `(1.0, True)` : absence de preuve présentée comme une identité sûre.
Ces observations n’établissent pas si les captures de Carlito étaient bruitées,
trop distantes ou peu représentatives : leurs enregistrements ne sont pas disponibles.

## Comportement livré dans le code

- Réglages → Voix → Ma reconnaissance vocale : cinq phrases variées puis trois
  réponses courtes. Le micro ne s’ouvre que sur un clic d’enregistrement.
- Capture PCM16 mono à 16 kHz, huit secondes au maximum ; fermeture sur arrêt,
  délai, annulation, masquage ou démontage du composant. Les autorisations et
  modules audio arrivant après une annulation ne rallument pas le microphone.
- Chaque capture est validée sans l’enrôler. Le bouton final revalide les huit
  captures et leur cohérence. Les cinq longues doivent chacune correspondre à
  au moins trois des quatre autres ; les trois courtes doivent correspondre
  à une longue au minimum. Le seuil de similarité reste **0,45**.
- Écriture atomique, fichier privé, empreintes uniquement. L’ancien profil
  persiste en cas d’annulation, capture invalide, incohérence, conflit de version
  ou échec d’écriture. Les captures brutes sont temporaires en mémoire, jamais
  sauvegardées sur le disque par ce parcours.
- Les profils existants restent lisibles. Le dialogue ne les nourrit plus
  automatiquement. Sans profil exploitable, le verrou demande un enregistrement
  guidé ; il ne transforme plus cette absence en autorisation.
- Une courte phrase ou un mot isolé sont comparés dès **200 ms de parole audible**,
  au même seuil de similarité de **0,45**. La limite d’une seconde reste requise
  pour apprendre les trois captures courtes du profil, pas pour vérifier un mot.
  L’entrée audio accepte aussi ces mots complets à la fin du tour ; les seuils
  plus longs des sous-titres et de la spéculation ne changent pas.
- En cas d’identité incertaine, aucune consigne de répéter ou de rallonger la
  phrase, et aucune annonce vocale : la barre indique « Écoute active · voix non
  confirmée. ». La séance et son microphone restent ouverts ; le prochain tour
  est vérifié indépendamment. Ni réponse privée, ni commande, ni message utilisateur
  définitif ne sont déclenchés par un tour incertain. Ce signal ne prétend pas
  que le mot a été accepté ; supprimer une consigne ne supprime pas les faux refus.
- Le bouton « Tester ma voix » vérifie un nouvel extrait sans outil, sans
  apprentissage ni modification du profil. Il distingue reconnaissance, manque
  de parole, refus, profil absent et moteur indisponible.

Le contrôle d’énergie (trames de 20 ms, seuil RMS 0,003) écarte silence et
fragments brefs ; **ce n’est pas un détecteur de langage ou une protection
contre une voix enregistrée**. Une empreinte vocale reste une comparaison
statistique. Aucun taux de reconnaissance de la voix réelle de Carlito n’est
annoncé avant ses essais.

## Contrats

Les quatre routes `/v1/voice/profile` (GET/PUT), `/sample` (POST) et `/check`
(POST) exigent la clé locale et refusent le téléphone. Le classement existant
`/v1/voice/` les refuse sur le tailnet ; l’instantané du contrat a été régénéré.
Le format JSON/base64 évite le défaut des corps binaires de WKWebView. Les
calculs ONNX/disque s’exécutent dans des routes synchrones hors boucle ASGI.

Nouveaux états WebSocket : `voiceNeedsMoreSpeech`, `voiceProfileRequired`,
`voiceCheckUnavailable`. Les clients français et anglais connaissent ces états.
Les brouillons vocaux refusés ou incertains disparaissent du chat.

## Vérifications effectuées

- Suite vocale, routes et contrat tailnet : **630 tests réussis**, sept anciens
  tests natifs sautés faute de fichiers WAV historiques, trois tests live exclus.
- TypeScript sans émission : réussi. Tests frontend ciblés, internationalisation,
  capture, lecteur, conversation et hook vocal : **75 tests** après ajout de deux
  contrôles d’annulation/nettoyage du microphone.
- Contrôle natif distinct, avec le vrai TitaNet installé et un profil temporaire :
  huit captures Thomas (5 longues et 3 courtes), puis six phrases non utilisées
  pour l’enregistrement, comparées à la voix synthétique Amélie. La phrase longue,
  « Oui, tout à fait » et « Non, merci » de Thomas passent (scores 0,95/0,84/0,81).
  Les mêmes essais d’Amélie sont refusés ou incertains ; aucun accord. Dans cette
  première version, « Oui », « Non » et « D’accord » isolés étaient incertains
  pour les deux voix à cause du seuil de durée, corrigé ci-dessous. Calcul des
  empreintes mesuré entre 7 et 20 ms sur ce banc. Ce sont **des voix synthétiques**,
  pas une validation de la voix de Carlito ni une mesure générale de sécurité.
- Aperçu isolé à 340 px avec vrais composants/CSS mais captures et réponses API
  simulées : huit étapes, arrêt automatique, confirmation et test incertain
  vérifiés au navigateur. Aucune écriture dans le profil réel.

### Correction des mots isolés, le même soir

Carlito refuse les demandes répétées de compléter ou de réessayer. Deux seuils
empêchaient certains mots d’atteindre la comparaison : une seconde dans
`SpeakerVerifier`, et 350 ms de parole forte dans la capture. La capture finale
et la comparaison utilisent maintenant 200 ms ; les calculs provisoires gardent
350 ms. Le niveau sonore, le seuil d’identité, le modèle et l’ancien profil ne
sont pas modifiés. Aucun son n’est répété, allongé ou mélangé avec le tour précédent.

- **711 tests Python réussis**, sept natifs historiques sautés (WAV absents), trois
  live exclus : parole courte, clic écarté, identité différente au tour suivant,
  absence d’apprentissage implicite, profil guidé, serveur et parcours vocal.
- TypeScript, **71 tests frontend ciblés**, lint et format Python : réussis.
- Contrôle natif TitaNet : 36 fichiers, six phrases pour chacune des six voix
  synthétiques macOS Thomas, Amélie, Jacques, Eddy, Grandpa et Flo. Profil Thomas
  temporaire de huit captures, sans toucher au profil de Carlito. Les six essais
  Thomas passent, dont « Oui » / « Non » (260 ms chacun) et « D’accord » (680 ms).
  Aucun des trente essais des cinq autres voix n’est accepté. Bruit aléatoire
  et sinusoïdes à 240 ms, 500 ms et une seconde restent sous le seuil de similarité.
- Le même contrôle traverse aussi `send_audio` par trames de 20 ms, détection
  de fin de tour puis vrai filtre d’empreinte : six réponses autorisées, trente
  refusées, profil inchangé. **Transcription et réponse sont simulées sur ce banc** :
  il valide le passage du son et l’identité, pas les mots réellement compris par
  Whisper. Calcul d’empreinte des trois mots isolés : environ 2,5 à 3,6 ms à chaud.

Ces voix synthétiques ne constituent pas une mesure de sécurité générale ou un
taux de reconnaissance de Carlito. Le filtrage d’identité reste actif à chaque
tour ; une confiance héritée de la séance n’autorise pas une autre voix.

Version reconstruite, signée, installée et relancée ; serveur rechargé. La sonde
locale confirme Orion disponible et les cinq empreintes du profil existant
toujours présentes. Le bundle livré contient la nouvelle indication et plus
l’instruction de prononcer quelques mots supplémentaires. Contrôle de l’application
native effectué sans ouvrir son microphone.

## Validation utilisateur restante

Faire enregistrer son profil à Carlito dans Réglages → Voix. Essayer une
phrase nouvelle, une réponse courte (« oui, c’est bien ça »), un mot isolé et,
avec accord de la personne, une autre voix. Vérifier le texte reconnu **et** le
verdict d’identité : ce sont deux contrôles différents. Un mot isolé peut maintenant
être reconnu sans ajout de paroles ; un score incertain reste signalé sobrement,
sans demande de répéter. Aucune acceptation systématique n’est promise.
