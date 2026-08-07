"""Tests for the value layer: implied odds, de-vig, +EV filter, parlay assembly."""

from __future__ import annotations

import pytest

from edge_model.value.filter import (
    ALLOWED_MARKETS,
    Leg,
    assemble_parlay,
    devig,
    evaluate_leg,
    implied,
    is_allowed_market,
    is_playable_leg,
)


def test_implied() -> None:
    assert implied(2.0) == pytest.approx(0.5)
    assert implied(5.0) == pytest.approx(0.2)
    with pytest.raises(ValueError):
        implied(1.0)


def test_devig() -> None:
    # 1.91 / 1.91 is a classic ~4.7% margin pair; fair over = 0.5
    fair = devig(1.91, 1.91)
    assert fair == pytest.approx(0.5, abs=1e-9)
    # over priced shorter than under => fair over > 0.5
    assert devig(1.5, 2.5) > 0.6


def test_evaluate_leg_single_side_uses_raw_implied() -> None:
    leg = evaluate_leg(
        home="A", away="B", side="over", line=1.5,
        decimal_odds=1.2, over_prob=0.85,
    )
    assert leg.implied == pytest.approx(1 / 1.2)
    assert leg.fair_implied == pytest.approx(1 / 1.2)
    assert leg.edge == pytest.approx(0.85 - 1 / 1.2)


def test_evaluate_leg_devigs_when_both_sides_known() -> None:
    leg = evaluate_leg(
        home="A", away="B", side="over", line=1.5,
        decimal_odds=1.2, over_prob=0.85, other_side_odds=2.0,
    )
    expected_fair = devig(1.2, 2.0)
    assert leg.fair_implied == pytest.approx(expected_fair)
    assert leg.edge == pytest.approx(0.85 - expected_fair)


def test_allowed_markets_only_o15_and_u45() -> None:
    assert is_allowed_market("over", 1.5)
    assert is_allowed_market("under", 4.5)
    assert not is_allowed_market("under", 1.5)
    assert not is_allowed_market("over", 4.5)
    assert not is_allowed_market("over", 2.5)
    assert ("over", 1.5) in ALLOWED_MARKETS
    assert ("under", 4.5) in ALLOWED_MARKETS


def test_playable_leg_odds_bounds() -> None:
    base = dict(home="A", away="B", side="over", line=1.5, over_prob=0.85, other_side_odds=2.0)
    too_low = evaluate_leg(**base, decimal_odds=1.1)
    ok = evaluate_leg(**base, decimal_odds=1.2)
    too_high = evaluate_leg(**base, decimal_odds=1.3)
    assert not is_playable_leg(too_low)
    assert is_playable_leg(ok)
    assert not is_playable_leg(too_high)


def test_playable_leg_rejects_disallowed_market() -> None:
    leg = evaluate_leg(
        home="A", away="B", side="over", line=2.5,
        decimal_odds=1.2, over_prob=0.95, other_side_odds=1.8,
    )
    assert leg.edge > 0.05
    assert not is_playable_leg(leg)


def test_playable_leg_edge_threshold() -> None:
    leg = evaluate_leg(
        home="A", away="B", side="over", line=1.5,
        decimal_odds=1.2, over_prob=0.85, other_side_odds=2.0,
    )
    # 0.85 vs fair ~0.625 => edge ~0.225, playable at default 0.03
    assert is_playable_leg(leg)
    assert not is_playable_leg(leg, min_edge=0.5)


def _leg(home: str, odds: float, model_prob: float, edge: float) -> Leg:
    return Leg(
        home=home, away="X", side="over", line=1.5,
        decimal_odds=odds, model_prob=model_prob,
        fair_implied=model_prob - edge, edge=edge,
    )


def test_assemble_parlay_skips_when_fewer_than_min_legs() -> None:
    two = [_leg(f"H{i}", 1.2, 0.85, 0.05) for i in range(2)]
    assert assemble_parlay(two) is None


def test_assemble_parlay_picks_strongest_edges() -> None:
    legs = [
        _leg("H1", 1.2, 0.85, 0.05),
        _leg("H2", 1.25, 0.88, 0.09),
        _leg("H3", 1.2, 0.84, 0.04),
        _leg("H4", 1.25, 0.90, 0.11),
        _leg("H5", 1.15, 0.82, 0.02),
        _leg("H6", 1.2, 0.86, 0.06),
        _leg("H7", 1.15, 0.83, 0.03),
        _leg("H8", 1.25, 0.87, 0.08),
        _leg("H9", 1.2, 0.85, 0.05),
        _leg("H10", 1.2, 0.84, 0.04),
    ]
    parlay = assemble_parlay(legs)
    assert parlay is not None
    assert len(parlay.legs) >= 8
    assert parlay.legs[0].edge >= parlay.legs[-1].edge
    assert parlay.combined_odds >= 5.0
    assert parlay.model_prob > 0
    assert parlay.ev > 0


def test_assemble_parlay_cannot_reach_target_returns_none() -> None:
    # 8 legs at 1.15 => 1.15^8 = 3.06 < 5.0, so skip
    legs = [_leg(f"H{i}", 1.15, 0.83, 0.05) for i in range(10)]
    assert assemble_parlay(legs) is None


def test_assemble_parlay_one_leg_per_match() -> None:
    a = Leg(home="A", away="B", side="over", line=1.5,
            decimal_odds=1.2, model_prob=0.85, fair_implied=0.80, edge=0.05)
    b = Leg(home="A", away="B", side="under", line=4.5,
            decimal_odds=1.2, model_prob=0.86, fair_implied=0.80, edge=0.06)
    rest = [_leg(f"T{i}", 1.2, 0.85, 0.05) for i in range(9)]
    parlay = assemble_parlay([a, b, *rest])
    assert parlay is not None
    same_match = [leg for leg in parlay.legs if (leg.home, leg.away) == ("A", "B")]
    assert len(same_match) == 1


def test_assemble_parlay_respects_edge_threshold() -> None:
    legs = [_leg(f"H{i}", 1.2, 0.85, 0.05) for i in range(10)]
    assert assemble_parlay(legs, min_edge=0.5) is None
