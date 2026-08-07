"""Tests for the dashboard JSON generator (network-free)."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from edge_model.backtest.backtest import BacktestResult, BetRecord, ParlayRecord
from edge_model.dashboard.generate import (
    _backtest_section,
    _fixture_section,
    _paper_section,
    _past_tips,
    _strategy_section,
    _tips_section,
    _weekly_pl,
    build_payload,
    write_payload,
)
from edge_model.data.football_data import Match
from edge_model.model.dixon_coles import TeamModel
from edge_model.track.paper import PaperBook
from edge_model.value.filter import (
    MAX_LEG_ODDS,
    MAX_LEGS,
    MIN_EDGE,
    MIN_LEG_ODDS,
    MIN_LEGS,
    TARGET_PARLAY_ODDS,
    Leg,
    Parlay,
)


def _model() -> TeamModel:
    return TeamModel(
        attack={"Arsenal": 1.4, "Chelsea": 1.0, "Bayern": 1.3, "Bremen": 0.9},
        defense={"Arsenal": 0.8, "Chelsea": 1.0, "Bayern": 0.7, "Bremen": 1.2},
        gamma=1.25,
        rho=0.05,
        base_rate=1.3,
        fitted_date=date(2026, 8, 1),
    )


def _match(day: int, home: str, away: str, h: int, a: int) -> Match:
    return Match(
        season="2526",
        league="E0",
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


def _leg(home: str, away: str, edge: float) -> tuple[Leg, str]:
    leg = Leg(
        home=home,
        away=away,
        side="over",
        line=1.5,
        decimal_odds=1.22,
        model_prob=0.8,
        fair_implied=0.8 - edge,
        edge=edge,
    )
    return (leg, "E0")


def _parlay() -> Parlay:
    legs = tuple(leg for leg, _ in [_leg("Arsenal", "Chelsea", 0.06), _leg("Bayern", "Bremen", 0.05)])
    combined = 1.0
    for leg in legs:
        combined *= leg.decimal_odds
    model_prob = 1.0
    for leg in legs:
        model_prob *= leg.model_prob
    return Parlay(legs=legs, combined_odds=combined, model_prob=model_prob, stake=100.0)


def _paper(tmp_path: Path) -> PaperBook:
    book = PaperBook(tmp_path / "trades.csv")
    book.append(sport="football", league="E0", home="Arsenal", away="Chelsea",
                side="over", line=1.5, odds=1.22, stake=100.0)
    book.append(sport="football", league="E0", home="Bayern", away="Bremen",
                side="under", line=4.5, odds=1.12, stake=100.0)
    book.settle("Arsenal", "Chelsea", actual_total=3)
    book.settle("Bayern", "Bremen", actual_total=1)  # under 4.5 wins
    return book


def test_strategy_section_constants() -> None:
    strat = _strategy_section()
    assert strat["markets"] == [["over", 1.5], ["under", 4.5]]
    assert strat["leg_odds_window"] == [MIN_LEG_ODDS, MAX_LEG_ODDS]
    assert strat["target_parlay_odds"] == TARGET_PARLAY_ODDS
    assert strat["min_legs"] == MIN_LEGS
    assert strat["max_legs"] == MAX_LEGS
    assert strat["min_edge"] == MIN_EDGE
    assert strat["flat_book_odds"] == {"over:1.5": 1.22, "under:4.5": 1.12}


def test_backtest_section_maps_result_fields() -> None:
    bets = (
        BetRecord(date=date(2026, 1, 8), league="E0", home="A", away="B", side="over",
                  line=1.5, odds=1.22, model_prob=0.8, edge=0.05, actual_total=3, won=True),
        BetRecord(date=date(2026, 1, 8), league="E0", home="C", away="D", side="under",
                  line=4.5, odds=1.12, model_prob=0.9, edge=0.04, actual_total=1, won=False),
    )
    parlays = (
        ParlayRecord(date=date(2026, 1, 8), legs=bets, combined_odds=1.37,
                     model_prob=0.72, stake=100.0, won=False),
    )
    result = BacktestResult(
        bets=bets, parlays=parlays, stake_per_bet=100.0,
        qualifier_matchdays=5, feasible_matchdays=2,
    )
    section = _backtest_section(result, n_matches=5256, leagues=["E0"], seasons=["2526"])
    assert section["matches"] == 5256
    assert section["parlays"] == 1
    assert section["parlay_wins"] == 0
    assert section["parlay_hit_rate"] == 0.0
    assert section["legs"] == 2
    assert section["leg_hit_rate"] == pytest.approx(0.5)
    assert section["feasible_matchdays"] == 2
    assert section["matchdays_with_qualifier"] == 5
    assert section["side_hit_rates"]["over"]["hit_rate"] == pytest.approx(1.0)
    assert section["side_hit_rates"]["under"]["hit_rate"] == pytest.approx(0.0)
    assert section["calibration"] == [{"bin_low": 0.8, "actual": 0.5, "n": 2}]


def test_paper_section_and_weekly_pl(tmp_path: Path) -> None:
    paper = _paper(tmp_path)
    section = _paper_section(paper, starting=2000.0)
    assert section["bankroll"] == pytest.approx(2000.0 + 122.0 + 112.0 - 200.0)
    assert section["net_pl"] == pytest.approx(34.0)
    assert section["hit_rate"] == pytest.approx(1.0)
    assert section["settled_bets"] == 2
    assert section["win_streak"]["kind"] == "wins"
    assert section["paused"] is False
    assert len(section["bankroll_series"]) == 2
    assert len(section["recent_trades"]) == 2
    weeks = _weekly_pl(paper)
    assert len(weeks) == 1
    assert weeks[0]["pl"] == pytest.approx(34.0)


def test_past_tips_groups_by_day(tmp_path: Path) -> None:
    paper = _paper(tmp_path)
    tips = _past_tips(paper)
    assert len(tips) == 1
    assert tips[0]["legs"] == 2
    assert tips[0]["won"] is True
    assert tips[0]["status"] == "bet"
    assert tips[0]["combined_odds"] == pytest.approx(round(1.22 * 1.12, 2), rel=1e-6)


def test_fixture_section_computes_model_and_edges() -> None:
    model = _model()
    fixtures = _fixture_section(model, [("E0", "Arsenal", "Chelsea", {"line": 2.5, "over": 1.22, "under": 1.60}), ("SP1", "Unknown", "Side", {"line": None, "over": None, "under": None})])
    assert len(fixtures) == 2
    entry = fixtures[0]
    assert entry["league"] == "E0"
    assert entry["totals_odds"]["over"] == 1.22
    assert 0.0 < entry["model"]["over1.5"] < 1.0
    assert 0.0 < entry["model"]["under4.5"] < 1.0
    # a 0.03 edge threshold means the qualifies flag must be a boolean list
    assert isinstance(entry["qualifies"], list)
    # unknown teams: model should not raise and stays in [0, 1]
    unknown = fixtures[1]
    assert 0.0 <= unknown["model"]["over1.5"] <= 1.0


def test_tips_no_bet_when_few_legs(tmp_path: Path) -> None:
    paper = PaperBook(tmp_path / "trades.csv")
    legs = [_leg("Arsenal", "Chelsea", 0.06)]  # 1 leg < MIN_LEGS
    tips = _tips_section(legs, parlay=None, paper=paper)
    assert tips["status"] == "no_bet"
    assert tips["parlay"] is None
    assert "qualifying legs" in tips["no_bet_reason"]
    assert len(tips["candidate_legs"]) == 1


def test_tips_bet_with_parlay(tmp_path: Path) -> None:
    paper = PaperBook(tmp_path / "trades.csv")
    legs = [_leg("Arsenal", "Chelsea", 0.06)] * MIN_LEGS
    parlay = _parlay()
    tips = _tips_section(legs, parlay=parlay, paper=paper)
    assert tips["status"] == "bet"
    assert tips["parlay"] is not None
    assert tips["parlay"]["combined_odds"] == pytest.approx(round(1.22 * 1.22, 2), rel=1e-6)
    assert tips["no_bet_reason"] is None


def test_tips_paused(tmp_path: Path) -> None:
    paper = PaperBook(tmp_path / "trades.csv")
    for i in range(5):
        paper.append(sport="football", league="E0", home=f"H{i}", away="B",
                     side="over", odds=1.5, stake=100.0)
        paper.settle(f"H{i}", "B", actual_total=1.0)  # all losses
    tips = _tips_section([], parlay=None, paper=paper)
    assert tips["status"] == "paused"
    assert tips["parlay"] is None


def test_build_payload_full_structure(tmp_path: Path) -> None:
    paper = _paper(tmp_path)
    matches = [_match(i, "Arsenal", "Chelsea", 2, 1) for i in range(3)]
    payload = build_payload(
        matches=matches,
        backtest_result=None,
        model=_model(),
        legs=[_leg("Arsenal", "Chelsea", 0.06)],
        parlay=None,
        paper=paper,
        starting_bankroll=2000.0,
        fixture_teams=[("E0", "Arsenal", "Chelsea", {"line": 2.5, "over": 1.22, "under": 1.60})],
    )
    for key in ("generated_at", "as_of_date", "strategy", "backtest", "paper", "fixtures", "tips"):
        assert key in payload
    assert payload["backtest"]["matches"] == 3
    assert payload["fixtures"][0]["league"] == "E0"


def test_build_payload_reuses_backtest_dict(tmp_path: Path) -> None:
    paper = _paper(tmp_path)
    payload = build_payload(
        matches=[],
        backtest_result=None,
        model=_model(),
        legs=[],
        parlay=None,
        paper=paper,
        starting_bankroll=2000.0,
        backtest_dict={"parlays": 42, "parlay_wins": 9, "roi": 0.1},
    )
    assert payload["backtest"]["parlays"] == 42
    assert payload["backtest"]["roi"] == 0.1


def test_write_payload_roundtrip(tmp_path: Path) -> None:
    paper = _paper(tmp_path)
    payload = build_payload(
        matches=[],
        backtest_result=None,
        model=_model(),
        legs=[],
        parlay=None,
        paper=paper,
        starting_bankroll=2000.0,
    )
    out = tmp_path / "data.json"
    write_payload(payload, out)
    loaded = json.loads(out.read_text())
    assert loaded["strategy"]["min_legs"] == MIN_LEGS
    assert loaded["tips"]["status"] == "no_bet"
