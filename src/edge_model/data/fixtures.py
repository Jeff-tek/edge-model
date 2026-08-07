"""Live fixtures + odds via TheOddsAPI (free tier).

Free tier: https://the-odds-api.com — 500 requests/month, soccer sport key
covers dozens of leagues. Set ODDS_API_KEY env var.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime

API_BASE = "https://api.the-odds-api.com/v4"
SPORT = "soccer_fifa_world_cup"  # default; overridden by SPORT_KEY env
MARKETS = "totals"

# The free tier allows one sport key. Common soccer keys:
# soccer_epl, soccer_la_liga, soccer_serie_a, soccer_bundesliga,
# soccer_ligue_one, soccer_eredivisie, soccer_brazil_serie_a,
# soccer_japan_j_league, soccer_argentina_primera_division, etc.
SPORT_KEYS = [
    "soccer_epl",
    "soccer_la_liga",
    "soccer_serie_a",
    "soccer_bundesliga",
    "soccer_ligue_one",
    "soccer_eredivisie",
    "soccer_brazil_serie_a",
    "soccer_japan_j_league",
    "soccer_argentina_primera_division",
    "soccer_portugal_primeira_liga",
    "soccer_belgium_first_div",
    "soccer_germany_bundesliga2",
]


@dataclass(frozen=True, slots=True)
class MarketLine:
    point: float  # e.g. 2.5
    over_odds: float | None
    under_odds: float | None


@dataclass(frozen=True, slots=True)
class Fixture:
    id: str
    commence_time: datetime
    home: str
    away: str
    totals: tuple[MarketLine, ...]  # usually just one line (2.5)


def _get_json(url: str, timeout: int = 60) -> object:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _api_key() -> str:
    key = os.environ.get("ODDS_API_KEY", "")
    if not key:
        raise RuntimeError("ODDS_API_KEY environment variable is not set")
    return key


def fetch_fixtures(
    *,
    key: str | None = None,
    sport_key: str | None = None,
    timeout: int = 60,
) -> list[Fixture]:
    """Fetch upcoming fixtures with totals markets from TheOddsAPI."""
    api_key = key or _api_key()
    sport = sport_key or os.environ.get("SPORT_KEY", SPORT)
    query = urllib.parse.urlencode(
        {
            "apiKey": api_key,
            "regions": "eu,uk",
            "markets": MARKETS,
            "oddsFormat": "decimal",
        }
    )
    url = f"{API_BASE}/sports/{sport}/odds/?{query}"
    data = _get_json(url, timeout=timeout)
    if not isinstance(data, list):
        raise RuntimeError(f"unexpected TheOddsAPI response: {data!r}")

    out: list[Fixture] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        commence = item.get("commence_time")
        try:
            start = datetime.fromisoformat(str(commence).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        totals: list[MarketLine] = []
        for bm in item.get("bookmakers", []) if isinstance(item.get("bookmakers"), list) else []:
            if not isinstance(bm, dict):
                continue
            for mkt in bm.get("markets", []) if isinstance(bm.get("markets"), list) else []:
                if not isinstance(mkt, dict) or mkt.get("key") != "totals":
                    continue
                for outcome in mkt.get("outcomes", []) if isinstance(mkt.get("outcomes"), list) else []:
                    if not isinstance(outcome, dict):
                        continue
                    point = outcome.get("point")
                    if point is None:
                        continue
                    if outcome.get("name") == "Over":
                        totals.append(MarketLine(point=float(point), over_odds=outcome.get("price"), under_odds=None))
                    elif outcome.get("name") == "Under":
                        totals.append(MarketLine(point=float(point), over_odds=None, under_odds=outcome.get("price")))
        if totals:
            out.append(
                Fixture(
                    id=str(item.get("id", "")),
                    commence_time=start.astimezone(UTC),
                    home=str(item.get("home_team", "")),
                    away=str(item.get("away_team", "")),
                    totals=tuple(totals),
                )
            )
    return out


def group_fixtures_by_line(fixtures: list[Fixture], line: float = 2.5) -> list[tuple[Fixture, MarketLine]]:
    """Keep fixtures that offer the requested totals line."""
    out: list[tuple[Fixture, MarketLine]] = []
    for f in fixtures:
        for tl in f.totals:
            if abs(tl.point - line) < 1e-9:
                out.append((f, tl))
                break
    return out
