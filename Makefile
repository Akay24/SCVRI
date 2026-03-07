# ─────────────────────────────────────────────────────────────────────────────
# SCVRI Platform — Developer convenience Makefile
#
# Usage:
#   make <target>
#   make help           — list all targets with descriptions
# ─────────────────────────────────────────────────────────────────────────────

.DEFAULT_GOAL := help
SHELL := /usr/bin/env bash

# ── Project config ────────────────────────────────────────────────────────────
SERVICES := iam supplier-management risk-intelligence visibility alert-engine integration
REGISTRY  := ghcr.io/scvri
TAG       ?= dev
COMPOSE   := docker compose -f docker-compose.dev.yml
K8S_DIR   := infra/k8s

# ── Colors ────────────────────────────────────────────────────────────────────
BOLD  := \033[1m
RESET := \033[0m
GREEN := \033[32m
CYAN  := \033[36m

# ── Help ──────────────────────────────────────────────────────────────────────
.PHONY: help
help:  ## Show this help
	@echo ""
	@echo "$(BOLD)SCVRI Platform — Available targets$(RESET)"
	@echo ""
	@grep -E '^[a-zA-Z_/-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  $(CYAN)%-35s$(RESET) %s\n", $$1, $$2}'
	@echo ""

# ── Local dev infrastructure ──────────────────────────────────────────────────
.PHONY: up down restart logs ps
up:  ## Start all local dev infrastructure (postgres, redis, kafka, etc.)
	$(COMPOSE) up -d
	@echo "$(GREEN)✓ Infrastructure up$(RESET)"
	@echo "  Postgres  → localhost:5432"
	@echo "  Redis     → localhost:6379"
	@echo "  Kafka     → localhost:9092"
	@echo "  Kafka UI  → http://localhost:8080"
	@echo "  MailHog   → http://localhost:8025"

down:  ## Stop and remove all local dev containers (keeps volumes)
	$(COMPOSE) down

down-v:  ## Stop and remove containers AND volumes (destroys all data!)
	$(COMPOSE) down -v

restart:  ## Restart all dev infrastructure
	$(COMPOSE) restart

logs:  ## Tail logs for all dev services (Ctrl-C to stop)
	$(COMPOSE) logs -f

ps:  ## Show running dev containers
	$(COMPOSE) ps

# ── Database ──────────────────────────────────────────────────────────────────
.PHONY: db-shell db-migrate
db-shell:  ## Open a psql shell in the local postgres container
	$(COMPOSE) exec postgres psql -U scvri -d scvri_db

db-migrate:  ## Run Alembic migrations for a specific service (SERVICE=iam)
	@test -n "$(SERVICE)" || (echo "Usage: make db-migrate SERVICE=iam"; exit 1)
	cd services/$(SERVICE) && poetry run alembic upgrade head

# ── Per-service dev commands ──────────────────────────────────────────────────
define SERVICE_TARGETS
.PHONY: run/$(1) lint/$(1) test/$(1) build/$(1)

run/$(1):  ## Run $(1) service locally (hot-reload)
	cd services/$(1) && \
	  poetry run uvicorn $$(shell poetry run python -c \
	    "import importlib.util, pathlib; \
	     pkg = next(pathlib.Path('src').iterdir()).name; \
	     print(f'{pkg}.main:app')") \
	    --reload --host 0.0.0.0 --port $$(shell grep SERVICE_PORT .env.dev | cut -d= -f2)

lint/$(1):  ## Lint + type-check $(1) service
	@echo "$(BOLD)Linting: $(1)$(RESET)"
	cd services/$(1) && poetry run ruff check src/ tests/
	cd services/$(1) && poetry run ruff format --check src/ tests/
	cd services/$(1) && poetry run mypy src/

test/$(1):  ## Run tests for $(1) service
	@echo "$(BOLD)Testing: $(1)$(RESET)"
	cd services/$(1) && \
	  ENVIRONMENT=test poetry run pytest tests/ \
	    --cov=src --cov-report=term-missing \
	    --cov-fail-under=70 -v --tb=short

build/$(1):  ## Build Docker image for $(1) service (TAG=dev)
	docker build \
	  -t $(REGISTRY)/$(1):$(TAG) \
	  -f services/$(1)/Dockerfile \
	  .
endef

$(foreach svc,$(SERVICES),$(eval $(call SERVICE_TARGETS,$(svc))))

# ── Bulk operations ───────────────────────────────────────────────────────────
.PHONY: lint-all test-all build-all
lint-all:  ## Lint all services + shared library
	@echo "$(BOLD)Linting shared library$(RESET)"
	cd shared && poetry run ruff check src/ tests/
	cd shared && poetry run mypy src/
	@for svc in $(SERVICES); do $(MAKE) lint/$$svc; done

test-all:  ## Run all tests (requires dev infra running: make up)
	cd shared && poetry run pytest tests/ --tb=short -q
	@for svc in $(SERVICES); do $(MAKE) test/$$svc; done

build-all:  ## Build Docker images for all services (TAG=dev)
	@for svc in $(SERVICES); do $(MAKE) build/$$svc TAG=$(TAG); done

# ── Shared library ────────────────────────────────────────────────────────────
.PHONY: shared-install shared-test shared-lint
shared-install:  ## Install shared library in dev mode into all service envs
	@for svc in $(SERVICES); do \
	  echo "Installing shared into services/$$svc ..."; \
	  cd services/$$svc && poetry run pip install -e ../../shared && cd ../..; \
	done

shared-test:  ## Run shared library tests
	cd shared && poetry run pytest tests/ -v --tb=short

shared-lint:  ## Lint shared library
	cd shared && poetry run ruff check src/ tests/ && poetry run mypy src/

# ── Kubernetes ────────────────────────────────────────────────────────────────
.PHONY: k8s-apply k8s-diff k8s-delete k8s-status k8s-logs
k8s-apply:  ## Apply k8s manifests via kustomize (NAMESPACE=scvri)
	kubectl kustomize $(K8S_DIR) | kubectl apply -f -

k8s-diff:  ## Dry-run diff against current cluster state
	kubectl kustomize $(K8S_DIR) | kubectl diff -f -

k8s-delete:  ## Delete all SCVRI resources (WARNING: destructive)
	kubectl kustomize $(K8S_DIR) | kubectl delete -f -

k8s-status:  ## Show pod status in the scvri namespace
	kubectl get pods,svc,hpa,pdb -n scvri

k8s-logs:  ## Tail logs for a deployment (DEPLOY=iam)
	@test -n "$(DEPLOY)" || (echo "Usage: make k8s-logs DEPLOY=iam"; exit 1)
	kubectl logs -n scvri deployment/$(DEPLOY) -f --tail=100

k8s-exec:  ## Open a shell in a running pod (DEPLOY=iam)
	@test -n "$(DEPLOY)" || (echo "Usage: make k8s-exec DEPLOY=iam"; exit 1)
	kubectl exec -it -n scvri deployment/$(DEPLOY) -- /bin/sh

# ── Code generation / maintenance ─────────────────────────────────────────────
.PHONY: gen-secrets openapi
gen-secrets:  ## Generate random values for all secrets-template.yaml placeholders
	@echo "Generating secret values ..."
	@echo "POSTGRES_PASSWORD: $$(openssl rand -base64 32)"
	@echo "REDIS_PASSWORD:    $$(openssl rand -base64 24)"
	@echo "IAM_PRIVATE_KEY:   (use: openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:4096)"
	@echo "WEBHOOK_SECRET:    $$(openssl rand -hex 32)"
	@echo "SMTP_PASSWORD:     <set from your mail provider>"

openapi:  ## Export OpenAPI schemas from all running services
	@for port in 8000 8001 8002 8003 8004 8005; do \
	  svc=$$(case $$port in 8000) echo iam;; 8001) echo supplier-management;; \
	  8002) echo risk-intelligence;; 8003) echo visibility;; \
	  8004) echo alert-engine;; 8005) echo integration;; esac); \
	  echo "Exporting $$svc ..."; \
	  curl -sf http://localhost:$$port/openapi.json \
	    > docs/openapi/$$svc.json && echo "  ✓ docs/openapi/$$svc.json" || echo "  ✗ $$svc not running"; \
	done

# ── Format all code ───────────────────────────────────────────────────────────
.PHONY: fmt
fmt:  ## Auto-format all Python code with ruff
	cd shared && poetry run ruff format src/ tests/
	@for svc in $(SERVICES); do \
	  cd services/$$svc && poetry run ruff format src/ tests/ && cd ../..; \
	done

# ── Pre-commit ────────────────────────────────────────────────────────────────
.PHONY: pre-commit-install pre-commit-run
pre-commit-install:  ## Install pre-commit hooks
	pip install pre-commit && pre-commit install

pre-commit-run:  ## Run pre-commit checks on all files
	pre-commit run --all-files

# ── Cleanup ───────────────────────────────────────────────────────────────────
.PHONY: clean
clean:  ## Remove Python caches, coverage files, and build artifacts
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null; true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null; true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null; true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null; true
	find . -name "coverage.xml" -delete 2>/dev/null; true
	find . -name ".coverage" -delete 2>/dev/null; true
	@echo "$(GREEN)✓ Cleaned$(RESET)"
