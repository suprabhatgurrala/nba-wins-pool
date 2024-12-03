# Define variables for Docker Compose files
COMPOSE_FILE_PROD=compose.prod.yml
COMPOSE_FILE_TEST=compose.testing.yml

# Default target (optional)
.DEFAULT_GOAL := help

# Help target to list all commands
help:
	@echo "Usage: make [target]"
	@echo ""
	@echo "Available targets:"
	@echo "  dev           Start the application in development mode"
	@echo "  prod          Start the application in production mode"
	@echo "  backend_test  Run backend unit tests"
	@echo "  e2e_tests     Run end-to-end tests with Playwright"
	@echo "  down          Stop all running services and clean up"
	@echo ""
	@echo "Optional: Pass PROJECT_NAME=<project-name> to set a custom Docker Compose project name"

# Start development environment
dev:
	@docker compose up --build --watch

# Start production environment
prod:
	@docker compose -f compose.yml -f compose.prod.yml up --build

# Run backend tests
backend_tests:
	@docker compose -p $(PROJECT_NAME) --profile unit -f $(COMPOSE_FILE_TEST) run --build backend-unit-tests

# Run end-to-end tests
e2e_tests:
	@docker compose -p $(PROJECT_NAME) --profile e2e -f $(COMPOSE_FILE_TEST) up --build --abort-on-container-exit --exit-code-from playwright

# Stop all services and clean up
down:
	@docker compose down -v
