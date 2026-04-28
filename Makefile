.PHONY: install lint type-check test check index-build index-verify

install:
	uv pip install -e ".[dev]"

lint:
	ruff check . --fix

type-check:
	mypy turnzero/

test:
	pytest tests/ -v

check: lint type-check test

index-build:
	TURNZERO_DATA_DIR=data turnzero index build

index-verify:
	turnzero index verify

release: index-build
	hatch build
