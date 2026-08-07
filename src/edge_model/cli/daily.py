#!/usr/bin/env python3
"""Daily briefing script.

Fit the Dixon-Coles model on recent football-data.co.uk history, then:
  - if ODDS_API_KEY is set: pull live fixtures+odds from TheOddsAPI
  - else: read odds_today.csv (league,home,away,side,line,odds[,other_odds])
Evaluate legs, assemble the parlay, write the briefing, and log paper trades.

Usage:
  ODDS_API_KEY=xxx python -m edge_model.cli.daily \
      --seasons 2324 2425 2526 --leagues E0 SP1 I1 D1 F1 \
      --odds odds_today.csv --bankroll 2000
"""

from __future__ import annotations

import argparse
import csv
from datetime import date
from pathlib import Path

from edge_model.backtest.backtest import run_backtest
from edge_model.data.fixtures import Fixture, fetch_fixtures, group_fixtures_by_line
from edge_model.data.football_data import load_league
from edge_model.model.dixon_coles import TeamModel, fit_model, p_over
from edge_model.report.briefing import build_briefing
from edge_model.track.paper import PaperBook
from edge_model.value.filter import (
    ALLOWED_MARKETS,
    MAX_LEG_ODDS,
    MIN_LEG_ODDS,
    Leg,
    assemble_parlay,
    evaluate_leg,
    is_allowed_market,
)


def _load_odds_csv(path: str) -> list[dict[str, str]]:
    with Path(path).open(newline="") as f:
        return list(csv.DictReader(f))


def _candidate_legs_from_csv(
    model: TeamModel,
    rows: list[dict[str, str]],
) -> list[Leg]:
    legs: list[Leg] = []
    for row in rows:
        try:
            side = row["side"].strip().lower()
            line = float(row["line"])
            odds = float(row["odds"])
            other = float(row["other_odds"]) if row.get("other_odds") else None
        except (KeyError, ValueError):
            continue
        if not is_allowed_market(side, line):
            continue
        if not (MIN_LEG_ODDS <= odds <= MAX_LEG_ODDS):
            continue
        over_prob = p_over(model, row["home"], row["away"], line)
        legs.append(
            evaluate_leg(
                home=row["home"],
                away=row["away"],
                side=side,
                line=line,
                decimal_odds=odds,
                over_prob=over_prob,
                other_side_odds=other,
            )
        )
    return legs


def _candidate_legs_from_api(model: TeamModel, fixtures: list[Fixture]) -> list[Leg]:
    legs: list[Leg] = []
    for side, line in ALLOWED_MARKETS:
        for fixture, market in group_fixtures_by_line(fixtures, line):
            odds = market.over_odds if side == "over" else market.under_odds
            other = market.under_odds if side == "over" else market.over_odds
            if odds is None or not (MIN_LEG_ODDS <= odds <= MAX_LEG_ODDS):
                continue
            over_prob = p_over(model, fixture.home, fixture.away, market.point)
            legs.append(
                evaluate_leg(
                    home=fixture.home,
                    away=fixture.away,
                    side=side,
                    line=market.point,
                    decimal_odds=odds,
                    over_prob=over_prob,
                    other_side_odds=other,
                )
            )
    return legs


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily edge-model briefing")
    parser.add_argument("--seasons", nargs="+", default=["2324", "2425", "2526"])
    parser.add_argument("--leagues", nargs="+", default=["E0", "SP1", "I1", "D1", "F1"])
    parser.add_argument("--odds", help="CSV of today's bookie odds (manual mode)")
    parser.add_argument("--bankroll", type=float, default=2000.0)
    parser.add_argument("--book", default="data/paper_trades.csv")
    parser.add_argument("--out", default="data/briefing.md")
    parser.add_argument("--dashboard", default="", help="also write dashboard JSON to this path")
    parser.add_argument("--backtest", action="store_true", help="also run the backtest")
    args = parser.parse_args()

    matches = []
    for league in args.leagues:
        matches.extend(load_league(args.seasons, league))
    if not matches:
        raise SystemExit("no match data downloaded — check --seasons/--leagues")

    model = fit_model(matches)
    print(f"fitted {len(matches)} matches across {len(args.leagues)} leagues")

    if args.odds:
        rows = _load_odds_csv(args.odds)
        legs = _candidate_legs_from_csv(model, rows)
        source = f"manual odds file ({args.odds})"
    else:
        try:
            fixtures = fetch_fixtures()
            legs = _candidate_legs_from_api(model, fixtures)
            source = "TheOddsAPI live odds"
        except RuntimeError as exc:
            raise SystemExit(f"no ODDS_API_KEY and no --odds file: {exc}") from exc

    paper = PaperBook(args.book)
    parlay = assemble_parlay(legs)
    briefing = build_briefing(
        todays_date=date.today(),
        candidate_legs=legs,
        parlay=parlay,
        paper=paper,
        starting_bankroll=args.bankroll,
    )

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(briefing)
    print(briefing)
    print(f"\n[briefing written to {args.out}; source: {source}]")

    if args.dashboard:
        from edge_model.dashboard.generate import _legs_from_csv, build_payload, write_payload

        if args.odds:
            rows = _load_odds_csv(args.odds)
            dashboard_legs = _legs_from_csv(model, rows)
            fixture_teams: list[tuple[str, str, str, dict[str, object]]] = [
                (row.get("league", ""), row["home"], row["away"], {"line": None, "over": None, "under": None})
                for row in rows
                if row.get("home") and row.get("away")
            ]
        else:
            dashboard_legs = [(leg, "") for leg in legs]
            fixture_teams = []
        payload = build_payload(
            matches=matches,
            backtest_result=None,
            model=model,
            legs=dashboard_legs,
            parlay=parlay,
            paper=paper,
            starting_bankroll=args.bankroll,
            fixture_teams=fixture_teams,
        )
        write_payload(payload, Path(args.dashboard))
        print(f"[dashboard written to {args.dashboard}]")

    if parlay is not None:
        for leg in parlay.legs:
            paper.append(
                sport="football",
                league=args.leagues[0] if len(args.leagues) == 1 else "",
                home=leg.home,
                away=leg.away,
                line=leg.line,
                side=leg.side,
                odds=leg.decimal_odds,
                stake=parlay.stake,
            )

    if args.backtest:
        for league in args.leagues:
            result = run_backtest([m for m in matches if m.league == league])
            print(
                f"\nbacktest {league}: {result.n_bets} bets, "
                f"hit {result.hit_rate * 100:.1f}%, ROI {result.roi * 100:+.1f}%"
            )


if __name__ == "__main__":
    main()
