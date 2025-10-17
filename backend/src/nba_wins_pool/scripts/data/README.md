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
```

## Updating Data

To add new seasons or pools, simply add rows to `rosters.csv` following the existing format. The script will automatically:
1. Extract unique pools and create them
2. Extract unique (pool, season) combinations and create pool seasons
3. Create or reuse rosters
4. Create roster slots linking rosters to teams
