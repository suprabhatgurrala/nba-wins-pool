"""Sportsbook odds → probabilities.

Every de-vigged probability in the app goes through :func:`shin_devig`, so game
moneylines, win totals, make-playoffs and futures all remove the book's margin the
same way.
"""

from collections.abc import Sequence
from math import sqrt

from scipy.optimize import brentq


def american_to_implied(odds: float) -> float:
    """Raw implied probability (vig included) of American odds."""
    return 100.0 / (odds + 100.0) if odds > 0 else -odds / (-odds + 100.0)


def _shin_probs(q: Sequence[float], total: float, z: float) -> list[float]:
    return [(sqrt(z * z + 4.0 * (1.0 - z) * p * p / total) - z) / (2.0 * (1.0 - z)) for p in q]


def shin_devig(raw: Sequence[float], n_winners: float = 1.0) -> list[float]:
    """Fair probabilities from one market's raw implied probabilities (Shin's method).

    Shin models a share *z* of the money as coming from bettors who know the outcome; the
    book protects itself by shading every price, long shots most (a winning long-shot bet
    costs it the most). Solving for the *z* that makes the fair probabilities sum to one
    takes more of the margin from long shots than proportional de-vigging (``raw / sum``),
    which leaves the favorite-longshot bias in. On the 2026-27 preseason title market
    (overround 23%), proportional gave OKC 23.9%, Shin 26.1%.

    Markets with several winners (four of eight teams reach the conference semis) are
    solved as one-winner shares of ``raw / n_winners``. A market with no overround (or
    under one) has nothing to remove beyond rescaling, so it's normalized proportionally.

    Args:
        raw: Raw implied probabilities of every outcome in the market (vig included).
        n_winners: How many outcomes win (the fair probabilities sum to this).

    Returns:
        Fair probabilities in the order of *raw*, each capped at 1.
    """
    q = [p / n_winners for p in raw]
    total = sum(q)
    if total <= 0:
        return [0.0] * len(q)
    if total <= 1.0 or len(q) < 2:
        return [min(1.0, p / total * n_winners) for p in q]

    def excess(z: float) -> float:
        return sum(_shin_probs(q, total, z)) - 1.0

    # At z = 0 the probabilities sum to √total > 1, and the sum falls as z grows
    z_max = 0.999
    if excess(z_max) > 0:
        return [min(1.0, p / total * n_winners) for p in q]
    z = brentq(excess, 0.0, z_max, xtol=1e-12)
    return [min(1.0, p * n_winners) for p in _shin_probs(q, total, z)]
