"""Simulate the NBA Cup and the regular-season games whose matchups depend on it.

Rules: https://www.nba.com/news/nba-cup-101

Every team plays 82 regular-season games, but only 80 have opponents when the schedule
is released. The rest are decided by the Cup:

- Group stage: 4 games per team, scheduled like any other regular-season game.
- Knockouts: the 3 group winners and 1 wild card per conference play quarterfinals
  (1v4, 2v3, higher seed hosts). QF winners play a semifinal, SF winners play the
  Championship.
- QF losers in each conference play each other. The 22 non-advancing teams play two
  games against each other: 20 within conference, 2 cross-conference, and no team
  plays both of its games cross-conference.
- QF, SF and those filler games count in the standings. The Championship doesn't (it is
  a finalist's 83rd game), but it does count toward pool wins.

Until those matchups are set, the schedule lists the games with blank teams (or leaves
them out entirely), so the main simulation can't sample them. ``simulate_cup`` fills the
gap: in every simulation it ranks the groups, plays out the bracket, and tops each team up
to 82 games. Games already on the schedule with both teams set are never re-simulated;
their outcomes come from the main simulation (or the final score).

Cup games are identified by the schedule's ``cup_round`` (:func:`.schedule.with_cup_rounds`,
from NBA's ``gameSubtype``), not by labels or game IDs: labels have moved between fields
every season, and nothing guarantees the IDs. Groups are found from who plays whom (every
pair in a group meets once, and groups don't overlap); labels only name them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.special import log_expit, logit

from nba_wins_pool.services.nba_simulator.core.calibration import build_ratings_array
from nba_wins_pool.services.nba_simulator.core.constants import (
    REGULAR_SEASON_HOME_COURT_ADVANTAGE_POINTS,
    SPREAD_TO_WIN_PROB_K,
)
from nba_wins_pool.services.nba_simulator.core.game_probability import (
    RatingOffsets,
    home_win_probability,
    per_sim_home_prob,
    per_sim_ratings,
    ratings_for,
    remaining_fraction,
)
from nba_wins_pool.services.nba_simulator.core.playoff_seeding import load_team_metadata
from nba_wins_pool.services.nba_simulator.core.schedule import (
    CupRound,
    GameStatus,
    GameType,
    cup_round_mask,
    is_cup_championship,
)

logger = logging.getLogger(__name__)

REGULAR_SEASON_GAMES = 82

_KNOCKOUT_ROUNDS = {CupRound.QUARTERFINAL: "qf", CupRound.SEMIFINAL: "sf", CupRound.CHAMPIONSHIP: "final"}
_KNOCKOUT_LAYOUT = {"quarterfinal": 4, "semifinal": 2, "championship": 1}
_MARGIN_U_CLIP = 1e-4
_MIN_REMAINING = 6.0 / 2880.0  # 6 seconds: keeps the remaining-time noise above zero
_GROUP_NAME_RE = r"((?:East|West) Group [A-Z])"


def _home_court(hca: bool) -> float:
    # Cup games are regular-season games, so they use the regular-season home court
    return REGULAR_SEASON_HOME_COURT_ADVANTAGE_POINTS if hca else 0.0


@dataclass
class CupSimResult:
    """Output of :func:`simulate_cup`. Arrays are ``(n_teams, n_sims)`` indexed by ``all_tricodes``."""

    all_tricodes: list[str]
    standings_wins: np.ndarray  # wins from unscheduled games that count in the standings (QF/SF/filler)
    championship_wins: np.ndarray  # 1.0 where the team wins a Championship that hasn't been played yet
    added_games: np.ndarray  # standings games simulated here (scheduled games + these = 82)
    summary: pd.DataFrame  # tricode, conference, group, knockout_pct, semifinal_pct, final_pct, champ_pct

    def standings_wins_by_tricode(self) -> dict[str, np.ndarray]:
        return {tc: self.standings_wins[i] for i, tc in enumerate(self.all_tricodes)}

    def pool_wins_by_tricode(self) -> dict[str, np.ndarray]:
        total = self.standings_wins + self.championship_wins
        return {tc: total[i] for i, tc in enumerate(self.all_tricodes)}


def _has_teams(df: pd.DataFrame) -> pd.Series:
    return df["home_tricode"].fillna("").astype(bool) & df["away_tricode"].fillna("").astype(bool)


def margins_from_uniforms(
    home_win_prob: np.ndarray,
    uniforms: np.ndarray,
    current_margin: float | None = None,
    remaining: float = 1.0,
) -> np.ndarray:
    """Final home margins consistent with outcomes drawn as ``uniforms < home_win_prob``.

    The margin is logistic with scale ``1/k`` (``k`` = ``SPREAD_TO_WIN_PROB_K``), the
    distribution behind the win model. Before tip-off it's centered on ``logit(p) / k``:
    exactly the expected margin for a ratings game (``rating_margin``) and the implied
    spread for a market one, with sd ``π / (k·√3)`` ≈ 13.6 points. Then
    ``margin = (logit(p) - logit(u)) / k``.

    For a game in progress, pass the *current_margin* and the fraction of the game
    *remaining*: the final margin is centered on the current one, with the scale shrunk
    to ``√remaining / k`` (the noise of the minutes left). Its own win probability ``q``
    differs from the market's ``p``, so each uniform maps into the matching side: home
    wins (``u < p``) take the top ``q`` of the distribution, losses the bottom ``1 - q``.
    That reduces to the formula above before tip-off.

    Either way the margin is positive exactly when the main simulation recorded a home
    win, and at least one point (games can't end tied).
    """
    p = np.clip(np.asarray(home_win_prob, dtype=np.float64), 1e-6, 1 - 1e-6)
    # 1e-4 caps a blowout at ~73 points beyond the expected margin
    u = np.clip(np.asarray(uniforms, dtype=np.float64), _MARGIN_U_CLIP, 1 - _MARGIN_U_CLIP)
    if p.ndim == 1 and u.ndim == 2:
        p = p[:, None]
    home_won = u < p
    if current_margin is None:
        margin = (logit(p) - logit(u)) / SPREAD_TO_WIN_PROB_K
    else:
        scale = np.sqrt(max(remaining, _MIN_REMAINING)) / SPREAD_TO_WIN_PROB_K
        z = current_margin / scale  # the distribution's own win probability is expit(z)
        # log of the tail mass each uniform maps to, kept in logs so near-certain games stay finite
        log_tail = np.where(
            home_won,
            np.log(u / p) + log_expit(z),  # top (u/p)·q of the distribution
            np.log((1 - u) / (1 - p)) + log_expit(-z),  # bottom ((1-u)/(1-p))·(1-q)
        )
        logit_tail = log_tail - np.log1p(-np.exp(np.minimum(log_tail, -1e-12)))
        margin = current_margin + np.where(home_won, -scale * logit_tail, scale * logit_tail)
    return np.where(home_won, np.maximum(margin, 1.0), np.minimum(margin, -1.0))


@dataclass
class _KnownGame:
    home: int
    away: int
    winner: np.ndarray  # (n_sims,) team index
    counted: bool  # True when the win is already in completed results or the main simulation


class _CupSimulator:
    def __init__(
        self,
        schedule: pd.DataFrame,
        game_df: pd.DataFrame,
        home_wins_sim: np.ndarray,
        uniforms: np.ndarray,
        ratings: dict[str, float] | None,
        n_sims: int,
        rng: np.random.Generator,
        team_meta: dict[str, dict[str, str]],
        rating_offsets: RatingOffsets | None = None,
    ):
        self.schedule = schedule
        self.n_sims = n_sims
        self.rng = rng
        self.team_meta = team_meta
        self.all_tricodes = sorted(team_meta)
        self.team_idx = {t: i for i, t in enumerate(self.all_tricodes)}
        self.n_teams = len(self.all_tricodes)
        self.conf = np.array([team_meta[t]["conference"] for t in self.all_tricodes])
        # (n_teams,) or, with per-simulation rating offsets, (n_teams, n_sims)
        self.ratings = (
            per_sim_ratings(build_ratings_array(ratings, self.all_tricodes), self.all_tricodes, rating_offsets)
            if ratings
            else None
        )
        self.rating_offsets = rating_offsets
        self.sims = np.arange(n_sims)

        self.game_df = game_df
        self.home_wins_sim = home_wins_sim
        self.uniforms = uniforms
        self.game_row = {gid: i for i, gid in enumerate(game_df["game_id"])} if "game_id" in game_df.columns else {}

        self.standings_wins = np.zeros((self.n_teams, n_sims), dtype=np.float32)
        self.championship_wins = np.zeros((self.n_teams, n_sims), dtype=np.float32)
        self.extra_games = np.zeros((self.n_teams, n_sims), dtype=np.int32)
        # Listed home games so far (the NBA balances everyone to 41; fillers are hosted toward that)
        self.home_games = np.repeat(self._listed_home_games()[:, None], n_sims, axis=1)
        self.reached = {k: np.zeros((self.n_teams, n_sims), dtype=np.bool_) for k in ("qf", "sf", "final", "champ")}

    # -- probabilities ---------------------------------------------------

    def _ratings_or_raise(self) -> np.ndarray:
        if self.ratings is None:
            raise ValueError("Power ratings are required to simulate NBA Cup games without scheduled matchups.")
        return self.ratings

    def _sample_winner(self, home: np.ndarray, away: np.ndarray, hca: bool) -> np.ndarray:
        r = self._ratings_or_raise()
        p = home_win_probability(ratings_for(r, home), ratings_for(r, away), home_court=_home_court(hca))
        return np.where(self.rng.random(self.n_sims) < p, home, away)

    def _add_win(self, target: np.ndarray, winner: np.ndarray, mask: np.ndarray) -> None:
        np.add.at(target, (winner[mask], self.sims[mask]), 1.0)

    # -- scheduled games -------------------------------------------------

    def _scheduled_outcome(self, row: pd.Series, hca: bool) -> tuple[np.ndarray, np.ndarray]:
        """(home_won bool, home margin) per sim for a schedule row with both teams set."""
        if row["status"] == GameStatus.FINAL:
            home_won = np.full(self.n_sims, row["home_score"] > row["away_score"])
            # Overtime games count as 0 toward group-stage point differential. The schedule
            # feed has no period, so also check the status text ("Final/OT", "Final/2OT").
            overtime = (row.get("period") or 0) > 4 or "OT" in str(row.get("status_text") or "")
            margin = 0.0 if overtime else float(row["home_score"] - row["away_score"])
            return home_won, np.full(self.n_sims, margin)
        i = self.game_row.get(row["game_id"])
        if i is not None:
            prob = float(self.game_df["home_win_prob"].iloc[i])
            per_sim = self.rating_offsets is not None and "rating_margin" in self.game_df
            if per_sim and pd.notna(self.game_df["rating_margin"].iloc[i]):
                # Ratings-based game under per-simulation ratings: the outcome used each sim's probability
                prob = per_sim_home_prob(self.game_df, np.array([i]), self.rating_offsets)[0]
            return self.home_wins_sim[i] > 0.5, self._margins(row, prob, self.uniforms[i])
        # Missing from the main simulation (it samples every unfinished game, so this is a fallback)
        h, a = self.team_idx[row["home_tricode"]], self.team_idx[row["away_tricode"]]
        r = self._ratings_or_raise()
        hca = hca and not bool(row.get("is_neutral") or False)
        prob = home_win_probability(
            ratings_for(r, np.full(self.n_sims, h)),
            ratings_for(r, np.full(self.n_sims, a)),
            home_court=_home_court(hca),
        )
        u = self.rng.random(self.n_sims)
        return u < prob, self._margins(row, prob, u)

    def _margins(self, row: pd.Series, prob, uniforms: np.ndarray) -> np.ndarray:
        """Final margins for an unfinished game: from tip-off, or from the live score when in progress."""
        if row["status"] != GameStatus.INGAME or pd.isna(row.get("home_score")) or pd.isna(row.get("away_score")):
            return margins_from_uniforms(prob, uniforms)
        if int(row.get("period") or 0) > 4:
            # Already in overtime, which counts 0 toward point differential
            return np.zeros(self.n_sims)
        return margins_from_uniforms(
            prob,
            uniforms,
            current_margin=float(row["home_score"] - row["away_score"]),
            remaining=remaining_fraction(row.get("period"), row.get("game_clock")),
        )

    def _known_ko_games(self) -> list[_KnownGame]:
        known: list[_KnownGame] = []
        rounds = self.schedule["cup_round"].map(_KNOCKOUT_ROUNDS) if "cup_round" in self.schedule else None
        if rounds is None:
            return known
        for i, row in self.schedule[rounds.notna()].iterrows():
            rnd = rounds[i]
            h, a = self.team_idx.get(row["home_tricode"]), self.team_idx.get(row["away_tricode"])
            if h is None or a is None:  # TBD slot
                continue
            if rnd == "final" and row["status"] != GameStatus.FINAL:
                # The Championship is excluded from the main simulation, so sample it here
                prob = row.get("home_win_prob")
                if pd.notna(prob):
                    winner = np.where(self.rng.random(self.n_sims) < float(prob), h, a)
                else:
                    winner = self._sample_winner(np.full(self.n_sims, h), np.full(self.n_sims, a), hca=False)
                known.append(_KnownGame(h, a, winner, counted=False))
                continue
            home_won, _ = self._scheduled_outcome(row, hca=True)
            known.append(_KnownGame(h, a, np.where(home_won, h, a), counted=True))
        return known

    # -- bracket ---------------------------------------------------------

    def _play(
        self, home: np.ndarray, away: np.ndarray, hca: bool, known: list[_KnownGame], *, is_final: bool = False
    ) -> tuple[np.ndarray, np.ndarray]:
        """Play a knockout game per sim. Returns (winner, loser)."""
        winner = np.full(self.n_sims, -1)
        counted = np.zeros(self.n_sims, dtype=np.bool_)
        for g in known:
            m = ((home == g.home) & (away == g.away)) | ((home == g.away) & (away == g.home))
            if m.any():
                winner[m] = g.winner[m]
                counted[m] = g.counted
        unknown = winner < 0
        if unknown.any():
            winner[unknown] = self._sample_winner(home, away, hca)[unknown]
        loser = np.where(winner == home, away, home)
        unscheduled = ~counted
        if is_final:
            self._add_win(self.championship_wins, winner, unscheduled)
        else:
            self._add_win(self.standings_wins, winner, unscheduled)
            np.add.at(self.extra_games, (home[unscheduled], self.sims[unscheduled]), 1)
            np.add.at(self.extra_games, (away[unscheduled], self.sims[unscheduled]), 1)
            np.add.at(self.home_games, (home[unscheduled], self.sims[unscheduled]), 1)
        return winner, loser

    def _group_keys(self) -> tuple[np.ndarray, np.ndarray, dict[int, str]] | None:
        """Ranking keys per team per sim: (group key with H2H, cross-group key without H2H, group names)."""
        group_rows = self.schedule[
            cup_round_mask(self.schedule, CupRound.GROUP)
            & _has_teams(self.schedule)
            & (self.schedule["game_type"] == GameType.REGULAR_SEASON)
        ]
        if group_rows.empty:
            return None

        group_of = self._group_names(group_rows)
        wins = np.zeros((self.n_teams, self.n_sims), dtype=np.float64)
        pt_diff = np.zeros((self.n_teams, self.n_sims), dtype=np.float64)
        outcomes = []
        for _, row in group_rows.iterrows():
            h, a = self.team_idx.get(row["home_tricode"]), self.team_idx.get(row["away_tricode"])
            if h is None or a is None:
                continue
            home_won, margin = self._scheduled_outcome(row, hca=True)
            wins[h] += home_won
            wins[a] += ~home_won
            pt_diff[h] += margin
            pt_diff[a] -= margin
            outcomes.append((h, a, home_won))

        # Head-to-head among teams tied on wins. Each pair meets once, so the win count
        # against tied teams ranks them the same as the win pct.
        h2h = np.zeros_like(wins)
        for h, a, home_won in outcomes:
            same = wins[h] == wins[a]
            h2h[h] += same & home_won
            h2h[a] += same & ~home_won

        # Remaining tiebreakers (total points, prior-season record) fall through to a random draw.
        pd_term = np.clip(pt_diff, -499, 499) + 500
        draw = self.rng.random((self.n_teams, self.n_sims)) * 0.5
        group_key = wins * 1e4 + h2h * 1e3 + pd_term + draw
        cross_key = wins * 1e4 + pd_term + draw
        return group_key, cross_key, group_of

    def _group_names(self, group_rows: pd.DataFrame) -> dict[int, str]:
        """Team index -> group name. Groups are the connected teams in *group_rows*.

        Named from the NBA label ("East Group A") when the games carry one, else by
        conference and order ("East Group 1").
        """
        parent = list(range(self.n_teams))

        def root(t: int) -> int:
            while parent[t] != t:
                parent[t] = parent[parent[t]]
                t = parent[t]
            return t

        labels: dict[int, str] = {}
        text = (
            group_rows.reindex(columns=["series_game_text", "series_status_text"])
            .fillna("")
            .astype(str)
            .agg(" ".join, axis=1)
            .str.extract(_GROUP_NAME_RE, expand=False)
        )
        for i, row in group_rows.iterrows():
            h, a = self.team_idx.get(row["home_tricode"]), self.team_idx.get(row["away_tricode"])
            if h is None or a is None:
                continue
            parent[root(h)] = root(a)
            if pd.notna(text[i]):
                labels[h] = labels[a] = text[i]

        teams = pd.concat([group_rows["home_tricode"], group_rows["away_tricode"]])
        members: dict[int, list[int]] = {}
        for t in sorted({self.team_idx[tc] for tc in teams if tc in self.team_idx}):
            members.setdefault(root(t), []).append(t)

        names: dict[int, str] = {}
        counter: dict[str, int] = {}
        for group in sorted(members.values()):
            conf = self.conf[group[0]]
            label = next((labels[t] for t in group if t in labels), None)
            if label is None:
                counter[conf] = counter.get(conf, 0) + 1
                label = f"{conf} Group {counter[conf]}"
            for t in group:
                names[t] = label
        return names

    def _simulate_conference_bracket(
        self, conf: str, group_key: np.ndarray, cross_key: np.ndarray, groups: dict[str, list[int]], known
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Returns (sf_winner, qf_loser_a, qf_loser_b, loser_a_seed, loser_b_seed) per sim.

        Seeds come from the schedule's quarterfinals once the NBA has set them (see
        :meth:`_scheduled_seeds`), else from this simulation's group standings.
        """
        seeds = self._scheduled_seeds(conf, cross_key)
        if seeds is None:
            firsts, seconds = [], []
            for name in sorted(g for g in groups if conf in g):
                members = np.array(groups[name])
                order = np.argsort(-group_key[members], axis=0)
                firsts.append(members[order[0]])
                seconds.append(members[order[1]])
            firsts_arr, seconds_arr = np.stack(firsts), np.stack(seconds)

            wild_card = seconds_arr[np.argmax(cross_key[seconds_arr, self.sims], axis=0), self.sims]
            seed_order = np.argsort(-cross_key[firsts_arr, self.sims], axis=0)
            s1, s2, s3 = (firsts_arr[seed_order[k], self.sims] for k in range(3))
        else:
            s1, s2, s3, wild_card = seeds

        for team in (s1, s2, s3, wild_card):
            self.reached["qf"][team, self.sims] = True
        win_a, lose_a = self._play(s1, wild_card, hca=True, known=known)
        win_b, lose_b = self._play(s2, s3, hca=True, known=known)

        # Seeds 1/4 play seeds 2/3, so the 1/4 winner is the higher seed only when it's the 1 seed
        sf_home = np.where(win_a == s1, win_a, win_b)
        sf_away = np.where(win_a == s1, win_b, win_a)
        for team in (win_a, win_b):
            self.reached["sf"][team, self.sims] = True
        sf_winner, _ = self._play(sf_home, sf_away, hca=not self._sf_neutral(), known=known)
        self.reached["final"][sf_winner, self.sims] = True
        return sf_winner, lose_a, lose_b, np.where(lose_a == s1, 1, 4), np.where(lose_b == s2, 2, 3)

    def _scheduled_seeds(
        self, conf: str, cross_key: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None:
        """``(seed 1, seed 2, seed 3, wild card)`` per sim from the conference's scheduled quarterfinals.

        None until both quarterfinals have teams. The NBA's own bracket beats ours: we skip
        two of its tiebreakers (total points, prior-season record), and a different pairing
        would play an imaginary quarterfinal next to the real one. The higher seed hosts, and
        the rows carry seeds 1-4; without them, the two hosts are ordered by *cross_key*.
        """
        qf = self.schedule[cup_round_mask(self.schedule, CupRound.QUARTERFINAL) & _has_teams(self.schedule)]
        games = []
        for _, row in qf.iterrows():
            h, a = self.team_idx.get(row["home_tricode"]), self.team_idx.get(row["away_tricode"])
            if h is not None and a is not None and self.conf[h] == conf:
                games.append((h, a, row.get("home_seed"), row.get("away_seed")))
        if len(games) != 2:
            return None

        def full(t: int) -> np.ndarray:
            return np.full(self.n_sims, t)

        by_seed = {}
        for h, a, hs, as_ in games:
            for team, seed in ((h, hs), (a, as_)):
                if pd.notna(seed):
                    by_seed[int(seed)] = team
        if sorted(by_seed) == [1, 2, 3, 4] and {by_seed[1], by_seed[4]} in ({g[0], g[1]} for g in games):
            return full(by_seed[1]), full(by_seed[2]), full(by_seed[3]), full(by_seed[4])

        # No seeds on the rows: keep the real pairings, rank the two hosts ourselves
        (h1, a1, *_), (h2, a2, *_) = games
        first = cross_key[h1] >= cross_key[h2]
        return (
            np.where(first, h1, h2),
            np.where(first, h2, h1),
            np.where(first, a2, a1),
            np.where(first, a1, a2),
        )

    def _knockout_layout(self) -> dict[str, int]:
        rounds = self.schedule["cup_round"] if "cup_round" in self.schedule else pd.Series(dtype=object)
        counts = rounds.dropna().map(lambda r: CupRound(r).value).value_counts()
        return {r: int(n) for r, n in counts.items() if r != CupRound.GROUP.value}

    def _sf_neutral(self) -> bool:
        sf = self.schedule[cup_round_mask(self.schedule, CupRound.SEMIFINAL)]
        if "is_neutral" in sf and sf["is_neutral"].fillna(False).astype(bool).any():
            return True
        text = sf.get("series_status_text")
        return text is not None and text.fillna("").astype(str).str.contains("Neutral").any()

    # -- filler games ----------------------------------------------------

    def _listed_home_games(self) -> np.ndarray:
        """Home games per team among scheduled regular-season games with both teams set (the
        Championship excluded). Before the Cup every team has 40 of its 80."""
        sched = self.schedule
        rs = sched[(sched["game_type"] == GameType.REGULAR_SEASON) & ~is_cup_championship(sched) & _has_teams(sched)]
        counts = rs["home_tricode"].value_counts()
        return np.array([counts.get(t, 0) for t in self.all_tricodes], dtype=np.int32)

    def _host(self, a: np.ndarray, b: np.ndarray, a_first: np.ndarray | bool = True) -> tuple[np.ndarray, np.ndarray]:
        """(home, away) per sim: the team with fewer home games hosts, toward 41 each; ties go
        to *a* where *a_first*. That reproduces the NBA's Cup fillers (2023-24 through 2025-26):
        every non-advancing team gets one home and one road game, and the quarterfinal loser
        who played on the road hosts the other (the higher seed when both did)."""
        ha, hb = self.home_games[a, self.sims], self.home_games[b, self.sims]
        a_hosts = (ha < hb) | ((ha == hb) & a_first)
        return np.where(a_hosts, a, b), np.where(a_hosts, b, a)

    def _deficits(self) -> np.ndarray:
        sched = self.schedule
        rs = sched[(sched["game_type"] == GameType.REGULAR_SEASON) & ~is_cup_championship(sched) & _has_teams(sched)]
        counts = pd.concat([rs["home_tricode"], rs["away_tricode"]]).value_counts()
        known = np.array([counts.get(t, 0) for t in self.all_tricodes], dtype=np.int32)
        return np.maximum(REGULAR_SEASON_GAMES - known[:, None] - self.extra_games, 0)

    def _play_filler(
        self, a: np.ndarray, b: np.ndarray, mask: np.ndarray, deficit: np.ndarray, a_first: np.ndarray | bool = True
    ) -> None:
        """Regular-season game between a and b in the sims where mask is set, hosted by :meth:`_host`."""
        if not mask.any():
            return
        home, away = self._host(a, b, a_first)
        winner = self._sample_winner(home, away, hca=True)
        self._add_win(self.standings_wins, winner, mask)
        np.add.at(self.home_games, (home[mask], self.sims[mask]), 1)
        np.subtract.at(deficit, (a[mask], self.sims[mask]), 1)
        np.subtract.at(deficit, (b[mask], self.sims[mask]), 1)

    def _random_order(self, members: np.ndarray, pool: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Randomly order pool members per sim (pool first). Returns (order (n, n_sims), pool size)."""
        keys = self.rng.random((len(members), self.n_sims)) + (~pool) * 2.0
        return members[np.argsort(keys, axis=0)], pool.sum(axis=0)

    def _schedule_eliminated_teams(self, deficit: np.ndarray, standings_key: np.ndarray | None = None) -> None:
        """Two games each for the teams that didn't advance, per the NBA Cup rules.

        The rules: 2 of the 22 games are cross-conference, between bottom-finishing teams in
        Group Play, with no team playing more than one; the other 20 are within conference.

        Per simulation and conference, the teams needing two games form a random path in
        which each team plays its neighbors. The two lowest-ranked by *standings_key* (the
        cross-group key: wins, then point differential; random without one) are the path's
        ends, so they're the ones with a game left, and play cross-conference by rank: 15th
        vs 15th, 14th vs 14th, the 2023-24 through 2025-26 pattern. That's 20 within-conference
        and 2 cross-conference games, nobody playing two cross.

        The rules also pair within-conference teams otherwise scheduled to meet three times.
        That isn't modeled: restricting the path to those pairs moved no team's mean wins by
        more than simulation noise (max 0.08 vs 0.10 between seeds, 2026-27 preseason, 50k
        sims), since they're an arbitrary set of non-division opponents, and it needed a
        per-simulation search.

        Each path team hosts the next (:meth:`_host` breaks the tie that way), so a path start
        has had its home game and a path end hasn't. East's path runs from 15th to 14th and
        West's from 14th to 15th, so each cross game pairs a start with an end, and everyone
        gets one home and one road game.
        """
        orders, sizes, ends = {}, {}, {}
        for conf in ("East", "West"):
            members = np.where(self.conf == conf)[0]
            pool = deficit[members] == 2
            key = standings_key[members] if standings_key is not None else self.rng.random(pool.shape)
            worst = np.argsort(np.where(pool, key, np.inf), axis=0, kind="stable")
            last, second_last = worst[0], worst[1]
            start, end = (last, second_last) if conf == "East" else (second_last, last)
            # Sort keys: start first, then the rest of the pool in random order, end last, others after
            keys = 1.0 + self.rng.random(pool.shape) + (~pool) * 10.0
            keys[start, self.sims] = 0.0
            keys[end, self.sims] = 3.0
            order = members[np.argsort(keys, axis=0)]
            orders[conf], sizes[conf] = order, pool.sum(axis=0)
            ends[conf] = (members[last], members[second_last])
        ok = (sizes["East"] >= 2) & (sizes["West"] >= 2)

        for conf in ("East", "West"):
            order, k = orders[conf], sizes[conf]
            for p in range(order.shape[0] - 1):
                self._play_filler(order[p], order[p + 1], ok & (p + 1 < k), deficit)

        (east_15, east_14), (west_15, west_14) = ends["East"], ends["West"]
        self._play_filler(east_15, west_15, ok, deficit)
        self._play_filler(east_14, west_14, ok, deficit)

    def _fill_leftovers(self, deficit: np.ndarray) -> None:
        """Any games still missing go against a random same-conference team that also needs games."""
        for t in range(self.n_teams):
            members = np.where((self.conf == self.conf[t]) & (np.arange(self.n_teams) != t))[0]
            while (deficit[t] > 0).any():
                need = deficit[t] > 0
                order, k = self._random_order(members, deficit[members] > 0)
                # Fall back to any conference opponent when no one else needs a game
                opp = np.where(k > 0, order[0], members[self.rng.integers(len(members), size=self.n_sims)])
                home, away = self._host(np.full(self.n_sims, t), opp)
                winner = self._sample_winner(home, away, hca=True)
                self._add_win(self.standings_wins, winner, need & (winner == t))
                np.add.at(self.home_games, (home[need], self.sims[need]), 1)
                deficit[t] -= need

    # -- entry -----------------------------------------------------------

    def run(self) -> CupSimResult:
        known = self._known_ko_games()
        bracket = self._group_keys()
        groups: dict[str, list[int]] = {}
        if bracket is None:
            logger.warning("NBA Cup groups not found in schedule; filling Cup-dependent games without a bracket")
        else:
            for team, name in bracket[2].items():
                groups.setdefault(name, []).append(team)
            if sorted(len(m) for m in groups.values()) != [5] * 6:
                logger.warning("Unexpected NBA Cup group layout %s; skipping bracket simulation", groups)
                bracket = None
            elif (layout := self._knockout_layout()) != _KNOCKOUT_LAYOUT:
                logger.warning("Unexpected NBA Cup knockout games %s; skipping bracket simulation", layout)
                bracket = None

        qf_losers: list[tuple[np.ndarray, ...]] = []
        if bracket is not None:
            group_key, cross_key, _ = bracket
            east_w, *east_l = self._simulate_conference_bracket("East", group_key, cross_key, groups, known)
            west_w, *west_l = self._simulate_conference_bracket("West", group_key, cross_key, groups, known)
            qf_losers = [tuple(east_l), tuple(west_l)]
            champ, _ = self._play(east_w, west_w, hca=False, known=known, is_final=True)
            self.reached["champ"][champ, self.sims] = True
        else:
            # A scheduled Championship still counts toward pool wins
            for g in known:
                if not g.counted:
                    self._add_win(self.championship_wins, g.winner, np.ones(self.n_sims, dtype=np.bool_))
                    self.reached["champ"][g.winner, self.sims] = True

        deficit = self._deficits()
        initial_deficit = deficit.copy()
        for lose_a, lose_b, seed_a, seed_b in qf_losers:
            both = (deficit[lose_a, self.sims] > 0) & (deficit[lose_b, self.sims] > 0)
            self._play_filler(lose_a, lose_b, both, deficit, a_first=seed_a < seed_b)
        if (deficit == 2).any():
            self._schedule_eliminated_teams(deficit, bracket[1] if bracket is not None else None)
        if (deficit > 0).any():
            self._fill_leftovers(deficit)

        summary = pd.DataFrame(
            {
                "tricode": self.all_tricodes,
                "conference": self.conf,
                "group": [bracket[2].get(i) if bracket else None for i in range(self.n_teams)],
                "knockout_pct": self.reached["qf"].mean(axis=1),
                "semifinal_pct": self.reached["sf"].mean(axis=1),
                "final_pct": self.reached["final"].mean(axis=1),
                "champ_pct": self.reached["champ"].mean(axis=1),
            }
        )
        added_games = self.extra_games + (initial_deficit - deficit)
        return CupSimResult(self.all_tricodes, self.standings_wins, self.championship_wins, added_games, summary)


def has_cup(schedule: pd.DataFrame) -> bool:
    """True when the schedule contains the NBA Cup Championship (2023-24 onward)."""
    return not schedule.empty and bool(is_cup_championship(schedule).any())


def simulate_cup(
    schedule: pd.DataFrame,
    game_df: pd.DataFrame,
    home_wins_sim: np.ndarray,
    uniforms: np.ndarray,
    ratings: dict[str, float] | None,
    n_sims: int,
    seed: int | None = None,
    team_meta: dict[str, dict[str, str]] | None = None,
    rating_offsets: RatingOffsets | None = None,
) -> CupSimResult | None:
    """Simulate the NBA Cup bracket and every regular-season game it decides.

    Args:
        schedule: Full season schedule from ``data.get_nba_schedule()``.
        game_df: Games sampled by the main simulation (``game_probabilities()`` output).
        home_wins_sim: ``(n_games, n_sims)`` main-simulation outcomes, aligned with *game_df*.
        uniforms: ``(n_games, n_sims)`` uniforms that produced *home_wins_sim*, used to
            sample group-stage margins consistent with those outcomes.
        ratings: Tricode → power rating for games without scheduled matchups. Only
            required when such games remain.
        n_sims: Number of simulations.
        seed: Optional RNG seed.
        team_meta: Optional tricode → ``{conference, division}``.
        rating_offsets: Optional per-simulation rating offsets, the same the main simulation used.

    Returns:
        :class:`CupSimResult`, or ``None`` when the season has no Cup.
    """
    if not has_cup(schedule):
        return None
    sim = _CupSimulator(
        schedule,
        game_df,
        home_wins_sim,
        uniforms,
        ratings,
        n_sims,
        np.random.default_rng(seed),
        team_meta or load_team_metadata(),
        rating_offsets=rating_offsets,
    )
    return sim.run()
