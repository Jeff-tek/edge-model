"""Offline xG team-strength table + Poisson totals probs + blend with Dixon-Coles.

Free-data workflow (no API key, stdlib only):
  1. Export team xG from Understat or FBref once per week into CSV:
     league,team,gp,xg_for,xg_against
  2. Pass --xg-csv data/xg.csv to daily.py, or xg_table=... to run_backtest().
  3. Leg prob = (1 - w) * model_prob + w * xg_prob (default w = 0.35).

Why this helps profitability: goals are noisy, xG is stickier. Blending
shrinks Dixon-Coles overreaction to 1-2 fluky results, which is exactly
what kills O1.5/U4.5 legs at 1.15-1.25 odds.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path

HOME_XG_BOOST = 1.12  # home teams create ~12% more than their season avg
MAX_GOALS = 12
DEFAULT_XG_WEIGHT = 0.35


@dataclass(frozen=True, slots=True)
class XgTeam:
    league: str
    team: str
    gp: int
    xg_for: float
    xg_against: float

    @property
    def xg_for_per(self) -> float:
        return self.xg_for / self.gp if self.gp > 0 else 0.0

    @property
    def xg_against_per(self) -> float:
        return self.xg_against / self.gp if self.gp > 0 else 0.0


XgTable = dict[tuple[str, str], XgTeam]  # (league, team) -> row


def _to_float(raw: str | None) -> float | None:
    if raw is None:
        return None
    s = raw.strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_xg_csv(csv_text: str) -> XgTable:
    """Parse xG CSV text. Header needs team,xg_for,xg_against; league/gp optional."""
    out: XgTable = {}
    reader = csv.DictReader(csv_text.splitlines())
    for row in reader:
        team = (row.get("team") or "").strip()
        if not team:
            continue
        xg_for = _to_float(row.get("xg_for"))
        xg_against = _to_float(row.get("xg_against"))
        if xg_for is None or xg_against is None:
            continue
        league = (row.get("league") or "").strip()
        gp_raw = (row.get("gp") or "").strip()
        try:
            gp = int(gp_raw) if gp_raw else 0
        except ValueError:
            gp = 0
        out[(league, team)] = XgTeam(
            league=league, team=team, gp=gp, xg_for=xg_for, xg_against=xg_against
        )
    return out


def load_xg_csv(path: str | Path) -> XgTable:
    """Load an xG CSV file from disk (offline export, no network)."""
    return parse_xg_csv(Path(path).read_text(encoding="utf-8-sig"))


def get_xg(table: XgTable, league: str, team: str) -> XgTeam | None:
    """League-scoped lookup with fallback to league-agnostic match."""
    if (league, team) in table:
        return table[(league, team)]
    for (lg, tm), row in table.items():
        if tm == team and lg == "":
            return row
    return None


def xg_lambdas(home: XgTeam, away: XgTeam, home_boost: float = HOME_XG_BOOST) -> tuple[float, float]:
    """Expected goals from xG averages: mean of own creation + opp concession."""
    lambda_h = (home.xg_for_per + away.xg_against_per) / 2.0 * home_boost
    lambda_a = (away.xg_for_per + home.xg_against_per) / 2.0 / home_boost
    return (max(lambda_h, 0.05), max(lambda_a, 0.05))


def _pois_pmf(k: int, lam: float) -> float:
    return math.exp(k * math.log(lam) - lam - math.lgamma(k + 1)) if lam > 0 else (1.0 if k == 0 else 0.0)


def xg_p_over(home: XgTeam, away: XgTeam, line: float) -> float:
    """P(total > line) under independent Poissons from xG lambdas."""
    lambda_h, lambda_a = xg_lambdas(home, away)
    over = 0.0
    for x in range(MAX_GOALS + 1):
        px = _pois_pmf(x, lambda_h)
        for y in range(MAX_GOALS + 1):
            if x + y > line:
                over += px * _pois_pmf(y, lambda_a)
    return min(max(over, 0.0), 1.0)


def blend_prob(model_prob: float, xg_prob: float, weight: float = DEFAULT_XG_WEIGHT) -> float:
    """Convex blend of model prob and xG prob. Weight = trust in xG."""
    if not 0.0 <= weight <= 1.0:
        raise ValueError(f"xG weight must be in [0, 1], got {weight}")
    if not 0.0 <= model_prob <= 1.0:
        raise ValueError(f"model_prob outside [0, 1]: {model_prob}")
    if not 0.0 <= xg_prob <= 1.0:
        raise ValueError(f"xg_prob outside [0, 1]: {xg_prob}")
    return (1.0 - weight) * model_prob + weight * xg_prob
