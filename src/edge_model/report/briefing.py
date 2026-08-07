"""Daily morning briefing: markdown report for the bettor's 30-minute window."""

from __future__ import annotations

from datetime import date

from edge_model.track.paper import PaperBook
from edge_model.value.filter import Leg, Parlay


def _fmt_pct(p: float) -> str:
    return f"{p * 100:.1f}%"


def _fmt_odds(o: float) -> str:
    return f"{o:.2f}"


def leg_line(leg: Leg) -> str:
    return (
        f"- **{leg.home} vs {leg.away}** | {leg.side.upper()} {leg.line:g} "
        f"@ {_fmt_odds(leg.decimal_odds)} | model {_fmt_pct(leg.model_prob)} "
        f"vs fair {_fmt_pct(leg.fair_implied)} | edge {_fmt_pct(leg.edge)}"
    )


def build_briefing(
    *,
    todays_date: date,
    candidate_legs: list[Leg],
    parlay: Parlay | None,
    paper: PaperBook,
    starting_bankroll: float,
    no_bet_reason: str | None = None,
) -> str:
    lines: list[str] = []
    lines.append(f"# Daily Briefing — {todays_date.isoformat()}")
    lines.append("")
    lines.append(f"> {paper.status_line(starting_bankroll)}")
    lines.append("")

    lines.append("## Candidate legs (all +EV candidates from your bookie odds)")
    if candidate_legs:
        for leg in candidate_legs:
            lines.append(leg_line(leg))
    else:
        lines.append("- None — no legs passed the +EV filter.")
    lines.append("")

    if paper.is_paused():
        lines.append("## STOP — PAUSED")
        lines.append("")
        lines.append(
            "5 consecutive losses reached. Do not place bets until the model "
            "is recalibrated and you review the weekly report."
        )
        lines.append("")
    elif parlay is None:
        lines.append("## NO BET TODAY")
        lines.append("")
        lines.append(
            no_bet_reason
            or "Fewer than 8 qualifying O1.5/U4.5 legs at 1.15-1.25, or "
            "their combined odds can't reach 5.0. Forcing a leg to hit 5.0 "
            "gives the bookmaker's margin a free ride — skip."
        )
        lines.append("")
    else:
        lines.append("## Recommended accumulator")
        lines.append("")
        for i, leg in enumerate(parlay.legs, 1):
            lines.append(f"{i}. {leg_line(leg)}")
        lines.append("")
        lines.append(
            f"Combined odds: **{_fmt_odds(parlay.combined_odds)}** | "
            f"model win prob: {_fmt_pct(parlay.model_prob)} | "
            f"EV per $1: {parlay.ev:+.3f} | "
            f"stake: **${parlay.stake:.0f}**"
        )
        lines.append("")
        lines.append(
            "Expected return on $1: "
            f"${parlay.expected_return:.2f} (break-even is $1.00)"
        )
        lines.append("")

    pending = paper.pending()
    if pending:
        lines.append("## Pending bets awaiting settlement")
        lines.append("")
        for t in pending:
            lines.append(
                f"- {t.date} {t.home} vs {t.away} | {t.side} {t.line:g} "
                f"@{t.odds:.2f} | stake ${t.stake:.0f}"
            )
        lines.append("")
    return "\n".join(lines)
