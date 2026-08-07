"""Value layer: implied probabilities, +EV leg filter, parlay assembly.

Strategy: bet only Over 1.5 and Under 4.5 totals at leg odds [1.15, 1.25],
assembled into a parlay of 5.0+ combined odds, at most one leg per match.
"""

from __future__ import annotations

from dataclasses import dataclass

MIN_LEG_ODDS = 1.15
MAX_LEG_ODDS = 1.25
TARGET_PARLAY_ODDS = 5.0
MIN_LEGS = 8
MAX_LEGS = 13
DEFAULT_STAKE = 100.0
# Minimum edge (model prob - fair implied prob) to accept a leg.
MIN_EDGE = 0.03
ALLOWED_MARKETS: frozenset[tuple[str, float]] = frozenset(
    {("over", 1.5), ("under", 4.5)}
)


@dataclass(frozen=True, slots=True)
class Leg:
    home: str
    away: str
    side: str  # "over" | "under"
    line: float
    decimal_odds: float
    model_prob: float
    fair_implied: float  # de-vigged implied probability
    edge: float  # model_prob - fair_implied

    @property
    def implied(self) -> float:
        return 1.0 / self.decimal_odds

    @property
    def ev(self) -> float:
        """Expected value of a $1 bet at decimal odds."""
        return self.model_prob * self.decimal_odds - 1.0


@dataclass(frozen=True, slots=True)
class Parlay:
    legs: tuple[Leg, ...]
    combined_odds: float
    model_prob: float  # product of leg model probabilities (independent assumption)
    stake: float

    @property
    def ev(self) -> float:
        return self.model_prob * self.combined_odds - 1.0

    @property
    def expected_return(self) -> float:
        """Expected payout per $1 staked (incl. stake)."""
        return self.model_prob * self.combined_odds


def implied(odds: float) -> float:
    if odds <= 1.0:
        raise ValueError(f"decimal odds must be > 1.0, got {odds}")
    return 1.0 / odds


def devig(over_odds: float, under_odds: float) -> float:
    """Fair over probability after removing the bookmaker margin (two-way market)."""
    p_over = implied(over_odds)
    p_under = implied(under_odds)
    return p_over / (p_over + p_under)


def evaluate_leg(
    home: str,
    away: str,
    side: str,
    line: float,
    decimal_odds: float,
    over_prob: float,
    *,
    other_side_odds: float | None = None,
) -> Leg:
    """Build a Leg, de-vigging the odds when both sides are available.

    When only one side's odds are known, the raw implied probability is used
    as the threshold (the bookmaker margin then has to be beaten by MIN_EDGE).
    """
    if side not in ("over", "under"):
        raise ValueError(f"side must be 'over' or 'under', got {side!r}")
    if other_side_odds is not None:
        if side == "over":
            fair = devig(decimal_odds, other_side_odds)
        else:
            fair = devig(other_side_odds, decimal_odds)
    else:
        fair = implied(decimal_odds)

    model_prob = over_prob if side == "over" else 1.0 - over_prob
    return Leg(
        home=home,
        away=away,
        side=side,
        line=line,
        decimal_odds=decimal_odds,
        model_prob=model_prob,
        fair_implied=fair,
        edge=model_prob - fair,
    )


def is_allowed_market(side: str, line: float) -> bool:
    """Only O1.5 and U4.5 markets are in scope for this strategy."""
    return (side, line) in ALLOWED_MARKETS


def is_playable_leg(leg: Leg, min_edge: float = MIN_EDGE) -> bool:
    """A leg is playable iff market allowed, odds in [1.15, 1.25], and edge
    beats the threshold."""
    return (
        is_allowed_market(leg.side, leg.line)
        and MIN_LEG_ODDS <= leg.decimal_odds <= MAX_LEG_ODDS
        and leg.edge >= min_edge
    )


def assemble_parlay(
    legs: list[Leg],
    *,
    stake: float = DEFAULT_STAKE,
    target_odds: float = TARGET_PARLAY_ODDS,
    min_legs: int = MIN_LEGS,
    max_legs: int = MAX_LEGS,
    min_edge: float = MIN_EDGE,
) -> Parlay | None:
    """Greedily assemble a parlay from +EV legs toward the target odds.

    Returns None (SKIP DAY) when fewer than min_legs playable legs exist or
    the target cannot be reached within max_legs. Legs are ranked by edge;
    we add the strongest until the combined odds reach the target or
    max_legs is hit. At most one leg per match keeps the parlay
    near-independent. Assumes legs are independent.
    """
    playable = sorted(
        (leg for leg in legs if is_playable_leg(leg, min_edge)),
        key=lambda leg: leg.edge,
        reverse=True,
    )
    if len(playable) < min_legs:
        return None

    chosen: list[Leg] = []
    seen_matches: set[tuple[str, str]] = set()
    combined = 1.0
    for leg in playable:
        if (leg.home, leg.away) in seen_matches:
            continue
        chosen.append(leg)
        seen_matches.add((leg.home, leg.away))
        combined *= leg.decimal_odds
        if combined >= target_odds or len(chosen) >= max_legs:
            break

    if len(chosen) < min_legs or combined < target_odds:
        return None

    model_prob = 1.0
    for leg in chosen:
        model_prob *= leg.model_prob
    return Parlay(
        legs=tuple(chosen),
        combined_odds=combined,
        model_prob=model_prob,
        stake=stake,
    )
