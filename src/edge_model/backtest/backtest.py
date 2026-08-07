"""Walk-forward simulation of the O1.5/U4.5 parlay strategy.

football-data.co.uk publishes odds only for the 2.5 line, so the 1.5/4.5
markets must be simulated at a flat assumed price. Each week the model is
refit on all history; every match in the window yields an O1.5 and a U4.5
candidate priced per-market at `BOOK_ODDS`. A leg is playable when model prob
beats the de-vigged fair implied probability
(book_odds * (1 + book_margin)) by at least `min_edge`. Each matchday then
gets one parlay (greedy by edge, one leg per match) targeting 5.0+ combined
odds; the parlay is recorded as won iff every leg won.

The per-side prices are calibrated to observed base rates
(P(O1.5) ~ 77.6% -> fair ~1.289; P(U4.5) ~ 84.4% -> fair ~1.185) minus a
typical bookmaker margin, so the simulated book is roughly realistic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from edge_model.data.football_data import Match
from edge_model.model.dixon_coles import fit_model, p_over
from edge_model.value.filter import (
    MAX_LEGS,
    MIN_LEGS,
    TARGET_PARLAY_ODDS,
    is_allowed_market,
)

# Per-market simulated flat book prices and overrounds (football-data.co.uk
# has no 1.5/4.5 odds historically, so we assume a realistic flat price per
# market: 1.22 on O1.5, 1.12 on U4.5, with a ~4-5% two-way margin).
BOOK_ODDS: dict[tuple[str, float], float] = {("over", 1.5): 1.22, ("under", 4.5): 1.12}
BOOK_MARGIN: dict[tuple[str, float], float] = {("over", 1.5): 0.04, ("under", 4.5): 0.05}
WINDOW_DAYS = 7
MIN_EDGE = 0.03
OVERS = (("over", 1.5), ("under", 4.5))


@dataclass(frozen=True, slots=True)
class BetRecord:
    date: date
    league: str
    home: str
    away: str
    side: str  # "over" | "under"
    line: float
    odds: float
    model_prob: float
    edge: float
    actual_total: int
    won: bool


@dataclass(frozen=True, slots=True)
class ParlayRecord:
    date: date
    legs: tuple[BetRecord, ...]
    combined_odds: float
    model_prob: float
    stake: float
    won: bool


@dataclass(frozen=True, slots=True)
class BacktestResult:
    bets: tuple[BetRecord, ...]
    parlays: tuple[ParlayRecord, ...]
    stake_per_bet: float
    qualifier_matchdays: int = 0  # days with >= 1 qualifying leg
    feasible_matchdays: int = 0  # days with >= MIN_LEGS qualifying legs

    @property
    def n_bets(self) -> int:
        return len(self.bets)

    @property
    def wins(self) -> int:
        return sum(1 for b in self.bets if b.won)

    @property
    def hit_rate(self) -> float:
        return self.wins / self.n_bets if self.n_bets else 0.0

    @property
    def n_parlays(self) -> int:
        return len(self.parlays)

    @property
    def parlay_wins(self) -> int:
        return sum(1 for p in self.parlays if p.won)

    @property
    def parlay_hit_rate(self) -> float:
        return self.parlay_wins / self.n_parlays if self.n_parlays else 0.0

    @property
    def roi(self) -> float:
        """Return on investment of the parlay book (fraction of stake won/lost)."""
        if not self.parlays:
            return 0.0
        total_staked = self.n_parlays * self.stake_per_bet
        total_returned = sum(
            (p.combined_odds * self.stake_per_bet) if p.won else 0.0 for p in self.parlays
        )
        return (total_returned - total_staked) / total_staked

    @property
    def net_profit(self) -> float:
        total_staked = self.n_parlays * self.stake_per_bet
        total_returned = sum(
            (p.combined_odds * self.stake_per_bet) if p.won else 0.0 for p in self.parlays
        )
        return total_returned - total_staked

    def side_hit_rates(self) -> dict[str, tuple[int, float]]:
        """(count, hit_rate) per side among all leg bets."""
        out: dict[str, list[bool]] = {}
        for b in self.bets:
            out.setdefault(b.side, []).append(b.won)
        return {side: (len(ws), sum(ws) / len(ws)) for side, ws in out.items()}

    def calibration(self, bins: int = 5) -> list[tuple[float, float, int]]:
        """(bin_low, actual_win_rate, n_in_bin) by model probability decile."""
        if not self.bets:
            return []
        width = 1.0 / bins
        out: list[tuple[float, float, int]] = []
        for i in range(bins):
            low = i * width
            high = low + width
            in_bin = [b for b in self.bets if low <= b.model_prob < high]
            if in_bin:
                rate = sum(1 for b in in_bin if b.won) / len(in_bin)
                out.append((low, rate, len(in_bin)))
        return out


def run_backtest(
    matches: list[Match],
    *,
    book_odds: dict[tuple[str, float], float] | None = None,
    book_margin: dict[tuple[str, float], float] | None = None,
    stake_per_bet: float = 100.0,
    min_edge: float = MIN_EDGE,
    window_days: int = WINDOW_DAYS,
) -> BacktestResult:
    """Walk-forward parlay simulation over a set of matches.

    A leg is playable when model prob beats the de-vigged fair implied
    probability of its per-side book price: fair = 1 / (odds * (1 + margin)).
    """
    odds = book_odds if book_odds is not None else dict(BOOK_ODDS)
    margin = book_margin if book_margin is not None else dict(BOOK_MARGIN)
    for key, o in odds.items():
        if o <= 1.0:
            raise ValueError(f"book odds {o} for {key} must be > 1.0")
    for key, mgn in margin.items():
        if not 0.0 <= mgn < 1.0:
            raise ValueError(f"margin {mgn} for {key} outside [0, 1)")
    ordered = sorted(matches, key=lambda m: (m.date, m.home))
    if not ordered:
        return BacktestResult(bets=(), parlays=(), stake_per_bet=stake_per_bet)

    start, end = ordered[0].date, ordered[-1].date
    bets: list[BetRecord] = []
    parlays: list[ParlayRecord] = []
    qualifier_matchdays = 0
    feasible_matchdays = 0
    fair_implied = {key: 1.0 / (o * (1.0 + margin[key])) for key, o in odds.items()}

    cursor = start
    while cursor <= end:
        window_end = cursor + timedelta(days=window_days - 1)
        history = [m for m in ordered if m.date < cursor]
        window = [m for m in ordered if cursor <= m.date <= window_end]
        model = fit_model(history) if history else None

        # candidate legs per matchday inside the window
        by_day: dict[date, list[tuple[Match, str, float, float, float]]] = {}
        for m in window:
            if model is None or m.home not in model.attack or m.away not in model.attack:
                continue
            for side, line in OVERS:
                if not is_allowed_market(side, line):
                    continue
                over_prob = p_over(model, m.home, m.away, line)
                prob = over_prob if side == "over" else 1.0 - over_prob
                if prob - fair_implied[(side, line)] >= min_edge:
                    by_day.setdefault(m.date, []).append(
                        (m, side, line, prob, odds[(side, line)])
                    )

        for day, cands in by_day.items():
            if cands:
                qualifier_matchdays += 1
                if len(cands) >= MIN_LEGS:
                    feasible_matchdays += 1
            legs: list[BetRecord] = []
            for match, side, line, prob, leg_odds in cands:
                actual = match.home_goals + match.away_goals
                won = actual > line if side == "over" else actual <= line
                legs.append(
                    BetRecord(
                        date=match.date,
                        league=match.league,
                        home=match.home,
                        away=match.away,
                        side=side,
                        line=line,
                        odds=leg_odds,
                        model_prob=prob,
                        edge=prob - fair_implied[(side, line)],
                        actual_total=actual,
                        won=won,
                    )
                )

            # greedy parlay: strongest edge first, one leg per match, to 5.0+
            ranked = sorted(legs, key=lambda b: b.edge, reverse=True)
            chosen: list[BetRecord] = []
            seen_matches: set[tuple[str, str]] = set()
            combined = 1.0
            for b in ranked:
                if (b.home, b.away) in seen_matches:
                    continue
                chosen.append(b)
                seen_matches.add((b.home, b.away))
                combined *= b.odds
                if combined >= TARGET_PARLAY_ODDS or len(chosen) >= MAX_LEGS:
                    break
            if len(chosen) < MIN_LEGS or combined < TARGET_PARLAY_ODDS:
                continue

            parlay_prob = 1.0
            for b in chosen:
                parlay_prob *= b.model_prob
            parlays.append(
                ParlayRecord(
                    date=day,
                    legs=tuple(chosen),
                    combined_odds=combined,
                    model_prob=parlay_prob,
                    stake=stake_per_bet,
                    won=all(b.won for b in chosen),
                )
            )
            bets.extend(chosen)

        cursor = window_end + timedelta(days=1)

    return BacktestResult(
        bets=tuple(bets),
        parlays=tuple(parlays),
        stake_per_bet=stake_per_bet,
        qualifier_matchdays=qualifier_matchdays,
        feasible_matchdays=feasible_matchdays,
    )
