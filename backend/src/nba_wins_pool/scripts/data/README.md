# Seed Data Files

This directory contains the source data files used by the `seed_data.py` script to populate the database.

## Files

### `nba_teams.json`
Contains all 30 NBA teams with:
- `nba_id`: Official NBA API team ID
- `name`: Full team name
- `abbreviation`: 3-letter team code (e.g., "LAL", "BOS")
- `logo_url`: CDN URL for team logo

### `rosters.csv`
Contains roster slot assignments across all pools and seasons with:
- `pool`: Pool slug (e.g., "sg", "kk")
- `season`: Season identifier (e.g., "2024-25")
- `roster`: Roster/owner name
- `team`: Team abbreviation (matches `nba_teams.json`)
- `auction_price`: Price paid for the team in auction

### `nba_schedule_cache/<season>.json.gz`
Gzipped raw `scheduleleaguev2` responses, one per season, seeded straight into the
`external_data` cache table by `seed_data.py --nba-cache`.

They exist because stats.nba.com regularly takes minutes to return a full season
schedule, and often hangs outright — which made seeding a fresh database (E2E tests
in particular) unreliable. Responses for completed seasons never change.

Refresh them from a database that already has the cache populated:

```bash
make dump-nba-schedule-cache                                      # every cached season
make run-script script=dump_nba_schedule_cache.py args='--season 2025-26'
```

Only dump a season once it's over; a mid-season dump bakes in partial results.

## Usage

The seed script automatically reads these files:

```bash
# Seed everything
make seed-data

# Seed only teams
make seed-data-teams

# Seed only roster slots
make seed-data-roster-slots

# Force overwrite existing data
make seed-data-force

# Seed specific pool
make seed-data-pool pool=sg

# Seed everything without calling any external API (used by the E2E stack)
make run-script script=seed_data.py args='--offline'
```

## Updating Data

To add new seasons or pools, simply add rows to `rosters.csv` following the existing format. The script will automatically:
1. Extract unique pools and create them
2. Extract unique (pool, season) combinations and create pool seasons
3. Create or reuse rosters
4. Create roster slots linking rosters to teams
