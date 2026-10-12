"""Fit the postseason-wins regressions used by the auction valuation.

The auction values a team at its projected regular-season wins plus expected
playoff and play-in wins (the pool counts both), estimated from the odds the app
stores as::

    playoff_wins ≈ playoff_odds * P(make playoffs) + conf_odds * P(win conference)
    play_in_wins ≈ play_in_odds * P(make playoffs) * (1 - P(make playoffs))

The play-in term is a hump on the bubble: locks and no-hopers rarely play in it.
All three coefficients are non-negative least squares with no intercept:

- Odds: preseason make/miss playoffs, conference and title futures from
  SportsOddsHistory (now hosted at https://www.covers.com/sportsoddshistory/nba-odds/),
  de-vigged with Shin's method like every price in the app (utils/odds.shin_devig).
- Targets: each team's playoff and play-in wins from the ESPN scoreboard. The
  play-in model only uses seasons with the play-in tournament (2020-21 onward).

--write adds the fit to POSTSEASON_WIN_COEFFICIENTS for the season after the last
one fit (--for-season to override), leaving earlier seasons' coefficients in place.

Downloads are cached under calibration/data/ (pass --refresh to refetch); a
finished season never changes, so only the newest season needs fetching.

Usage (from backend/):
    uv run --group model python calibration/playoff_wins_regression.py
    uv run --group model python calibration/playoff_wins_regression.py --write
    uv run --group model python calibration/playoff_wins_regression.py --as-of "Jan 1"
"""

import argparse
import io
import re
import sys

import numpy as np
import pandas as pd
import requests
from _common import (
    DATA_DIR,
    HTTP_HEADERS,
    REPO_DIR,
    SRC_DIR,
    fetch_postseason_wins,
    last_completed_season,
    parse_season_range,
    season_str,
)
from scipy.optimize import nnls

from nba_wins_pool.utils.odds import american_to_implied, shin_devig

SOH_BASE = "https://www.covers.com/sportsoddshistory"
SOH_PAGES = {
    "regular_season_wins": "nba-win/?sa=nba&t=win&o=t",
    "make_playoffs": "nba-win/?sa=nba&t=post&o=s",
    "win_championship": "nba-main/?sa=nba&a=finals&o=t",
    "win_conference_east": "nba-main/?sa=nba&a=east&o=t",
    "win_conference_west": "nba-main/?sa=nba&a=west&o=t",
}
# Futures pages have a two-row header: (phase, date), e.g. ("Preseason, as of...", "Oct 21")
FUTURES_PAGES = {"win_championship", "win_conference_east", "win_conference_west"}

SOH_CACHE = DATA_DIR / "sportsoddshistory"
POSTSEASON_CACHE = DATA_DIR / "espn_postseason_wins"

AUCTION_SERVICE_PATH = SRC_DIR / "services" / "auction_valuation_service.py"
FIRST_SEASON = 2015  # 2014-15; the earliest season the original fit used
FIRST_PLAY_IN_SEASON = "2020-2021"


# ---------------------------------------------------------------------------
# Data loading (cached)
# ---------------------------------------------------------------------------
def _read_soh_table(page: str, url: str) -> pd.DataFrame:
    html = requests.get(url, headers=HTTP_HEADERS, timeout=30).text
    header = [0, 1] if page in FUTURES_PAGES else 0
    for table in pd.read_html(io.StringIO(html), header=header):
        cols = [c[-1] if isinstance(c, tuple) else c for c in table.columns]
        if "Team" in cols:
            return table
    raise ValueError(f"No team table at {url}")


def load_soh_season(end_year: int, refresh: bool) -> dict[str, pd.DataFrame]:
    folder = SOH_CACHE / season_str(end_year)
    folder.mkdir(parents=True, exist_ok=True)
    tables = {}
    for page, query in SOH_PAGES.items():
        path = folder / f"{page}.csv"
        if refresh or not path.exists():
            print(f"  downloading {page} {season_str(end_year)}", file=sys.stderr)
            _read_soh_table(page, f"{SOH_BASE}/{query}&y={season_str(end_year)}").to_csv(path, index=False)
        tables[page] = pd.read_csv(path, header=[0, 1] if page in FUTURES_PAGES else 0)
    return tables


def load_postseason_wins(end_year: int, refresh: bool) -> pd.DataFrame:
    path = POSTSEASON_CACHE / f"{season_str(end_year)}.csv"
    if refresh or not path.exists():
        print(f"  downloading ESPN postseason results {season_str(end_year)}", file=sys.stderr)
        wins = fetch_postseason_wins(end_year)
        if not wins:
            raise ValueError(f"No completed postseason games on ESPN for {season_str(end_year)}")
        POSTSEASON_CACHE.mkdir(parents=True, exist_ok=True)
        rows = [{"espn_name": name, **counts} for name, counts in sorted(wins.items())]
        pd.DataFrame(rows, columns=["espn_name", "playoff_wins", "play_in_wins"]).to_csv(path, index=False)
    return pd.read_csv(path)


# ---------------------------------------------------------------------------
# Feature construction
# ---------------------------------------------------------------------------
def futures_column(df: pd.DataFrame, as_of: str) -> tuple:
    """The (phase, date) column to read futures odds from.

    ``preseason`` picks the last preseason snapshot (opening night), which is when
    pools draft; anything else is matched against the date row, e.g. "Jan 1".
    """
    cols = [c for c in df.columns if c[1] != "Team"]
    if as_of == "preseason":
        preseason = [c for c in cols if c[0].lower().startswith("preseason")]
        if not preseason:
            raise ValueError("No preseason columns in futures table")
        return preseason[-1]
    matches = [c for c in cols if c[1] == as_of]
    if not matches:
        raise ValueError(f"No futures column dated {as_of!r}; available: {[c[1] for c in cols]}")
    return matches[0]


def devig_futures(df: pd.DataFrame, as_of: str) -> pd.Series:
    """Shin-de-vigged win probability per team for one futures market (missing odds -> 0)."""
    team_col = next(c for c in df.columns if c[1] == "Team")
    odds = pd.to_numeric(df[futures_column(df, as_of)], errors="coerce")
    teams = df[team_col]
    priced = odds.notna()
    probs = pd.Series(0.0, index=teams.values)
    probs[teams[priced].values] = shin_devig([american_to_implied(o) for o in odds[priced]])
    return probs


def build_season(end_year: int, as_of: str, refresh: bool) -> pd.DataFrame:
    tables = load_soh_season(end_year, refresh)

    df = tables["make_playoffs"][["Team", "Conference", "Make Odds", "Miss Odds"]].dropna()
    df["make_prob"] = [
        shin_devig([american_to_implied(m), american_to_implied(x)])[0]
        for m, x in zip(df["Make Odds"], df["Miss Odds"])
    ]
    df = df.merge(tables["regular_season_wins"][["Team", "Win Total"]], on="Team", how="left")

    conf = pd.concat([devig_futures(tables[p], as_of) for p in ("win_conference_east", "win_conference_west")])
    df["conf_prob"] = df["Team"].map(conf).fillna(0.0)
    df["bubble"] = df["make_prob"] * (1.0 - df["make_prob"])
    df["title_prob"] = df["Team"].map(devig_futures(tables["win_championship"], as_of)).fillna(0.0)

    # ESPN keys teams by nickname ("Trail Blazers"); SportsOddsHistory uses the full name
    results = load_postseason_wins(end_year, refresh)
    nickname = {team: next((n for n in results["espn_name"] if team.endswith(f" {n}")), None) for team in df["Team"]}
    unmatched = sorted({n for n in results["espn_name"]} - set(nickname.values()))
    if unmatched:
        raise ValueError(f"{season_str(end_year)}: ESPN teams with no odds row: {unmatched}")
    for col in ("playoff_wins", "play_in_wins"):
        wins = results.set_index("espn_name")[col]
        df[col] = df["Team"].map(nickname).map(wins).fillna(0).astype(int)
    df["season"] = season_str(end_year)
    return df


def app_season(end_year: int) -> str:
    """2027 -> '2026-27' (the app's SeasonStr format)."""
    return f"{end_year - 1}-{end_year % 100:02d}"


def write_coefficients(for_season: str, playoff: float, conf: float, play_in: float, summary: str) -> None:
    """Add (or replace) the POSTSEASON_WIN_COEFFICIENTS entry for *for_season*.

    Earlier seasons' entries are left alone, so their auction values don't change.
    """
    text = AUCTION_SERVICE_PATH.read_text()
    entry = (
        f"    # playoff_wins_regression.py: {summary}\n"
        f'    "{for_season}": PostseasonWinCoefficients(playoff_odds={playoff:.4f}, '
        f"conf_odds={conf:.4f}, play_in_odds={play_in:.4f}),\n"
    )
    existing = re.compile(
        rf"^    # playoff_wins_regression\.py:.*\n    \"{re.escape(for_season)}\": PostseasonWinCoefficients\(.*\),\n",
        re.MULTILINE,
    )
    if existing.search(text):
        text = existing.sub(lambda _: entry, text)
    else:
        if f'"{for_season}": PostseasonWinCoefficients' in text:
            sys.exit(f"{for_season} has a hand-written entry in {AUCTION_SERVICE_PATH.name}; edit it by hand")
        start = text.index("POSTSEASON_WIN_COEFFICIENTS: dict")
        end = text.index("\n}\n", start) + 1
        if any(k > for_season for k in re.findall(r'^    "(\d{4}-\d{2})"', text[start:end], re.MULTILINE)):
            sys.exit(f"{AUCTION_SERVICE_PATH.name} already has a fit for a season after {for_season}")
        text = text[:end] + entry + text[end:]
    AUCTION_SERVICE_PATH.write_text(text)
    print(f"Updated {AUCTION_SERVICE_PATH.relative_to(REPO_DIR)}: POSTSEASON_WIN_COEFFICIENTS[{for_season!r}]")


# ---------------------------------------------------------------------------
# Fitting
# ---------------------------------------------------------------------------
def r_squared(y: np.ndarray, pred: np.ndarray) -> float:
    return 1.0 - ((y - pred) ** 2).sum() / ((y - y.mean()) ** 2).sum()


def fit(df: pd.DataFrame, target: str, features: list[str], intercept: bool = False) -> tuple[np.ndarray, float]:
    """Non-negative least squares; returns (coefficients[, intercept last], R²)."""
    X = df[features].to_numpy(float)
    if intercept:
        X = np.column_stack([X, np.ones(len(X))])
    y = df[target].to_numpy(float)
    coef, _ = nnls(X, y)
    return coef, r_squared(y, X @ coef)


def leave_one_season_out_rmse(df: pd.DataFrame, target: str, features: list[str]) -> float:
    errors = []
    for season in df["season"].unique():
        train, test = df[df["season"] != season], df[df["season"] == season]
        coef, _ = fit(train, target, features)
        errors.append(test[target].to_numpy(float) - test[features].to_numpy(float) @ coef)
    return float(np.sqrt(np.mean(np.concatenate(errors) ** 2)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--seasons",
        default=f"{FIRST_SEASON}-{last_completed_season()}",
        help="Season end years to fit on, e.g. 2015-2026 (default: %(default)s)",
    )
    parser.add_argument(
        "--as-of",
        default="preseason",
        help="Futures snapshot: 'preseason' (last preseason line) or a date label like 'Jan 1'",
    )
    parser.add_argument("--refresh", action="store_true", help="Re-download cached seasons")
    parser.add_argument(
        "--write",
        action="store_true",
        help=f"Add the fit to POSTSEASON_WIN_COEFFICIENTS in {AUCTION_SERVICE_PATH.name}",
    )
    parser.add_argument(
        "--for-season",
        help="Season the written fit takes effect from, e.g. 2026-27 (default: the season after the last one fit)",
    )
    args = parser.parse_args()

    seasons = parse_season_range(args.seasons)
    for_season = args.for_season or app_season(seasons[-1] + 1)
    df = pd.concat([build_season(y, args.as_of, args.refresh) for y in seasons], ignore_index=True)

    print(f"\nSeasons {season_str(seasons[0])} .. {season_str(seasons[-1])}: n={len(df)} team-seasons")
    print(f"Futures as of: {args.as_of}")
    print("\nCheck: market probabilities vs outcomes (mean per season)")
    print(f"  make playoffs  {df['make_prob'].sum() / len(seasons):5.2f}  (16)")
    print(f"  win conference {df['conf_prob'].sum() / len(seasons):5.2f}  (2)")
    print(f"  win title      {df['title_prob'].sum() / len(seasons):5.2f}  (1)")
    print(f"  playoff wins   {df['playoff_wins'].sum() / len(seasons):5.1f}")

    playoff_features = ["make_prob", "conf_prob"]
    playoff_coef, r2_playoff = fit(df, "playoff_wins", playoff_features)
    rmse = leave_one_season_out_rmse(df, "playoff_wins", playoff_features)
    print("\nPlayoff wins (used by the app): NNLS, no intercept")
    print(f"  playoff_odds = {playoff_coef[0]:.4f}")
    print(f"  conf_odds    = {playoff_coef[1]:.4f}")
    print(f"  R² {r2_playoff:.4f}   leave-one-season-out RMSE {rmse:.3f} wins")

    print("  alternatives (diagnostic only; the app stores make + conference probabilities):")
    for label, features, intercept in [
        ("+ intercept", playoff_features, True),
        ("+ title", [*playoff_features, "title_prob"], False),
        ("+ title + win total", ["Win Total", *playoff_features, "title_prob"], False),
    ]:
        c, r = fit(df.dropna(subset=features), "playoff_wins", features, intercept)
        names = features + (["intercept"] if intercept else [])
        print(f"    {label:22} R² {r:.4f}  " + "  ".join(f"{n}={v:.4f}" for n, v in zip(names, c)))

    play_in = df[df["season"] >= FIRST_PLAY_IN_SEASON]
    if play_in.empty:
        sys.exit(f"No play-in seasons in {args.seasons}")
    play_in_coef, r2 = fit(play_in, "play_in_wins", ["bubble"])
    rmse = leave_one_season_out_rmse(play_in, "play_in_wins", ["bubble"])
    y = play_in["play_in_wins"]
    n_seasons = play_in["season"].nunique()
    print(f"\nPlay-in wins (used by the app), {n_seasons} seasons, n={len(play_in)}: NNLS, no intercept")
    print(f"  play_in_odds = {play_in_coef[0]:.4f}   (x make_prob * (1 - make_prob))")
    print(f"  R² {r2:.4f}   leave-one-season-out RMSE {rmse:.3f} wins (a constant: {y.std(ddof=0):.3f})")
    print(f"  predicted per season {play_in_coef[0] * play_in['bubble'].sum() / n_seasons:.2f} (actual: 6)")
    print("  Preseason odds say little about who lands in the play-in; this mostly spreads its")
    print("  6 wins over the bubble teams instead of ignoring them.")
    print("  mean play-in wins by make_prob:")
    bins = pd.cut(play_in["make_prob"], [0, 0.1, 0.25, 0.4, 0.6, 0.75, 0.9, 1.0])
    observed = play_in.groupby(bins, observed=True).agg(
        actual=("play_in_wins", "mean"), model=("bubble", "mean"), n=("play_in_wins", "size")
    )
    observed["model"] *= play_in_coef[0]
    for interval, row in observed.iterrows():
        print(f"    {str(interval):12} actual {row['actual']:.2f}  model {row['model']:.2f}  n={int(row['n'])}")

    if args.write:
        playoff_seasons = f"{app_season(seasons[0])}..{app_season(seasons[-1])}"
        play_in_seasons = f"{app_season(int(play_in['season'].min()[-4:]))}..{app_season(seasons[-1])}"
        summary = (
            f"{args.as_of} odds, Shin de-vigged, NNLS. Playoff {playoff_seasons} (n={len(df)}, R² {r2_playoff:.3f}); "
            f"play-in {play_in_seasons} (n={len(play_in)}, R² {r2:.3f})"
        )
        write_coefficients(for_season, playoff_coef[0], playoff_coef[1], play_in_coef[0], summary)


if __name__ == "__main__":
    main()
