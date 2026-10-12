# Calibration scripts

Repeatable fits for the hard-coded model constants. Each script downloads what it
needs, caches it under `data/`, prints the fit with diagnostics, and with `--write`
rewrites the constants in the source file. Run them from `backend/` (or via `make`):

| Script | Constants | Written to | Data |
|---|---|---|---|
| `game_constants.py` | `SPREAD_TO_WIN_PROB_K`, `REGULAR_SEASON_HOME_COURT_ADVANTAGE_POINTS`, `PLAYOFF_HOME_COURT_ADVANTAGE_POINTS`, `REST_DAY_ADVANTAGE_POINTS_PER_DAY`, `GAME_MARGIN_SD` | `services/nba_simulator/core/constants.py` | ESPN closing lines (via the `espn-nba-odds` skill's fetcher) |
| `playoff_wins_regression.py` | `POSTSEASON_WIN_COEFFICIENTS[<next season>]` (playoff, conference and play-in multipliers) | `services/auction_valuation_service.py` | [SportsOddsHistory](https://www.covers.com/sportsoddshistory/nba-odds/) preseason odds + ESPN postseason results |

```bash
make calibrate-game-constants                    # print the fit (last 5 completed seasons)
make calibrate-game-constants args='--write'     # ...and update constants.py
make calibrate-playoff-wins args='--write'       # 2014-15 through the last completed season

# or directly, with options
cd backend
uv run --group model python calibration/game_constants.py --seasons 2022-2026
uv run --group model python calibration/playoff_wins_regression.py --as-of "Jan 1"
```

Seasons are named by the year they end in (`2026` = 2025-26). The default window
rolls forward on July 1, once the Finals are over.

## When to rerun

After each season ends (July onward), so the new season joins the fit. Rerun with `--write`,
review the diff and the printed diagnostics, and update the stats quoted in the
comments next to each constant (sample sizes, per-season values) from the output.
The auction coefficients are also quoted in `frontend/src/docs/auction-strategy.md`.

The auction coefficients are **versioned by season**: `--write` adds an entry keyed by
the season after the last one fit (`--for-season` to override). Earlier entries stay
as they are, so past seasons' auction pages keep the values they were drafted with.
Rerunning before that season starts just replaces its entry. The simulator constants
are not versioned: simulation results are stored when they run (current season only),
so changing a constant never rewrites a past season.

## Cached data (`data/`)

Checked in, so a refit reproduces exactly without the network and only a newly
finished season needs downloading. Pass `--refresh` to re-download everything.

- `espn_odds/<season>.csv`: one row per regular-season, play-in and playoff game
  with the closing spread, moneylines, score and UTC tip time.
- `sportsoddshistory/<season>/`: win totals, make/miss playoffs, and conference and
  title futures (two-row header: phase, snapshot date).
- `espn_postseason_wins/<season>.csv`: playoff and play-in wins per team. The playoff
  wins match basketball-reference's playoff records exactly.

## Method notes

- All prices are de-vigged with Shin's method (`utils/odds.shin_devig`), the same as
  the app's live FanDuel prices, so the fitted constants apply to the probabilities
  the app actually computes.
- The postseason regressions use the **last preseason** futures snapshot by
  default, which is when pools hold their auctions. `--as-of "Jan 1"` reproduces the
  original notebook's choice (2.89 / 18.58 vs its 2.78 / 19.77). Mid-season odds are
  more informative (R² 0.46 vs 0.375), so they give a larger conference coefficient
  and a smaller make-playoffs one. The "alternatives" block shows that title odds
  and win totals add nothing once make-playoffs and conference odds are in.
- Play-in wins are modeled as `PLAY_IN_ODDS_COEFFICIENT * p * (1 - p)` on the
  make-playoffs probability, a hump on the bubble teams that stays sensible as odds
  sharpen during the season (locks and eliminated teams go to 0). Preseason odds
  barely predict who lands in the play-in (R² ~0.02 over the 6 play-in seasons), so the
  term mainly spreads the play-in's 6 wins a season over the bubble instead of
  ignoring them. Least squares under-allocates them slightly (~5.4 predicted per season).
- Rest days are counted on US/Eastern calendar dates. ESPN timestamps are UTC,
  which would put most evening tips on the next day and break back-to-back detection.
