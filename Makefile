.PHONY: all help install clean test test-unit test-integration \
		coverage lint format typecheck check build publish publish-test \
		example run wheel-check


all: clean build lint typecheck test

# Default target
help:
	@echo "macbundler - macOS application bundler"
	@echo ""
	@echo "Usage: make [target]"
	@echo ""
	@echo "Development:"
	@echo "  install          Install package in development mode"
	@echo "  clean            Remove build artifacts and caches"
	@echo ""
	@echo "Testing:"
	@echo "  test             Run all tests"
	@echo "  test-unit        Run unit tests only"
	@echo "  test-integration Run integration tests only"
	@echo "  coverage         Run tests with coverage report"
	@echo ""
	@echo "Code Quality:"
	@echo "  lint             Run ruff linter"
	@echo "  format           Format code with ruff"
	@echo "  typecheck        Run mypy type checker"
	@echo "  check            Run all checks (lint, typecheck, test)"
	@echo ""
	@echo "Build & Publish:"	
	@echo "  build            Build package distributions"
	@echo "  wheel-check      Check wheels"
	@echo "  publish          Publish to PyPI"
	@echo "  publish-test     Publish to Test PyPI"
	@echo ""
	@echo "Utilities:"
	@echo "  run              Run macbundler CLI"
	@echo "  example          Build, run, and cleanup example"

# ============================================================================
# Development
# ============================================================================

install:
	@uv sync

clean:
	@rm -rf build/
	@rm -rf dist/
	@rm -rf *.egg-info/
	@rm -rf .*_cache/
	@rm -rf .coverage
	@rm -rf htmlcov/
	@rm -rf demo.app/
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@find . -type f -name "*.pyo" -delete 2>/dev/null || true

# ============================================================================
# Testing
# ============================================================================

test:
	@uv run pytest tests/ -v

test-unit:
	@uv run pytest tests/test_bundler.py tests/test_dylibbundler.py -v

test-integration:
	@uv run pytest tests/test_integration.py -v

coverage:
	@uv run pytest tests/ --cov=macbundler --cov-report=term-missing --cov-report=html
	@echo "Coverage report: htmlcov/index.html"

# ============================================================================
# Code Quality
# ============================================================================

lint:
	@uv run ruff check --fix .

format:
	@uv run ruff format .

format-check:
	@uv run ruff format --check .

typecheck:
	@uv run mypy macbundler.py --ignore-missing-imports

check: lint typecheck test
	@echo "All checks passed!"

# ============================================================================
# Build & Publish
# ============================================================================

build: clean
	@uv build
	@uv run twine check dist/*

wheel-check:
	@uv run twine check dist/*

publish: build
	@uv run twine upload dist/*

publish-test: build
	@uv run twine upload --repository testpypi dist/*

# ============================================================================
# Utilities
# ============================================================================

run:
	@uv run python -m macbundler $(ARGS)

# Example: make bundle-example
example:
	@make -C tests/rpath && rm tests/rpath/dependent && rm -rf tests/rpath/libs
