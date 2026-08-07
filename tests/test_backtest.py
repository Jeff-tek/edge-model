"""Tests for the walk-forward backtest: parlay assembly, matchday accounting."""

from __future__ import annotations

import math
import random
from datetime import date, timedelta

import pytest

from edge_model.backtest.backtest import run_backtest
from edge_model.data.football_data import Match
from edge_model.model.dixon_coles import fit_model


def _match(day: int, league: str, home: str, away: str, h: int, a: int) -> Match:
    return Match(
        season="2526", league=league, date=date(2026, 1, 1) + timedelta(days=day),
        home=home, away=away, home_goals=h, away_goals=a,
        b365_over=None, b365_under=None, pinnacle_over=None, pinnacle_under=None,
    )


def _rpois(rng: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    limit, k, p = math.exp(-lam), 0, 1.0
    while p > limit:
        k += 1
        p *= rng.random()
    return k - 1


def _synthetic_league(weeks: int = 30, teams: int = 8) -> list[Match]:
    """Round-robin of `teams` teams, 4 matches per week, Poisson scores."""
    rng = random.Random(11)
    names = [f"T{i}" for i in range(teams)]
    matches: list[Match] = []
    day = 0
    for _ in range(weeks):
        for i in range(0, teams, 2):
            home, away = names[i], names[i + 1]
            matches.append(_match(day, "E0", home, away, _rpois(rng, 1.6), _rpois(rng, 1.0)))
        day += 7
    return matches


def test_run_backtest_tracks_matchday_counts() -> None:
    matches = _synthetic_league(weeks=40, teams=10)
    result = run_backtest(matches, stake_per_bet=50.0)
    # every recorded parlay implies >= MIN_LEGS qualifying legs that day
    assert result.feasible_matchdays <= result.qualifier_matchdays
    assert result.qualifier_matchdays >= result.n_parlays
    assert result.n_parlays >= 0
    assert result.stake_per_bet == 50.0
    if result.n_parlays:
        assert result.n_parlays == len(result.parlays)
        assert 0.0 <= result.parlay_hit_rate <= 1.0


def test_run_backtest_empty_input() -> None:
    result = run_backtest([])
    assert result.n_bets == 0
    assert result.n_parlays == 0
    assert result.feasible_matchdays == 0
    assert result.qualifier_matchdays == 0


def test_run_backtest_requires_valid_odds() -> None:
    matches = _synthetic_league(weeks=10, teams=8)
    with pytest.raises(ValueError):
        run_backtest(matches, book_odds={("over", 1.5): 1.0})


def test_fit_and_predict_smoke() -> None:
    matches = _synthetic_league(weeks=20, teams=8)
    model = fit_model(matches, max_iter=120)
    assert model.base_rate > 0
