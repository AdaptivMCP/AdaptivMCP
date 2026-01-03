.PHONY: install install-dev lint test precommit

install:
	python -m pip install -r requirements.txt

install-dev:
	python -m pip install -r dev-requirements.txt

lint:
	ruff check github_mcp tests main.py extra_tools.py

test:
	pytest -q

precommit:
	pre-commit install
	pre-commit run --all-files
