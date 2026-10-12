"""Simulate the NBA Play-In Tournament for seeds 7-10 in each conference.

Play-In structure (per conference):

  Game A: No. 7 hosts No. 8  - winner earns the conference 7-seed
  Game B: No. 9 hosts No. 10 - loser is eliminated
  Game C: loser(A) hosts winner(B) - winner earns the conference 8-seed, loser eliminated

Win probability model (priority order):

1. **FanDuel moneyline odds** — when available for a specific game (live odds for
   a game in progress), the market-derived ``home_win_prob`` is used directly.
   Game C is only priced once Games A and B are played, so its odds apply only
   in simulations with that matchup.
2. **Power ratings** — the home team's probability comes
   from :func:`.game_probability.home_win_probability` with the play-in/playoff
   home court (:data:`.constants.PLAYOFF_HOME_COURT_ADVANTAGE_POINTS`), the same
   formula the playoff series use. Ratings are required; a ``ValueError`` is
   raised if they are absent.

Partial results: when real play-in games have already been played, pass a
``ConferencePlayInResults`` for each conference to ``compute_play_in_results``.
Known outcomes override the probabilistic simulation for the relevant games.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from nba_wins_pool.services.nba_simulator.core.constants import PLAYOFF_HOME_COURT_ADVANTAGE_POINTS
from nba_wins_pool.services.nba_simulator.core.game_probability import home_win_probability, ratings_for


@dataclass
class ConferencePlayInResults:
    """Known outcomes for completed play-in games in one conference.

    Set each field to the tricode of the winner.  ``None`` means the game has
    not been played yet and will be simulated.

    Attributes:
        game_a_winner: Winner of the No. 7 vs No. 8 game — earns the 7-seed.
        game_b_winner: Winner of the No. 9 vs No. 10 game — advances to Game C.
        game_c_winner: Winner of loser(A) vs winner(B) — earns the 8-seed.
    """

    game_a_winner: str | None = None
    game_b_winner: str | None = None
    game_c_winner: str | None = None


def _rating_prob(home_rating: np.ndarray, away_rating: np.ndarray) -> np.ndarray:
    """Home team's win probability in a play-in game (higher seed hosts)."""
    return home_win_probability(home_rating, away_rating, home_court=PLAYOFF_HOME_COURT_ADVANTAGE_POINTS)


def simulate_play_in_conference(
    conf_team_arr: np.ndarray,
    seeds: np.ndarray,
    rng: np.random.Generator,
    n_sims: int,
    ratings: np.ndarray,
    game_a_winner_idx: int | None = None,
    game_b_winner_idx: int | None = None,
    game_c_winner_idx: int | None = None,
    p_a_override: float | None = None,
    p_b_override: float | None = None,
    game_c_odds: tuple[int, int, float] | None = None,
    wins_out: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Simulate play-in outcomes for one conference across all simulations.

    When a winner index is provided for a game, that outcome is used instead of
    sampling.  Random numbers are always pre-drawn so reproducibility is
    unaffected by whether results are known or not.

    Args:
        conf_team_arr: Global team indices for this conference, shape ``(n_conf_teams,)``.
        seeds: Conference seeds array, shape ``(n_teams, n_sims)``.
        rng: RNG instance (three ``rng.random`` calls are made unconditionally).
        n_sims: Number of simulations.
        ratings: float32 array of shape ``(n_teams,)`` with each team's power
            rating indexed by global team index, or ``(n_teams, n_sims)`` when ratings
            are offset per simulation.  Win probabilities are derived from rating
            differences via the logistic model.  Required.
        game_a_winner_idx: Global index of the team that won Game A, or ``None``.
        game_b_winner_idx: Global index of the team that won Game B, or ``None``.
        game_c_winner_idx: Global index of the team that won Game C, or ``None``.
        p_a_override: FanDuel-derived home-team win probability for Game A
            (No. 7 vs No. 8).  Takes priority over power ratings when set.
        p_b_override: FanDuel-derived home-team win probability for Game B
            (No. 9 vs No. 10).  Takes priority over power ratings when set.
        game_c_odds: ``(home_idx, away_idx, home_win_prob)`` FanDuel odds for a Game C
            matchup. Used in the simulations where loser(A) hosts winner(B) with
            exactly those teams.
        wins_out: Optional ``(n_teams, n_sims)`` array; each play-in game's winner
            gets +1 in the simulations where the play-in ran.

    Returns:
        ``(seed7_teams, seed8_teams)`` - int32 arrays of shape ``(n_sims,)`` holding
        the global team index that earned each seed.  A value of ``-1`` means the
        play-in could not be run for that simulation (fewer than 10 conference teams
        or a seed 7-10 slot was vacant).
    """
    conf_seeds = seeds[conf_team_arr, :]  # (n_conf_teams, n_sims)

    def _team_at_seed(k: int) -> tuple[np.ndarray, np.ndarray]:
        """Global team index and validity mask for teams holding seed *k*."""
        mask = conf_seeds == k  # (n_conf_teams, n_sims)
        valid = mask.any(axis=0)
        row_idx = np.argmax(mask, axis=0)
        return conf_team_arr[row_idx], valid

    t7, v7 = _team_at_seed(7)
    t8, v8 = _team_at_seed(8)
    t9, v9 = _team_at_seed(9)
    t10, v10 = _team_at_seed(10)

    valid = v7 & v8 & v9 & v10  # (n_sims,) - True when all four seeds exist

    # Always pre-draw random numbers — keeps reproducibility regardless of
    # whether known results override the outcome.
    rand_a = rng.random(n_sims)
    rand_b = rng.random(n_sims)
    rand_c = rng.random(n_sims)

    # Game A: No. 7 vs No. 8 - winner earns the 7-seed
    # Priority: FanDuel override > power ratings
    if p_a_override is not None:
        p_a = np.full(n_sims, p_a_override)
    else:
        p_a = _rating_prob(ratings_for(ratings, t7), ratings_for(ratings, t8))

    # Game B: No. 9 vs No. 10 - loser eliminated
    if p_b_override is not None:
        p_b = np.full(n_sims, p_b_override)
    else:
        p_b = _rating_prob(ratings_for(ratings, t9), ratings_for(ratings, t10))

    if game_a_winner_idx is not None:
        # seed-7 team wins iff they ARE the known winner; fall back to sim where
        # neither bracket participant matches (shouldn't occur in practice).
        home_is_winner = t7 == game_a_winner_idx
        neither_a = (t7 != game_a_winner_idx) & (t8 != game_a_winner_idx)
        game_a_7_wins = np.where(neither_a, rand_a < p_a, home_is_winner)
    else:
        game_a_7_wins = rand_a < p_a

    seed7_team = np.where(game_a_7_wins, t7, t8)
    loser_a = np.where(game_a_7_wins, t8, t7)

    if game_b_winner_idx is not None:
        home_is_winner = t9 == game_b_winner_idx
        neither_b = (t9 != game_b_winner_idx) & (t10 != game_b_winner_idx)
        game_b_9_wins = np.where(neither_b, rand_b < p_b, home_is_winner)
    else:
        game_b_9_wins = rand_b < p_b

    winner_b = np.where(game_b_9_wins, t9, t10)

    # Game C: loser(A) vs winner(B) - winner earns the 8-seed
    rating_loser_a = ratings_for(ratings, np.where(game_a_7_wins, t8, t7))
    rating_winner_b = ratings_for(ratings, np.where(game_b_9_wins, t9, t10))
    p_c = _rating_prob(rating_loser_a, rating_winner_b)
    if game_c_odds is not None:
        c_home, c_away, c_prob = game_c_odds
        p_c = np.where((loser_a == c_home) & (winner_b == c_away), c_prob, p_c)

    if game_c_winner_idx is not None:
        home_is_winner = loser_a == game_c_winner_idx
        neither_c = (loser_a != game_c_winner_idx) & (winner_b != game_c_winner_idx)
        game_c_loser_a_wins = np.where(neither_c, rand_c < p_c, home_is_winner)
    else:
        game_c_loser_a_wins = rand_c < p_c

    seed8_team = np.where(game_c_loser_a_wins, loser_a, winner_b)

    if wins_out is not None:
        sims = np.nonzero(valid)[0]
        for winner in (seed7_team, winner_b, seed8_team):  # Games A, B, C
            np.add.at(wins_out, (winner[valid], sims), 1.0)

    # Replace results for invalid simulations with sentinel -1
    seed7_out = np.where(valid, seed7_team, -1).astype(np.int32)
    seed8_out = np.where(valid, seed8_team, -1).astype(np.int32)

    return seed7_out, seed8_out


def compute_play_in_results(
    east_teams: list[int],
    west_teams: list[int],
    seeds: np.ndarray,
    n_teams: int,
    n_sims: int,
    rng: np.random.Generator,
    power_ratings: dict[str, float],
    team_idx: dict[str, int],
    play_in_results: dict[str, ConferencePlayInResults] | None = None,
    fanduel_game_probs: dict[tuple[str, str], float] | None = None,
    wins_out: np.ndarray | None = None,
    rating_offsets: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Run play-in simulation for both conferences and accumulate per-team results.

    Args:
        east_teams: Global indices of East conference teams.
        west_teams: Global indices of West conference teams.
        seeds: ``(n_teams, n_sims)`` int32 conference seed per team per sim.
        n_teams: Total number of teams.
        n_sims: Number of simulations.
        rng: Shared RNG (three calls per conference).
        power_ratings: Dict mapping tricode -> power rating.  Required;
            raises ``ValueError`` if empty.  Teams absent from the dict are
            assigned 0.0 (league average).
        team_idx: Tricode -> global index mapping.
        play_in_results: Optional dict mapping ``"East"`` / ``"West"`` to a
            ``ConferencePlayInResults`` with known game outcomes.  ``None`` means
            all games are simulated.
        fanduel_game_probs: Optional dict mapping ``(home_tricode, away_tricode)``
            to the home team's win probability derived from FanDuel moneyline odds.
            When present for a game, these take priority over power ratings.
            For Game C, the priced pair of a 7/8 seed hosting a 9/10 seed is used
            in the simulations with that matchup.
        wins_out: Optional ``(n_teams, n_sims)`` array accumulating play-in game
            wins per team (they count toward pool wins).
        rating_offsets: Optional ``(n_teams, n_sims)`` per-simulation rating offsets,
            indexed like *team_idx* (see :class:`.game_probability.RatingOffsets`).

    Returns:
        ``(play_in_7, play_in_8)`` - float32 arrays of shape ``(n_teams, n_sims)``.
        Each entry is ``1.0`` if the team earned that play-in seed in the simulation,
        ``0.0`` otherwise.
    """
    if not power_ratings:
        raise ValueError("Power ratings are required for play-in simulation but were not provided.")

    # Convert tricode -> rating dict into an index-aligned array.
    # Teams missing from power_ratings default to 0.0 (league average).
    ratings = np.zeros(n_teams, dtype=np.float32)
    for tricode, val in power_ratings.items():
        if tricode in team_idx:
            ratings[team_idx[tricode]] = val
    if rating_offsets is not None:
        ratings = ratings[:, None] + rating_offsets

    # Build a reverse mapping for FanDuel lookup (global index -> tricode).
    idx_to_tricode: dict[int, str] = {}
    if fanduel_game_probs:
        idx_to_tricode = {v: k for k, v in team_idx.items()}

    play_in_7 = np.zeros((n_teams, n_sims), dtype=np.float32)
    play_in_8 = np.zeros((n_teams, n_sims), dtype=np.float32)

    conf_map = {"East": east_teams, "West": west_teams}

    for conf, conf_teams in conf_map.items():
        known = play_in_results.get(conf) if play_in_results else None

        def _resolve(tricode: str | None) -> int | None:
            if tricode is None or team_idx is None:
                return None
            return team_idx.get(tricode)

        game_a_idx = _resolve(known.game_a_winner) if known else None
        game_b_idx = _resolve(known.game_b_winner) if known else None
        game_c_idx = _resolve(known.game_c_winner) if known else None

        # Resolve FanDuel per-game win probabilities for Games A and B.
        # Seeds are deterministic in play-in phase, so seeds[:, 0] is authoritative.
        p_a_override: float | None = None
        p_b_override: float | None = None
        game_c_odds: tuple[int, int, float] | None = None
        if fanduel_game_probs and idx_to_tricode:
            seed_by_global: dict[int, int] = {gi: int(seeds[gi, 0]) for gi in conf_teams}
            tricode_at: dict[int, str] = {
                seed_val: idx_to_tricode[gi] for gi, seed_val in seed_by_global.items() if gi in idx_to_tricode
            }
            t7_tc = tricode_at.get(7)
            t8_tc = tricode_at.get(8)
            t9_tc = tricode_at.get(9)
            t10_tc = tricode_at.get(10)
            if t7_tc and t8_tc:
                p_a_override = fanduel_game_probs.get((t7_tc, t8_tc))
            if t9_tc and t10_tc:
                p_b_override = fanduel_game_probs.get((t9_tc, t10_tc))
            # Game C: loser(A) (a 7/8 seed) hosts winner(B) (a 9/10 seed)
            for home_tc in (t7_tc, t8_tc):
                for away_tc in (t9_tc, t10_tc):
                    prob = fanduel_game_probs.get((home_tc, away_tc)) if home_tc and away_tc else None
                    if prob is not None:
                        game_c_odds = (team_idx[home_tc], team_idx[away_tc], prob)

        conf_arr = np.array(conf_teams, dtype=np.int32)
        s7, s8 = simulate_play_in_conference(
            conf_arr,
            seeds,
            rng,
            n_sims,
            ratings,
            game_a_winner_idx=game_a_idx,
            game_b_winner_idx=game_b_idx,
            game_c_winner_idx=game_c_idx,
            p_a_override=p_a_override,
            p_b_override=p_b_override,
            game_c_odds=game_c_odds,
            wins_out=wins_out,
        )

        # Scatter seed-7 results: play_in_7[team, sim] = 1
        valid7 = s7 >= 0
        if valid7.any():
            valid_s7 = np.where(valid7)[0]
            play_in_7[s7[valid7], valid_s7] = 1.0

        # Scatter seed-8 results
        valid8 = s8 >= 0
        if valid8.any():
            valid_s8 = np.where(valid8)[0]
            play_in_8[s8[valid8], valid_s8] = 1.0

    return play_in_7, play_in_8
