# Talk To Diapason — Résonance

## Direction du 12 septembre 2026

Référence donnée par Carlito : un volume organique de voiles ponctués,
violet et rose, avec des plis cyan et nacrés sur fond noir.
Le rendu est procédural, pas une vidéo en boucle ni une image générée.

Palette : noir `#000000`, iris `#7555ff`, orchidée `#da75ee`,
glace `#a4e9ff`, nacre `#f2ebff`, texte secondaire `#a49daf`.
Geist Variable est déjà disponible localement : aucune police distante.
L'expressivité est concentrée sur le volume ; les commandes restent sobres.

```text
Diapason  Conversation vocale                         Détails  Fermer

                 trois voiles de lumière

                       On en parle ?
              Micro fermé jusqu'au démarrage
                   [ Commencer à parler ]

Moteur vocal local                                    Échap pour fermer
```

Lorsque des paroles existent, le volume se place à gauche et le fil à droite.
Sous 680 px, les deux passent en colonne ; le fil et le corps peuvent défiler.
Les erreurs et commandes ne disparaissent pas sous la conversation.

## Ce qui pilote le volume

- `idle` : respiration lente, aucun branchement d'analyse du micro.
- `connecting` : transition plus resserrée, étiquette « Connexion en cours ».
  Il n'existe pas de vrai signal « raisonnement » dans le moteur vocal :
  ne pas inventer cet état dans l'interface.
- `listening` : le volume se resserre et suit `micNode` du moteur vocal.
- `speaking` : ouverture du volume ; les variations suivent `outputNode`.
- `error` : rendu immobile et message explicite, sans animation de réussite.

L'amplitude audio est nulle en l'absence de source ou de signal.
La respiration au repos n'est pas une mesure sonore.
Le niveau vient désormais du RMS temporel du PCM, et non de la moyenne
des bandes FFT (qui diluait la voix dans les bandes silencieuses).
La fenêtre de 1024 échantillons représente 64 ms à 16 kHz. Un seuil
d'environ -50 dBFS et un plancher du pic à 0,04 empêchent le bruit seul
d'être progressivement amplifié. Le pic s'adapte sur trois secondes.
Le seuil de mouvement est de 3,5 % du niveau normalisé, avec une attaque de
65 ms et un relâchement de 180 ms dans la scène.
Les préférences de réduction des mouvements figent la géométrie.
Un onglet masqué arrête la boucle de rendu ; la fermeture libère ses ressources.
WebGL indisponible : repli CSS statique, sans bloquer les commandes vocales.

## Périmètre technique

- `frontend/src/components/Chat/TalkOrb.tsx` et `TalkOrb.css` : panneau,
  fil, commandes, focus et messages d'erreur.
- `frontend/src/components/VoiceResonance/` : trois voiles Three.js,
  animation lissée et qualité adaptative. Pas de nouvelle dépendance.
- `frontend/src/hooks/useAudioSpectrum.ts` : détache seulement l'analyseur
  observateur, **pas** toutes les sorties du nœud emprunté au moteur vocal.
- `frontend/src/i18n/messages.ts` : textes français et anglais.

Ne pas modifier `AIEntity` : il est utilisé par d'autres surfaces.
L'ancien `VoiceTerrain` et son HUD sont conservés dans leurs modules, mais
ne sont plus montés dans Talk To Diapason.
Le protocole vocal, le Mesh et les permissions ne changent pas. Le correctif
vocal suivant modifie aussi la durée de vie des calculs côté backend.

## Vérification et aperçu

Depuis `frontend/` :

```sh
npx tsc --noEmit
npx vitest run
npm run build:tauri
npm run dev -- --host 127.0.0.1 --port 5177
```

Ouvrir `http://127.0.0.1:5177/resonance-preview.html`.
Ce banc est une entrée Vite de développement, absente du build de production.
Son bandeau annonce les états simulés ; il n'appelle pas le moteur vocal
et ne capture aucun micro. Il permet de vérifier les cinq états, le fil,
la fermeture et la reprise de parole. Ce n'est pas une preuve d'appel réel.

Vérification effectuée le 12 septembre : 378 tests frontend réussis,
dont 14 nouveaux tests du mouvement et du branchement audio ; TypeScript et
build frontend Tauri réussis. Vérification visuelle dans le navigateur à
1280 × 900 et 390 × 844, sans débordement horizontal ; reprise de parole
et affichage de l'erreur vérifiés avec le banc.

Cette première vérification frontend ne construisait ni ne déployait
d'installateur. L'installation Mac a ensuite été autorisée, voir ci-dessous.

## Installation Mac du 12 septembre 2026

Installée dans `/Applications/Diapason.app`, puis relancée et observée
dans WKWebView : volume de points visible, interface Résonance présente,
état d'écoute et transcription du test vocal de Carlito visibles.
La réponse sonore de bout en bout n'a pas été certifiée par cette observation.

Construction isolée à partir de `b5093d6706b9703e53f782bb05eef9c84dffe7ca`,
avec seulement les changements Résonance ajoutés. Les modifications non
commitées de Succès n'ont pas été embarquées. Sur cette copie isolée :
353 tests frontend et 49 tests Rust Tauri réussis. Deux tests Rust de sockets
étaient d'abord interdits par le bac à sable ; la suite entière est verte
après relance avec accès aux sockets locaux.

Le bundle est re-signé avec la même identité Apple Development que
l'installation précédente. Signature vérifiée avant et après remplacement.
SHA-256 du binaire installé :
`e9be98455015b8846b66013dfb63e69639a6be0e2d1be5f6e1a0efb5763b6605`.

L'ancienne application est dans
`/Users/carlito.e/.diapason/backups/Diapason.app.precedente`.
L'interface web du serveur a reçu les mêmes assets que le bundle isolé.
Le serveur Python n'a pas redémarré et `/health` répond toujours `ok`.

Windows n'a pas été mis à jour : `pc-bureau` était `offline` lors du contrôle
GitHub. Aucun push, lancement de workflow ni déploiement Windows n'a été fait.
Il reste à rendre le runner disponible, publier les changements avec accord
de Carlito, puis construire et valider le MSI et le rendu WebView2.

## Correctif vocal du 12 septembre — premier lot

### Défauts corrigés

- `useVoiceLive` retirait `micNode` à chaque interruption de lecture. Le
  micro pouvait transcrire mais l'animation n'avait plus de source. Seul
  l'arrêt de capture retire maintenant cette source.
- La lecture n'avait aucun `onended` : `speaking` survivait au dernier son.
  `LectureVocale` possède les sources en attente, les arrête à l'interruption
  et revient à l'écoute à la fin du dernier morceau. Les callbacks d'une
  ancienne lecture ne peuvent plus modifier une nouvelle réponse.
- Les sessions sont identifiées : une permission micro accordée après
  « Terminer » est immédiatement libérée ; un ancien WebSocket ne ferme
  plus la capture de la session qui l'a remplacé.
- La capture passe par un AudioWorklet local, en PCM16 mono par trames de
  20 ms. Si la WebView le refuse, repli sur 1024 échantillons (64 ms à
  16 kHz), contre 4096/256 ms auparavant. La fréquence annoncée est celle
  du contexte réel, pas une constante supposée. Aucun retour micro audible.
- Le worklet est un asset local **non inline** : une URL `data:` produite
  par Vite aurait été refusée par la CSP de Tauri. Aucune CSP assouplie.
- Une spéculation différente de la transcription confirmée est annulée
  avant le nouveau calcul, pas à la fin de la bonne réponse. Les tours
  vides, ignorés ou interrompus libèrent aussi leur spéculation ; synthèse
  en attente et rediffusion des jetons sont annulées avec elle. Une fonction
  native déjà en exécution dans un thread n'est pas tuée par cette annulation.

### Vérifications

- 375 tests Python de `tests/speech/` réussis, 7 sautés. Utiliser un
  `DIAPASON_HOME` temporaire : quelques tests voisins ouvrent la config et
  les bases par défaut. Ne pas les laisser utiliser les données de Carlito.
- TypeScript, Ruff sur les fichiers modifiés et contrôle d'identité verts.
- 373 tests frontend réussis sur la copie isolée réellement construite,
  sans les 25 tests supplémentaires de l'autre chantier Succès.
- Test navigateur du vrai AudioWorklet : 135 trames / 43 200 échantillons
  à 16 kHz, pic PCM 3921, à partir d'un oscillateur de test muet. Le bouton
  « Tester le signal sans micro » est uniquement dans l'aperçu DEV.
  Ce test n'est ni une reconnaissance de parole, ni une mesure de latence
  d'une conversation complète, ni une validation du worklet dans WKWebView.
- Build Tauri Mac réussi, signature Apple Development conservée et vérifiée.

### État déployé et limites

La correction frontend est installée dans `/Applications/Diapason.app`.
L'application a été relancée et son panneau vocal observé dans WKWebView,
micro fermé. La version précédente est conservée dans
`~/.diapason/backups/Diapason.app.precedente`.
SHA-256 du binaire installé :
`15612254317b4e508cdc4eadf0034bd72dad796bbdc8b082d9e70d8049890abc`.

Copie isolée de construction : `/private/tmp/diapason-voix-build.hkI5Bd`.
Les mêmes assets ont été copiés dans le statique du serveur ; son ancien
statique est conservé dans `static-precedent` sous cette copie.

**Le serveur Python n'a pas été relancé** (PID 67047 conservé, health `ok`).
La correction de spéculation est donc écrite et testée, mais pas encore
active dans ce processus. Une relance chargerait aussi les modifications
Succès non commitées : une demande de choix a été envoyée à Carlito.
Ne pas annoncer cette optimisation comme déjà active avant la relance.

À valider avec Carlito : suivi de sa voix dans l'app installée, reprise de
parole après une réponse et après interruption, puis temps jusqu'au premier
audio sur plusieurs conversations. Les objectifs de 100 ms pour le visuel
et 1–2 s pour une réponse simple ne sont **pas** des mesures obtenues.
Windows n'a pas été construit ni déployé pour ce lot. Aucun commit ni push.
