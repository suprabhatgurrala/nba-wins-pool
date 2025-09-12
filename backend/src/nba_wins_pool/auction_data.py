import json
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from nba_wins_pool.nba_data import nba_logo_url, nba_tricode_to_id

MAKE_PLAYOFFS_SUFFIX = "To Make Playoffs"
REG_SEASON_WINS_SUFFIX = "Regular Season Wins"

# Linear regression results to estimate Playoff Wins
PLAYOFF_ODDS_COEFFICIENT = 2.7828
CONF_ODDS_COEFFICIENT = 19.7734

data_path = Path(__file__).parent / "data"
with open(data_path / "fanduel_team_to_tricode.json") as f:
    fanduel_to_tricode = json.load(f)


def fetch_odds():
    """Fetches the latest NBA odds data from FanDuel's sportsbook API."""
    url = "https://api.sportsbook.fanduel.com/sbapi/content-managed-page"

    params = {
        "page": "CUSTOM",
        "customPageId": "nba",
        "pbHorizontal": "false",
        "_ak": "FhMFpcPWXMeyZxOx",
        "timezone": "America/New_York",
    }

    headers = {
        "X-Sportsbook-Region": "NJ",
        "sec-ch-ua-platform": '"Windows"',
        "Referer": "https://sportsbook.fanduel.com/",
        "sec-ch-ua": '"Not;A=Brand";v="99", "Brave";v="139", "Chromium";v="139"',
        "sec-ch-ua-mobile": "?0",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
        "Accept": "application/json",
    }

    response = requests.get(url, params=params, headers=headers)
    response.raise_for_status()
    return response.json()


def get_playoff_odds_from_market(market):
    """
    Helper method to parse playoff odds from Fanduel response.

    Args:
        market (dict): A market dictionary from the Fanduel API response.
    """
    row = {}
    yes_odds = None
    no_odds = None
    for runner in market["runners"]:
        odds = runner["winRunnerOdds"]["trueOdds"]["decimalOdds"]["decimalOdds"]
        if runner["runnerName"] == "Yes":
            yes_odds = odds
        elif runner["runnerName"] == "No":
            no_odds = odds
    row[f"{MAKE_PLAYOFFS_SUFFIX}: Yes"] = yes_odds
    row[f"{MAKE_PLAYOFFS_SUFFIX}: No"] = no_odds
    return {
        "team": market["marketName"].split(MAKE_PLAYOFFS_SUFFIX)[0].strip(),
        "make_playoffs": yes_odds,
        "miss_playoffs": no_odds,
    }


def get_reg_season_total_from_market(market):
    """
    Helper method to parse win totals from Fanduel response.

    Args:
        market (dict): A market dictionary from the Fanduel API response.
    """
    win_total = None
    over_odds = None
    under_odds = None
    for runner in market["runners"]:
        if runner["runnerStatus"] != "ACTIVE":
            continue
        name = runner["runnerName"].lower()
        odds = runner["winRunnerOdds"]["trueOdds"]["decimalOdds"]["decimalOdds"]
        win_total_str = name.removesuffix("wins")
        if "over" in name:
            win_total_str = win_total_str.removeprefix("over").strip()
            over_odds = odds
        elif "under" in name:
            win_total_str = win_total_str.removeprefix("under").strip()
            under_odds = odds
        if win_total is not None:
            assert win_total == float(win_total_str), f"{win_total} is not equal to {float(win_total_str)}\n{market}"
        else:
            win_total = float(win_total_str)
    return {
        "team": market["marketName"].split("Regular Season Wins")[0].strip(),
        "reg_season_wins": win_total,
        "over_reg_season_wins": over_odds,
        "under_reg_season_wins": under_odds,
    }


def get_conf_odds_from_market(market):
    """
    Helper method to parse conference odds from Fanduel response.

    Args:
        market (dict): A market dictionary from the Fanduel API response.
    """
    rows = []
    if "east" in market["marketName"].lower():
        conf = "East"
    elif "west" in market["marketName"].lower():
        conf = "West"
    for runner in market["runners"]:
        rows.append(
            {
                "team": runner["runnerName"],
                "conf_odds": runner["winRunnerOdds"]["trueOdds"]["decimalOdds"]["decimalOdds"],
                "conf": conf,
            }
        )
    return pd.DataFrame(rows)


def get_title_odds_from_market(market):
    """
    Helper method to parse title odds from Fanduel response.

    Args:
        market (dict): A market dictionary from the Fanduel API response.
    """
    return pd.DataFrame(
        [
            {
                "team": runner["runnerName"],
                "title_odds": runner["winRunnerOdds"]["trueOdds"]["decimalOdds"]["decimalOdds"],
            }
            for runner in market["runners"]
        ]
    )


def get_vig_adjusted_probabilities(outcome_a, outcome_b, vig=0.02):
    """
    Convert decimal odds to probabilities and adjust for vig.
    outcome_a: Decimal odds for outcome A (e.g., team makes playoffs)
    outcome_b: Decimal odds for outcome B (e.g., team misses playoffs)
    vig: The bookmaker's margin (used to infer probabilities when one outcome is missing)
    """
    raw_prob_a = 1 / outcome_a
    raw_prob_b = 1 / outcome_b
    total_raw_prob = (raw_prob_a + raw_prob_b).fillna(1 + vig)
    raw_prob_a = raw_prob_a.fillna(total_raw_prob - raw_prob_b)
    return raw_prob_a / total_raw_prob


def get_probabilities_from_odds(df):
    """
    Helper method to convert decimal odds to probabilities and calculate expected wins.
    Args:
        df (pd.DataFrame): DataFrame containing odds data for each team.

    Returns:
        pd.DataFrame: DataFrame with probability and expected wins columns.
    """
    df["make_playoffs_prob"] = get_vig_adjusted_probabilities(df["make_playoffs"], df["miss_playoffs"])
    df["over_reg_season_wins_prob"] = get_vig_adjusted_probabilities(
        df["over_reg_season_wins"], df["under_reg_season_wins"]
    )
    east_conf_sum = (1 / df.where(df["conf"] == "East")["conf_odds"]).sum()
    west_conf_sum = (1 / df.where(df["conf"] == "West")["conf_odds"]).sum()
    df["conf_prob"] = np.where(
        df["conf"] == "East", (1 / df["conf_odds"]) / east_conf_sum, (1 / df["conf_odds"]) / west_conf_sum
    )
    raw_title_prob = 1 / df["title_odds"]
    df["title_prob"] = raw_title_prob / raw_title_prob.sum()
    df["total_expected_wins"] = (
        df["reg_season_wins"]
        + (df["make_playoffs_prob"] * PLAYOFF_ODDS_COEFFICIENT)
        + (df["conf_prob"] * CONF_ODDS_COEFFICIENT)
    )

    return df.sort_values(by="total_expected_wins", ascending=False)


def get_auction_values(df, num_owners, budget_per_owner, teams_per_owner):
    """
    Perform value over replacement calculation and assign auction values.

    Args:
        df (pd.DataFrame): DataFrame containing expected wins for each team.
        num_owners (int): Number of owners in the league.
        budget_per_owner (int): Budget allocated to each owner.
        teams_per_owner (int): Number of teams each owner will draft.

    Returns:
        pd.DataFrame: DataFrame with an additional 'auction_value' column.
    """
    total_budget = num_owners * budget_per_owner
    total_drafted_teams = num_owners * teams_per_owner

    replacement_level = df["total_expected_wins"].nlargest(total_drafted_teams).min()
    value_over_replacement = df["total_expected_wins"] - replacement_level
    total_value_over_replacement = value_over_replacement.nlargest(total_drafted_teams).sum()
    df["auction_value"] = (value_over_replacement / total_value_over_replacement) * total_budget
    df["auction_value"] = df["auction_value"].clip(lower=1).round(0)

    return df


def get_auction_data(num_owners=6, budget_per_owner=200, teams_per_owner=4):
    """
    Main method which fetches odds data, parses it, and computes auction values.

    Args:
        num_owners (int): Number of owners in the league.
        budget_per_owner (int): Budget allocated to each owner.
        teams_per_owner (int): Number of teams each owner will draft.

    Returns:
        pd.DataFrame: DataFrame containing teams with their auction values and probabilities.
    """
    odds_response = fetch_odds()
    markets = odds_response.get("attachments", {}).get("markets", {})

    playoffs_df = []
    reg_season_wins_df = []
    conf_df = []
    title_df = []
    for market in markets.values():
        market_type = market["marketType"]
        if market_type == "NBA_REGULAR_SEASON_WINS_SGP":
            reg_season_wins_df.append(get_reg_season_total_from_market(market))
        if market_type == "NBA_TO_MAKE_PLAYOFFS":
            playoffs_df.append(get_playoff_odds_from_market(market))
        if market_type == "NBA_CONFERENCE_WINNER":
            conf_df.append(get_conf_odds_from_market(market))
        if market_type == "NBA_CHAMPIONSHIP":
            title_df = get_title_odds_from_market(market)

    playoffs_df = pd.DataFrame(playoffs_df).set_index("team")
    reg_season_wins_df = pd.DataFrame(reg_season_wins_df).set_index("team")
    conf_df = pd.concat(conf_df).set_index("team")
    title_df = pd.DataFrame(title_df).set_index("team")

    df = pd.concat([playoffs_df, reg_season_wins_df, conf_df, title_df], axis=1)
    df["nba_tricode"] = df.index.map(fanduel_to_tricode)
    df["logo_url"] = df["nba_tricode"].apply(lambda x: nba_logo_url.format(nba_team_id=nba_tricode_to_id[x]))
    df = get_probabilities_from_odds(df)
    df = get_auction_values(df, num_owners, budget_per_owner, teams_per_owner)
    return df.replace({np.nan: None}).reset_index()
