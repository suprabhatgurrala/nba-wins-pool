# Define variables for Docker Compose files
COMPOSE_FILE_DEV=compose.override.yml
COMPOSE_FILE_PROD=compose.prod.yml
COMPOSE_FILE_TEST=compose.testing.yml

# Docker Compose project name (set via DOCKER_PROJECT_NAME environment variable or empty)
PROJECT_FLAG=$(if $(DOCKER_PROJECT_NAME),-p $(DOCKER_PROJECT_NAME))

# Default target (optional)
.DEFAULT_GOAL := help

# Help target to list all commands
help:
	@echo "Usage: make [target]"
	@echo ""
	@echo "Available targets:"
	@echo "  dev           Start the application in development mode"
	@echo "  prod          Start the application in production mode"
	@echo "  backend_tests  Run backend unit tests"
	@echo "  e2e_tests     Run end-to-end tests with Playwright"
	@echo "  down          Stop all running services and clean up"
	@echo ""
	@echo "Optional: Set environment variable DOCKER_PROJECT_NAME=<project-name> to set a custom Docker Compose project name"

# Start development environment
dev:
	@docker compose up --build --watch

# Start production environment
prod:
	@docker compose -f compose.yml -f $(COMPOSE_FILE_PROD) up --build

# Run backend tests
backend_tests:
	@docker compose $(PROJECT_FLAG) -f $(COMPOSE_FILE_TEST) run --build backend-unit-tests

# Run end-to-end tests
e2e_tests:
	@docker compose $(PROJECT_FLAG) -f $(COMPOSE_FILE_DEV) -f $(COMPOSE_FILE_TEST) run --build playwright

# Stop all services and clean up
down:
	@docker compose down -v
