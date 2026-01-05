.PHONY: help install install-prod build clean clean-venv test test-coverage lint lint-check format format-check dev-install uninstall check pre-commit venv

# Virtual environment configuration
VENV := .venv
PYTHON := $(VENV)/bin/python3
PIP := $(VENV)/bin/pip3

# Detect if we should use venv (skip if SKIP_VENV=1)
ifndef SKIP_VENV
  USE_VENV := 1
endif

help:
	@echo "G-Ledger Build Commands"
	@echo "======================="
	@echo ""
	@echo "Development:"
	@echo "  make dev-install    Install in development mode (editable)"
	@echo "  make test           Run test suite"
	@echo "  make test-coverage  Run tests with coverage report"
	@echo "  make lint           Check code quality with ruff"
	@echo "  make lint-check     Check code quality (no fixes)"
	@echo "  make format         Format code with black"
	@echo "  make format-check   Check code formatting (no changes)"
	@echo "  make check          Run all pre-commit checks (alias: pre-commit)"
	@echo ""
	@echo "Production:"
	@echo "  make build          Build distribution packages"
	@echo "  make install        Install package (production)"
	@echo "  make install-prod   Build and install for production"
	@echo "  make uninstall      Remove installed package"
	@echo ""
	@echo "Cleanup:"
	@echo "  make clean          Remove build artifacts"
	@echo "  make clean-venv     Remove virtual environment"
	@echo ""
	@echo "Note: Virtual environment (.venv) is auto-created and used."
	@echo "      Set SKIP_VENV=1 to use system Python instead."

# Create virtual environment if it doesn't exist
venv:
ifdef USE_VENV
	@if [ ! -d "$(VENV)" ]; then \
		echo "Creating virtual environment in $(VENV)..."; \
		python3 -m venv $(VENV); \
		echo "✓ Virtual environment created"; \
		echo "Installing pip and build tools..."; \
		$(PIP) install --upgrade pip setuptools wheel; \
		echo "✓ Build tools installed"; \
	fi
endif

# Development installation (editable)
dev-install: venv
ifdef USE_VENV
	$(PIP) install -e ".[dev]"
else
	pip install -e ".[dev]"
endif

# Production installation from source
install:
	pip install .

# Build distribution packages
build: venv
ifdef USE_VENV
	$(PIP) install --upgrade build
	$(PYTHON) -m build
else
	python3 -m pip install --upgrade build
	python3 -m build
endif

# Build and install for production
install-prod: clean build
	pip install dist/*.whl

# Uninstall the package
uninstall:
	pip uninstall -y gledger

# Run tests
test: venv
ifdef USE_VENV
	$(PYTHON) -m pytest tests/ -v
else
	python3 -m pytest tests/ -v
endif

# Run tests with coverage
test-coverage: venv
ifdef USE_VENV
	$(PYTHON) -m pytest tests/ -v --cov=gledger --cov-report=html --cov-report=term
else
	python3 -m pytest tests/ -v --cov=gledger --cov-report=html --cov-report=term
endif

# Lint code (with auto-fix)
lint: venv
ifdef USE_VENV
	$(PYTHON) -m ruff check src/ tests/ --fix
else
	python3 -m ruff check src/ tests/ --fix
endif

# Lint code (check only, no fixes)
lint-check: venv
ifdef USE_VENV
	$(PYTHON) -m ruff check src/ tests/
else
	python3 -m ruff check src/ tests/
endif

# Format code
format: venv
ifdef USE_VENV
	$(PYTHON) -m black src/ tests/
else
	python3 -m black src/ tests/
endif

# Check code formatting (no changes)
format-check: venv
ifdef USE_VENV
	$(PYTHON) -m black --check src/ tests/
else
	python3 -m black --check src/ tests/
endif

# Pre-commit verification - runs all checks
check: format-check lint-check test build
	@echo ""
	@echo "✅ All pre-commit checks passed!"
	@echo "   - Code formatting verified"
	@echo "   - Linting passed"
	@echo "   - All tests passed"
	@echo "   - Build succeeded"
	@echo ""
	@echo "Ready to commit! 🚀"

# Alias for check
pre-commit: check

# Clean build artifacts
clean:
	rm -rf build/
	rm -rf dist/
	rm -rf src/*.egg-info
	rm -rf .pytest_cache/
	rm -rf .coverage
	rm -rf htmlcov/
	rm -rf .ruff_cache/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete

# Clean virtual environment
clean-venv:
	rm -rf $(VENV)
	@echo "✓ Virtual environment removed"
