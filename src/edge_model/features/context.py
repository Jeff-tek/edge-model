"""Rest / congestion / motivation adjustments for totals (pure, stdlib-only).

All inputs derive from data you already have: Match history (dates) +
league tables computed from that history. No new API, no key.

Profit logic for O1.5 / U4.5 parlays:
  - short rest + congestion -> fewer goals -> downgrade overs, upgrade unders
  - dead-rubber late-season games -> rotation / low intensity -> flag to
    require extra edge on overs (caller decides; backtest applies small
    under-lean via prob delta)

API:
  days_rest / matches_in_window -> raw signals
  prob_adjustment(...) -> delta to add to model p(over) for the given line
  adjust_prob(...) -> clipped base + delta
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from edge_model.data.football_data import Match

TIRED_REST_DAYS = 3  # <= this counts as short rest
CONGESTION_WINDOW = 7
CONGESTION_COUNT = 3  # >= this many games in window counts as congested
LATE_SEASON_GP = 30  # big-5 leagues play 34-38; 30+ = run-in


@dataclass(frozen=True, slots=True)
class ContextSignals:
    home_rest: int | None
    away_rest: int | None
    home_congestion: int
    away_congestion: int
    dead_rubber: bool


def _team_dates(history: list[Match], team: str, before: date, league: str = "") -> list[date]:
    dates = [
        m.date
        for m in history
        if m.date < before and (m.home == team or m.away == team) and (not league or m.league == league)
    ]
    return sorted(dates)


def days_rest(team: str, fixture_date: date, history: list[Match], league: str = "") -> int | None:
    """Days since team's last game before fixture_date; None if unknown."""
    dates = _team_dates(history, team, fixture_date, league)
    if not dates:
        return None
    return (fixture_date - dates[-1]).days


def matches_in_window(
    team: str, fixture_date: date, history: list[Match], window_days: int = CONGESTION_WINDOW, league: str = ""
) -> int:
    """Games the team played in (fixture_date - window_days, fixture_date)."""
    return sum(1 for d in _team_dates(history, team, fixture_date, league) if (fixture_date - d).days <= window_days)


def league_points(history: list[Match], league: str) -> dict[str, tuple[int, int]]:
    """team -> (points, games) from history for one league."""
    out: dict[str, list[int]] = {}
    for m in history:
        if m.league != league:
            continue
        out.setdefault(m.home, [0, 0])
        out.setdefault(m.away, [0, 0])
        out[m.home][1] += 1
        out[m.away][1] += 1
        if m.home_goals > m.away_goals:
            out[m.home][0] += 3
        elif m.home_goals < m.away_goals:
            out[m.away][0] += 3
        else:
            out[m.home][0] += 1
            out[m.away][0] += 1
    return {t: (pts, gp) for t, (pts, gp) in out.items()}


def is_dead_rubber(home: str, away: str, fixture_date: date, history: list[Match], league: str) -> bool:
    """Late-season game where both sides are safe mid-table (low motivation)."""
    table = league_points([m for m in history if m.date < fixture_date], league)
    if home not in table or away not in table:
        return False
    (hp, hgp), (ap, agp) = table[home], table[away]
    if min(hgp, agp) < LATE_SEASON_GP:
        return False
    pts = sorted(p for p, _ in table.values())
    if len(pts) < 6:
        return False
    # both teams >8 clear of drop and >8 off the top -> nothing to play for
    return min(hp, ap) - pts[0] > 8 and pts[-1] - max(hp, ap) > 8


def signals_for(home: str, away: str, fixture_date: date, history: list[Match], league: str = "") -> ContextSignals:
    return ContextSignals(
        home_rest=days_rest(home, fixture_date, history, league),
        away_rest=days_rest(away, fixture_date, history, league),
        home_congestion=matches_in_window(home, fixture_date, history, CONGESTION_WINDOW, league),
        away_congestion=matches_in_window(away, fixture_date, history, CONGESTION_WINDOW, league),
        dead_rubber=is_dead_rubber(home, away, fixture_date, history, league) if league else False,
    )


def prob_adjustment(sig: ContextSignals) -> float:
    """Delta to add to p(over): tired/congested/dead-rubber -> unders lean."""
    delta = 0.0
    for rest in (sig.home_rest, sig.away_rest):
        if rest is not None and rest <= 2:
            delta -= 0.025
        elif rest == TIRED_REST_DAYS:
            delta -= 0.012
    if max(sig.home_congestion, sig.away_congestion) >= CONGESTION_COUNT:
        delta -= 0.015
    if sig.dead_rubber:
        delta -= 0.01
    return delta


def adjust_prob(base_prob: float, sig: ContextSignals) -> float:
    """Clipped base + context delta."""
    return min(max(base_prob + prob_adjustment(sig), 0.01), 0.99)
