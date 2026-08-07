"""Paper-trade tracker: CSV log, bankroll, streak, and the 5-loss pause rule."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

PAUSE_AFTER_LOSSES = 5

FIELDS = [
    "date",
    "sport",
    "league",
    "home",
    "away",
    "market",
    "line",
    "side",
    "odds",
    "stake",
    "result",  # "pending" | "win" | "loss"
    "payout",
    "note",
]


@dataclass(frozen=True, slots=True)
class Trade:
    date: date
    sport: str
    league: str
    home: str
    away: str
    market: str
    line: float
    side: str
    odds: float
    stake: float
    result: str
    payout: float
    note: str


class PaperBook:
    """Append-only CSV log of bets with bankroll / streak / pause helpers."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=FIELDS)
                writer.writeheader()

    def _rows(self) -> list[dict[str, str]]:
        with self.path.open(newline="") as f:
            return list(csv.DictReader(f))

    def append(
        self,
        *,
        sport: str,
        league: str,
        home: str,
        away: str,
        market: str = "totals",
        line: float = 2.5,
        side: str,
        odds: float,
        stake: float,
        note: str = "",
    ) -> None:
        with self.path.open("a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writerow(
                {
                    "date": date.today().isoformat(),
                    "sport": sport,
                    "league": league,
                    "home": home,
                    "away": away,
                    "market": market,
                    "line": line,
                    "side": side,
                    "odds": odds,
                    "stake": stake,
                    "result": "pending",
                    "payout": "",
                    "note": note,
                }
            )

    def settle(self, home: str, away: str, actual_total: float, *, line: float = 2.5) -> bool:
        """Settle the oldest pending trade for a fixture. Returns True if settled."""
        rows = self._rows()
        for row in rows:
            if row["result"] == "pending" and row["home"] == home and row["away"] == away:
                over = actual_total > float(row["line"] or line)
                won = (row["side"] == "over") == over
                row["result"] = "win" if won else "loss"
                row["payout"] = f"{float(row['odds']) * float(row['stake']):.2f}" if won else "0.00"
                self._rewrite(rows)
                return True
        return False

    def _rewrite(self, rows: list[dict[str, str]]) -> None:
        with self.path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)

    def trades(self) -> list[Trade]:
        out: list[Trade] = []
        for row in self._rows():
            out.append(
                Trade(
                    date=datetime.strptime(row["date"], "%Y-%m-%d").date(),
                    sport=row["sport"],
                    league=row["league"],
                    home=row["home"],
                    away=row["away"],
                    market=row["market"],
                    line=float(row["line"] or 0),
                    side=row["side"],
                    odds=float(row["odds"]),
                    stake=float(row["stake"]),
                    result=row["result"],
                    payout=float(row["payout"] or 0),
                    note=row["note"],
                )
            )
        return out

    def pending(self) -> list[Trade]:
        return [t for t in self.trades() if t.result == "pending"]

    def settled(self) -> list[Trade]:
        return [t for t in self.trades() if t.result in ("win", "loss")]

    def bankroll(self, starting: float) -> float:
        bankroll = starting
        for t in self.settled():
            bankroll += t.payout - t.stake
        return bankroll

    def net_pl(self) -> float:
        return sum(t.payout - t.stake for t in self.settled())

    def win_streak(self) -> tuple[int, str]:
        """Current consecutive results: (count, 'wins'|'losses')."""
        results = [t.result for t in self.settled()]
        if not results:
            return (0, "")
        last = results[-1]
        count = 0
        for r in reversed(results):
            if r != last:
                break
            count += 1
        return (count, "wins" if last == "win" else "losses")

    def is_paused(self) -> bool:
        count, kind = self.win_streak()
        return kind == "losses" and count >= PAUSE_AFTER_LOSSES

    def hit_rate(self) -> float:
        settled = self.settled()
        if not settled:
            return 0.0
        return sum(1 for t in settled if t.result == "win") / len(settled)

    def weekly_pl(self, week_start: date) -> float:
        week_end = week_start + timedelta(days=6)
        return sum(
            t.payout - t.stake
            for t in self.settled()
            if week_start <= t.date <= week_end
        )

    def status_line(self, starting: float) -> str:
        bankroll = self.bankroll(starting)
        count, kind = self.win_streak()
        paused = " PAUSED" if self.is_paused() else ""
        return (
            f"Bankroll: ${bankroll:.2f} (start ${starting:.2f}) | "
            f"Net P/L: ${self.net_pl():+.2f} | "
            f"Hit rate: {self.hit_rate() * 100:.1f}% | "
            f"Streak: {count} {kind}{paused}"
        )
