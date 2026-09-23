"""Les formats que le chat sait réellement rendre, sans exécuter de code."""

from diapason.core.types import Message
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
  La vue 3D s'exporte en IMAGE PNG/PDF, pas en SVG vectoriel.
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


def instruire_visuels(messages: list[Message]) -> list[Message]:
    """Le client doit annoncer son rendu, l'API texte reste compatible."""
    return ajouter_consigne(messages, CONSIGNE_VISUELS)
