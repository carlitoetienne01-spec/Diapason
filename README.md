<div align="center">
  <h1>Diapason</h1>
  <p><em>(dérivé d'Diapason — Personal AI, On Personal Devices)</em></p>

  <p><i>Personal AI, On Personal Devices.</i></p>

  <p>
    <a href="https://arxiv.org/abs/2605.17172"><img src="https://img.shields.io/badge/arXiv-2605.17172-b31b1b.svg" alt="arXiv"></a>
    <a href="https://diapason.stanford.edu/"><img src="https://img.shields.io/badge/project-Diapason-blue" alt="Project"></a>
    <a href="https://carlitoetienne01-spec.github.io/Diapason/"><img src="https://img.shields.io/badge/docs-mkdocs-blue" alt="Docs"></a>
    <img src="https://img.shields.io/badge/python-%3E%3D3.10-blue" alt="Python">
    <img src="https://img.shields.io/badge/license-Apache%202.0-green" alt="License">
    <a href="https://discord.gg/CMVBmDQ5Fj"><img src="https://img.shields.io/badge/discord-join-7289da?logo=discord&logoColor=white" alt="Discord"></a>
    <a href="https://x.com/DiapasonAI"><img src="https://img.shields.io/badge/X-@DiapasonAI-black?logo=x&logoColor=white" alt="X / Twitter"></a>
  </p>
</div>

---

<div align="center">
  <img alt="Diapason demo reel" src="assets/diapason_demo_reel.webp" width="75%">
</div>

---

> **[Documentation](https://carlitoetienne01-spec.github.io/Diapason/)**
>
> **[Project Site](https://diapason.stanford.edu/)**
>
> **[Paper](https://arxiv.org/abs/2605.17172)**
>
> **[Roadmap](https://carlitoetienne01-spec.github.io/Diapason/development/roadmap/)**

## Why Diapason?

Personal AI agents are exploding in popularity, but nearly all of them still route intelligence through cloud APIs. Your "personal" AI continues to depend on someone else's server. At the same time, our [Intelligence Per Watt](https://www.intelligence-per-watt.ai/) research showed that local language models already handle 88.7% of single-turn chat and reasoning queries, with intelligence efficiency improving 5.3× from 2023 to 2025. The models and hardware are increasingly ready. What has been missing is the software stack to make local-first personal AI practical.

Diapason is that stack. It is a framework for local-first personal AI, built around three core ideas: shared primitives for building on-device agents; evaluations that treat energy, FLOPs, latency, and dollar cost as first-class constraints alongside accuracy; and a learning loop that improves models using local trace data. The goal is simple: make it possible to build personal AI agents that run locally by default, calling the cloud only when truly necessary. Diapason aims to be both a research platform and a production foundation for local AI, in the spirit of PyTorch.

## Installation status

This repository is currently private, its GitHub Pages installer URLs are not
published, and its GitHub Releases list is empty. There is therefore no honest
public one-liner or downloadable `.msi`/AppImage yet.

- **macOS:** the working desktop build is installed locally with
  `./scripts/install-desktop.sh` from an authenticated checkout.
- **Native Windows:** clone with an authorized GitHub account, then run
  `deploy/windows/install.ps1`. This installs the Python server and browser UI;
  the Tauri `.msi` still needs validation on a real Windows machine.
- **Linux / WSL2:** use the authenticated checkout and the Unix installer;
  packaged desktop artifacts are not released yet.

The prepared Tauri release workflow will publish Windows, macOS and Linux
artifacts after hosted runners and signing are restored. Until then, see the
in-repository installation docs rather than the unavailable GitHub Pages site.

## Quick Start

```bash
diapason                          # start chatting (default: chat-simple)
diapason init --preset <name>     # switch to a starter config
```

> Prefix `diapason ...` with `uv run`, or `source .venv/bin/activate` first.

| Preset | What it does |
|---|---|
| `morning-digest-mac` / `morning-digest-linux` / `morning-digest-minimal` | Spoken daily briefing from email, calendar, health, news |
| `deep-research` | Multi-hop research across indexed docs with citations |
| `code-assistant` | Agent with code execution, file I/O, and shell access |
| `scheduled-monitor` | Stateful agent on a schedule with memory |
| `chat-simple` | Lightweight conversation, no tools |

Example:

```bash
diapason init --preset morning-digest-mac
diapason connect gdrive          # one OAuth covers Gmail / Calendar / Tasks
diapason digest --fresh          # generate and play your first briefing
```

Per-preset deep dives: [morning digest](https://carlitoetienne01-spec.github.io/Diapason/user-guide/morning-digest/) · [deep research](https://carlitoetienne01-spec.github.io/Diapason/user-guide/deep-research/) · [code assistant](https://carlitoetienne01-spec.github.io/Diapason/user-guide/code-assistant/) · [scheduled monitor](https://carlitoetienne01-spec.github.io/Diapason/user-guide/scheduled-monitor/) · [chat simple](https://carlitoetienne01-spec.github.io/Diapason/user-guide/chat-simple/) · or the full [quickstart guide](https://carlitoetienne01-spec.github.io/Diapason/getting-started/quickstart/).

### Skills

Skills teach agents how to better use tools and improve their reasoning. Every skill is a tool — agents discover them from a catalog and invoke them on demand.

```bash
# Install skills from public sources
diapason skill install hermes:arxiv
diapason skill sync hermes --category research

# Use skills with any agent
diapason ask "Use the code-explainer skill to explain this Python code: for i in range(5): print(i*2)"

# Optimize skills from your trace history
diapason optimize skills --policy dspy

# Benchmark the impact
diapason bench skills --max-samples 5 --seeds 42
```

Import from [Hermes Agent](https://github.com/NousResearch/hermes-agent) (~150 skills), [OpenClaw](https://github.com/openclaw/skills) (~13,700 community skills), or any GitHub repo. Skills follow the [agentskills.io](https://agentskills.io/specification) open standard.

See the [Skills User Guide](https://carlitoetienne01-spec.github.io/Diapason/user-guide/skills/) and [Skills Tutorial](https://carlitoetienne01-spec.github.io/Diapason/tutorials/skills-workflow/) for details.

### Built-in Agents

Diapason ships with eight built-in agents across three execution modes (on-demand, scheduled, continuous):

| Agent | Type | What it does |
|-------|------|-------------|
| `morning_digest` | Scheduled | Daily briefing from email, calendar, health, news — with TTS audio |
| `deep_research` | On-demand | Multi-hop research with citations across web and local docs |
| `monitor_operative` | Continuous | Long-horizon monitoring with memory, compression, and retrieval |
| `orchestrator` | On-demand | Multi-turn reasoning with automatic tool selection |
| `native_react` | On-demand | ReAct (Thought-Action-Observation) loop agent |
| `operative` | Continuous | Persistent autonomous agent with state management |
| `native_openhands` | On-demand | CodeAct — generates and executes Python code |
| `simple` | On-demand | Single-turn chat, no tools |

See the [User Guide](https://carlitoetienne01-spec.github.io/Diapason/user-guide/morning-digest/) and [Tutorials](https://carlitoetienne01-spec.github.io/Diapason/tutorials/) for detailed setup instructions.

Full documentation — including Docker deployment, cloud engines, development setup, and tutorials — at **[carlitoetienne01-spec.github.io/Diapason](https://carlitoetienne01-spec.github.io/Diapason/)**.

## Community

- **GitHub:** [github.com/carlitoetienne01-spec/Diapason](https://github.com/carlitoetienne01-spec/Diapason)
- **Discord:** [discord.gg/CMVBmDQ5Fj](https://discord.gg/CMVBmDQ5Fj)
- **X / Twitter:** [@DiapasonAI](https://x.com/DiapasonAI)
- **Docs:** [carlitoetienne01-spec.github.io/Diapason](https://carlitoetienne01-spec.github.io/Diapason/)

## Contributing

We welcome contributions! See the [Contributing Guide](CONTRIBUTING.md) for incentives, contribution types, and the PR process.

Quick start for contributors:

```bash
git clone https://github.com/carlitoetienne01-spec/Diapason.git
cd Diapason
uv sync --extra dev
uv run pre-commit install
uv run pytest tests/ -v
```

Browse the [Roadmap](https://carlitoetienne01-spec.github.io/Diapason/development/roadmap/) for areas where help is needed. Comment **"take"** on any issue to get auto-assigned.

## About

Diapason is part of [Intelligence Per Watt](https://www.intelligence-per-watt.ai/), a research initiative studying the intelligence efficiency of AI systems. The project is developed at [Hazy Research](https://hazyresearch.stanford.edu/) and the [Scaling Intelligence Lab](https://scalingintelligence.stanford.edu/) at [Stanford SAIL](https://ai.stanford.edu/).

## Sponsors

<p>
  <a href="https://www.laude.org/">Laude Institute</a> &bull;
  <a href="https://datascience.stanford.edu/marlowe">Stanford Marlowe</a> &bull;
  <a href="https://cloud.google.com/">Google Cloud Platform</a> &bull;
  <a href="https://lambda.ai/">Lambda Labs</a> &bull;
  <a href="https://ollama.com/">Ollama</a> &bull;
  <a href="https://research.ibm.com/">IBM Research</a> &bull;
  <a href="https://hai.stanford.edu/">Stanford HAI</a>
</p>

## Citation
```bibtex
@misc{saadfalcon2026diapasonpersonalaipersonal,
      title={Diapason: Personal AI, On Personal Devices}, 
      author={Jon Saad-Falcon and Avanika Narayan and Robby Manihani and Tanvir Bhathal and Herumb Shandilya and Hakki Orhun Akengin and Gabriel Bo and Andrew Park and Matthew Hart and Caia Costello and Chuan Li and Christopher Ré and Azalia Mirhoseini},
      year={2026},
      eprint={2605.17172},
      archivePrefix={arXiv},
      primaryClass={cs.LG},
      url={https://arxiv.org/abs/2605.17172}, 
}
```

## License

[Apache 2.0](LICENSE)
