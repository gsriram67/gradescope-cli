"""Plain-text formatting helpers shared by the CLI and the TUI.

Pure functions (no widgets), so they are trivially unit-testable. The TUI
wraps these in Rich ``Text`` with the style names returned here.
"""

from __future__ import annotations

from datetime import datetime, timedelta

STATUS_LABELS = {
    "graded": "graded",
    "submitted": "submitted",
    "open": "open",
    "pending": "pending",
    "error": "error",
}

# Status -> TUI color.
STATUS_STYLES = {
    "graded": "green",
    "submitted": "yellow",
    "open": "cyan",
    "pending": "yellow",
    "error": "red",
}

# Due within this window is highlighted "soon".
DUE_SOON = timedelta(hours=48)


def fmt_due(due: datetime | None) -> str:
    return due.strftime("%Y-%m-%d %H:%M") if due is not None else "-"


def humanize_amount(delta: timedelta) -> str:
    """Humanize a duration: "3 days", "5 hours", "12 minutes", "just now"."""
    seconds = abs(delta.total_seconds())
    if seconds < 60:
        return "just now"
    minutes = seconds / 60
    if minutes < 60:
        n = int(minutes)
        return f"{n} minute{'s' if n != 1 else ''}"
    hours = minutes / 60
    if hours < 24:
        n = int(hours)
        return f"{n} hour{'s' if n != 1 else ''}"
    days = hours / 24
    n = int(days)
    return f"{n} day{'s' if n != 1 else ''}"


def due_text(due: datetime | None, *, now: datetime | None = None) -> str:
    """Absolute due date plus a relative hint, e.g. "2026-11-25 23:59 · in 1 day"."""
    if due is None:
        return "-"
    now = now or datetime.now()
    base = fmt_due(due)
    delta = due - now
    if delta.total_seconds() < 0:
        return f"{base} · overdue {humanize_amount(-delta)}"
    return f"{base} · in {humanize_amount(delta)}"


def due_style(due: datetime | None, *, now: datetime | None = None) -> str:
    """Color style for a due date: red when overdue, yellow when due soon."""
    if due is None:
        return ""
    now = now or datetime.now()
    delta = due - now
    if delta.total_seconds() < 0:
        return "red"
    if delta < DUE_SOON:
        return "yellow"
    return ""


def status_label(status: str | None) -> str:
    return STATUS_LABELS.get(status or "", status or "-")


def status_style(status: str | None) -> str:
    return STATUS_STYLES.get(status or "", "")


def score_bar(score: float | None, max_score: float | None, width: int = 12) -> str:
    """Bubbletea-style text progress bar, e.g. ``██████░░░░░░``."""
    if score is None or max_score is None or max_score <= 0:
        return "░" * width
    filled = min(width, max(0, round(score / max_score * width)))
    return "█" * filled + "░" * (width - filled)


def score_fraction(score: float | None, max_score: float | None) -> float | None:
    if score is None or max_score is None or max_score <= 0:
        return None
    return score / max_score


def score_text(score: float | None, max_score: float | None) -> str:
    """e.g. ``8.5/10 (85%)``."""
    if score is None or max_score is None:
        return "-"
    frac = score_fraction(score, max_score)
    pct = f" ({frac:.0%})" if frac is not None else ""
    return f"{score:g}/{max_score:g}{pct}"


def score_style(score: float | None, max_score: float | None) -> str:
    """Bar color: green >= 80%, yellow >= 50%, red below."""
    frac = score_fraction(score, max_score)
    if frac is None:
        return ""
    if frac >= 0.8:
        return "green"
    if frac >= 0.5:
        return "yellow"
    return "red"
