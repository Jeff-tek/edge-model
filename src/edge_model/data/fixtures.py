"""Live fixtures + odds via TheOddsAPI (free tier).

Free tier: https://the-odds-api.com — 500 requests/month, soccer sport key
covers dozens of leagues. Set ODDS_API_KEY env var.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime

API_BASE = "https://api.the-odds-api.com/v4"
SPORT = "soccer_epl"  # default fallback; overridden by SPORT_KEY env
MARKETS = "totals"

# Model league code -> TheOddsAPI sport key (verified active as of 2026-08).
LEAGUE_SPORT_KEYS: dict[str, str] = {
    "E0": "soccer_epl",
    "SP1": "soccer_spain_la_liga",
    "I1": "soccer_italy_serie_a",
    "D1": "soccer_germany_bundesliga",
    "F1": "soccer_france_ligue_one",
}

# Common soccer keys (kept for reference / manual SPORT_KEY override):
# soccer_epl, soccer_spain_la_liga, soccer_italy_serie_a,
# soccer_germany_bundesliga, soccer_france_ligue_one, soccer_eredivisie,
# soccer_brazil_serie_a, soccer_japan_j_league,
# soccer_argentina_primera_division, soccer_portugal_primeira_liga,
# soccer_belgium_first_div, soccer_germany_bundesliga2, etc.
SPORT_KEYS = list(LEAGUE_SPORT_KEYS.values()) + [
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


def fetch_fixtures_by_league(
    *,
    key: str | None = None,
    leagues: list[str] | None = None,
    timeout: int = 60,
) -> dict[str, list[Fixture]]:
    """Fetch upcoming fixtures for each model league.

    Returns {league_code: [Fixture]}. A league whose sport key is inactive or
    unreachable is skipped with a warning rather than failing the whole run.
    """
    api_key = key or _api_key()
    wanted = leagues or list(LEAGUE_SPORT_KEYS)
    out: dict[str, list[Fixture]] = {}
    for league in wanted:
        sport = LEAGUE_SPORT_KEYS.get(league)
        if sport is None:
            print(f"[fixtures] no sport key for league {league!r}, skipping")
            continue
        try:
            fixtures = fetch_fixtures(key=api_key, sport_key=sport, timeout=timeout)
            out[league] = fixtures
            print(f"[fixtures] {league} ({sport}): {len(fixtures)} fixtures")
        except urllib.error.HTTPError as exc:
            print(f"[fixtures] {league} ({sport}) unavailable ({exc.code}): {exc.reason}")
        except urllib.error.URLError as exc:
            print(f"[fixtures] {league} ({sport}) network error: {exc.reason}")
    return out
