.PHONY: bootstrap install install-dev format format-check lint typecheck security test test-cov precommit rg-shell

bootstrap:
	python scripts/bootstrap.py --deps dev

install:
	python -m pip install -r dev-requirements.txt

install-dev:
	python -m pip install -r dev-requirements.txt

format:
	ruff format .

format-check:
	ruff format --check .

lint:
	ruff check .

typecheck:
	mypy .

security:
	python -m pip check
	pip-audit -r dev-requirements.txt
	bandit -q -r github_mcp --ini .bandit

test:
	pytest -q

test-cov:
	pytest -q --cov=github_mcp --cov-report=term-missing:skip-covered --cov-fail-under=45

precommit:
	pre-commit install
	pre-commit run --all-files

# Open an interactive shell with vendored `rg` on PATH.
rg-shell:
	./scripts/dev-shell.sh
