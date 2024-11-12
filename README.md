# nba-wins-pool
website to display the standings of an NBA Wins Pool

## Prereqs
Install [`uv`](https://docs.astral.sh/uv/getting-started/installation/). `uv` can manage the Python environment, dependencies, and run the app.

## Running the Server locally
```
uv run fastapi dev src/nba_wins_pool/main_backend.py --host 0.0.0.0
```

Then navigate to `localhost:8000` to see the response.

## Running Server & Dependencies with Docker
This project uses docker-compose to coordinate spinning up containers for the python web app, database, etc.

### Start all containers
- `--build` - tells docker to rebuild the base image
- `--watch` - enables hot-reloading
```bash
docker-compose up --build --watch
```

## Development Setup
Install the package with `dev` extras:
```
uv pip install -e ".[dev]"
```

Run `pre-commit install` to setup commit hooks
