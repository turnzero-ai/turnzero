.PHONY: install lint type-check test check index-build index-verify install-hooks uninstall-hooks

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

install-hooks:
	@cp .claude/hooks/pre-commit.sh .git/hooks/pre-commit
	@cp .claude/hooks/pre-push.sh .git/hooks/pre-push
	@chmod +x .git/hooks/pre-commit .git/hooks/pre-push
	@echo "✓ Git hooks installed (pre-commit + pre-push)"
	@echo "  Note: .claude/hooks/*.py are gitignored — kept locally only."
	@echo "  If missing after a fresh setup, restore from this repo's sprint history."

uninstall-hooks:
	@rm -f .git/hooks/pre-commit .git/hooks/pre-push
	@echo "✓ Git hooks removed"
