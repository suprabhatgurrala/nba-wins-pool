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
Contains the teams each owner won in every pool season's auction, with:
- `pool`: Pool slug (e.g., "sg", "kk")
- `season`: Season identifier (e.g., "2024-25")
- `roster`: Roster/owner name
- `team`: Team abbreviation (matches `nba_teams.json`)
- `auction_price`: Price paid for the team in auction

### `pool_seasons.json`
Per pool season history that can't be derived from the roster slots, one object per pool season:
- `pool`, `season`: as in `rosters.csv`
- `starting_budget`: per-drafter auction budget; omitted means $200
- `auction_at`: when the auction took place (ISO, UTC); empty skips seeding that season's auction
- `projection_date`: day of the odds the preseason valuations were computed from; becomes the pool season's
  `auction_projection_date`
- `rules`: buy-in and payouts as a list of lines, as shown on the pool season page (omitted for none)

The values come from each season's Google Sheet. The auction time is the sheet's creation time (Drive keeps no
other usable timestamp), except sg 2021-22, whose sheet predates the odds it prices off, so it is dated to the odds.
The projection date is the "Odds from DraftKings as of ..." note on the Preseason DD tab, which was never updated
after 2023-24, so 2024-25 uses the only odds snapshot stored for that season. Seasons whose auction ran in the app
(sg and kk 2025-26 onwards) are left out and keep their real dates. sg 2025-26 has no rules: its sheet's Rules tab
was only copied over from the previous season.

`seed_data.py` writes the valuation date and rules onto each listed pool season. Rules are only written where none
are set, so rules edited in the app are never overwritten.

Every pool season in `rosters.csv` gets a completed auction built from it: one participant per roster, one lot per
team, and an activity feed replaying owners taking turns nominating, each team sold in a single bid at its final
price. That replay is invented, since the real bidding was never recorded; its events carry a `historical_seed` flag.
The roster slots are then created from the auction by the same code the app runs when an auction completes, so each
slot links to its lot. An auction built this way is rebuilt when `rosters.csv` or its entry here changes, an unused
NOT_STARTED placeholder is filled in, and an auction run in the app is never touched.

### `nba_schedule_cache/<season>.json.gz`
Gzipped raw `scheduleleaguev2` responses, one per season, seeded straight into the
`external_data` cache table by `seed_data.py --nba-cache`.

They exist because stats.nba.com regularly takes minutes to return a full season
schedule, and often hangs outright — which made seeding a fresh database (E2E tests
in particular) unreliable. Responses for completed seasons never change.

A fixture is preferred over the API whenever one exists, except under `--force`,
which means "go ask the API" — pass `--offline` alongside it to refresh from the
fixtures instead.

Refresh them from a database that already has the cache populated:

```bash
make dump-nba-schedule-cache                          # every cached season
make dump-nba-schedule-cache args='--season 2025-26'
```

Only dump a season once it's over; a mid-season dump bakes in partial results.

## Usage

`seed_data.py` reads all of these files and seeds everything in dependency order (teams, pools, pool seasons, rosters,
NBA schedule cache, projections, then each season's auction and roster slots). It is safe to re-run:

```bash
make seed-data                  # everything
make seed-data pool=sg          # only one pool's rosters and auctions
make refresh-nba-cache          # refetch the NBA schedule cache from the NBA API (slow, rarely needed)

# Seed everything without calling any external API (used by the E2E stack)
make run-script script=seed_data.py args='--offline'
```

Seasons before 2025-26 are owned by these files: re-running brings the database in line with them, so fixing a price
in `rosters.csv` and re-seeding is all it takes. From 2025-26 on the app owns the data: an auction run in the app,
its roster slots, and any valuation date or rules set in the app are left alone, and the files only fill in a
database that has none (a fresh one).

## Updating Data

To add new seasons or pools, add rows to `rosters.csv` following the existing format, and an entry to
`pool_seasons.json` for the auction date, valuation date and rules. The script will:
1. Extract unique pools and create them
2. Extract unique (pool, season) combinations and create pool seasons
3. Create or reuse rosters
4. Build each season's auction and create the roster slots from it
