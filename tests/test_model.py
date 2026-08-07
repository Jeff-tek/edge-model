"""Tests for the Dixon-Coles model: fit convergence, prediction sanity."""

from __future__ import annotations

import math
import random
from datetime import date, timedelta

import pytest

from edge_model.data.football_data import Match
from edge_model.model.dixon_coles import (
    expected_total,
    fit_model,
    p_over,
    p_under,
    score_matrix,
    tau_adjust,
)


def _rpois(rng: random.Random, lam: float) -> int:
    """Knuth's Poisson sampler (stdlib — random.Random has no poisson)."""
    if lam <= 0:
        return 0
    limit, k, p = math.exp(-lam), 0, 1.0
    while p > limit:
        k += 1
        p *= rng.random()
    return k - 1


def _match(day: int, home: str, away: str, h: int, a: int, league: str = "E0") -> Match:
    return Match(
        season="2526", league=league, date=date(2026, 1, 1) + timedelta(days=day),
        home=home, away=away, home_goals=h, away_goals=a,
        b365_over=None, b365_under=None, pinnacle_over=None, pinnacle_under=None,
    )


def test_tau_adjust_values() -> None:
    assert tau_adjust(1.0, 1.0, 0, 0, 0.05) == pytest.approx(1.0 - 0.05)
    assert tau_adjust(1.0, 1.0, 1, 0, 0.05) == pytest.approx(1.0 + 0.05)
    assert tau_adjust(1.0, 1.0, 0, 1, 0.05) == pytest.approx(1.0 + 0.05)
    assert tau_adjust(1.0, 1.0, 1, 1, 0.05) == pytest.approx(1.0 - 0.05)
    assert tau_adjust(2.0, 3.0, 2, 2, 0.05) == 1.0  # no correction for other scores


def test_score_matrix_is_normalized() -> None:
    rng = random.Random(42)
    matches = []
    for i in range(120):
        home, away = f"T{i % 10}", f"T{(i + 3) % 10}"
        # generate from a Poisson-ish process with home advantage
        lh, la = 1.5, 1.1
        matches.append(_match(i, home, away, _rpois(rng, lh), _rpois(rng, la)))
    model = fit_model(matches, max_iter=150)
    probs = score_matrix(model, "T0", "T1")
    total = sum(sp.prob for sp in probs)
    assert total == pytest.approx(1.0, abs=1e-6)
    # over + under must sum to 1 for any line
    assert p_over(model, "T0", "T1", 2.5) + p_under(model, "T0", "T1", 2.5) == pytest.approx(1.0)


def test_fit_recovers_strong_team_dominance() -> None:
    """A very strong home team should produce a higher expected total than a
    matchup of two weak teams, and its p_over should be larger."""
    rng = random.Random(7)
    matches: list[Match] = []
    for i in range(200):
        day = i // 4
        if i % 4 == 0:
            home, away, lh, la = "STRONG", "WEAK", 3.0, 0.8
        elif i % 4 == 1:
            home, away, lh, la = "WEAK", "STRONG", 0.8, 3.0
        elif i % 4 == 2:
            home, away, lh, la = "WEAK", "WEAK2", 1.0, 0.9
        else:
            home, away, lh, la = "STRONG", "STRONG2", 2.6, 2.4
        matches.append(_match(day, home, away, _rpois(rng, lh), _rpois(rng, la)))

    model = fit_model(matches, max_iter=400)
    assert expected_total(model, "STRONG", "WEAK") > expected_total(model, "WEAK", "WEAK2")
    assert p_over(model, "STRONG", "WEAK", 2.5) > p_over(model, "WEAK", "WEAK2", 2.5)


def test_fit_requires_matches() -> None:
    with pytest.raises(ValueError):
        fit_model([])


def test_home_advantage_raises_home_expectation() -> None:
    rng = random.Random(3)
    matches = [
        _match(i, f"H{i % 6}", f"A{i % 6}", _rpois(rng, 1.6), _rpois(rng, 1.1))
        for i in range(150)
    ]
    model = fit_model(matches, max_iter=300)
    assert model.gamma > 1.0
