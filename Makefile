# Everything runs through uv, which installs Python 3.12 and the locked dependencies on first use.

.DEFAULT_GOAL := help
.PHONY: help setup models data archive run eval check test lint format

help: ## List the targets
	@grep -E '^[a-z]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  make %-7s %s\n", $$1, $$2}'

setup: ## Install dependencies and create .env from .env.example
	uv sync
	@test -f .env || (cp .env.example .env && echo "created .env: add your OPENROUTER_API_KEY")

models: ## Pull the Ollama models named in config.yaml
	@for model in $$(uv run python -c "import yaml; print(*[m['model'] for m in yaml.safe_load(open('config.yaml'))['models'].values() if m['provider'] == 'ollama'])"); do \
		ollama pull $$model; \
	done

data: ## Crawl more public job postings from djinni.co into data/
	uv run python main.py crawl-jobs

archive: ## Python postings 2019-2026 from the Wayback Machine into data/archive/ (~1 h)
	uv run python main.py crawl-archive

run: ## Run every experiment in config.yaml, then score them (results/)
	uv run python main.py run

eval: ## Re-score stored results without calling any model
	uv run python main.py eval

check: ## Count texts and golden labels, validate the labels
	uv run python main.py check

test: ## Unit tests (offline)
	uv run pytest -q

lint: ## Ruff lint and format check
	uv run ruff check .
	uv run ruff format --check .

format: ## Apply ruff fixes and formatting
	uv run ruff check --fix .
	uv run ruff format .
