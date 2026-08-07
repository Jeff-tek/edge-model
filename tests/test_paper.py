"""Tests for the paper-trade tracker: log, settle, streak, pause rule."""

from __future__ import annotations

from datetime import date

import pytest

from edge_model.track.paper import PAUSE_AFTER_LOSSES, PaperBook


def test_append_and_pending(tmp_path) -> None:
    book = PaperBook(tmp_path / "trades.csv")
    book.append(sport="football", league="E0", home="Arsenal", away="Chelsea",
                side="over", odds=1.55, stake=100.0)
    pending = book.pending()
    assert len(pending) == 1
    assert pending[0].result == "pending"
    assert pending[0].date == date.today()


def test_settle_win_and_loss(tmp_path) -> None:
    book = PaperBook(tmp_path / "trades.csv")
    book.append(sport="football", league="E0", home="A", away="B",
                side="over", line=2.5, odds=1.60, stake=100.0)
    book.append(sport="football", league="E0", home="C", away="D",
                side="under", line=2.5, odds=1.50, stake=100.0)

    assert book.settle("A", "B", actual_total=3.0, line=2.5) is True  # over wins
    assert book.settle("C", "D", actual_total=4.0, line=2.5) is True  # under loses

    settled = book.settled()
    assert len(settled) == 2
    assert settled[0].result == "win"
    assert settled[0].payout == pytest.approx(160.0)
    assert settled[1].result == "loss"
    assert settled[1].payout == 0.0

    assert book.net_pl() == pytest.approx(160.0 - 200.0)
    assert book.bankroll(starting=2000.0) == pytest.approx(1960.0)
    assert book.hit_rate() == pytest.approx(0.5)


def test_streak_and_pause(tmp_path) -> None:
    book = PaperBook(tmp_path / "trades.csv")
    for i in range(PAUSE_AFTER_LOSSES):
        book.append(sport="football", league="E0", home=f"H{i}", away="B",
                    side="over", odds=1.5, stake=100.0)
        book.settle(f"H{i}", "B", actual_total=1.0)  # over loses
    assert book.is_paused() is True
    count, kind = book.win_streak()
    assert kind == "losses"
    assert count == PAUSE_AFTER_LOSSES


def test_pause_releases_after_win(tmp_path) -> None:
    book = PaperBook(tmp_path / "trades.csv")
    for i in range(PAUSE_AFTER_LOSSES):
        book.append(sport="football", league="E0", home=f"H{i}", away="B",
                    side="over", odds=1.5, stake=100.0)
        book.settle(f"H{i}", "B", actual_total=1.0)
    book.append(sport="football", league="E0", home="WIN", away="B",
                side="over", odds=1.5, stake=100.0)
    book.settle("WIN", "B", actual_total=4.0)
    assert book.is_paused() is False


def test_status_line(tmp_path) -> None:
    book = PaperBook(tmp_path / "trades.csv")
    line = book.status_line(starting=2000.0)
    assert "Bankroll: $2000.00" in line
