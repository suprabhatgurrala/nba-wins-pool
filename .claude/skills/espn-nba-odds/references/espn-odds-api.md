# ESPN NBA odds API reference

Field-level detail for `sports.core.api.espn.com` odds and the site scoreboard.
Read this when the bundled script doesn't already extract what you need.

Source for the endpoint catalog: https://github.com/pseudo-r/Public-ESPN-API

## Contents

- [Endpoints](#endpoints)
- [Scoreboard response](#scoreboard-response)
- [Odds response](#odds-response)
- [Providers](#providers)
- [Season types](#season-types)
- [Related endpoints](#related-endpoints)

## Endpoints

All are public and need no auth or API key.

```
# Event list for a month (limit=1000 is required)
GET https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=YYYYMM&limit=1000

# Odds for one event (event id and competition id are the same value for NBA)
GET https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/events/{id}/competitions/{id}/odds

# Per-book detail for one event
GET https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/events/{id}/competitions/{id}/odds/{providerId}

# ESPN's own win-probability model (BPI), not a sportsbook line
GET https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/events/{id}/competitions/{id}/predictor

# Season-long futures (championship, win totals)
GET https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/seasons/{year}/futures

# Paginated event list — 25 per page regardless of limit, so the scoreboard is usually easier
GET https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/seasons/{year}/types/{type}/events?page=N
```

### Parameter behavior

| Param | Notes |
|---|---|
| `dates=YYYYMM` | Works. Returns games spilling a few days past the month boundary, so de-dupe by event id. |
| `dates=YYYYMMDD` | Works for a single day. |
| `dates=YYYYMMDD-YYYYMMDD` | **Returns HTTP 400.** Documented but non-functional as of 2026-09. |
| `limit` | Honored by the scoreboard (use `1000`). Ignored by the core API, which is fixed at 25/page. |

Responses are gzip-encoded. Use `curl --compressed` or set `Accept-Encoding: gzip`.

## Scoreboard response

```
events[]
  id                      -> event id, reused as the competition id
  date                    -> ISO8601 UTC, e.g. "2025-10-28T23:00Z"
  shortName               -> "AWAY @ HOME" using ESPN abbreviations
  season {year, type, slug}
  competitions[0]
    neutralSite           -> bool
    status.type.completed -> bool
    odds                  -> null for completed games; populated only pregame
    competitors[]
      homeAway            -> "home" | "away"
      score               -> string
      team.abbreviation   -> ESPN abbrev (GS, NY, SA, UTAH, WSH, NO, PHX)
```

ESPN abbreviations differ from NBA tricodes. The repo's mapping lives at
`backend/src/nba_wins_pool/services/nba_simulator/espn_to_nba_abbrev_map.json`;
pass `--nba-tricodes` to apply it.

## Odds response

```
count, items[]
items[]
  provider {id, name, priority}
  details           -> "OKC -6.5", the favored team named in plain text
  spread            -> float, from the HOME team's perspective (negative = home favored)
  overUnder         -> float
  overOdds/underOdds
  homeTeamOdds / awayTeamOdds
    favorite, underdog  -> bool
    moneyLine           -> int, American odds
    spreadOdds          -> float, the juice
    open  { pointSpread{american, alternateDisplayValue}, spread{...}, moneyLine{...} }
    close { same shape }
    current { same shape }
```

### Reading a spread out of open/close/current

`pointSpread.american` is a **string** and can be `"-4.5"`, `"+3"`, `"EVEN"`, or
`"PK"`. Parse defensively; return null on anything unexpected rather than
coercing, since a bad coercion here corrupts the sign convention silently.

Extraction order that works in practice: `homeTeamOdds.close` →
`homeTeamOdds.current` → top-level `spread`.

`open` vs `close` are genuinely distinct — for 2025-26, 1,005 of 1,326 games had
line movement between them, with swings up to 17 points. Use `close` for
backtesting (it's the sharpest number) and `open` only if you're specifically
studying line movement.

### Nested `$ref` fields

The core API returns `$ref` URLs instead of inlined objects in many places
(`provider`, team links). The odds endpoint inlines everything needed for
spreads, so no `$ref` following is required for the normal pull.

## Providers

**Ids are not a stable key — ESPN reassigns them across seasons.** DraftKings
alone has been id 40 (2021-24) and id 100 (2025-26); id 41 in those older
seasons belongs to SugarHouse, an unrelated book. Match on the provider's own
`name` string instead (case-insensitive substring), which is what
`fetch_espn_odds.py` does.

| Name (substring match) | Notes |
|---|---|
| `draftkings` | Primary source. Broadest coverage in the current (2025-26) season. |
| `espn bet` | Fallback. House book; fills the games DraftKings skips this season. |
| `caesars` | Several state-specific variants existed pre-2024 (`Caesars Sportsbook (New Jersey)`, `(Colorado)`, `(Tennessee)`, etc.) — all match this substring. |
| `fanduel` | Does not appear in this endpoint's provider list in any season 2021-22 through 2025-26. The repo's simulator gets FanDuel odds from a separate sportsbook API, not from here. |
| `bet365`, `unibet`, `mgm`, `betmgm` | Present in older seasons (pre-2024), part of the broader multi-book field. |
| anything with `live` in the name | **In-game odds, not a pregame line.** Ranked last regardless of book. |

### Coverage has collapsed over time

The odds endpoint used to aggregate a real multi-book market. It has narrowed
sharply to one or two books per season:

| Season | Books posting a line | Notes |
|---|---|---|
| 2021-22 | 17 | teamrankings, consensus, DraftKings (id 40), Caesars ×4 states, MGM, Unibet, PointsBet, Westgate, etc. — near-universal per-game coverage |
| 2022-23 | 19 | Same broad field; ESPN BET debuts (1,321/1,322 games) |
| 2023-24 | 16 | ESPN BET now leads (1,315); legacy books still ~95% covered |
| 2024-25 | 2 | ESPN BET (1,327) + its live-odds feed only |
| 2025-26 | 2 | DraftKings, id 100 (1,075) + ESPN BET (299) |

No single book covers a full season by itself in the current or prior season —
check the `provider` column per row rather than assuming uniform coverage.

## Season types

| type | Meaning |
|---|---|
| 1 | Preseason |
| 2 | Regular season (**also contains All-Star exhibitions**) |
| 3 | Postseason / playoffs |
| 4 | All-Star (inconsistently used) |
| 5 | Play-In tournament |

All-Star games under type 2 use fake team codes (`STARS`, `WORLD`, `STRIPES`)
and never have a line.

### 2025-26 season counts, as a shape check

| Bucket | Count |
|---|---|
| Regular season (type 2) | 1,239 |
| Postseason (type 3) | 85 |
| Play-in (type 5) | 6 |
| **Total** | **1,330** |
| With a closing spread | 1,326 (the 4 misses are All-Star games) |

Type 2 exceeds the nominal 1,230 because it absorbs the NBA Cup championship and
the All-Star exhibitions.

## Related endpoints

The simulator already consumes some of these — see
`backend/src/nba_wins_pool/services/nba_simulator/CLAUDE.md`:

- `.../competitions/{id}/predictor` — ESPN BPI win probabilities, used as the
  fallback when no sportsbook line exists.
- `.../competitions/{id}/probabilities` — live win probability by play.
- `cdn.nba.com/static/json/staticData/brackets/{year}/PlayoffBracket.json` —
  NBA-side bracket state, keyed by NBA tricodes rather than ESPN abbrevs.
