# NBA Wins Pool Backend
Backend for display the standings of an NBA Wins Pool

## Prereqs
Install [`uv`](https://docs.astral.sh/uv/getting-started/installation/). `uv` can manage the Python environment, dependencies, and run the app.

## Running the Server locally

```
uv run fastapi dev src/nba_wins_pool/main_backend.py --host 0.0.0.0
```

Then navigate to `localhost:8000` to see the response.

## Development Setup
Install the package with `dev` extras:
```
uv pip install -e ".[dev]"
```
