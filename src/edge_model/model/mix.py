"""Blend Dixon-Coles totals probs with offline xG Poisson probs (pure)."""

from __future__ import annotations

from edge_model.data.xg import DEFAULT_XG_WEIGHT, XgTable, blend_prob, get_xg, xg_p_over
from edge_model.model.dixon_coles import TeamModel, p_over


def blended_over_prob(
    model: TeamModel,
    home: str,
    away: str,
    line: float,
    league: str = "",
    xg_table: XgTable | None = None,
    xg_weight: float = DEFAULT_XG_WEIGHT,
) -> float:
    """Dixon-Coles p_over, blended with xG Poisson when both teams are known."""
    base = p_over(model, home, away, line)
    if not xg_table:
        return base
    xh = get_xg(xg_table, league, home)
    xa = get_xg(xg_table, league, away)
    if xh is None or xa is None:
        return base
    return blend_prob(base, xg_p_over(xh, xa, line), xg_weight)
