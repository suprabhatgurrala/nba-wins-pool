"""Shin de-vigging (utils/odds.py)."""

import pytest

from nba_wins_pool.utils.odds import american_to_implied, shin_devig


def test_american_to_implied():
    assert american_to_implied(-110) == pytest.approx(110 / 210)
    assert american_to_implied(150) == pytest.approx(0.4)


def test_even_market_splits_evenly():
    assert shin_devig([american_to_implied(-110)] * 2) == pytest.approx([0.5, 0.5])


def test_takes_more_of_the_vig_from_the_long_shot():
    yes, no = american_to_implied(-340), american_to_implied(270)  # DET to make the playoffs, 2026-27
    fair_yes, fair_no = shin_devig([yes, no])
    assert fair_yes + fair_no == pytest.approx(1.0)
    assert fair_yes == pytest.approx(0.7512, abs=1e-4)
    assert fair_yes > yes / (yes + no)


def test_many_outcomes_share_one_insider_fraction():
    raw = [american_to_implied(o) for o in (150, 250, 500, 900, 1400, 2500, 4000, 8000)]
    assert sum(raw) > 1.05  # a title-style market with a margin to remove
    fair = shin_devig(raw)
    assert sum(fair) == pytest.approx(1.0)
    assert fair == sorted(fair, reverse=True)
    # Relative to proportional, the favorite gains and the longest shot loses
    total = sum(raw)
    assert fair[0] > raw[0] / total and fair[-1] < raw[-1] / total


def test_several_winners():
    raw = [american_to_implied(o) for o in (-900, -400, -250, -150, 120, 200, 350, 700)]  # 4 of 8 advance
    fair = shin_devig(raw, n_winners=4)
    assert sum(fair) == pytest.approx(4.0)
    assert all(0 < p <= 1 for p in fair)


def test_no_overround_is_normalized():
    assert shin_devig([0.4, 0.4]) == pytest.approx([0.5, 0.5])
    assert shin_devig([0.0, 0.0]) == [0.0, 0.0]
    assert shin_devig([0.8]) == [1.0]
