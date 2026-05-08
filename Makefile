# Gateforge-Loom — operator targets
# Usage: `make <target>`

SHELL := /bin/bash
COMPOSE := docker compose
PROJECT := gateforge-loom

.PHONY: help up down restart build logs ps health test clean nuke

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

up: ## Build and start all services
	@if [ ! -f .env ]; then echo "ERROR: .env not found. Run: cp .env.example .env"; exit 1; fi
	$(COMPOSE) up -d --build
	@echo ""
	@echo "Services starting. Run 'make health' in ~10s."

down: ## Stop and remove containers (keeps volumes)
	$(COMPOSE) down

restart: ## Restart all services
	$(COMPOSE) restart

build: ## Rebuild images without starting
	$(COMPOSE) build

logs: ## Tail logs from all services
	$(COMPOSE) logs -f --tail=50

ps: ## List running containers
	$(COMPOSE) ps

health: ## Hit every service /health endpoint
	@bash scripts/health.sh

test: ## End-to-end smoke test (plan -> recall -> execute -> write)
	@bash scripts/smoke-test.sh

clean: ## Stop services and remove volumes (DATA LOSS)
	$(COMPOSE) down -v

nuke: clean ## clean + remove built images
	$(COMPOSE) down --rmi all -v --remove-orphans
