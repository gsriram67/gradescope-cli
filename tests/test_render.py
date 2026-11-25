"""Tests for the shared text-formatting helpers (render.py)."""

from __future__ import annotations

from datetime import datetime, timedelta

from gradescope_cli import render

NOW = datetime(2026, 11, 24, 12, 0)


class TestHumanize:
    def test_amounts(self) -> None:
        assert render.humanize_amount(timedelta(seconds=30)) == "just now"
        assert render.humanize_amount(timedelta(minutes=5)) == "5 minutes"
        assert render.humanize_amount(timedelta(minutes=1)) == "1 minute"
        assert render.humanize_amount(timedelta(hours=3)) == "3 hours"
        assert render.humanize_amount(timedelta(hours=26)) == "1 day"
        assert render.humanize_amount(timedelta(days=5)) == "5 days"

    def test_due_text_future_and_past(self) -> None:
        future = NOW + timedelta(days=2)
        past = NOW - timedelta(days=3)
        assert render.due_text(future, now=NOW) == "2026-11-26 12:00 · in 2 days"
        assert render.due_text(past, now=NOW) == "2026-11-21 12:00 · overdue 3 days"
        assert render.due_text(None) == "-"

    def test_due_style(self) -> None:
        assert render.due_style(NOW - timedelta(hours=1), now=NOW) == "red"  # overdue
        assert render.due_style(NOW + timedelta(hours=24), now=NOW) == "yellow"  # due soon
        assert render.due_style(NOW + timedelta(days=10), now=NOW) == ""  # fine
        assert render.due_style(None) == ""

    def test_due_compact(self) -> None:
        # NOW = 2026-11-24 12:00
        assert render.due_compact(NOW - timedelta(days=39), now=NOW) == "10-16 12:00 · overdue 39d"
        assert (
            render.due_compact(NOW + timedelta(days=2, hours=3), now=NOW) == "11-26 15:00 · in 2d"
        )
        assert render.due_compact(None) == "-"

    def test_humanize_short(self) -> None:
        assert render.humanize_amount(timedelta(days=39), short=True) == "39d"
        assert render.humanize_amount(timedelta(hours=5), short=True) == "5h"
        assert render.humanize_amount(timedelta(minutes=12), short=True) == "12m"
        assert render.humanize_amount(timedelta(seconds=30), short=True) == "now"


class TestScore:
    def test_bar(self) -> None:
        assert render.score_bar(10, 10) == "█" * 12
        assert render.score_bar(5, 10) == "█" * 6 + "░" * 6
        assert render.score_bar(None, 10) == "░" * 12
        assert render.score_bar(5, 0) == "░" * 12

    def test_score_text(self) -> None:
        assert render.score_text(8.5, 10) == "8.5/10 (85%)"
        assert render.score_text(None, 10) == "-"

    def test_score_style(self) -> None:
        assert render.score_style(9, 10) == "green"
        assert render.score_style(6, 10) == "yellow"
        assert render.score_style(2, 10) == "red"
        assert render.score_style(None, 10) == ""


class TestStatus:
    def test_labels_and_styles(self) -> None:
        assert render.status_label("graded") == "graded"
        assert render.status_label(None) == "-"
        assert render.status_style("graded") == "green"
        assert render.status_style("open") == "cyan"
        assert render.status_style("weird") == ""
