#!/usr/bin/env python3
"""Fetch per-game point spreads, totals, and moneylines from the public ESPN API.

Two stages, because neither endpoint alone has what we need:
  1. site scoreboard  -> the event list (ids, teams, dates, final scores)
  2. core API /odds   -> the sportsbook line for one event

Stage 2 is required for any game that has already tipped off: the scoreboard
embeds an `odds` object only for *upcoming* games and nulls it out afterward,
so historical spreads are reachable only per-event.

Usage:
    python fetch_espn_odds.py --season 2026
    python fetch_espn_odds.py --season 2026 --start 2026-01-01 --end 2026-01-31
    python fetch_espn_odds.py --season 2026 --season-types 2 --nba-tricodes

Season year follows ESPN's convention: the 2025-26 season is `--season 2026`.
"""

import argparse
import csv
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import requests

SCOREBOARD_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
)
ODDS_URL = "https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/events/{eid}/competitions/{eid}/odds"

# ESPN season types. All-Star exhibitions are filed under 2 with fake team
# abbreviations (STARS/WORLD/STRIPES) and carry no line -- see --drop-exhibitions.
SEASON_TYPES = {
    1: "preseason",
    2: "regular",
    3: "postseason",
    4: "allstar",
    5: "playin",
}

# Provider ranking is by NAME, not id. ESPN reassigns provider ids across
# seasons -- id 41 is DraftKings in 2025-26 but SugarHouse in 2021-24, and
# DraftKings itself has been id 40, 41, and 100 across seasons. Ids are not
# a stable key; match on the provider's own name string instead.
#
# Best first: DraftKings is the primary source -- widest, most consistent
# coverage in the current season. ESPN BET fills the games DraftKings skips.
# Any live-odds feed is in-game, not a pregame line, so it sorts last
# regardless of book.
PROVIDER_NAME_PRIORITY = [
    "draftkings",
    "espn bet",
    "caesars",
    "fanduel",
    "betmgm",
    "mgm",
    "unibet",
    "bet365",
]


def _provider_rank(name: str) -> int:
    name = (name or "").lower()
    if (
        "live" in name
    ):  # in-game feed, e.g. "ESPN Bet - Live Odds", "Draft Kings - Live Odds"
        return 99
    for i, key in enumerate(PROVIDER_NAME_PRIORITY):
        if key in name:
            return i
    return len(
        PROVIDER_NAME_PRIORITY
    )  # unranked book, still preferred over a live feed


DEFAULT_MAX_WORKERS = 8

FIELDS = [
    "event_id",
    "date",
    "season_type",
    "season_type_name",
    "away_team",
    "home_team",
    "away_score",
    "home_score",
    "home_spread_close",
    "home_spread_open",
    "over_under",
    "away_moneyline",
    "home_moneyline",
    "provider",
    "details",
    "neutral_site",
    "completed",
]


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers["Accept-Encoding"] = "gzip"
    return session


def months(start: date, end: date):
    """Yield YYYYMM strings covering [start, end].

    ESPN currently 400s on the documented explicit day-range form
    (`dates=20251001-20251031`) but accepts a bare month, so we page by month
    and filter client-side. Month responses also need `limit=1000`; the default
    caps at 100 events and silently truncates a busy month.
    """
    cur = start.replace(day=1)
    while cur <= end:
        yield f"{cur:%Y%m}"
        cur = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)


def fetch_events(session, season, start, end, season_types, verbose=True):
    """Collect events from the scoreboard, keyed by event id to drop month-overlap dupes."""
    events: dict[str, dict] = {}
    for month in months(start, end):
        r = session.get(
            SCOREBOARD_URL, params={"dates": month, "limit": 1000}, timeout=30
        )
        r.raise_for_status()
        batch = r.json().get("events", [])
        kept = 0
        for e in batch:
            season_info = e.get("season", {})
            stype = season_info.get("type")
            if season_info.get("year") != season or stype not in season_types:
                continue
            if not (start.isoformat() <= e["date"][:10] <= end.isoformat()):
                continue
            comp = e["competitions"][0]
            try:
                home = next(c for c in comp["competitors"] if c["homeAway"] == "home")
                away = next(c for c in comp["competitors"] if c["homeAway"] == "away")
            except StopIteration:
                continue
            events[e["id"]] = {
                "event_id": e["id"],
                "date": e["date"][:10],
                "season_type": stype,
                "season_type_name": SEASON_TYPES.get(stype, str(stype)),
                "home_team": home["team"]["abbreviation"],
                "away_team": away["team"]["abbreviation"],
                "home_score": home.get("score"),
                "away_score": away.get("score"),
                "neutral_site": comp.get("neutralSite", False),
                "completed": comp.get("status", {})
                .get("type", {})
                .get("completed", False),
            }
            kept += 1
        if verbose:
            print(f"  {month}: {kept} kept / {len(batch)} returned", file=sys.stderr)
    return list(events.values())


def _spread_value(node):
    """Extract a numeric point spread from an open/close/current odds node.

    ESPN mixes string forms here ("-4.5", "+3", "EVEN", "PK"), so parse
    defensively and return None rather than guessing on anything unexpected.
    """
    if not node:
        return None
    ps = node.get("pointSpread") or {}
    raw = (
        ps.get("american") or ps.get("alternateDisplayValue") or ps.get("displayValue")
    )
    if raw in (None, "-", ""):
        return None
    if raw in ("EVEN", "PK", "PK.", "pk"):
        return 0.0
    try:
        return float(str(raw).replace("+", "").strip())
    except ValueError:
        return None


def fetch_odds(session, event, preferred_provider=None):
    """Attach the best available pregame line to one event row.

    Sign convention: `home_spread_close` is stated from the HOME team's
    perspective, so negative means the home team is favored. ESPN's top-level
    `spread` already uses that convention, and the `details` string (e.g.
    "OKC -6.5") names whichever team is favored -- keep `details` in the output
    so the convention stays auditable downstream.
    """
    eid = event["event_id"]
    row = dict(event)
    row.update(
        provider=None,
        home_spread_close=None,
        home_spread_open=None,
        over_under=None,
        home_moneyline=None,
        away_moneyline=None,
        details=None,
    )
    try:
        r = session.get(ODDS_URL.format(eid=eid), timeout=30)
        r.raise_for_status()
        items = r.json().get("items", [])
    except Exception as exc:  # noqa: BLE001 - one bad event must not sink the run
        row["error"] = str(exc)
        return row

    if not items:
        return row

    def rank(item):
        name = item.get("provider", {}).get("name", "")
        if preferred_provider and preferred_provider.lower() in name.lower():
            return -1
        return _provider_rank(name)

    items.sort(key=rank)
    best = items[0]
    home_odds = best.get("homeTeamOdds") or {}
    away_odds = best.get("awayTeamOdds") or {}

    # Prefer the explicit close, fall back to current, then the top-level spread.
    close = _spread_value(home_odds.get("close"))
    if close is None:
        close = _spread_value(home_odds.get("current"))
    if close is None and best.get("spread") is not None:
        try:
            close = float(best["spread"])
        except (TypeError, ValueError):
            close = None

    row.update(
        provider=best.get("provider", {}).get("name"),
        home_spread_close=close,
        home_spread_open=_spread_value(home_odds.get("open")),
        over_under=best.get("overUnder"),
        home_moneyline=home_odds.get("moneyLine"),
        away_moneyline=away_odds.get("moneyLine"),
        details=best.get("details"),
    )
    return row


def apply_tricode_map(rows, map_path):
    """Rewrite ESPN abbreviations to NBA tricodes (GS -> GSW) for joins with NBA-side data."""
    mapping = json.loads(Path(map_path).read_text())
    for row in rows:
        row["home_team"] = mapping.get(row["home_team"], row["home_team"])
        row["away_team"] = mapping.get(row["away_team"], row["away_team"])
    return rows


def validate(rows):
    """Sanity-check the pull. A silently wrong sign convention is the main risk here.

    Real closing lines put home ATS cover rate near 50% and correlate strongly
    with actual margin. If cover rate drifts far from 0.5 or the correlation is
    negative, the spread sign was most likely flipped somewhere.
    """
    import statistics

    done = [
        r
        for r in rows
        if r.get("completed")
        and r.get("home_spread_close") is not None
        and r.get("home_score") not in (None, "")
        and r.get("away_score") not in (None, "")
    ]
    report = {
        "games": len(rows),
        "with_close": sum(1 for r in rows if r.get("home_spread_close") is not None),
        "with_open": sum(1 for r in rows if r.get("home_spread_open") is not None),
        "errors": sum(1 for r in rows if r.get("error")),
        "completed_scored": len(done),
    }
    if len(done) >= 30:
        margins = [int(r["home_score"]) - int(r["away_score"]) for r in done]
        spreads = [r["home_spread_close"] for r in done]
        report["home_ats_cover_rate"] = round(
            sum(1 for m, s in zip(margins, spreads) if m + s > 0) / len(done), 4
        )
        report["mean_home_margin"] = round(statistics.mean(margins), 3)
        report["mean_home_spread"] = round(statistics.mean(spreads), 3)
        report["corr_margin_vs_neg_spread"] = round(
            statistics.correlation(margins, [-s for s in spreads]), 4
        )
    return report


def main():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--season",
        type=int,
        required=True,
        help="ESPN season year (2025-26 season = 2026)",
    )
    p.add_argument("--start", help="ISO start date (default: Oct 1 of season-1)")
    p.add_argument("--end", help="ISO end date (default: Jun 30 of season)")
    p.add_argument(
        "--season-types",
        default="2,3,5",
        help="Comma-separated ESPN season types. 1=pre 2=regular 3=post 4=allstar 5=play-in (default: 2,3,5)",
    )
    p.add_argument(
        "--provider",
        help="Preferred sportsbook, matched by substring (e.g. 'espn bet', 'draftkings', 'fanduel')",
    )
    p.add_argument(
        "--drop-exhibitions",
        action="store_true",
        help="Drop All-Star games (fake team codes, never have a line)",
    )
    p.add_argument(
        "--nba-tricodes",
        metavar="MAP_JSON",
        nargs="?",
        const="auto",
        help="Map ESPN abbrevs to NBA tricodes using espn_to_nba_abbrev_map.json",
    )
    p.add_argument(
        "--out", default="nba_odds", help="Output path prefix (default: nba_odds)"
    )
    p.add_argument("--workers", type=int, default=DEFAULT_MAX_WORKERS)
    args = p.parse_args()

    start = (
        date.fromisoformat(args.start) if args.start else date(args.season - 1, 10, 1)
    )
    end = date.fromisoformat(args.end) if args.end else date(args.season, 6, 30)
    season_types = {int(t) for t in args.season_types.split(",") if t.strip()}

    session = build_session()
    print(f"Fetching {args.season} schedule {start} -> {end}...", file=sys.stderr)
    events = fetch_events(session, args.season, start, end, season_types)

    if args.drop_exhibitions:
        fake = {"STARS", "WORLD", "STRIPES", "USA", "GLOBE"}
        events = [
            e
            for e in events
            if e["home_team"] not in fake and e["away_team"] not in fake
        ]

    print(
        f"{len(events)} events; fetching odds with {args.workers} workers...",
        file=sys.stderr,
    )
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        rows = list(pool.map(lambda e: fetch_odds(session, e, args.provider), events))

    if args.nba_tricodes:
        map_path = args.nba_tricodes
        if map_path == "auto":
            repo_map = (
                Path(__file__).resolve().parents[4]
                / "backend/src/nba_wins_pool/services/nba_simulator/espn_to_nba_abbrev_map.json"
            )
            map_path = repo_map
        rows = apply_tricode_map(rows, map_path)

    rows.sort(key=lambda r: (r["date"], r["event_id"]))

    csv_path, json_path = f"{args.out}.csv", f"{args.out}.json"
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    with open(json_path, "w") as f:
        json.dump(rows, f, indent=1)

    report = validate(rows)
    print(json.dumps(report, indent=2), file=sys.stderr)
    print(f"Wrote {csv_path} and {json_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
