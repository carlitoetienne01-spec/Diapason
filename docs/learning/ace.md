# L'optimiseur ACE (Agentic Context Engineering)

Diapason prend en charge [ACE](https://github.com/ace-agent/ace) comme
troisième optimiseur, aux côtés de DSPy et GEPA. Là où DSPy amorce des
exemples few-shot et où GEPA fait évoluer les prompts par mutation
réflexive, **ACE fait évoluer un *playbook* textuel** — des stratégies
en langage naturel, annotées, que l'agent lit au moment de l'inférence.
Le playbook est tenu à jour par une triade d'appels au modèle :
Generator, Reflector, Curator.

## Quand choisir ACE

| Forme de la tâche | DSPy | GEPA | ACE |
|---|---|---|---|
| Question-réponse en un tour, avec une métrique nette | fort | fort | plus faible |
| Agent au long cours qui doit accumuler des consignes | faible | moyen | fort |
| Domaine ouvert, où les stratégies comptent plus que les gabarits | faible | moyen | fort |
| Quand tu veux *lire* ce que l'optimiseur a appris | moyen | moyen | fort |

Le produit phare d'ACE, c'est `final_playbook.txt` — un fichier
lisible par un humain, dans ce genre :

```
## STRATEGIES & INSIGHTS
[str-00001] helpful=5 harmful=0 :: Quand l'utilisateur demande une
                                   conversion d'unités, préférer la
                                   forme rationnelle exacte avant
                                   d'arrondir.
[str-00002] helpful=3 harmful=1 :: Citer une source primaire avant
                                   d'affirmer une date.
```

Si lire ces stratégies ressemble à la forme de « ce que
l'apprentissage devrait produire » pour ta tâche, ACE est le bon
choix.

## L'installation

ACE **n'est pas sur PyPI** à l'heure de Diapason v1.0.1, et le dépôt
amont est organisé comme une base de code de recherche (plusieurs
dossiers à la racine) plutôt que comme un paquet Python. C'est pour
cela qu'il n'existe pas d'extra `learning-ace`. Installe plutôt ACE à
la main :

```bash
# 1. Cloner ACE quelque part en dehors de ta copie de Diapason
git clone https://github.com/ace-agent/ace.git ~/code/ace
cd ~/code/ace
curl -LsSf https://astral.sh/uv/install.sh | sh   # si tu n'as pas uv
uv sync

# 2. Rendre le src/ d'ACE importable depuis le venv de Diapason
echo "$HOME/code/ace/src" > \
  "$(python -c 'import site; print(site.getsitepackages()[0])')/ace.pth"

# 3. Poser la clé d'API du fournisseur qu'ACE va appeler
cp ~/code/ace/.env.example ~/code/ace/.env
# Modifie ~/code/ace/.env pour y poser API_KEY pour le fournisseur choisi.

# 4. Vérifier que l'import se résout depuis le venv de Diapason
python -c "from diapason.learning.agents.ace_optimizer import HAS_ACE; print(HAS_ACE)"
# True
```

Si `HAS_ACE` affiche `False`, c'est que le fichier `.pth` n'est pas
pris en compte — vérifie que le chemin correspond bien à
`site.getsitepackages()[0]` pour le même interpréteur Python que celui
avec lequel tu fais tourner Diapason.

## La configuration

ACE se configure sous `[learning.agent.ace]`, dans ton TOML de
configuration Diapason :

```toml
[learning.agent]
policy = "ace"

[learning.agent.ace]
# Les trois rôles d'ACE. Vide = hérite du modèle distant par défaut de
# la primitive Intelligence.
generator_model = "claude-opus-4-7"
reflector_model = "claude-opus-4-7"
curator_model = "claude-sonnet-4-6"

api_provider = "openai"     # sambanova | together | openai | commonstack

num_epochs = 1
max_num_rounds = 3
playbook_token_budget = 80000
max_tokens = 4096

task_name = "diapason"
save_dir = ""               # par défaut : ~/.diapason/learning/ace/<task>/

min_traces = 20
```

## Le lancement

Une fois configuré, le même orchestrateur qui lance DSPy et GEPA lance
aussi ACE — choisis-le par le champ `policy` ci-dessus. Pour forcer un
lancement unique :

```bash
diapason optimize agent --policy ace
```

ACE écrit son état intermédiaire et le playbook final dans `save_dir`.
Diapason reprendra le playbook au prochain démarrage de l'agent (par
le même mécanisme d'overlay annexe que celui qu'utilise le système de
compétences).

## Le comportement de l'adaptateur de traces

Les traces de Diapason sont converties au format `train_samples` /
`val_samples` / `test_samples` d'ACE par une découpe 70 / 15 / 15 (qui
préserve l'ordre, pour la reproductibilité). Chaque trace devient un
échantillon `{question: trace.query, ground_truth_answer:
trace.result}`. Les traces dont le `query` ou le `result` est vide
sont écartées avant la découpe.

Le `DataProcessor` qu'attend ACE est bâti à partir de
`_TraceDataProcessor`, dans
`src/diapason/learning/agents/ace_optimizer.py` — il fait une
recherche de sous-chaîne insensible à la casse pour
`answer_is_correct`, et en prend la moyenne comme justesse globale. Si
tu optimises pour un domaine où la sous-chaîne est le mauvais signal
de justesse (problèmes de maths, code, sorties structurées), dérive
`_TraceDataProcessor` et passe-le depuis ton propre appelant à
`ACEAgentOptimizer.optimize()`.

## Les limites en v1.0.1

- **Pas d'installation automatique.** Le document ci-dessus est le
  seul chemin.
- **L'adaptateur de traces juge la justesse par sous-chaîne.**
  Redéfinis-le pour un score propre à ton domaine.
- **Un seul fournisseur par lancement.** ACE attribue le même
  `api_provider` aux trois rôles. Pour en mélanger plusieurs, lance
  ACE hors de Diapason et dépose toi-même le playbook obtenu dans
  `save_dir`.

Tout cela sera repris le jour où ACE publiera un paquet PyPI ou une
interface de fournisseur stable — suis
[ace-agent/ace#issues](https://github.com/ace-agent/ace/issues) pour
les changements amont qui nous permettraient de resserrer l'enveloppe.
