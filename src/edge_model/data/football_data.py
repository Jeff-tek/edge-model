"""Football-data.co.uk downloader and parser.

Verified schema (mmz4281/{season}/E0.csv):
  Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,...,
  B365H,B365D,B365A,...,PSH,PSD,PSA,...,
  B365>2.5,B365<2.5,P>2.5,P<2.5,Max>2.5,...

We only keep: date, teams, full-time goals, Bet365 O/U 2.5 odds,
Pinnacle O/U 2.5 odds.
"""

from __future__ import annotations

import csv
import io
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime

BASE_URL = "https://www.football-data.co.uk/mmz4281/{season}/{league}.csv"

# season is "2526" style (two-digit years of season span)
# league codes: E0=EPL, SP1=LaLiga, I1=SerieA, D1=Bundesliga, F1=Ligue1,
#               N1=Eredivisie, P1=Portugal, B1=Belgium, T1=Turkey, SC0=Scotland
SEASONS = ["2324", "2425", "2526"]
BIG5 = ["E0", "SP1", "I1", "D1", "F1"]


@dataclass(frozen=True, slots=True)
class Match:
    season: str
    league: str
    date: date
    home: str
    away: str
    home_goals: int
    away_goals: int
    b365_over: float | None  # Bet365 >2.5 decimal odds
    b365_under: float | None
    pinnacle_over: float | None  # Pinnacle >2.5 decimal odds
    pinnacle_under: float | None


def _to_float(raw: str) -> float | None:
    s = raw.strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _to_date(raw: str) -> date:
    return datetime.strptime(raw.strip(), "%d/%m/%Y").date()


def fetch_league_csv(season: str, league: str, timeout: int = 60) -> str:
    """Download the raw CSV for one season+league from football-data.co.uk."""
    url = BASE_URL.format(season=season, league=league)
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        raw = resp.read()
        assert isinstance(raw, bytes)
        return raw.decode("utf-8-sig")


def parse_league_csv(season: str, league: str, csv_text: str) -> list[Match]:
    """Parse a raw CSV into Match records, skipping rows without full-time goals."""
    out: list[Match] = []
    reader = csv.DictReader(io.StringIO(csv_text))
    for row in reader:
        fthg = _to_float(row.get("FTHG", ""))
        ftag = _to_float(row.get("FTAG", ""))
        if fthg is None or ftag is None:
            continue
        date_raw = row.get("Date", "")
        try:
            match_date = _to_date(date_raw)
        except ValueError:
            continue
        out.append(
            Match(
                season=season,
                league=league,
                date=match_date,
                home=row.get("HomeTeam", "").strip(),
                away=row.get("AwayTeam", "").strip(),
                home_goals=int(fthg),
                away_goals=int(ftag),
                b365_over=_to_float(row.get("B365>2.5", "")),
                b365_under=_to_float(row.get("B365<2.5", "")),
                pinnacle_over=_to_float(row.get("P>2.5", "")),
                pinnacle_under=_to_float(row.get("P<2.5", "")),
            )
        )
    return out


def load_league(
    seasons: list[str],
    league: str,
    timeout: int = 60,
) -> list[Match]:
    """Download and parse one league across multiple seasons."""
    matches: list[Match] = []
    for season in seasons:
        csv_text = fetch_league_csv(season, league, timeout=timeout)
        matches.extend(parse_league_csv(season, league, csv_text))
    return matches


def load_big5(seasons: list[str] | None = None, timeout: int = 60) -> list[Match]:
    """Download all big-5 leagues across the given seasons."""
    seasons = seasons or SEASONS
    matches: list[Match] = []
    for league in BIG5:
        matches.extend(load_league(seasons, league, timeout=timeout))
    return matches
