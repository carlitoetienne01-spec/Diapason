"""Les formats que le chat sait réellement rendre, sans exécuter de code."""

import re
import unicodedata

from diapason.core.types import Message, Role
from diapason.server.questions_chat import ajouter_consigne

CONSIGNE_VISUELS = """VISUELS DANS LE CHAT
Si un schéma, une illustration ou un graphique est demandé ou aide vraiment,
produis directement le visuel dans un bloc Markdown fermé. N'annonce pas un
fichier inexistant et ne demande pas d'installer un logiciel. Choisis :
- ```mermaid pour les diagrammes : flowchart, sequenceDiagram, classDiagram,
  stateDiagram-v2, erDiagram, gantt, pie, mindmap ou timeline. Libellés courts.
  Pas de directive init, frontmatter, HTML, liens, style ou classDef.
- ```svg pour les illustrations : un SVG autonome avec xmlns et viewBox,
  title et desc, formes et texte. Aucun script, style CSS, image externe ou
  événement. Utilise les attributs fill/stroke avec var(--color-accent),
  var(--color-text), var(--color-bg) et var(--color-border) pour suivre le thème.
- ```diapason-chart pour les données : JSON strict au format
  {"title":"Titre","type":"bar","xKey":"name",
   "series":[{"key":"value","label":"Valeur"}],
   "data":[{"name":"A","value":12}],"sample":true,"source":"Exemple fictif"}.
  Types : bar, line, area, pie. Pour pie : une série, valeurs positives.
  Valeurs numériques finies ; aucune fonction JavaScript. Les noms de clés
  commencent par une lettre et ne contiennent que lettres, chiffres, _.
- ```diapason-matplotlib pour une figure scientifique vectorielle ;
  ```diapason-plotly pour zoomer dans les axes et lire les valeurs au survol.
  Dans les DEUX cas, JSON strict, jamais de code Python/JavaScript :
  {"title":"Mesures","type":"scatter","xLabel":"Temps (s)",
   "yLabel":"Distance (m)","series":[{"name":"Essai","x":[1,2,3],
   "y":[2,4,5],"errorY":[0.1,0.2,0.1]}],"sample":true,
   "source":"Exemple fictif"}.
  Types : line, scatter, histogram. errorY facultatif, positif, même
  longueur que x/y. Histogramme : observations dans x, sans y/errorY,
  bins de 2 à 60 (12 par défaut). Maximum 6 séries et 300 points AU TOTAL.
  Matplotlib uniquement : type heatmap avec matrix rectangulaire
  (20×20 maximum), xLabels/yLabels facultatifs, sans series.
  Nombres finis entre -1e12 et 1e12, aucune formule à évaluer.
  Privilégie diapason-chart pour les graphiques simples à catégories.
- ```diapason-plotly3d : vue 3D interactive. JSON uniquement :
  {"title":"Points","type":"scatter3d","xLabel":"X","yLabel":"Y",
   "zLabel":"Z","series":[{"name":"A","x":[1,2],"y":[2,4],"z":[3,5]}],
   "sample":true,"source":"Exemple fictif"}.
  Maximum 6 séries et 300 points au total, longueurs x/y/z égales.
  Une surface prend type="surface", matrix rectangulaire de hauteurs
  (2×2 à 20×20), sans series ; X/Y sont alors les indices de la grille.
  Nombres finis entre -1e12 et 1e12, aucune formule ou code.
  Pour des ENSEMBLES CONCEPTUELS (Ikigai, zones qui se recoupent),
  utilise type="venn3d", PAS scatter3d ni des axes chiffrés :
  {"title":"Relations","type":"venn3d",
   "sets":[{"id":"a","label":"Créativité"},{"id":"b","label":"Technique"}],
   "intersections":[],"centerLabel":"Création"}.
  De 2 à 4 ensembles, identifiants uniques, libellés de 80 caractères maximum.
  Ils sont disposés depuis le haut dans le sens antihoraire. Pour 3 ou 4
  ensembles : intersections facultatives ENTRE DEUX VOISINS, avec
  {"sets":["a","b"],"label":"Relation"}. Pas de doublons ni de paires opposées.
  centerLabel nomme la zone commune. Relations et centre : 40 caractères max.
  source facultative. Aucun champ series, matrix, sample ou axe pour venn3d.
  Vue de face vectorielle par défaut : cercles vides aux contours blancs
  sur fond noir, leur zone commune en rouge, textes sans encadrés. La
  rotation 3D est accessible dans les options. Aucune échelle quantitative.
  La vue 3D s'exporte en IMAGE PNG/PDF, pas en SVG vectoriel.
Un point isolé ne représente PAS un diagramme conceptuel. Vérifie avant de
répondre que chaque ensemble et chaque relation décrits figurent dans le
dessin. Ne décris pas une couleur précise des données : le rendu l'adapte
au thème. Exception : venn3d a une zone commune rouge, par convention.
Ne fabrique pas des chiffres réels : utilise les données fournies/reçues,
cite leur origine dans source ; sample=false pour des mesures fournies,
sample=true UNIQUEMENT pour des valeurs fictives de simulation/exemple.
Si les données indispensables manquent, demande-les. Explique brièvement le
visuel. Maximum 8 visuels par réponse, 300 lignes de données, 8 séries,
160 lignes Mermaid et 60000 caractères par SVG. Modifie un visuel demandé
en renvoyant sa version complète, conservée dans la discussion.
IMPORTANT : le nom après les trois accents graves active le dessin.
N'emploie JAMAIS ```json pour un graphique à afficher. Exemple COMPLET :
```diapason-plotly
{"title":"Exemple","type":"line",
 "series":[{"name":"A","x":[1,2],"y":[2,4]}],
 "sample":true,"source":"Valeurs fictives"}
```
"""

# Le 23/09/2026, le modèle a appelé « Ikigai » un point (0,0,0), puis
# décrit quatre éléments absents du dessin. Cet exemple structurel fournit
# les relations du schéma populaire, sans inventer les réponses de Carlito.
EXEMPLE_IKIGAI = """POUR LE DIAGRAMME IKIGAI DEMANDÉ
Utilise le schéma populaire à QUATRE dimensions distinctes : aimer,
être doué, être rémunéré, besoins du monde. Ne fusionne pas deux dimensions
dans un axe Z. Ce schéma est une interprétation populaire de l'ikigai,
pas sa définition complète ni une mesure de la personne.
Voici le bloc complet qui rend réellement les quatre zones et leurs liens.
Adapte les libellés à la langue du demandeur. N'invente pas ses réponses
personnelles. Ne substitue pas un nuage de points à ces ensembles :
```diapason-plotly3d
{"title":"Ikigai — quatre dimensions","type":"venn3d",
 "sets":[{"id":"aimer","label":"Ce que tu aimes"},
         {"id":"talent","label":"Ce pour quoi tu es doué"},
         {"id":"revenu","label":"Ce pour quoi tu peux être rémunéré"},
         {"id":"besoin","label":"Ce dont le monde a besoin"}],
 "intersections":[{"sets":["aimer","talent"],"label":"Passion"},
                  {"sets":["talent","revenu"],"label":"Profession"},
                  {"sets":["revenu","besoin"],"label":"Vocation"},
                  {"sets":["besoin","aimer"],"label":"Mission"}],
 "centerLabel":"Ikigai",
 "source":"Interprétation populaire à quatre cercles"}
```
Explique brièvement le schéma déjà produit, au présent. Ne dis pas seulement
que tu vas le générer. La zone rouge est l'intersection des QUATRE cercles,
pas un point ni un carré décoratif. Aucun volume rempli, cartouche de texte
ou axe chiffré. La vue de face s'affiche d'abord ; la rotation reste optionnelle.
"""


def demande_diagramme_ikigai(messages: list[Message]) -> bool:
    """Seul le dernier tour utilisateur active cet exemple spécialisé."""
    dernier = next(
        (m.content or "" for m in reversed(messages) if m.role == Role.USER), ""
    )
    plat = "".join(
        c
        for c in unicodedata.normalize("NFKD", dernier.casefold())
        if not unicodedata.combining(c)
    )
    return bool(
        re.search(r"\bikigai\b", plat)
        and re.search(
            r"\b(?:diagramme|schema|dessin\w*|diagram|draw|illustr\w*|"
            r"fais|fait|cree|genere|trace|represente|create|generate)\b",
            plat,
        )
    )


def instruire_visuels(messages: list[Message]) -> list[Message]:
    """Le client doit annoncer son rendu, l'API texte reste compatible."""
    consigne = CONSIGNE_VISUELS
    if demande_diagramme_ikigai(messages):
        consigne += "\n" + EXEMPLE_IKIGAI
    return ajouter_consigne(messages, consigne)
