# Découverte locale des appareils

*26 août 2026 — mDNS/DNS-SD, protocole version 1.*

## Ce que la découverte fait

Elle répare une adresse devenue périmée après un changement de Wi-Fi, de box
ou de DHCP. Elle ne crée pas d'appareil, ne jumelle personne et ne confère
aucune capacité. Un appareil doit déjà être `TRUSTED` dans le registre local.

Le service publié est :

```text
<pseudonyme>._diapason-mesh._tcp.local.
TXT: v=1
```

Le pseudonyme est un HMAC-SHA256 calculé avec la clé publique de l'appareil et
une époque d'une heure, tronqué à seize caractères base32. Les pairs déjà
appairés connaissent cette clé et calculent les valeurs attendues pour l'heure
précédente, courante et suivante. Un inconnu voit une chaîne opaque qui tourne.

## Ce qui n'est jamais publié

- le `deviceId` ;
- le nom de l'appareil ou de son propriétaire ;
- l'`ownerId` de la flotte ;
- la clé publique ou son empreinte ;
- la plateforme et la version ;
- les capacités.

Le port et l'adresse IP sont nécessairement dans SRV/A : ils ne révèlent rien
qu'un balayage du réseau local ne puisse déjà constater.

## Pourquoi mDNS n'écrit jamais dans le registre

mDNS n'est pas authentifié. Un service trouvé est donc seulement une adresse
candidate. Diapason lui envoie une balise de présence signée. Le destinataire
répond avec sa propre balise signée ; `verify_beacon` vérifie cette réponse
avec la clé Ed25519 enregistrée au jumelage, puis seulement
`heartbeat_signed` retient l'adresse.

```text
mDNS non signé
    ↓ candidat connu par pseudonyme
balise A signée → candidat
    ↓
balise B signée ← candidat
    ↓ vérification Ed25519
adresse B retenue
```

Une annonce inconnue ne reçoit aucun appel HTTP. Une annonce falsifiée ne peut
pas signer la réponse et ne change donc rien.

## Cycle de vie et limites

La tâche suit le cycle de vie FastAPI et s'arrête avec le serveur. Toutes les
quinze secondes, elle réévalue l'adresse et l'époque ; cela répare la veille et
les changements de réseau sans dépendre d'API natives différentes par OS.

Deux conditions sont cumulatives : `mesh.discovery = true` et un socket Mesh
réellement joignable sur le LAN. Un serveur limité à `127.0.0.1` ne publie
rien. IPv4 privé est supporté ; IPv6 et les adresses lien-local restent hors du
transport actuel. La validation sur un vrai réseau entre deux appareils reste
obligatoire avant de déclarer cette case pleinement fonctionnelle.
