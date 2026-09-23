.PHONY: setup build test lint format

PYTHON := .venv/bin/python
MATURIN := .venv/bin/maturin

# Mirrors .github/workflows/ci.yml so `make test` matches CI locally.

# ATTENTION : `uv sync` ÉLAGUE tout extra non listé (constaté deux fois,
# dernière le 24 août 2026 : faster-whisper et pytest disparus du venv, la
# voix serait morte au redémarrage suivant). La machine de Carlito vit avec
# la liste complète ci-dessous — toujours vérifier les imports critiques
# avant de relancer un service.
setup:
	uv sync --extra dev --extra framework-comparison --extra server \
	  --extra desktop --extra tools-search --extra speech --extra voice-local \
	  --extra speech-wake --extra documents \
	  --group dev --group desktop-native
	@# sherpa-onnx perd ses dylibs à CHAQUE sync (constaté deux fois les
	@# 24 et 25 août 2026) : la roue s'installe, la bibliothèque native
	@# n'est pas reposée, et la reconnaissance du locuteur tombe. La
	@# réinstaller ici évite de rechercher la cause une troisième fois.
	uv pip install --reinstall --quiet "sherpa-onnx>=1.10"

build:
	$(MATURIN) develop --manifest-path rust/crates/diapason-python/Cargo.toml

test: build
	$(PYTHON) -m pytest tests/ -n auto -q --tb=short -m "not live and not cloud and not hub"

lint:
	$(PYTHON) -m ruff check src/ tests/
	$(PYTHON) -m ruff format --check src/ tests/

format:
	$(PYTHON) -m ruff format src/ tests/
