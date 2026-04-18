.PHONY: install lint type-check test check index-build index-verify

install:
	uv pip install -e ".[dev]"

lint:
	ruff check . --fix

type-check:
	mypy promptgraph/

test:
	pytest tests/ -v

check: lint type-check test

index-build:
	promptgraph index build

index-verify:
	promptgraph index verify
