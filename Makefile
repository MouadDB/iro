# Makefile for Incident Response Orchestrator (IRO)

# Variables
PYTHON := python3
PIP := pip3
PROJECT_NAME := incident-response-orchestrator
VERSION := $(shell grep version setup.py | cut -d'"' -f2)
DOCKER_REGISTRY := gcr.io/$(GCP_PROJECT)
IMAGE_NAME := iro
FULL_IMAGE_NAME := $(DOCKER_REGISTRY)/$(IMAGE_NAME):$(VERSION)

# Default target
.PHONY: help
help: ## Show this help message
	@echo "IRO - Incident Response Orchestrator"
	@echo "===================================="
	@echo ""
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# Development
.PHONY: install
install: ## Install dependencies and package in development mode
	$(PIP) install -r requirements.txt
	$(PIP) install -e .

.PHONY: install-dev
install-dev: ## Install development dependencies
	$(PIP) install -r requirements.txt
	$(PIP) install -e .[dev]
	pre-commit install

.PHONY: format
format: ## Format code with black
	black src/ tests/ --line-length 100

.PHONY: lint
lint: ## Run linting checks
	flake8 src/ tests/ --max-line-length 100
	mypy src/

.PHONY: test
test: ## Run all tests
	pytest tests/ -v

.PHONY: test-unit
test-unit: ## Run unit tests only
	pytest tests/unit/ -v

.PHONY: test-integration
test-integration: ## Run integration tests only
	pytest tests/integration/ -v

.PHONY: test-coverage
test-coverage: ## Run tests with coverage report
	pytest tests/ --cov=src --cov-report=html --cov-report=term

.PHONY: clean
clean: ## Clean up build artifacts
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf .pytest_cache/
	rm -rf .coverage
	rm -rf htmlcov/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

# Application
.PHONY: run
run: ## Run IRO locally
	$(PYTHON) -m src.iro.main

.PHONY: run-dev
run-dev: ## Run IRO in development mode with debug logging
	LOG_LEVEL=DEBUG $(PYTHON) -m src.iro.main

.PHONY: run-config
run-config: ## Run IRO with custom config file
	$(PYTHON) -m src.iro.main --config config/development.yaml

# Docker
.PHONY: docker-build
docker-build: ## Build Docker image
	docker build -t $(IMAGE_NAME):$(VERSION) .
	docker tag $(IMAGE_NAME):$(VERSION) $(IMAGE_NAME):latest

.PHONY: docker-run
docker-run: ## Run Docker container locally
	docker run -p 8080:8080 \
		-e GCP_PROJECT=$(GCP_PROJECT) \
		-e LOG_LEVEL=INFO \
		$(IMAGE_NAME):$(VERSION)

.PHONY: docker-push
docker-push: ## Push Docker image to registry
	docker tag $(IMAGE_NAME):$(VERSION) $(FULL_IMAGE_NAME)
	docker tag $(IMAGE_NAME):latest $(DOCKER_REGISTRY)/$(IMAGE_NAME):latest
	docker push $(FULL_IMAGE_NAME)
	docker push $(DOCKER_REGISTRY)/$(IMAGE_NAME):latest

# Kubernetes
.PHONY: k8s-deploy
k8s-deploy: ## Deploy to Kubernetes
	./scripts/deploy.sh deploy

.PHONY: k8s-status
k8s-status: ## Check Kubernetes deployment status
	./scripts/deploy.sh status

.PHONY: k8s-logs
k8s-logs: ## Show Kubernetes logs
	./scripts/deploy.sh logs

.PHONY: k8s-cleanup
k8s-cleanup: ## Remove Kubernetes deployment
	./scripts/deploy.sh cleanup

# Configuration
.PHONY: config-validate
config-validate: ## Validate configuration files
	$(PYTHON) -c "from src.iro.config import load_config; load_config('config/default.yaml'); print('✓ Configuration valid')"

.PHONY: config-generate
config-generate: ## Generate example configuration
	@echo "# Example IRO Configuration" > config/example.yaml
	@echo "# Copy this file and customize for your environment" >> config/example.yaml
	@cat config/default.yaml >> config/example.yaml
	@echo "Generated config/example.yaml"

# Database/Storage (if needed in future)
.PHONY: db-migrate
db-migrate: ## Run database migrations (placeholder)
	@echo "Database migrations not implemented yet"

# Documentation
.PHONY: docs
docs: ## Generate documentation
	@echo "Documentation generation not implemented yet"
	@echo "For now, see README.md for documentation"

.PHONY: docs-serve
docs-serve: ## Serve documentation locally
	@echo "Documentation server not implemented yet"

# Security
.PHONY: security-scan
security-scan: ## Run security scans
	safety check --json || true
	bandit -r src/ -f json || true

.PHONY: vulnerability-check
vulnerability-check: ## Check for known vulnerabilities
	safety check

# Performance
.PHONY: benchmark
benchmark: ## Run performance benchmarks
	@echo "Benchmarks not implemented yet"

.PHONY: profile
profile: ## Profile application performance
	$(PYTHON) -m cProfile -o profile.stats -m src.iro.main &
	sleep 30
	kill %%
	$(PYTHON) -c "import pstats; p = pstats.Stats('profile.stats'); p.sort_stats('cumulative').print_stats(20)"

# Monitoring
.PHONY: metrics
metrics: ## Get current metrics
	curl -s http://localhost:8080/api/metrics | jq '.' || echo "IRO not running or metrics unavailable"

.PHONY: health
health: ## Check application health
	curl -s http://localhost:8080/api/health | jq '.' || echo "IRO not running"

# Release
.PHONY: version
version: ## Show current version
	@echo "Current version: $(VERSION)"

.PHONY: bump-version
bump-version: ## Bump version (requires VERSION=x.y.z)
	@if [ -z "$(VERSION)" ]; then \
		echo "Usage: make bump-version VERSION=x.y.z"; \
		exit 1; \
	fi
	sed -i 's/version="[^"]*"/version="$(VERSION)"/' setup.py
	sed -i 's/version: "[^"]*"/version: "$(VERSION)"/' config/default.yaml

.PHONY: release
release: test docker-build docker-push ## Create a release (test, build, push)
	@echo "Released version $(VERSION)"

# CI/CD helpers
.PHONY: ci-test
ci-test: ## Run tests in CI environment
	pytest tests/ --cov=src --cov-report=xml --junitxml=test-results.xml

.PHONY: ci-build
ci-build: ## Build in CI environment
	docker build -t $(IMAGE_NAME):$(VERSION) .

.PHONY: ci-deploy
ci-deploy: ## Deploy in CI environment
	@echo "CI deployment not implemented yet"

# Development utilities
.PHONY: shell
shell: ## Start Python shell with IRO modules loaded
	$(PYTHON) -c "from src.iro import *; import IPython; IPython.start_ipython()"

.PHONY: notebook
notebook: ## Start Jupyter notebook for development
	jupyter notebook --notebook-dir=. --ip=0.0.0.0

.PHONY: reset-dev
reset-dev: clean install-dev ## Reset development environment
	@echo "Development environment reset complete"

# Monitoring and debugging
.PHONY: debug-info
debug-info: ## Show debug information
	@echo "Python version: $(shell $(PYTHON) --version)"
	@echo "IRO version: $(VERSION)"
	@echo "Docker images:"
	@docker images | grep $(IMAGE_NAME) || echo "No IRO Docker images found"
	@echo "Kubernetes resources:"
	@kubectl get all -n incident-response 2>/dev/null || echo "No Kubernetes resources found"

.PHONY: logs-tail
logs-tail: ## Tail application logs
	tail -f /tmp/iro.log 2>/dev/null || echo "No log file found"

# Quick commands
.PHONY: quick-test
quick-test: format lint test ## Quick validation (format, lint, test)

.PHONY: quick-deploy
quick-deploy: quick-test docker-build k8s-deploy ## Quick deployment (test, build, deploy)

.PHONY: dev-setup
dev-setup: install-dev config-generate ## Setup development environment
	@echo "Development environment setup complete!"
	@echo "Run 'make run-dev' to start IRO in development mode"

# Environment checks
.PHONY: check-env
check-env: ## Check required environment variables
	@echo "Checking environment..."
	@if [ -z "$(GCP_PROJECT)" ]; then \
		echo "❌ GCP_PROJECT not set"; \
		exit 1; \
	else \
		echo "✓ GCP_PROJECT: $(GCP_PROJECT)"; \
	fi
	@if [ -z "$(GOOGLE_APPLICATION_CREDENTIALS)" ]; then \
		echo "⚠️  GOOGLE_APPLICATION_CREDENTIALS not set (may cause auth issues)"; \
	else \
		echo "✓ GOOGLE_APPLICATION_CREDENTIALS: $(GOOGLE_APPLICATION_CREDENTIALS)"; \
	fi
	@command -v kubectl >/dev/null 2>&1 && echo "✓ kubectl installed" || echo "❌ kubectl not found"
	@command -v docker >/dev/null 2>&1 && echo "✓ docker installed" || echo "❌ docker not found"

# All-in-one commands
.PHONY: first-run
first-run: dev-setup check-env ## Complete first-time setup and environment check
	@echo ""
	@echo "🎉 IRO setup complete!"
	@echo ""
	@echo "Next steps:"
	@echo "1. Set up your Google Cloud credentials"
	@echo "2. Configure your target Kubernetes cluster"
	@echo "3. Run 'make run-dev' to start IRO"
	@echo ""

.PHONY: full-test
full-test: format lint test-coverage security-scan ## Run all quality checks

.PHONY: production-deploy
production-deploy: full-test docker-build docker-push k8s-deploy ## Full production deployment pipeline

# Default target when no arguments provided
.DEFAULT_GOAL := help