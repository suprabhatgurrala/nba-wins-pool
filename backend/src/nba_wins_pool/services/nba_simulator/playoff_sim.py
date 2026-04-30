"""Simulate the NBA Playoffs (best-of-7 series).

Playoff structure (per conference):
  Round 1:  1v8, 4v5, 2v7, 3v6
  Round 2:  winner(1v8) vs winner(4v5), winner(2v7) vs winner(3v6)
  Round 3:  Conference Finals — two remaining teams
  Round 4:  NBA Finals — East champion vs West champion

Win probability model (priority order):
1. FanDuel moneyline odds — per-game home win probability when available for the
   next game in a series.  Applied to the current game only; subsequent games in
   the same series fall back to the power-rating model.
2. Power rating (ESPN BPI) — sigmoid fitted to 2024 NBA games post All-Star
   Break with home court adjustment:
       P = 1 / (1 + exp(-k * (rating_home - rating_away)))   k = 0.12668204
   HCA is +2.5 rating points for the home team.
   ESPN BPI ratings are required; a ValueError is raised if they are absent.

Home court advantage:
  Higher seed has home court for games 1, 2, 5, 7.
  Lower seed has home court for games 3, 4, 6.
  In rounds 2+, home court goes to the team with the lower (better) conference seed.
  In the Finals, home court goes to the team with more regular-season wins.

Play-in integration:
  Pass ``play_in_7`` / ``play_in_8`` — the ``(n_teams, n_sims)`` indicator arrays
  returned by ``compute_play_in_results`` — so that playoff seeds 7 and 8 are
  resolved correctly across simulations.  When omitted, the raw ``seeds`` array
  is used directly (appropriate when play-in results are already baked in).

Known series: build a ``PlayoffBracketState`` (keyed by tricode) from the NBA
bracket API and pass it to lock in games already played.  Completed series are
returned without sampling; partial series only simulate remaining games.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Home court schedule for best-of-7: True = higher seed (team A) is home
_HOME_PATTERN = np.array([True, True, False, False, True, False, True], dtype=bool)

# Home court advantage in power-rating points applied to the home team
_HCA_RATING = 2.5

# Sigmoid coefficient fitted to 2024 NBA games post All-Star Break
_SIGMOID_K = 0.12668204

# Round-1 bracket slots: (higher_seed, lower_seed).
# Ordering is chosen so that R1 slots 0+1 feed R2 slot 0 and slots 2+3 feed R2 slot 1.
_R1_MATCHUPS: list[tuple[int, int]] = [(1, 8), (4, 5), (2, 7), (3, 6)]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class KnownSeriesResult:
    """Known game-level state of a playoff series.

    Attributes:
        higher_seed_wins: Games won by the higher seed (home court advantage team).
        lower_seed_wins: Games won by the lower seed.
        next_game_home_win_prob: Optional FanDuel win probability for the home team
            in the *next* scheduled game.  Applied to the first simulated game only.
    """

    higher_seed_wins: int = 0
    lower_seed_wins: int = 0
    next_game_home_win_prob: float | None = None

    @property
    def games_played(self) -> int:
        return self.higher_seed_wins + self.lower_seed_wins

    @property
    def is_complete(self) -> bool:
        return self.higher_seed_wins == 4 or self.lower_seed_wins == 4


@dataclass
class PlayoffBracketState:
    """Known series results across the entire playoff bracket.

    Keys are ``(conference, round_num, high_seed_tricode)`` where:

    - *conference*: ``"East"``, ``"West"``, or ``"Finals"``
    - *round_num*: 1–4
    - *high_seed_tricode*: tricode of the home-court-advantage team in the series
      (the team with the better regular-season record / lower seed).
    """

    series_results: dict[tuple[str, int, str], KnownSeriesResult] = field(default_factory=dict)

    def get(self, conference: str, round_num: int, high_tricode: str) -> KnownSeriesResult | None:
        """Look up a known series result by conference, round, and high-seed tricode."""
        return self.series_results.get((conference, round_num, high_tricode))


# ---------------------------------------------------------------------------
# Probability helpers
# ---------------------------------------------------------------------------


def _diff_to_prob(rating_home: np.ndarray, rating_away: np.ndarray) -> np.ndarray:
    """Home team win probability from power-rating differential.

    Sigmoid fitted to 2024 NBA games post All-Star Break:
        P = 1 / (1 + exp(-k * (rating_home - rating_away)))   k = 0.12668204
    """
    return 1.0 / (1.0 + np.exp(-_SIGMOID_K * (rating_home - rating_away)))


# ---------------------------------------------------------------------------
# Core series simulation
# ---------------------------------------------------------------------------


def simulate_best_of_7(
    team_a: np.ndarray,
    team_b: np.ndarray,
    rng: np.random.Generator,
    n_sims: int,
    ratings: np.ndarray,
    known: KnownSeriesResult | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Simulate a best-of-7 series vectorized across all simulations.

    ``team_a`` is the higher seed and has home court for games 1, 2, 5, 7.
    ``team_b`` is the lower seed with home court for games 3, 4, 6.

    Random numbers are always pre-drawn for all 7 game positions so
    reproducibility is maintained regardless of how many games are actually
    played or whether a ``known`` result short-circuits sampling.

    When a ``KnownSeriesResult.next_game_home_win_prob`` is set, that probability
    overrides the model-derived one for the first remaining game only.

    Args:
        team_a: ``(n_sims,)`` int32 — global team index of the higher seed.
        team_b: ``(n_sims,)`` int32 — global team index of the lower seed.
        rng: Random number generator.
        n_sims: Number of simulations.
        ratings: ``(n_teams,)`` float32 power-rating array (ESPN BPI).  Win
            probabilities use the fitted sigmoid with HCA.  Required; raises
            ``ValueError`` if empty or None.
        known: Optional known series state.  ``is_complete`` series are returned
            directly; partial series simulate only remaining games.

    Returns:
        ``(a_wins, b_wins, a_wins_series)`` where:

        - *a_wins*: ``(n_sims,)`` int32 — games won by ``team_a``.
        - *b_wins*: ``(n_sims,)`` int32 — games won by ``team_b``.
        - *a_wins_series*: ``(n_sims,)`` bool — ``True`` if ``team_a`` wins.
    """
    if ratings is None or len(ratings) == 0:
        raise ValueError("ESPN BPI ratings are required for playoff simulation but were not provided.")

    known_a = known.higher_seed_wins if known else 0
    known_b = known.lower_seed_wins if known else 0

    # Always pre-draw random numbers for reproducibility
    rand = rng.random((7, n_sims), dtype=np.float32)

    # Completed series: return known result without sampling
    if known is not None and known.is_complete:
        a_wins_out = np.full(n_sims, known_a, dtype=np.int32)
        b_wins_out = np.full(n_sims, known_b, dtype=np.int32)
        return a_wins_out, b_wins_out, a_wins_out == 4

    # Per-game win probability for team_a (home vs away)
    r_a = ratings[team_a]  # (n_sims,)
    r_b = ratings[team_b]  # (n_sims,)
    p_home = _diff_to_prob(r_a + _HCA_RATING, r_b)  # team_a at home
    p_away = _diff_to_prob(r_a, r_b + _HCA_RATING)  # team_b at home

    # (7, n_sims) win probability matrix — varies by game position (home/away)
    p_per_game = np.where(_HOME_PATTERN[:, None], p_home[None, :], p_away[None, :])

    # Apply FanDuel override to the first remaining game when available
    games_played_already = known_a + known_b
    if known is not None and known.next_game_home_win_prob is not None:
        next_game_idx = games_played_already
        if next_game_idx < 7:
            is_home_a_for_next = _HOME_PATTERN[next_game_idx]
            override_prob = known.next_game_home_win_prob if is_home_a_for_next else 1.0 - known.next_game_home_win_prob
            p_per_game = p_per_game.copy()
            p_per_game[next_game_idx, :] = override_prob

    # (7, n_sims) simulated outcomes: True = team_a won that game
    game_a_wins = rand < p_per_game
    sim_idx = np.arange(n_sims)

    if games_played_already == 0:
        # Fast path: cumulative-sum + argmax to find the last game played
        a_wins_cum = np.cumsum(game_a_wins.astype(np.int32), axis=0)  # (7, n_sims)
        b_wins_cum = np.cumsum((~game_a_wins).astype(np.int32), axis=0)  # (7, n_sims)
        series_over = (a_wins_cum >= 4) | (b_wins_cum >= 4)
        last_game = np.argmax(series_over, axis=0)  # (n_sims,)
        a_wins_out = a_wins_cum[last_game, sim_idx].astype(np.int32)
        b_wins_out = b_wins_cum[last_game, sim_idx].astype(np.int32)
    else:
        # Partial series: start from known state and simulate remaining games.
        # At most 7 - games_played_already iterations (bounded at 4).
        cum_a = np.full(n_sims, known_a, dtype=np.int32)
        cum_b = np.full(n_sims, known_b, dtype=np.int32)
        for g in range(games_played_already, 7):
            active = (cum_a < 4) & (cum_b < 4)
            cum_a += (game_a_wins[g] & active).astype(np.int32)
            cum_b += (~game_a_wins[g] & active).astype(np.int32)
        a_wins_out = cum_a
        b_wins_out = cum_b

    return a_wins_out, b_wins_out, (a_wins_out == 4)


# ---------------------------------------------------------------------------
# Conference bracket helpers
# ---------------------------------------------------------------------------


def _team_at_seed(conf_team_arr: np.ndarray, seeds: np.ndarray, seed_val: int) -> np.ndarray:
    """Return the global team index at a given conference seed per simulation.

    Args:
        conf_team_arr: ``(n_conf_teams,)`` global team indices for this conference.
        seeds: ``(n_teams, n_sims)`` conference seed per team per simulation.
        seed_val: The seed to look up (1–8).

    Returns:
        ``(n_sims,)`` int32 array of global team indices.
    """
    conf_seeds = seeds[conf_team_arr, :]  # (n_conf_teams, n_sims)
    row_idx = np.argmax(conf_seeds == seed_val, axis=0)  # (n_sims,)
    return conf_team_arr[row_idx]


def _team_at_play_in_seed(
    conf_team_arr: np.ndarray,
    play_in: np.ndarray,
) -> np.ndarray:
    """Return the team that earned a play-in seed (7 or 8) per simulation.

    Args:
        conf_team_arr: ``(n_conf_teams,)`` global indices for this conference.
        play_in: ``(n_teams, n_sims)`` float32 — ``1.0`` if team earned the seed.

    Returns:
        ``(n_sims,)`` int32 array of global team indices.
    """
    conf_pi = play_in[conf_team_arr, :]  # (n_conf_teams, n_sims)
    row_idx = np.argmax(conf_pi >= 0.5, axis=0)  # (n_sims,)
    return conf_team_arr[row_idx]


def _lookup_known_series(
    team_a: np.ndarray,
    team_b: np.ndarray,
    conference: str,
    round_num: int,
    bracket_state: PlayoffBracketState,
    idx_to_tricode: dict[int, str],
) -> KnownSeriesResult | None:
    """Look up a known series result when team assignments are consistent across sims.

    The bracket state lookup only applies when ``team_a`` is the same across all
    simulations (i.e., when seeds are deterministic, as in the playoffs phase).
    During the play-in phase seeds vary per simulation, so ``None`` is returned.
    """
    if not np.all(team_a == team_a[0]):
        return None
    high_tricode = idx_to_tricode.get(int(team_a[0]))
    if high_tricode is None:
        return None
    return bracket_state.get(conference, round_num, high_tricode)


# ---------------------------------------------------------------------------
# Conference bracket simulation
# ---------------------------------------------------------------------------


def _simulate_conference_bracket(
    conf_team_arr: np.ndarray,
    seeds: np.ndarray,
    n_teams: int,
    rng: np.random.Generator,
    n_sims: int,
    ratings: np.ndarray,
    bracket_state: PlayoffBracketState | None = None,
    conference: str = "East",
    idx_to_tricode: dict[int, str] | None = None,
    play_in_7: np.ndarray | None = None,
    play_in_8: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Simulate all three conference playoff rounds.

    Args:
        conf_team_arr: ``(n_conf_teams,)`` global indices for teams in this conference.
            Should include all seeds 1–10 (seeds 9-10 are needed to supply seeds 7-8
            when ``play_in_7`` / ``play_in_8`` are not provided).
        seeds: ``(n_teams, n_sims)`` regular-season conference seeds.
        n_teams: Total number of teams (used to size output arrays).
        rng: Random number generator.
        n_sims: Number of simulations.
        ratings: ``(n_teams,)`` ESPN BPI power-rating array.
        bracket_state: Optional known series results.
        conference: ``"East"`` or ``"West"`` — used for bracket-state lookup.
        idx_to_tricode: Optional global-index → tricode mapping, required for
            bracket-state lookup.
        play_in_7: Optional ``(n_teams, n_sims)`` float32 — ``1.0`` if team earned
            playoff seed 7. When provided, overrides seed-7 lookup via ``seeds``.
        play_in_8: Optional ``(n_teams, n_sims)`` float32 — ``1.0`` if team earned
            playoff seed 8. When provided, overrides seed-8 lookup via ``seeds``.

    Returns:
        ``(playoff_wins, conf_champion)`` where:

        - *playoff_wins*: ``(n_teams, n_sims)`` float32 — games won in the playoffs.
        - *conf_champion*: ``(n_sims,)`` int32 — global index of conference champion.
    """
    playoff_wins = np.zeros((n_teams, n_sims), dtype=np.float32)
    sim_idx = np.arange(n_sims)

    def _get_seed(s: int) -> np.ndarray:
        if s == 7 and play_in_7 is not None:
            return _team_at_play_in_seed(conf_team_arr, play_in_7)
        if s == 8 and play_in_8 is not None:
            return _team_at_play_in_seed(conf_team_arr, play_in_8)
        return _team_at_seed(conf_team_arr, seeds, s)

    def _get_known(round_num: int, team_a: np.ndarray, team_b: np.ndarray) -> KnownSeriesResult | None:
        if bracket_state is None or idx_to_tricode is None:
            return None
        return _lookup_known_series(team_a, team_b, conference, round_num, bracket_state, idx_to_tricode)

    # --- Round 1: 1v8, 4v5, 2v7, 3v6 ---
    round1_winners = np.empty((4, n_sims), dtype=np.int32)
    for slot, (s_high, s_low) in enumerate(_R1_MATCHUPS):
        team_a = _get_seed(s_high)
        team_b = _get_seed(s_low)
        known = _get_known(1, team_a, team_b)
        a_wins, b_wins, a_wins_series = simulate_best_of_7(team_a, team_b, rng, n_sims, ratings, known=known)
        playoff_wins[team_a, sim_idx] += a_wins
        playoff_wins[team_b, sim_idx] += b_wins
        round1_winners[slot] = np.where(a_wins_series, team_a, team_b)

    # --- Round 2: winner(1v8) vs winner(4v5)  |  winner(2v7) vs winner(3v6) ---
    # R1 slots 0 (1v8) and 1 (4v5) feed R2 slot 0.
    # R1 slots 2 (2v7) and 3 (3v6) feed R2 slot 1.
    round2_winners = np.empty((2, n_sims), dtype=np.int32)
    for slot in range(2):
        r1_a = round1_winners[slot * 2]
        r1_b = round1_winners[slot * 2 + 1]
        # Home court: lower seed number = better record = home court
        seed_a = seeds[r1_a, sim_idx]
        seed_b = seeds[r1_b, sim_idx]
        team_a = np.where(seed_a <= seed_b, r1_a, r1_b)
        team_b = np.where(seed_a <= seed_b, r1_b, r1_a)
        known = _get_known(2, team_a, team_b)
        a_wins, b_wins, a_wins_series = simulate_best_of_7(team_a, team_b, rng, n_sims, ratings, known=known)
        playoff_wins[team_a, sim_idx] += a_wins
        playoff_wins[team_b, sim_idx] += b_wins
        round2_winners[slot] = np.where(a_wins_series, team_a, team_b)

    # --- Round 3: Conference Finals ---
    r2_a, r2_b = round2_winners[0], round2_winners[1]
    seed_a = seeds[r2_a, sim_idx]
    seed_b = seeds[r2_b, sim_idx]
    team_a = np.where(seed_a <= seed_b, r2_a, r2_b)
    team_b = np.where(seed_a <= seed_b, r2_b, r2_a)
    known = _get_known(3, team_a, team_b)
    a_wins, b_wins, a_wins_series = simulate_best_of_7(team_a, team_b, rng, n_sims, ratings, known=known)
    playoff_wins[team_a, sim_idx] += a_wins
    playoff_wins[team_b, sim_idx] += b_wins
    conf_champion = np.where(a_wins_series, team_a, team_b)

    return playoff_wins, conf_champion


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def simulate_playoffs(
    east_teams: list[int],
    west_teams: list[int],
    seeds: np.ndarray,
    total_wins: np.ndarray,
    n_teams: int,
    n_sims: int,
    rng: np.random.Generator,
    ratings: np.ndarray,
    bracket_state: PlayoffBracketState | None = None,
    team_idx: dict[str, int] | None = None,
    play_in_7: np.ndarray | None = None,
    play_in_8: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Simulate the full NBA playoff bracket for both conferences and the Finals.

    Each conference plays three rounds (first round, semi-finals, conference finals),
    followed by the NBA Finals between the two conference champions.

    Supports both deterministic seedings (playoffs phase, n_sims copies of the same
    seed assignment) and probabilistic seedings (play-in phase, seeds 7–8 vary per
    simulation).  When ``play_in_7`` / ``play_in_8`` are provided, those are used in
    place of the raw ``seeds`` array for playoff seeds 7 and 8.

    Args:
        east_teams: Global indices of all East conference teams.
        west_teams: Global indices of all West conference teams.
        seeds: ``(n_teams, n_sims)`` int32 — regular-season conference seed per team.
        total_wins: ``(n_teams, n_sims)`` float32 — win totals, used only to
            determine Finals home court (team with more regular-season wins).
        n_teams: Total number of teams.
        n_sims: Number of simulations.
        rng: Shared RNG instance.
        ratings: ``(n_teams,)`` float32 ESPN BPI power-rating array indexed by
            global team index.  Non-playoff teams should be 0.0 (league average).
        bracket_state: Optional ``PlayoffBracketState`` with known series results.
        team_idx: Optional tricode → global index mapping, required when
            ``bracket_state`` is provided so known series can be looked up by tricode.
        play_in_7: Optional ``(n_teams, n_sims)`` float32 from
            ``compute_play_in_results``.  When provided, seeds 7 in each conference
            are resolved from this array instead of ``seeds``.
        play_in_8: Optional ``(n_teams, n_sims)`` float32 from
            ``compute_play_in_results``.  When provided, seeds 8 in each conference
            are resolved from this array instead of ``seeds``.

    Returns:
        ``(playoff_wins, champion, east_champion, west_champion)`` where:

        - *playoff_wins*: ``(n_teams, n_sims)`` float32 — games won in the playoffs.
          Add to regular-season win totals for the full season win count.
        - *champion*: ``(n_sims,)`` int32 — global team index of the NBA champion.
        - *east_champion*: ``(n_sims,)`` int32 — global index of the East champion.
        - *west_champion*: ``(n_sims,)`` int32 — global index of the West champion.
    """
    sim_idx = np.arange(n_sims)

    idx_to_tricode: dict[int, str] = {v: k for k, v in team_idx.items()} if team_idx else {}

    east_arr = np.array(east_teams, dtype=np.int32)
    west_arr = np.array(west_teams, dtype=np.int32)

    # Conference brackets
    east_wins, east_champion = _simulate_conference_bracket(
        east_arr,
        seeds,
        n_teams,
        rng,
        n_sims,
        ratings,
        bracket_state=bracket_state,
        conference="East",
        idx_to_tricode=idx_to_tricode,
        play_in_7=play_in_7,
        play_in_8=play_in_8,
    )
    west_wins, west_champion = _simulate_conference_bracket(
        west_arr,
        seeds,
        n_teams,
        rng,
        n_sims,
        ratings,
        bracket_state=bracket_state,
        conference="West",
        idx_to_tricode=idx_to_tricode,
        play_in_7=play_in_7,
        play_in_8=play_in_8,
    )

    playoff_wins = east_wins + west_wins

    # NBA Finals — home court to team with more regular-season wins (ties to East champion)
    east_wins_total = total_wins[east_champion, sim_idx]
    west_wins_total = total_wins[west_champion, sim_idx]
    team_a = np.where(east_wins_total >= west_wins_total, east_champion, west_champion)
    team_b = np.where(east_wins_total >= west_wins_total, west_champion, east_champion)
    known: KnownSeriesResult | None = None
    if bracket_state is not None and idx_to_tricode:
        known = _lookup_known_series(team_a, team_b, "Finals", 4, bracket_state, idx_to_tricode)
    a_wins, b_wins, a_wins_series = simulate_best_of_7(team_a, team_b, rng, n_sims, ratings, known=known)
    playoff_wins[team_a, sim_idx] += a_wins
    playoff_wins[team_b, sim_idx] += b_wins
    champion = np.where(a_wins_series, team_a, team_b).astype(np.int32)

    return playoff_wins, champion, east_champion, west_champion


# ---------------------------------------------------------------------------
# High-level entry point: probabilities from power ratings
# ---------------------------------------------------------------------------

_DEFAULT_N_SIMS = 10_000


def compute_playoff_probabilities(
    ratings: dict[str, float],
    playoff_seedings: dict[str, tuple[str, int]],
    bracket_state: PlayoffBracketState | None = None,
    n_sims: int = _DEFAULT_N_SIMS,
    seed: int | None = None,
) -> pd.DataFrame:
    """Compute championship and conference-win probabilities from power ratings.

    Runs a Monte Carlo playoff bracket simulation using the fitted sigmoid model
    ``P = 1 / (1 + exp(-k * (r_home - r_away)))``.  Home court advantage (+2.5
    rating points) is applied automatically.

    Args:
        ratings: Power rating per team — ``{tricode: rating}``.  Higher is
            better.  Teams absent from the dict default to 0.0 (league average).
        playoff_seedings: Maps each playoff team's tricode to
            ``(conference, seed)`` where *conference* is ``"East"`` or ``"West"``
            and *seed* is 1–8.  Must cover exactly the 16 playoff teams.
        bracket_state: Optional known series results (e.g. from
            ``get_playoff_bracket_state()``).  Completed series are locked in;
            in-progress series simulate only remaining games.
        n_sims: Number of Monte Carlo trials (default 10 000).
        seed: Optional RNG seed for reproducibility.

    Returns:
        DataFrame with one row per playoff team and columns:

        - *tricode*
        - *conference*
        - *seed*
        - *rating* — input power rating
        - *champ_pct* — probability of winning the NBA championship
        - *conf_champ_pct* — probability of winning the conference (reaching Finals)
        - *mean_po_wins* — mean playoff games won
    """
    tricodes = list(playoff_seedings.keys())
    n_teams = len(tricodes)
    team_idx = {tc: i for i, tc in enumerate(tricodes)}

    # Build seeds and total_wins arrays (broadcast to n_sims)
    seeds_1 = np.zeros(n_teams, dtype=np.int32)
    for tc, (_, s) in playoff_seedings.items():
        seeds_1[team_idx[tc]] = s
    seeds = np.tile(seeds_1[:, None], (1, n_sims))

    # total_wins not used when ratings are provided, but the array is required
    total_wins = np.zeros((n_teams, n_sims), dtype=np.float32)

    # Build ratings array indexed by global team index
    ratings_arr = np.array([ratings.get(tc, 0.0) for tc in tricodes], dtype=np.float32)

    east_teams = [team_idx[tc] for tc, (conf, _) in playoff_seedings.items() if conf == "East"]
    west_teams = [team_idx[tc] for tc, (conf, _) in playoff_seedings.items() if conf == "West"]

    rng = np.random.default_rng(seed)
    playoff_wins, champion, east_champion, west_champion = simulate_playoffs(
        east_teams=east_teams,
        west_teams=west_teams,
        seeds=seeds,
        total_wins=total_wins,
        n_teams=n_teams,
        n_sims=n_sims,
        rng=rng,
        ratings=ratings_arr,
        bracket_state=bracket_state,
        team_idx=team_idx,
    )

    champ_pct = np.bincount(champion, minlength=n_teams).astype(np.float64) / n_sims
    east_conf_pct = np.bincount(east_champion, minlength=n_teams).astype(np.float64) / n_sims
    west_conf_pct = np.bincount(west_champion, minlength=n_teams).astype(np.float64) / n_sims
    conf_champ_pct = east_conf_pct + west_conf_pct

    rows = []
    for tc in tricodes:
        i = team_idx[tc]
        conf, s = playoff_seedings[tc]
        rows.append(
            {
                "tricode": tc,
                "conference": conf,
                "seed": s,
                "rating": ratings.get(tc, 0.0),
                "champ_pct": float(champ_pct[i]),
                "conf_champ_pct": float(conf_champ_pct[i]),
                "mean_po_wins": float(playoff_wins[i].mean()),
            }
        )

    return pd.DataFrame(rows).sort_values(["conference", "seed"]).reset_index(drop=True)
