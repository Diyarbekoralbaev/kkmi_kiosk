.PHONY: help up down logs migrate seed lint test backend-shell psql hemis-sync

COMPOSE := docker compose -f docker-compose.dev.yml

help:
	@echo "Targets:"
	@echo "  up          - Start full dev stack (postgres + backend + 2 panels)"
	@echo "  down        - Stop dev stack"
	@echo "  logs        - Tail backend logs"
	@echo "  migrate     - Run alembic upgrade head inside backend"
	@echo "  test        - Run pytest inside backend container"
	@echo "  lint        - Run ruff inside backend container"
	@echo "  backend-shell - sh into backend container"
	@echo "  psql        - Open psql to dev postgres"
	@echo "  hemis-sync  - Mirror HEMIS into Postgres (~95s, hits the live API)"

up:
	$(COMPOSE) up --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f backend

migrate:
	$(COMPOSE) exec backend alembic upgrade head

test:
	$(COMPOSE) exec backend pytest -ra

lint:
	$(COMPOSE) exec backend ruff check src

backend-shell:
	$(COMPOSE) exec backend bash

psql:
	$(COMPOSE) exec postgres psql -U kiosk -d kkmi_kiosk

hemis-sync:
	$(COMPOSE) run --rm hemis-sync
