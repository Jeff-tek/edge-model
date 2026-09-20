"""Tests for offline xG table + blend (pure, no network)."""

from __future__ import annotations

import pytest

from edge_model.data.xg import (
    XgTeam,
    blend_prob,
    get_xg,
    parse_xg_csv,
    xg_lambdas,
    xg_p_over,
)

CSV = """league,team,gp,xg_for,xg_against
E0,Arsenal,10,22.0,9.0
E0,Chelsea,10,15.0,14.0
"""


def test_parse_xg_csv() -> None:
    table = parse_xg_csv(CSV)
    assert table[("E0", "Arsenal")].gp == 10
    assert table[("E0", "Arsenal")].xg_for_per == pytest.approx(2.2)


def test_get_xg_falls_back_to_league_agnostic() -> None:
    table = parse_xg_csv("team,xg_for,xg_against\nArsenal,20.0,10.0\n")
    assert get_xg(table, "E0", "Arsenal") is not None
    assert get_xg(table, "E0", "Missing") is None


def test_xg_lambdas_positive_and_home_higher() -> None:
    home = XgTeam(league="E0", team="H", gp=10, xg_for=20.0, xg_against=10.0)
    away = XgTeam(league="E0", team="A", gp=10, xg_for=12.0, xg_against=12.0)
    lh, la = xg_lambdas(home, away)
    assert lh > 0 and la > 0
    assert lh > la


def test_xg_p_over_sane_range() -> None:
    home = XgTeam(league="E0", team="H", gp=10, xg_for=22.0, xg_against=9.0)
    away = XgTeam(league="E0", team="A", gp=10, xg_for=15.0, xg_against=14.0)
    p15 = xg_p_over(home, away, 1.5)
    p45 = xg_p_over(home, away, 4.5)
    assert 0.0 < p45 < p15 < 1.0


def test_blend_prob_weights() -> None:
    assert blend_prob(0.8, 0.6) == pytest.approx(0.8 * 0.65 + 0.6 * 0.35)
    assert blend_prob(0.8, 0.6, 0.0) == pytest.approx(0.8)
    assert blend_prob(0.8, 0.6, 1.0) == pytest.approx(0.6)
    with pytest.raises(ValueError):
        blend_prob(0.8, 0.6, 1.5)
