"""Generate the dashboard JSON payload (dashboard/data.json).

Contract: see dashboard/data.sample.json. Every section of the sample file
(strategy, backtest, paper, fixtures, tips) is reproduced from live data:

  - strategy:      constants from edge_model.value.filter + backtest
  - backtest:      BacktestResult over the given seasons/leagues
  - paper:         PaperBook CSV (bankroll series, weekly P/L, recent trades)
  - fixtures:      upcoming fixtures + model edges (odds source dependent)
  - tips:          candidate legs, today's parlay (or no-bet reason), past tips

CLI:
  python -m edge_model.dashboard.generate \
      --seasons 2324 2425 2526 --leagues E0 SP1 I1 D1 F1 \
      --out dashboard/data.json [--skip-backtest] [--odds odds_today.csv]
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from edge_model.backtest.backtest import BOOK_MARGIN, BOOK_ODDS, BacktestResult, run_backtest
from edge_model.data.fixtures import Fixture
from edge_model.data.football_data import Match, load_league
from edge_model.model.dixon_coles import TeamModel, fit_model, p_over
from edge_model.track.paper import PAUSE_AFTER_LOSSES, PaperBook, Trade
from edge_model.value.filter import (
    MAX_LEG_ODDS,
    MAX_LEGS,
    MIN_EDGE,
    MIN_LEG_ODDS,
    MIN_LEGS,
    TARGET_PARLAY_ODDS,
    Leg,
    Parlay,
    assemble_parlay,
    is_playable_leg,
)

LEAGUE_NAMES = {
    "E0": "Premier League",
    "SP1": "La Liga",
    "I1": "Serie A",
    "D1": "Bundesliga",
    "F1": "Ligue 1",
}

RECENT_TRADES = 10
PAST_TIPS = 10


def _fmt_pct(p: float) -> float:
    return round(p, 4)


def _strategy_section() -> dict[str, object]:
    return {
        "markets": [["over", 1.5], ["under", 4.5]],
        "leg_odds_window": [MIN_LEG_ODDS, MAX_LEG_ODDS],
        "target_parlay_odds": TARGET_PARLAY_ODDS,
        "min_legs": MIN_LEGS,
        "max_legs": MAX_LEGS,
        "min_edge": MIN_EDGE,
        "pause_after_losses": PAUSE_AFTER_LOSSES,
        "flat_book_odds": {f"{side}:{line:g}": o for (side, line), o in BOOK_ODDS.items()},
        "flat_book_margin": {f"{side}:{line:g}": m for (side, line), m in BOOK_MARGIN.items()},
    }


def _backtest_section(
    result: BacktestResult,
    n_matches: int,
    leagues: list[str],
    seasons: list[str],
) -> dict[str, object]:
    return {
        "matches": n_matches,
        "leagues": leagues,
        "seasons": seasons,
        "parlays": result.n_parlays,
        "parlay_wins": result.parlay_wins,
        "parlay_hit_rate": _fmt_pct(result.parlay_hit_rate),
        "roi": _fmt_pct(result.roi),
        "net_profit": round(result.net_profit, 2),
        "stake_per_bet": result.stake_per_bet,
        "legs": result.n_bets,
        "leg_hit_rate": _fmt_pct(result.hit_rate),
        "side_hit_rates": {
            side: {"count": n, "hit_rate": _fmt_pct(rate)}
            for side, (n, rate) in result.side_hit_rates().items()
        },
        "calibration": [
            {"bin_low": _fmt_pct(low), "actual": _fmt_pct(actual), "n": n}
            for low, actual, n in result.calibration()
        ],
        "feasible_matchdays": result.feasible_matchdays,
        "matchdays_with_qualifier": result.qualifier_matchdays,
    }


def _empty_backtest(n_matches: int, leagues: list[str], seasons: list[str]) -> dict[str, object]:
    return {
        "matches": n_matches,
        "leagues": leagues,
        "seasons": seasons,
        "parlays": 0,
        "parlay_wins": 0,
        "parlay_hit_rate": 0.0,
        "roi": 0.0,
        "net_profit": 0.0,
        "stake_per_bet": 100.0,
        "legs": 0,
        "leg_hit_rate": 0.0,
        "side_hit_rates": {},
        "calibration": [],
        "feasible_matchdays": 0,
        "matchdays_with_qualifier": 0,
    }


def _trade_dict(t: Trade) -> dict[str, object]:
    return {
        "date": t.date.isoformat(),
        "league": t.league,
        "home": t.home,
        "away": t.away,
        "side": t.side,
        "line": t.line,
        "odds": t.odds,
        "stake": t.stake,
        "result": t.result,
        "payout": t.payout,
    }


def _bankroll_series(paper: PaperBook, starting: float) -> list[dict[str, object]]:
    """Cumulative bankroll after each settled trade (oldest -> newest)."""
    settled = sorted(paper.settled(), key=lambda t: t.date)
    out: list[dict[str, object]] = []
    bankroll = starting
    for t in settled:
        bankroll += t.payout - t.stake
        out.append(
            {
                "date": t.date.isoformat(),
                "bankroll": round(bankroll, 2),
                "pl": round(t.payout - t.stake, 2),
            }
        )
    if not out:
        out.append(
            {"date": date.today().isoformat(), "bankroll": round(starting, 2), "pl": 0.0}
        )
    return out


def _weekly_pl(paper: PaperBook) -> list[dict[str, object]]:
    by_week: dict[date, float] = {}
    for t in paper.settled():
        week_start = t.date - timedelta(days=t.date.weekday())
        by_week[week_start] = by_week.get(week_start, 0.0) + (t.payout - t.stake)
    return [
        {"week_start": wk.isoformat(), "pl": round(pl, 2)}
        for wk, pl in sorted(by_week.items())
    ]


def _paper_section(paper: PaperBook, starting: float) -> dict[str, object]:
    bankroll = paper.bankroll(starting)
    count, kind = paper.win_streak()
    settled = paper.settled()
    return {
        "starting_bankroll": starting,
        "bankroll": round(bankroll, 2),
        "net_pl": round(paper.net_pl(), 2),
        "hit_rate": _fmt_pct(paper.hit_rate()),
        "settled_bets": len(settled),
        "win_streak": {"count": count, "kind": kind},
        "paused": paper.is_paused(),
        "bankroll_series": _bankroll_series(paper, starting),
        "weekly_pl": _weekly_pl(paper),
        "recent_trades": [
            _trade_dict(t)
            for t in sorted(settled, key=lambda t: t.date, reverse=True)[:RECENT_TRADES]
        ],
    }


def _past_tips(paper: PaperBook) -> list[dict[str, object]]:
    """Group settled trades by day; a parlay is won iff every leg won."""
    by_day: dict[date, list[Trade]] = {}
    for t in paper.settled():
        by_day.setdefault(t.date, []).append(t)
    out: list[dict[str, object]] = []
    for day, trades in sorted(by_day.items(), reverse=True):
        combined = 1.0
        for t in trades:
            combined *= t.odds
        stake = trades[0].stake
        won = all(t.result == "win" for t in trades)
        out.append(
            {
                "date": day.isoformat(),
                "status": "bet",
                "legs": len(trades),
                "combined_odds": round(combined, 2),
                "won": won,
                "payout": round(combined * stake, 2) if won else 0.0,
            }
        )
        if len(out) >= PAST_TIPS:
            break
    return out


def _fixture_section(
    model: TeamModel,
    fixtures: list[tuple[str, str, str, dict[str, object]]],
) -> list[dict[str, object]]:
    """One entry per fixture (league, home, away, totals_odds): model probs + edges."""
    out: list[dict[str, object]] = []
    for league, home, away, totals_odds in fixtures:
        over1_5 = p_over(model, home, away, 1.5)
        under4_5 = 1.0 - p_over(model, home, away, 4.5)
        fair_over = 1.0 / (BOOK_ODDS[("over", 1.5)] * (1.0 + BOOK_MARGIN[("over", 1.5)]))
        fair_under = 1.0 / (BOOK_ODDS[("under", 4.5)] * (1.0 + BOOK_MARGIN[("under", 4.5)]))
        edge_over = over1_5 - fair_over
        edge_under = under4_5 - fair_under
        qualifies = []
        if edge_over >= MIN_EDGE:
            qualifies.append("over1.5")
        if edge_under >= MIN_EDGE:
            qualifies.append("under4.5")
        out.append(
            {
                "commence_time": None,
                "league": league,
                "home": home,
                "away": away,
                "totals_odds": totals_odds,
                "model": {
                    "over1.5": _fmt_pct(over1_5),
                    "under4.5": _fmt_pct(under4_5),
                    "edge_over1.5": _fmt_pct(edge_over),
                    "edge_under4.5": _fmt_pct(edge_under),
                },
                "qualifies": qualifies,
            }
        )
    return out


def _candidate_leg_dict(leg: Leg, league: str) -> dict[str, object]:
    return {
        "home": leg.home,
        "away": leg.away,
        "league": league,
        "side": leg.side,
        "line": leg.line,
        "odds": leg.decimal_odds,
        "model_prob": _fmt_pct(leg.model_prob),
        "fair_implied": _fmt_pct(leg.fair_implied),
        "edge": _fmt_pct(leg.edge),
        "qualifies": is_playable_leg(leg),
    }


def _tips_section(
    legs: list[tuple[Leg, str]],
    parlay: Parlay | None,
    paper: PaperBook,
) -> dict[str, object]:
    candidates = sorted(legs, key=lambda pair: pair[0].edge, reverse=True)
    candidate_dicts = [_candidate_leg_dict(leg, league) for leg, league in candidates]
    playable = [leg for leg, _ in candidates if is_playable_leg(leg)]

    if paper.is_paused():
        status = "paused"
        reason = (
            f"{PAUSE_AFTER_LOSSES} consecutive losses reached — model paused. "
            "Do not place bets until it is recalibrated."
        )
        parlay_payload = None
    elif parlay is not None:
        status = "bet"
        reason = None
        parlay_payload = {
            "legs": [
                {
                    "home": leg.home,
                    "away": leg.away,
                    "side": leg.side,
                    "line": leg.line,
                    "odds": leg.decimal_odds,
                }
                for leg in parlay.legs
            ],
            "combined_odds": round(parlay.combined_odds, 2),
            "model_prob": _fmt_pct(parlay.model_prob),
            "stake": parlay.stake,
        }
    else:
        status = "no_bet"
        reason = (
            f"Only {len(playable)} qualifying legs today — need at least {MIN_LEGS} "
            f"to build a {TARGET_PARLAY_ODDS:g}+ parlay. Forcing a leg gives the "
            "bookmaker's margin a free ride. Skip."
        )
        parlay_payload = None

    return {
        "date": date.today().isoformat(),
        "status": status,
        "no_bet_reason": reason,
        "parlay": parlay_payload,
        "candidate_legs": candidate_dicts,
        "past_tips": _past_tips(paper),
    }


def build_payload(
    *,
    matches: list[Match],
    backtest_result: BacktestResult | None,
    model: TeamModel,
    legs: list[tuple[Leg, str]],
    parlay: Parlay | None,
    paper: PaperBook,
    starting_bankroll: float,
    fixture_teams: list[tuple[str, str, str, dict[str, object]]] | None = None,
    backtest_dict: dict[str, object] | None = None,
) -> dict[str, object]:
    """Assemble the full dashboard payload from live data.

    `backtest_dict` lets a fast daily refresh reuse the last computed
    backtest section instead of re-running the slow simulation.
    """
    leagues = _codes_of(matches, "league")
    seasons = _codes_of(matches, "season")
    bt = backtest_result
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "as_of_date": date.today().isoformat(),
        "strategy": _strategy_section(),
        "backtest": (
            backtest_dict
            if backtest_dict is not None
            else (
                _backtest_section(bt, len(matches), leagues, seasons)
                if bt is not None
                else _empty_backtest(len(matches), leagues, seasons)
            )
        ),
        "paper": _paper_section(paper, starting_bankroll),
        "fixtures": _fixture_section(model, fixture_teams or []),
        "tips": _tips_section(legs, parlay, paper),
    }


def _codes_of(matches: list[Match], attr: str) -> list[str]:
    seen: list[str] = []
    for m in matches:
        value = getattr(m, attr)
        if value not in seen:
            seen.append(value)
    return seen


def write_payload(payload: dict[str, object], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n")


def _legs_from_csv(model: TeamModel, rows: list[dict[str, str]]) -> list[tuple[Leg, str]]:
    """Build candidate legs from the manual odds CSV, keeping each leg's league."""
    out: list[tuple[Leg, str]] = []
    for row in rows:
        try:
            side = row["side"].strip().lower()
            line = float(row["line"])
            odds = float(row["odds"])
            other = float(row["other_odds"]) if row.get("other_odds") else None
        except (KeyError, ValueError):
            continue
        from edge_model.value.filter import evaluate_leg, is_allowed_market

        if not is_allowed_market(side, line):
            continue
        if not (MIN_LEG_ODDS <= odds <= MAX_LEG_ODDS):
            continue
        over_prob = p_over(model, row["home"], row["away"], line)
        leg = evaluate_leg(
            home=row["home"],
            away=row["away"],
            side=side,
            line=line,
            decimal_odds=odds,
            over_prob=over_prob,
            other_side_odds=other,
        )
        out.append((leg, row.get("league", "")))
    return out


def _totals_odds_from_api(fixtures: list[Fixture]) -> dict[tuple[str, str], dict[str, object]]:
    """Map (home, away) -> totals_odds dict for the 2.5 line when offered."""
    out: dict[tuple[str, str], dict[str, object]] = {}
    for fx in fixtures:
        for tl in fx.totals:
            if abs(tl.point - 2.5) < 1e-9:
                out[(fx.home, fx.away)] = {
                    "line": tl.point,
                    "over": tl.over_odds,
                    "under": tl.under_odds,
                }
                break
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate dashboard/data.json")
    parser.add_argument("--seasons", nargs="+", default=["2324", "2425", "2526"])
    parser.add_argument("--leagues", nargs="+", default=["E0", "SP1", "I1", "D1", "F1"])
    parser.add_argument("--out", default="dashboard/data.json")
    parser.add_argument("--book", default="data/paper_trades.csv")
    parser.add_argument("--bankroll", type=float, default=2000.0)
    parser.add_argument("--odds", help="manual odds CSV (league,home,away,side,line,odds[,other_odds])")
    parser.add_argument("--skip-backtest", action="store_true", help="skip the slow backtest (fast daily cron)")
    args = parser.parse_args()

    matches = []
    for league in args.leagues:
        matches.extend(load_league(args.seasons, league))
    if not matches:
        raise SystemExit("no match data downloaded — check --seasons/--leagues")

    model = fit_model(matches)
    print(f"fitted {len(matches)} matches across {len(args.leagues)} leagues")

    legs: list[tuple[Leg, str]] = []
    fixture_teams: list[tuple[str, str, str, dict[str, object]]] = []
    if args.odds:
        import csv

        rows: list[dict[str, str]] = []
        with Path(args.odds).open(newline="") as f:
            rows = list(csv.DictReader(f))
        legs = _legs_from_csv(model, rows)
        for row in rows:
            if row.get("home") and row.get("away"):
                fixture_teams.append(
                    (
                        row.get("league", ""),
                        row["home"],
                        row["away"],
                        {"line": None, "over": None, "under": None},
                    )
                )
    else:
        try:
            from edge_model.cli.daily import _candidate_legs_from_api
            from edge_model.data.fixtures import fetch_fixtures

            fixtures = fetch_fixtures()
            raw_legs = _candidate_legs_from_api(model, fixtures)
            legs = [(leg, "") for leg in raw_legs]
            league_code = _sport_key_to_league(os.environ.get("SPORT_KEY", ""))
            totals = _totals_odds_from_api(fixtures)
            for fx in fixtures:
                fixture_teams.append(
                    (league_code, fx.home, fx.away, totals.get((fx.home, fx.away), {"line": None, "over": None, "under": None}))
                )
        except RuntimeError as exc:
            print(f"no live odds available: {exc}")

    paper = PaperBook(args.book)
    parlay = assemble_parlay([leg for leg, _ in legs])

    bt = None
    backtest_dict: dict[str, object] | None = None
    if not args.skip_backtest:
        print("running backtest (takes a few minutes)...")
        bt = run_backtest(matches)
        print(
            f"backtest: {bt.n_parlays} parlays, hit {bt.parlay_hit_rate * 100:.1f}%, "
            f"ROI {bt.roi * 100:+.1f}%"
        )
    elif Path(args.out).exists():
        try:
            prev = json.loads(Path(args.out).read_text())
            backtest_dict = prev.get("backtest") if isinstance(prev, dict) else None
        except (json.JSONDecodeError, OSError):
            backtest_dict = None

    payload = build_payload(
        matches=matches,
        backtest_result=bt,
        model=model,
        legs=legs,
        parlay=parlay,
        paper=paper,
        starting_bankroll=args.bankroll,
        fixture_teams=fixture_teams,
        backtest_dict=backtest_dict,
    )
    write_payload(payload, Path(args.out))
    print(f"[dashboard written to {args.out}]")


def _sport_key_to_league(sport_key: str) -> str:
    """Map a TheOddsAPI soccer sport key to our league code where known."""
    return {
        "soccer_epl": "E0",
        "soccer_la_liga": "SP1",
        "soccer_serie_a": "I1",
        "soccer_bundesliga": "D1",
        "soccer_ligue_one": "F1",
    }.get(sport_key, "")


if __name__ == "__main__":
    main()
