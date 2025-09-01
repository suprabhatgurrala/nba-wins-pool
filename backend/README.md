# NBA Wins Pool Backend
Backend for display the standings of an NBA Wins Pool

## Prerequisites
- Install [`uv`](https://docs.astral.sh/uv/getting-started/installation/) - manages Python environment, dependencies, and runs the app
- Install [Docker](https://docs.docker.com/get-docker/) - required for database and containerized development

## Local Development Workflow

### 1. Start Development Environment
```bash
# Start all services (backend, frontend, database)
make dev

# Or start just the backend with database
make dev-backend
```

### 2. Apply Database Migrations
```bash
# Apply existing migrations to create tables
make migrate-apply
```

## Database

### Technology Stack
- **Database**: PostgreSQL
- **ORM**: SQLModel (async)
- **Migrations**: Alembic with PEP 621 configuration in `pyproject.toml`
- **Connection**: Async with `asyncpg` driver
- **Local credentials**: `postgres:postgres@localhost:5432/nba_wins_pool`

### Database Models
- **Pool**: Wins pool/league information
- **Member**: Pool participants
- **Team**: NBA teams with logos
- **TeamOwnership**: Records who owns which team in which season
- **SeasonMilestone**: Important dates and events

### Making Schema Changes
Migrations are checked into version control. Follow this workflow for schema changes:

1. **Modify SQLModel classes** in `src/nba_wins_pool/db/models/`
2. **Generate migration** with descriptive message:
   ```bash
   make migrate-gen message="add logo_url to team model"
   ```
3. **Review generated migration** in `backend/alembic/versions/`
4. **Test migration locally**:
   ```bash
   make migrate-apply
   ```
5. **If migration is incorrect**:
   - Delete the migration file from `backend/alembic/versions/`
   - Repeat steps 2-4 until correct
6. **Commit both** model changes and final migration file

### Migration Commands
```bash
# Apply pending migrations
make migrate-apply

# Undo last migration (for local testing)
make migrate-undo

# Generate new migration after model changes
make migrate-gen message="descriptive message"
```

**Important**: Only commit migrations you've tested locally. Delete and regenerate migrations until they're correct.

## Scripts
The project includes a flexible script system for database operations, data seeding, and other tasks.

#### Writing Scripts
Scripts are located in `src/nba_wins_pool/scripts/` and follow this structure:

```python
#!/usr/bin/env python3
import asyncio
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from nba_wins_pool.db.core import engine
from nba_wins_pool.models.team import Team

async def main():
    # Your async database operations here
    pass

if __name__ == "__main__":
    asyncio.run(main())
```

#### Running Scripts
```bash
# Run script by filename (searches in scripts folder)
make run-script script=seed_teams.py

# Run script with arguments
make run-script script=seed_teams.py args="--force"

# Run script by full path
make run-script script=src/nba_wins_pool/scripts/seed_teams.py
```

#### Data Seeding Scripts
The project includes several seeding scripts for populating the database:

```bash
# Seed NBA team data (30 teams with logos)
make seed-teams
make seed-teams-force    # Force overwrite existing data

# Seed season milestones (All-Star break, playoffs, etc.)
make seed-milestones
make seed-milestones-force

# Seed team ownership data (who owns which teams)
make seed-owners
make seed-owners-force
```

**Data Sources:**
- `src/nba_wins_pool/data/nba_teams.json` - NBA team information
- `src/nba_wins_pool/data/milestones.csv` - Season milestone dates
- `src/nba_wins_pool/data/team_owner.csv` - Team ownership records

**Seeding Order:**
1. Teams (required for ownership data)
2. Pools (required for milestones and ownership)
3. Milestones (optional, adds season dates)
4. Team Owners (creates members and ownership records)

These scripts demonstrate:
- Loading CSV and JSON data files
- Async database operations with SQLModel
- Error handling and logging
- Command-line argument parsing
- Duplicate prevention logic
- Relationship handling between models

## Running the Server

### Development Mode
```bash
# With Docker (recommended - includes database)
make dev-backend

# Standalone (requires separate database)
uv run fastapi dev src/nba_wins_pool/main_backend.py --host 0.0.0.0
```

Navigate to `localhost:8000` for the API and `localhost:8000/docs` for interactive documentation.

## Development Setup
Install the package with `dev` extras:
```bash
uv pip install -e ".[dev]"
```

## Testing

### Unit Tests
```bash
# Run locally
uv run pytest tests -s

# Run containerized
make backend_tests
```

### End-to-End Tests
```bash
make e2e_tests
```

## Code Formatting
```bash
# Format backend code
make format-backend

# Format both backend and frontend
make format
```

## Useful Make Commands
```bash
make help              # Show all available commands
make dev               # Start full development environment
make dev-backend       # Start backend + database only
make migrate-gen       # Generate new migration
make migrate-apply     # Apply pending migrations
make seed-teams        # Seed NBA team data
make seed-milestones   # Seed season milestone data
make seed-owners       # Seed team ownership data
make run-script        # Run custom scripts
make backend_tests     # Run backend unit tests
make format-backend    # Format code with ruff
make down              # Stop all services and clean up
```
