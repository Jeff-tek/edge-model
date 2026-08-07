#!/usr/bin/env python3
"""Settle pending paper trades from match results.

Reads results from either a manual CSV (match_date,home,away,total) or the
TheOddsAPI scores endpoint, and marks matching pending trades as win/loss.

Usage:
  python -m edge_model.cli.settle --book data/paper_trades.csv \
      --results results.csv
  ODDS_API_KEY=xxx python -m edge_model.cli.settle --from-scores
"""

from __future__ import annotations

import argparse
import csv
from datetime import date
from pathlib import Path

from edge_model.track.paper import PaperBook


def _results_from_csv(path: str) -> list[tuple[date, str, str, float]]:
    out: list[tuple[date, str, str, float]] = []
    with Path(path).open(newline="") as f:
        for row in csv.DictReader(f):
            try:
                home = row["home"].strip()
                away = row["away"].strip()
                total = float(row["total"])
            except (KeyError, ValueError):
                continue
            if "match_date" in row and row["match_date"].strip():
                try:
                    day = date.fromisoformat(row["match_date"].strip())
                except ValueError:
                    continue
            else:
                day = date.today()
            out.append((day, home, away, total))
    return out


def _results_from_scores(leagues: list[str]) -> list[tuple[date, str, str, float]]:
    from edge_model.data.fixtures import fetch_scores_by_league

    by_league = fetch_scores_by_league(leagues=leagues)
    out: list[tuple[date, str, str, float]] = []
    for league_results in by_league.values():
        for r in league_results:
            if r.completed and r.total_goals is not None:
                out.append((r.commence_time.date(), r.home, r.away, float(r.total_goals)))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Settle pending paper trades")
    parser.add_argument("--book", default="data/paper_trades.csv")
    parser.add_argument("--leagues", nargs="+", default=["E0", "SP1", "I1", "D1", "F1"])
    parser.add_argument("--bankroll", type=float, default=2000.0)
    parser.add_argument("--results", help="results CSV (match_date,home,away,total)")
    parser.add_argument("--from-scores", action="store_true",
                        help="pull results from TheOddsAPI scores endpoint")
    args = parser.parse_args()

    if not args.results and not args.from_scores:
        parser.error("provide --results FILE or --from-scores")

    paper = PaperBook(args.book)
    if args.results:
        results = _results_from_csv(args.results)
    else:
        results = _results_from_scores(args.leagues)

    n = paper.settle_from_results(results)
    pending = len(paper.pending())
    print(f"settled {n} trade(s); {pending} still pending")
    print(paper.status_line(args.bankroll))


if __name__ == "__main__":
    main()
