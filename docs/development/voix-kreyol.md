# Voix kreyòl — détection, bascule, prononciation

29 septembre 2026. Diapason répond à la voix dans la langue du tour :
français, kreyòl ayisyen ou anglais. Une phrase mixte suit la langue
dominante. Un « ok » trop court garde la langue du tour précédent.

Le code est dans `src/diapason/speech/langues/`. Les tests sont dans
`tests/speech/test_langues.py`.

## Ce que la voix peut faire, et ce qu'elle ne peut pas

La voix parlée est Orion (`language="French"` dans
`speech/realtime/ouvrier_voix.py`). Il n'y a pas de modèle acoustique
kreyòl installé. Le timbre reste celui de Diapason. Le kreyòl est rendu
par une graphie que ce français oral prononce plus juste : consonne
finale entendue, `g` dur dans « gen ». Accélérer le son sans vocodeur
de phase monterait la hauteur et ramènerait des coupures : la vitesse
reste 1,0. Le rythme plus vif vient du texte, dont on retire « euh » et
les points de suspension. Une question garde son `?`, ou le reçoit si
elle commence par kijan, kisa, poukisa, èske.

L'écran montre l'orthographe officielle. Seule la synthèse reçoit la
graphie phonétique.

## Détection

`detecter` compte des mots qui ne sont pas partagés entre les trois
langues. « wi » n'est pas « oui », « mèsi » n'est pas « merci »,
« byen » n'est pas « bien ». Un `ò` dans un mot inconnu pèse pour le
kreyòl. À égalité, ou si rien ne tranche, la mémoire du tour précédent
reste en place. Sans mémoire, le français est le point de départ.

`language = "fr"` et `language = "français"` dans la configuration sont des
noms de langue, pas un verrou : la bascule reste ouverte. Seule une
consigne plus longue reste fixe. L'oreille Whisper, elle, reste en
français (le modèle le plus proche) et reçoit une amorce courte
(`INVITE_OREILLE`) pour pouvoir écrire mwen, mèsi, kijan.

Chaque tour libre ajoute une consigne avant le message de
l'utilisateur. Elle demande le kreyòl en orthographe officielle, avec
les tournures « men wi », « sa k ap fèt », « ann avanse », « mwen la »,
et interdit le calque du français ou de l'anglais. Le français et
l'anglais ont la consigne inverse : pas de mot kreyòl mêlé.

## Guide phonétique

Source tenue par les tests : `GUIDE_PHONETIQUE` dans
`speech/langues/phonetique.py`.

| Écrit | Lu par Orion | Pourquoi |
|---|---|---|
| tèt | tète | le t final du français se tait |
| jèn | jène | le n doit rester une consonne |
| kè | kè | le è est déjà clair |
| sè | sè | idem |
| peyi | péyi | le é tient le /e/ |
| mèsi | mèssi | le s se prononce |
| avni | avni | rien à corriger |
| lapòs | laposse | le s final doit s'entendre |
| gen | gain | /gɛ̃/, pas le « jen » du g français |

« mwen » se lit « mouin », « men wi » se lit « main oui »,
« l ap » se lit « lape » pour que le p s'entende.

Une phrase française ou anglaise n'est pas réécrite.

## Reconnaissance

Whisper n'a pas de modèle kreyòl. S'il rend la phrase en graphie
française, la détection suit cette graphie. La bascule porte sur le
texte reconnu, pas sur le son brut.
