"""Schedule contract between the simulator core and its callers.

The core takes a schedule DataFrame with one row per game:

- ``game_id``, ``game_code``: NBA identifiers (``game_code`` is empty for TBD games)
- ``home_tricode``, ``away_tricode``: empty for TBD games
- ``home_score``, ``away_score``: final scores for completed games
- ``status``: :class:`GameStatus`
- ``status_text``: e.g. ``"Final/OT"``
- ``game_type``: :class:`GameType`
- ``series_game_text``, ``series_status_text``: NBA sublabels (e.g. ``"East Group A"``, ``"Neutral Site"``)
- ``game_subtype``: NBA's ``gameSubtype`` (``"in-season"`` for NBA Cup group games,
  ``"in-season-knockout"`` for knockouts)
- ``cup_round``: :class:`CupRound` value or None, from :func:`with_cup_rounds` (callers add it)
- ``home_win_prob``: optional market probability (e.g. FanDuel) for upcoming games

and, for regular-season simulations, a ``game_df`` of upcoming games to sample, with
``game_id``, ``game_code``, ``home_tricode``, ``away_tricode`` and ``home_win_prob``.

The enums mirror ``nba_wins_pool.types`` by name and value, so the app's
``NBAGameStatus`` / ``NBAGameType`` members compare equal to these.
"""

from enum import Enum, IntEnum

import pandas as pd

_CUP_GROUP_SUBTYPE = "in-season"
_CUP_KNOCKOUT_SUBTYPE = "in-season-knockout"


class GameStatus(IntEnum):
    PREGAME = 1
    INGAME = 2
    FINAL = 3


class GameType(str, Enum):
    PRESEASON = "Preseason"
    REGULAR_SEASON = "Regular Season"
    PLAY_IN = "Play-In"
    PLAYOFFS = "Playoffs"


class CupRound(str, Enum):
    GROUP = "group"
    QUARTERFINAL = "quarterfinal"
    SEMIFINAL = "semifinal"
    CHAMPIONSHIP = "championship"
    KNOCKOUT = "knockout"


_KNOCKOUT_ROUNDS = ((CupRound.CHAMPIONSHIP, 1), (CupRound.SEMIFINAL, 2), (CupRound.QUARTERFINAL, 4))
KNOCKOUT_GAMES = sum(n for _, n in _KNOCKOUT_ROUNDS)


def with_cup_rounds(schedule: pd.DataFrame) -> pd.DataFrame:
    """Copy of the full-season *schedule* with a ``cup_round`` column (:class:`CupRound` or None).

    Group and knockout games come from ``game_subtype``. Knockout rounds go by date: the
    last knockout game is the Championship, the two before it the semifinals, the four
    before those quarterfinals. With any other number of knockout games the rounds can't be
    told apart, so only the Championship (still the last) gets a round; the rest are
    :attr:`CupRound.KNOCKOUT`. Must see the whole season's knockout games, so call it
    before slicing.
    """
    out = schedule.copy()
    out["cup_round"] = None
    if "game_subtype" not in out.columns or out.empty:
        return out
    subtype = out["game_subtype"].fillna("").astype(str)
    out.loc[subtype == _CUP_GROUP_SUBTYPE, "cup_round"] = CupRound.GROUP
    knockouts = out.index[subtype == _CUP_KNOCKOUT_SUBTYPE]
    order = list(pd.to_datetime(out.loc[knockouts, "date_time"]).sort_values(ascending=False, kind="stable").index)
    if len(order) != KNOCKOUT_GAMES:
        out.loc[order, "cup_round"] = CupRound.KNOCKOUT
        out.loc[order[:1], "cup_round"] = CupRound.CHAMPIONSHIP
        return out
    for cup_round, n in _KNOCKOUT_ROUNDS:
        out.loc[order[:n], "cup_round"] = cup_round
        order = order[n:]
    return out


def cup_round_mask(schedule: pd.DataFrame, cup_round: CupRound) -> pd.Series:
    """Boolean mask of *schedule* rows in *cup_round* (all False without a ``cup_round`` column)."""
    if "cup_round" not in schedule.columns:
        return pd.Series(False, index=schedule.index)
    return schedule["cup_round"] == cup_round


def is_cup_championship(schedule: pd.DataFrame) -> pd.Series:
    """Boolean mask of NBA Cup Championship rows (``cup_round``, see :func:`with_cup_rounds`).

    The Championship doesn't count in the standings and is simulated with the Cup.
    """
    return cup_round_mask(schedule, CupRound.CHAMPIONSHIP)
