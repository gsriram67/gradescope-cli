"""Data models returned by the Gradescope backend."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Course:
    """A Gradescope course the account is enrolled in."""

    id: str
    name: str
    code: str | None = None
    url: str = ""


@dataclass(frozen=True)
class Assignment:
    """An assignment within a course."""

    id: str
    course_id: str
    title: str
    due_date: datetime | None = None
    url: str = ""


@dataclass(frozen=True)
class Submission:
    """A submission made to an assignment."""

    id: str
    course_id: str
    assignment_id: str
    url: str = ""


@dataclass(frozen=True)
class TestCaseResult:
    """Autograder result for a single test case."""

    __test__ = False  # not a pytest test class

    name: str
    score: float | None = None
    max_score: float | None = None
    status: str = "unknown"  # "passed" | "failed" | "unknown"


@dataclass(frozen=True)
class SubmissionStatus:
    """Parsed state of a submission page (autograder progress)."""

    status: str  # "pending" | "graded" | "error"
    score: float | None = None
    max_score: float | None = None
    test_cases: tuple[TestCaseResult, ...] = ()


@dataclass(frozen=True)
class AutograderResult:
    """Autograder outcome for a submission."""

    submission_id: str
    status: str  # "pending" | "graded" | "error"
    score: float | None = None
    max_score: float | None = None
    test_cases: list[TestCaseResult] = field(default_factory=list)


@dataclass(frozen=True)
class LeaderboardEntry:
    """One row of an assignment leaderboard."""

    rank: int
    name: str
    score: float
    submission_id: str | None = None
