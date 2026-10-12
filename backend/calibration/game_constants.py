"""Fit the simulator's per-game constants from historical closing lines.

Refits these constants in services/nba_simulator/core/constants.py:

- SPREAD_TO_WIN_PROB_K: slope of P(home win) = 1 / (1 + exp(k * home_spread)), least
  squares on probability against moneylines de-vigged with Shin's method (all season
  types; games whose spread and moneyline favor different teams are dropped).
- REGULAR_SEASON_HOME_COURT_ADVANTAGE_POINTS / PLAYOFF_HOME_COURT_ADVANTAGE_POINTS:
  mean points the closing spread gives the home team, excluding neutral sites
  (regular season incl. NBA Cup group play / play-in + playoffs).
- REST_DAY_ADVANTAGE_POINTS_PER_DAY: OLS slope of the closing home spread on the rest
  differential (home rest days - away rest days, each capped at REST_DAY_DIFFERENTIAL_CAP),
  regular season only. Rest days are counted on US/Eastern dates (ESPN timestamps are
  UTC, which puts most evening tips on the next day).
- GAME_MARGIN_SD: standard deviation of the final home margin around the closing
  spread, regular season.

Game lines come from the ESPN API via the espn-nba-odds skill's fetcher
(.claude/skills/espn-nba-odds). Each season is cached under calibration/data/espn_odds/
(pass --refresh to refetch); a full season takes ~10 seconds.

Usage (from backend/):
    uv run --group model python calibration/game_constants.py               # last 5 completed seasons
    uv run --group model python calibration/game_constants.py --seasons 2022-2026 --write
"""

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import numpy as np
import pandas as pd
from _common import (
    DATA_DIR,
    SRC_DIR,
    last_completed_season,
    load_espn_fetcher,
    parse_season_range,
    season_str,
    write_constants,
)
from scipy.optimize import minimize_scalar

from nba_wins_pool.services.nba_simulator.core.constants import REST_DAY_DIFFERENTIAL_CAP
from nba_wins_pool.utils.odds import american_to_implied, shin_devig

ODDS_CACHE = DATA_DIR / "espn_odds"
CONSTANTS_PATH = SRC_DIR / "services" / "nba_simulator" / "core" / "constants.py"
DEFAULT_N_SEASONS = 5
EXHIBITION_TEAMS = {"STARS", "WORLD", "STRIPES", "USA", "GLOBE"}
REGULAR, POSTSEASON, PLAY_IN = 2, 3, 5


# ---------------------------------------------------------------------------
# Data loading (cached)
# ---------------------------------------------------------------------------
def fetch_season(end_year: int) -> pd.DataFrame:
    fetcher = load_espn_fetcher()
    session = fetcher.build_session()
    # Wide window: the 2020-21 Finals ran into July, the 2019-20 bubble into October
    events = fetcher.fetch_events(
        session, end_year, date(end_year - 1, 9, 1), date(end_year, 10, 31), {REGULAR, POSTSEASON, PLAY_IN}
    )
    events = [e for e in events if e["home_team"] not in EXHIBITION_TEAMS and e["away_team"] not in EXHIBITION_TEAMS]
    print(f"  {season_str(end_year)}: fetching odds for {len(events)} games", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=fetcher.DEFAULT_MAX_WORKERS) as pool:
        rows = list(pool.map(lambda e: fetcher.fetch_odds(session, e), events))
    errors = [r for r in rows if r.get("error")]
    if errors:
        raise RuntimeError(f"{len(errors)} odds requests failed for {season_str(end_year)}, e.g. {errors[0]['error']}")
    return pd.DataFrame(rows, columns=fetcher.FIELDS).sort_values(["start_time", "event_id"])


def load_season(end_year: int, refresh: bool) -> pd.DataFrame:
    path = ODDS_CACHE / f"{season_str(end_year)}.csv"
    if refresh or not path.exists():
        ODDS_CACHE.mkdir(parents=True, exist_ok=True)
        fetch_season(end_year).to_csv(path, index=False)
    df = pd.read_csv(path)
    df["season"] = season_str(end_year)
    return df


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["local_date"] = pd.to_datetime(df["start_time"], utc=True).dt.tz_convert("America/New_York").dt.normalize()
    df["home_margin"] = df["home_score"] - df["away_score"]
    df["neutral_site"] = df["neutral_site"].astype(str).str.lower() == "true"
    df["completed"] = df["completed"].astype(str).str.lower() == "true"

    appearances = pd.concat(
        [
            df[["event_id", "season", "local_date", "home_team"]]
            .rename(columns={"home_team": "team"})
            .assign(side="home"),
            df[["event_id", "season", "local_date", "away_team"]]
            .rename(columns={"away_team": "team"})
            .assign(side="away"),
        ]
    ).sort_values("local_date")
    previous = appearances.groupby(["season", "team"])["local_date"].shift()
    appearances["rest"] = ((appearances["local_date"] - previous).dt.days - 1).clip(0, REST_DAY_DIFFERENTIAL_CAP)
    rest = appearances.pivot_table(index="event_id", columns="side", values="rest")
    df["home_rest"] = df["event_id"].map(rest["home"])
    df["away_rest"] = df["event_id"].map(rest["away"])
    df["rest_diff"] = df["home_rest"] - df["away_rest"]
    return df


# ---------------------------------------------------------------------------
# Fits
# ---------------------------------------------------------------------------
def fit_spread_to_win_prob_k(df: pd.DataFrame) -> dict:
    lines = df.dropna(subset=["home_spread_close", "home_moneyline", "away_moneyline"]).copy()
    raw = [
        [american_to_implied(h), american_to_implied(a)]
        for h, a in zip(lines["home_moneyline"], lines["away_moneyline"])
    ]
    lines["home_prob"] = [shin_devig(r)[0] for r in raw]
    lines["overround"] = [sum(r) - 1.0 for r in raw]
    disagree = ((lines["home_spread_close"] < 0) & (lines["home_prob"] < 0.5)) | (
        (lines["home_spread_close"] > 0) & (lines["home_prob"] > 0.5)
    )
    lines = lines[~disagree]

    def fit(subset: pd.DataFrame) -> tuple[float, float]:
        spread, prob = subset["home_spread_close"].to_numpy(), subset["home_prob"].to_numpy()

        def sse(k: float) -> float:
            return float(((1.0 / (1.0 + np.exp(k * spread)) - prob) ** 2).sum())

        k = minimize_scalar(sse, bounds=(0.01, 1.0), method="bounded").x
        return k, float(np.sqrt(sse(k) / len(subset)))

    k, rmse = fit(lines)
    return {
        "k": k,
        "rmse": rmse,
        "n": len(lines),
        "dropped": int(disagree.sum()),
        "median_overround": float(lines["overround"].median()),
        "by_season": {s: fit(g)[0] for s, g in lines.groupby("season")},
        "regular": fit(lines[lines["season_type"] == REGULAR])[0],
        "postseason": fit(lines[lines["season_type"] != REGULAR])[0],
    }


def home_court(df: pd.DataFrame, season_types: set[int]) -> dict:
    games = df[df["season_type"].isin(season_types) & ~df["neutral_site"]].dropna(subset=["home_spread_close"])
    return {
        "points": float(-games["home_spread_close"].mean()),
        "n": len(games),
        "by_season": (-games.groupby("season")["home_spread_close"].mean()).to_dict(),
    }


def fit_rest(df: pd.DataFrame) -> dict:
    games = df[(df["season_type"] == REGULAR) & ~df["neutral_site"]].dropna(subset=["home_spread_close", "rest_diff"])
    slope, intercept = np.polyfit(games["rest_diff"], games["home_spread_close"], 1)
    return {
        "points_per_day": float(-slope),
        "intercept": float(intercept),
        "corr": float(np.corrcoef(games["rest_diff"], games["home_spread_close"])[0, 1]),
        "n": len(games),
        "buckets": games.groupby("rest_diff")["home_spread_close"].agg(["mean", "size"]),
    }


def margin_sd(df: pd.DataFrame, season_types: set[int]) -> dict:
    games = df[df["season_type"].isin(season_types) & df["completed"]].dropna(subset=["home_spread_close"])
    games = games[(games["home_score"] + games["away_score"]) > 0]  # postponed games report 0-0
    resid = games["home_margin"] + games["home_spread_close"]
    return {"sd": float(resid.std()), "n": len(games)}


def validation(df: pd.DataFrame) -> pd.DataFrame:
    """Per-season sanity checks from the espn-nba-odds skill: cover rate ≈ 0.5, corr ≈ +0.5."""
    done = df[df["completed"] & (df["home_score"] + df["away_score"] > 0)].dropna(subset=["home_spread_close"])
    rows = {}
    for season, g in done.groupby("season"):
        result = g["home_margin"] + g["home_spread_close"]
        rows[season] = {
            "games": len(df[df["season"] == season]),
            "with_line": len(g),
            "home_cover_rate": float((result[result != 0] > 0).mean()),
            "corr_margin_neg_spread": float(np.corrcoef(g["home_margin"], -g["home_spread_close"])[0, 1]),
            "providers": ", ".join(g["provider"].value_counts().head(2).index),
        }
    return pd.DataFrame(rows).T


def main() -> None:
    last = last_completed_season()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--seasons",
        default=f"{last - DEFAULT_N_SEASONS + 1}-{last}",
        help="Season end years to fit on, e.g. 2022-2026 (default: last %d completed, %%(default)s)"
        % DEFAULT_N_SEASONS,
    )
    parser.add_argument("--refresh", action="store_true", help="Re-download cached seasons")
    parser.add_argument("--write", action="store_true", help=f"Write the fitted values to {CONSTANTS_PATH.name}")
    args = parser.parse_args()

    seasons = parse_season_range(args.seasons)
    df = prepare(pd.concat([load_season(y, args.refresh) for y in seasons], ignore_index=True))

    pd.set_option("display.width", 140)
    print(f"\nSeasons {season_str(seasons[0])} .. {season_str(seasons[-1])}: {len(df)} games")
    print("\nData checks (cover rate should be near 0.50, correlation near +0.5):")
    print(validation(df).to_string(float_format=lambda v: f"{v:.3f}"))

    k = fit_spread_to_win_prob_k(df)
    print(f"\nSPREAD_TO_WIN_PROB_K = {k['k']:.5f}")
    print(f"  n={k['n']} games ({k['dropped']} dropped: spread and moneyline disagree), RMSE {k['rmse']:.3f}")
    print(f"  median overround {k['median_overround']:.1%}")
    print(f"  regular season {k['regular']:.4f}, play-in + playoffs {k['postseason']:.4f}")
    print("  by season: " + ", ".join(f"{s} {v:.4f}" for s, v in k["by_season"].items()))

    hca_reg = home_court(df, {REGULAR})
    hca_post = home_court(df, {POSTSEASON, PLAY_IN})
    for name, hca in [
        ("REGULAR_SEASON_HOME_COURT_ADVANTAGE_POINTS", hca_reg),
        ("PLAYOFF_HOME_COURT_ADVANTAGE_POINTS", hca_post),
    ]:
        print(f"\n{name} = {hca['points']:.3f}")
        print(f"  n={hca['n']} non-neutral games")
        print("  by season: " + ", ".join(f"{s} {v:.2f}" for s, v in hca["by_season"].items()))

    rest = fit_rest(df)
    print(f"\nREST_DAY_ADVANTAGE_POINTS_PER_DAY = {rest['points_per_day']:.3f}")
    print(
        f"  fit: home_spread_close = {rest['intercept']:.3f} + ({-rest['points_per_day']:.3f} * rest_diff), "
        f"corr {rest['corr']:.3f}, n={rest['n']}"
    )
    print("  mean home spread by rest_diff (home - away rest days):")
    for diff, row in rest["buckets"].iterrows():
        print(f"    {diff:+.0f}: {row['mean']:6.2f}  n={int(row['size'])}")

    sd_reg = margin_sd(df, {REGULAR})
    sd_post = margin_sd(df, {POSTSEASON, PLAY_IN})
    print(f"\nGAME_MARGIN_SD = {sd_reg['sd']:.1f}")
    print(
        f"  regular season {sd_reg['sd']:.2f} (n={sd_reg['n']}), play-in + playoffs {sd_post['sd']:.2f} (n={sd_post['n']})"
    )
    print(f"  logistic sd implied by k: {np.pi / (k['k'] * np.sqrt(3)):.2f}")

    if args.write:
        write_constants(
            CONSTANTS_PATH,
            {
                "SPREAD_TO_WIN_PROB_K": f"{k['k']:.5f}",
                "REGULAR_SEASON_HOME_COURT_ADVANTAGE_POINTS": f"{hca_reg['points']:.3f}",
                "PLAYOFF_HOME_COURT_ADVANTAGE_POINTS": f"{hca_post['points']:.3f}",
                "REST_DAY_ADVANTAGE_POINTS_PER_DAY": f"{rest['points_per_day']:.3f}",
                "GAME_MARGIN_SD": f"{sd_reg['sd']:.1f}",
            },
        )


if __name__ == "__main__":
    main()
