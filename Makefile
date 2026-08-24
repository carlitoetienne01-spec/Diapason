.PHONY: setup build test lint format

# Mirrors .github/workflows/ci.yml so `make test` matches CI locally.

# ATTENTION : `uv sync` ÉLAGUE tout extra non listé (constaté deux fois,
# dernière le 24 août 2026 : faster-whisper et pytest disparus du venv, la
# voix serait morte au redémarrage suivant). La machine de Carlito vit avec
# la liste complète ci-dessous — toujours vérifier les imports critiques
# avant de relancer un service.
setup:
	uv sync --extra dev --extra framework-comparison --extra server \
	  --extra desktop --extra tools-search --extra speech --extra voice-local \
	  --group dev --group desktop-native

build:
	uv run maturin develop --manifest-path rust/crates/diapason-python/Cargo.toml

test: build
	uv run pytest tests/ -n auto -q --tb=short -m "not live and not cloud and not hub"

lint:
	uv run ruff check src/ tests/
	uv run ruff format --check src/ tests/

format:
	uv run ruff format src/ tests/
