# Define variables for Docker Compose files
COMPOSE_FILE_PROD=compose.prod.yml
COMPOSE_FILE_TEST=compose.testing.yml
COMPOSE_FILE_FORMAT=compose.formatting.yml

# Docker Compose project name (set via DOCKER_PROJECT_NAME environment variable or empty)
PROJECT_FLAG=$(if $(DOCKER_PROJECT_NAME),-p $(DOCKER_PROJECT_NAME))

# Default target (optional)
.DEFAULT_GOAL := help

# Help target to list all commands
help:
	@echo "Usage: make [target]"
	@echo ""
	@echo "Available targets:"
	@echo "  dev             Start the application in development mode"
	@echo "  dev-backend     Start the backend in development mode"
	@echo "  dev-frontend    Start the frontend in development mode"
	@echo "  prod            Start the application in production mode"
	@echo "  backend_tests   Run backend unit tests"
	@echo "  e2e_tests       Run end-to-end tests with Playwright"
	@echo "  down            Stop all running services and clean up"
	@echo "  format-backend  Format the backend codebase"
	@echo "  format-frontend Format the frontend codebase"
	@echo "  format          Format the backend and frontend codebases"
	@echo "  migrate-apply   Apply database migrations"
	@echo "  migrate-generate Generate a new database migration"
	@echo "  migrate-undo    Undo the last database migration"
	@echo "  seed-teams      Seed NBA team data into the database"
	@echo "  seed-owners     Seed team ownership data into the database"
	@echo "  run-script      Run a script by filename (usage: make run-script script=seed_teams.py args='--force')"
	@echo "  down            Stop all running services and clean up volumes"
	@echo ""
	@echo "Optional: Set environment variable DOCKER_PROJECT_NAME=<project-name> to set a custom Docker Compose project name"

# Start development environment
dev-backend:
	docker compose up --build --watch backend database-migrate

dev-frontend:
	docker compose up frontend --build --watch

dev:
	docker compose up --build --watch

# Migration commands for development
migrate-apply:
	docker compose run --build --rm database-migrate uv run alembic --config pyproject.toml upgrade head

migrate-gen:
	@if [ -z "$(message)" ]; then \
		echo "Usage: make migrate-gen message='Your migration message'"; \
		exit 1; \
	fi
	docker compose run --build --rm database-migrate uv run alembic --config pyproject.toml revision --autogenerate -m "$(message)"

migrate-undo:
	docker compose run --build --rm database-migrate uv run alembic --config pyproject.toml downgrade -1

# Generic script runner - run any script by filename or path
run-script:
	@if [ -z "$(script)" ]; then \
		echo "Usage: make run-script script=<filename.py> [args='--arg1 --arg2']"; \
		echo "Examples:"; \
		echo "  make run-script script=seed_teams.py"; \
		echo "  make run-script script=seed_teams.py args='--force'"; \
		echo "  make run-script script=src/nba_wins_pool/scripts/seed_teams.py args='--help'"; \
		exit 1; \
	fi
	@if echo "$(script)" | grep -q "/"; then \
		docker compose run --build --rm backend uv run python $(script) $(args); \
	else \
		docker compose run --build --rm backend uv run python src/nba_wins_pool/scripts/$(script) $(args); \
	fi

# Seed NBA team data
seed-teams:
	$(MAKE) run-script script=seed_teams.py

seed-teams-force:
	$(MAKE) run-script script=seed_teams.py args=--force

# Seed team ownership data
seed-owners:
	$(MAKE) run-script script=seed_team_owners.py

seed-owners-force:
	$(MAKE) run-script script=seed_team_owners.py args=--force

# Start production environment
prod:
	@docker compose -f compose.yml -f $(COMPOSE_FILE_PROD) up --build

# Run backend tests
backend_tests:
	@docker compose $(PROJECT_FLAG) -f $(COMPOSE_FILE_TEST) run --remove-orphans --build backend-unit-tests
	@docker compose $(PROJECT_FLAG) -f $(COMPOSE_FILE_TEST) down --volumes

# Run end-to-end tests
e2e_tests:
	@docker compose $(PROJECT_FLAG) -f $(COMPOSE_FILE_TEST) run --remove-orphans --build playwright
	@docker compose $(PROJECT_FLAG) -f $(COMPOSE_FILE_TEST) down --volumes

format-backend:
	@docker compose $(PROJECT_FLAG) -f $(COMPOSE_FILE_FORMAT) run --remove-orphans --build backend-format
	@docker compose $(PROJECT_FLAG) -f $(COMPOSE_FILE_FORMAT) down --volumes

format-frontend:
	@docker compose $(PROJECT_FLAG) -f $(COMPOSE_FILE_FORMAT) run --remove-orphans --build frontend-format
	@docker compose $(PROJECT_FLAG) -f $(COMPOSE_FILE_FORMAT) down --volumes

format: format-backend format-frontend

# Stop all services and clean up
down:
	@docker compose down -v
