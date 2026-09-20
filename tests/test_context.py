"""Tests for rest / congestion / dead-rubber context adjustments."""

from __future__ import annotations

from datetime import date, timedelta

from edge_model.data.football_data import Match
from edge_model.features.context import (
    adjust_prob,
    days_rest,
    is_dead_rubber,
    league_points,
    matches_in_window,
    prob_adjustment,
    signals_for,
)


def _match(day: int, home: str, away: str, h: int = 1, a: int = 1, league: str = "E0") -> Match:
    return Match(
        season="2526",
        league=league,
        date=date(2026, 1, 1) + timedelta(days=day),
        home=home,
        away=away,
        home_goals=h,
        away_goals=a,
        b365_over=None,
        b365_under=None,
        pinnacle_over=None,
        pinnacle_under=None,
    )


def test_days_rest_none_without_history() -> None:
    assert days_rest("Arsenal", date(2026, 2, 1), []) is None


def test_days_rest_counts_calendar_gap() -> None:
    hist = [_match(0, "Arsenal", "Chelsea"), _match(10, "Arsenal", "Spurs")]
    assert days_rest("Arsenal", date(2026, 1, 13), hist) == 2


def test_congestion_counts_window() -> None:
    hist = [_match(0, "A", "B"), _match(2, "A", "C"), _match(5, "A", "D")]
    assert matches_in_window("A", date(2026, 1, 7), hist) == 3


def test_tired_short_rest_downgrades_over() -> None:
    hist = [_match(0, "H", "X"), _match(9, "H", "Y")]
    fixture = date(2026, 1, 11)  # 1 day rest for H
    sig = signals_for("H", "A", fixture, hist)
    assert prob_adjustment(sig) < 0.0
    assert adjust_prob(0.80, sig) < 0.80


def test_fresh_teams_no_adjustment() -> None:
    hist = [_match(0, "H", "X"), _match(0, "A", "Y")]
    sig = signals_for("H", "A", date(2026, 1, 20), hist)
    assert prob_adjustment(sig) == 0.0
    assert adjust_prob(0.80, sig) == 0.80


def test_dead_rubber_needs_late_season_and_midtable() -> None:
    assert is_dead_rubber("H", "A", date(2026, 1, 10), [], "E0") is False
    # early season: never dead rubber even if table exists
    hist = [_match(0, "H", "A", 1, 1)]
    assert is_dead_rubber("H", "A", date(2026, 1, 10), hist, "E0") is False


def test_league_points_counts() -> None:
    hist = [_match(0, "H", "A", 2, 0), _match(1, "A", "H", 1, 1)]
    table = league_points(hist, "E0")
    assert table["H"] == (4, 2)
    assert table["A"] == (1, 2)
