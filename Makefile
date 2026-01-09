.PHONY: install install-dev format format-check lint typecheck security test precommit

install:
	python -m pip install -r requirements.txt

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

test:
	pytest -q

precommit:
	pre-commit install
	pre-commit run --all-files
