.PHONY: check
check:
	uv run mypy .
	uv run ruff check --fix
	uv run ruff format

.PHONY: test
test: check
	uv run pytest

.PHONY: install
install:
	uv tool install --force --reinstall .

.PHONY: setup
setup:
	uv sync
	uv run pre-commit install
