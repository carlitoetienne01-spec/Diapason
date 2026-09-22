---
title: Extraits de code
description: Des motifs à copier-coller pour les tâches Diapason les plus courantes
---

# Extraits de code

Des motifs prêts à l'emploi pour les tâches Diapason les plus courantes. Chaque extrait se suffit à lui-même et se copie-colle tel quel.

## Poser une question (3 lignes)

```python
from diapason import Diapason

with Diapason() as j:
    print(j.ask("Quelle est la capitale de la France ?"))
```

## Recevoir les jetons au fil de l'eau (4 lignes)

```python
import asyncio
from diapason import Diapason

async def main():
    with Diapason() as j:
        async for token in j.ask_stream("Raconte-moi une histoire"):
            print(token, end="", flush=True)

asyncio.run(main())
```

## Un agent avec des outils (5 lignes)

```python
from diapason import Diapason

with Diapason() as j:
    result = j.ask_full(
        "Cherche sur le web la dernière version de Python",
        agent="orchestrator",
        tools=["web_search", "think"],
    )
    print(result["content"])
```

## Mémoire : indexer + chercher (6 lignes)

```python
from diapason import Diapason

with Diapason() as j:
    j.memory.index("./docs/", chunk_size=512)
    results = j.memory.search("options de déploiement")
    for r in results:
        print(f"[{r['score']:.3f}] {r['content'][:100]}")
```

## Une recette TOML (4 lignes)

Décris un enchaînement d'agents en TOML — sans écrire une ligne de code :

```toml
[recipe]
name = "research_assistant"
agent = "orchestrator"
tools = ["web_search", "think", "file_read"]
prompt = "Fais des recherches sur le sujet donné et rédige un résumé."
```

Lance-la avec : `diapason compose run research_assistant "les avancées de l'informatique quantique"`

## Le serveur d'API (1 commande)

```bash
diapason serve --port 8000 --engine ollama --model qwen3:8b
```

N'importe quel client compatible OpenAI fonctionne avec ce point d'entrée.

## Déploiement Docker (2 commandes)

```bash
docker build -t diapason .
docker run -p 8000:8000 diapason serve --host 0.0.0.0
```

## Un outil maison (10 lignes)

```python
from diapason.core.registry import ToolRegistry
from diapason.core.types import ToolResult
from diapason.tools._stubs import BaseTool, ToolSpec

@ToolRegistry.register("my_tool")
class MyTool(BaseTool):
    tool_id = "my_tool"

    @property
    def spec(self):
        return ToolSpec(name="my_tool", description="Mon outil maison",
                        parameters={"type": "object", "properties": {"input": {"type": "string"}}})

    def execute(self, **params):
        return ToolResult(tool_name="my_tool", content=f"Traité : {params.get('input', '')}", success=True)
```

## Aiguiller entre plusieurs modèles (5 lignes)

```python
from diapason import Diapason

j = Diapason()
# L'aiguilleur choisit tout seul le meilleur modèle pour chaque question
simple = j.ask("Combien font 2+2 ?")            # part vers le modèle rapide et économe
complex = j.ask("Analyse cet article de recherche...")  # part vers le modèle capable
j.close()
```

## Demander confirmation à l'humain (6 lignes)

```python
from diapason import Diapason

with Diapason() as j:
    result = j.ask_full(
        "Supprime les vieux fichiers de journaux dans /tmp",
        agent="orchestrator",
        tools=["shell_exec", "file_read"],
    )
    print(f"L'agent a fait {result['turns']} tours")
    print(result["content"])
```

Des outils comme `shell_exec` peuvent recevoir `requires_confirmation: true` dans le TOML pour demander ton accord avant d'agir.
