# =============================================================================
# Archeon 3D — top-level Makefile
# =============================================================================
# Common tasks for local development, testing, and packaging. Run
# ``make help`` for a quick reference.
#
# Conventions:
# - ``make dev``         starts the API + the Vite frontend (two processes)
# - ``make test``        runs the full test matrix
# - ``make lint``        type-checks and lints
# - ``make build``       builds the frontend bundle
# - ``make clean``       removes build artifacts and caches
# =============================================================================

SHELL := /usr/bin/env bash
.SHELLFLAGS := -eu -o pipefail -c

# Where things live.
VENV         ?= .venv
PYTHON       ?= $(VENV)/bin/python
PIP          ?= $(VENV)/bin/pip
UVICORN      ?= $(VENV)/bin/uvicorn
FRONTEND_DIR := archeon_frontend
FRONTEND_PKG := $(FRONTEND_DIR)/package.json

# Load .env if present, so the targets pick up ARCHEON_* env vars.
ifneq (,$(wildcard ./.env))
include .env
export $(shell sed -n 's/^\([A-Z_][A-Z0-9_]*\)=.*/\1/p' .env 2>/dev/null)
endif

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help message.
	@awk 'BEGIN {FS = ":.*##"; printf "Targets:\n"} /^[a-zA-Z_-]+:.*##/ { printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

# ---------------------------------------------------------------------------
# Environment setup
# ---------------------------------------------------------------------------

.PHONY: venv
venv: ## Create the Python virtualenv (.venv) and upgrade pip.
	@if [ ! -d "$(VENV)" ]; then \
		echo ">>> creating venv at $(VENV)"; \
		python3 -m venv $(VENV); \
		$(PIP) install --upgrade pip wheel setuptools; \
	else \
		echo ">>> venv already exists at $(VENV)"; \
	fi

.PHONY: install
install: venv ## Install the package (incl. dev + ml extras) into the venv.
	@echo ">>> installing hy3dgen (with ml + dev extras)"
	$(PIP) install -e ".[ml,dev]"

.PHONY: install-native
install-native: install ## Compile texture extensions (requires CUDA toolkit + C++ compiler).
	ARCHEON_BUILD_NATIVE=1 $(PIP) install --no-build-isolation -e .

.PHONY: install-api
install-api: venv ## Install only the API deps (no model weights). Lightweight.
	@echo ">>> installing hy3dgen (API-only)"
	$(PIP) install -e ".[dev]"

.PHONY: install-frontend
install-frontend: ## Install npm deps for the frontend.
	@echo ">>> installing archeon_frontend deps"
	cd $(FRONTEND_DIR) && npm install --no-audit --no-fund

# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------

.PHONY: api
api: ## Start the Archeon API on $$ARCHEON_HOST:$$ARCHEON_PORT.
	@if [ ! -x "$(UVICORN)" ]; then echo ">>> venv missing — run 'make install' first"; exit 1; fi
	@echo ">>> starting API on http://$${ARCHEON_HOST:-127.0.0.1}:$${ARCHEON_PORT:-8081}"
	$(UVICORN) hy3dgen.api.server:app --host $${ARCHEON_HOST:-127.0.0.1} --port $${ARCHEON_PORT:-8081} --reload

.PHONY: frontend
frontend: ## Start the Vite dev server.
	@if [ ! -d "$(FRONTEND_DIR)/node_modules" ]; then echo ">>> frontend deps missing — run 'make install-frontend' first"; exit 1; fi
	@echo ">>> starting Vite dev server"
	cd $(FRONTEND_DIR) && npm run dev

.PHONY: dev
dev: ## Start API + frontend together (concurrently).
	@if [ ! -x "$(UVICORN)" ]; then $(MAKE) install-api; fi
	@if [ ! -d "$(FRONTEND_DIR)/node_modules" ]; then $(MAKE) install-frontend; fi
	@trap 'kill 0' INT TERM EXIT; \
		$(MAKE) --no-print-directory api & \
		$(MAKE) --no-print-directory frontend & \
		wait

# ---------------------------------------------------------------------------
# Tests + lint
# ---------------------------------------------------------------------------

.PHONY: test
test: ## Run the full pytest suite.
	@if [ ! -x "$(PYTHON)" ]; then $(MAKE) install-api; fi
	PYTHONPATH=. $(PYTHON) -m pytest tests/ -ra \
		--ignore=tests/test_texgen_loading.py \
		--ignore=tests/test_imports.py

.PHONY: lint
lint: ruff mypy tsc eslint ## Run all linters (ruff + mypy + tsc + eslint).

.PHONY: ruff
ruff: ## Run ruff (fast linter + formatter check).
	ruff check hy3dgen tests
	ruff format --check hy3dgen tests

.PHONY: ruff-fix
ruff-fix: ## Auto-fix what ruff can.
	ruff check hy3dgen tests --fix
	ruff format hy3dgen tests

.PHONY: mypy
mypy: ## Type-check the Python package.
	@if [ ! -x "$(PYTHON)" ]; then $(MAKE) install-api; fi
	rm -rf .mypy_cache
	$(PYTHON) -m mypy --follow-imports=silent --explicit-package-bases hy3dgen

.PHONY: tsc
tsc: ## Type-check the frontend.
	@if [ ! -d "$(FRONTEND_DIR)/node_modules" ]; then $(MAKE) install-frontend; fi
	cd $(FRONTEND_DIR) && npx tsc -b --noEmit

.PHONY: eslint
eslint: ## Lint the frontend.
	@if [ ! -d "$(FRONTEND_DIR)/node_modules" ]; then $(MAKE) install-frontend; fi
	cd $(FRONTEND_DIR) && npx eslint .

# ---------------------------------------------------------------------------
# Build artifacts
# ---------------------------------------------------------------------------

.PHONY: build
build: build-frontend ## Build everything (frontend bundle).

.PHONY: build-frontend
build-frontend: ## Build the frontend into archeon_frontend/dist/.
	@if [ ! -d "$(FRONTEND_DIR)/node_modules" ]; then $(MAKE) install-frontend; fi
	cd $(FRONTEND_DIR) && npm run build

.PHONY: wheel
wheel: ## Build a Python wheel/sdist.
	$(PYTHON) -m pip install --upgrade build
	$(PYTHON) -m build

# ---------------------------------------------------------------------------
# House-keeping
# ---------------------------------------------------------------------------

.PHONY: clean
clean: ## Remove build artifacts and Python caches (keeps venv).
	find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .mypy_cache \) -prune -exec rm -rf {} +
	rm -rf $(FRONTEND_DIR)/dist $(FRONTEND_DIR)/node_modules
	rm -rf build dist *.egg-info
	@echo ">>> cleaned (venv kept)"

.PHONY: purge
purge: clean ## Also remove the venv and all downloaded models.
	rm -rf $(VENV)
	@echo ">>> venv removed. Models in $$HF_HOME are untouched (delete manually if needed)."

# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------

.PHONY: status
status: ## Hit the API health endpoint (requires API to be running).
	@curl -sS http://$${ARCHEON_HOST:-127.0.0.1}:$${ARCHEON_PORT:-8081}/health | python3 -m json.tool || true

.PHONY: openapi
openapi: ## Dump the OpenAPI spec to openapi.json.
	@curl -sS http://$${ARCHEON_HOST:-127.0.0.1}:$${ARCHEON_PORT:-8081}/openapi.json | python3 -m json.tool > openapi.json
	@echo ">>> wrote openapi.json"
