---
name: espn-nba-odds
description: Fetch per-game NBA point spreads, closing/opening lines, over-unders, and moneylines from the public ESPN API for any season or date range. Use this whenever the task involves NBA betting lines, point spreads, Vegas odds, home-court-advantage estimation, rest-days effects, market-implied win probabilities, or backtesting the simulator against the market — including when the user just says "get the spreads", "pull the odds", "what did Vegas have this game at", or asks for historical game-level betting data. Also use it before hand-rolling any ESPN API call for odds, since the documented date-range parameter is broken and the scoreboard silently omits odds for completed games.
---

# ESPN NBA Odds

Pull game-level betting lines (spread, total, moneyline) for any NBA season from
ESPN's public, unauthenticated API.

## Quick start

The bundled script handles the whole pull. Start here rather than writing requests by hand:

```bash
python .claude/skills/espn-nba-odds/scripts/fetch_espn_odds.py --season 2026 --out nba_2025_26_spreads
```

`--season` uses ESPN's convention where the season is named for the year it ends
in: **2025-26 season = `--season 2026`**.

Useful flags:

| Flag | Purpose |
|---|---|
| `--start` / `--end` | Narrow to an ISO date window instead of the full season |
| `--season-types` | `1`=preseason `2`=regular `3`=postseason `5`=play-in (default `2,3,5`) |
| `--provider` | Force one sportsbook by name substring: `espn bet`, `draftkings`, `fanduel` |
| `--nba-tricodes` | Rewrite ESPN abbrevs to NBA tricodes (`GS`→`GSW`) for joining repo data |
| `--drop-exhibitions` | Drop All-Star games, which carry fake team codes and no line |

It writes `<out>.csv` and `<out>.json` and prints a validation report to stderr.

A full season is ~1,300 games and takes roughly 10 seconds at the default 8 workers.

## Why two endpoints

Neither endpoint alone is sufficient, which is the single most important thing
to know about this API:

1. **Scoreboard** (`site.api.espn.com/.../nba/scoreboard?dates=YYYYMM&limit=1000`)
   gives the event list — ids, teams, dates, final scores.
2. **Core odds** (`sports.core.api.espn.com/v2/.../events/{id}/competitions/{id}/odds`)
   gives the line for one event.

The scoreboard embeds an `odds` object only for games that **haven't tipped off
yet**. Once a game is final, that field is `null` forever. So any historical
pull must hit the per-event odds endpoint, one call per game. There is no bulk
odds endpoint.

## Sign convention

`home_spread_close` is stated **from the home team's perspective**: negative
means the home team is favored. ESPN's top-level `spread` field already uses
this convention.

Always keep the `details` column (e.g. `"OKC -6.5"`) in any derived dataset. It
names whichever team is favored in plain text, which makes the convention
auditable later — this is the easiest thing in the whole pipeline to silently
get backwards.

## Verify before trusting the data

The script prints a validation report, and it's worth actually reading. Because
a flipped sign still produces plausible-looking numbers, check these:

- **`home_ats_cover_rate` near 0.50.** Sportsbooks set lines so roughly half of
  games land each way. Drift far from 0.5 means the sign is flipped or you
  grabbed a live in-game line instead of a pregame one.
- **`corr_margin_vs_neg_spread` strongly positive** (~0.5 for NBA). Negative
  means the sign is definitely flipped.
- **`mean_home_spread` ≈ −`mean_home_margin`.** Both should reflect the same
  home-court advantage, around 2 points.

Reference values from full-season pulls, for comparison:

| Season | Games | Cover rate | Corr | Mean spread / margin |
|---|---|---|---|---|
| 2025-26 (`--season 2026`) | 1,330 | 0.516 | 0.52 | −2.00 / +1.78 |
| 2024-25 (`--season 2025`) | 1,329 | 0.502 | 0.51 | −1.99 / +1.88 |

Coverage goes back multiple seasons, so the same command works for historical pulls.

## Known gotchas

**The documented date-range form is broken.** `dates=20251001-20251031` returns
HTTP 400. Only the bare month form `dates=YYYYMM` works, and it needs
`limit=1000` — the default truncates at 100 events and drops games from busy
months without any error. The script pages by month and filters client-side.

**Responses are gzipped.** Set `Accept-Encoding: gzip` and let the client
decode, or use `curl --compressed`. Raw `curl` output will not parse as UTF-8.

**Provider ids are not stable across seasons — rank by name, not id.** DraftKings
has been id 40 (2021-24), 41 (nowhere, that's actually SugarHouse those seasons),
and 100 (2025-26). The script ranks providers by matching a lowercased substring
of the provider's own `name` field (`"espn bet"`, `"draftkings"`, …), which is
consistent across seasons; treating the id as a stable key silently mis-prioritizes
books.

**Provider coverage has collapsed over time and is uneven within a season.** The
odds endpoint used to aggregate a real multi-book market — 2021-22 had 17 books
posting a line on nearly every game. Starting 2024-25 that fell to essentially
one book per season (ESPN BET in 2024-25; DraftKings in 2025-26, with ESPN BET
filling the ~300 games DraftKings skips). The script falls back through the name
priority list and records which book each row came from in the `provider` column
— check that column before assuming coverage is uniform, especially for any
season before the one you're currently in.

**Any "live odds" feed is in-game, not a pregame line**, and will look wildly
off if treated as a closing number. The script's ranking sorts anything with
"live" in the provider name last, regardless of book.

**All-Star games are filed under season type 2** with fake team abbreviations
(`STARS`, `WORLD`, `STRIPES`) and never have a line. Use `--drop-exhibitions`.

**Play-in games are season type 5**, which is easy to miss since it isn't
sequential with the others.

**Postponed games keep their line but report `0-0` with `completed: false`.**
There were 4 of these in 2025-26. They're legitimate rows for line analysis but
must be excluded from any result-based backtest — the validation report already
filters them out of its cover-rate math.

## Deeper reference

`references/espn-odds-api.md` documents the full response shape, every provider
id, the season-type table, and the open/current/close node structure. Read it
when you need a field the script doesn't already extract.
