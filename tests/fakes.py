"""Shared fake API client for TUI tests (implements GradescopeAPI)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

from gradescope_cli.api.models import (
    Assignment,
    AutograderResult,
    Course,
    LeaderboardEntry,
    Submission,
    TestCaseResult,
)


class FakeClient:
    """Implements GradescopeAPI with canned data and call recording."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.email: str | None = None
        self.is_authenticated = False

    def login(self, email: str, password: str) -> None:
        self.calls.append(("login", (email, password)))
        self.email = email
        self.is_authenticated = True

    def list_courses(self) -> list[Course]:
        self.calls.append(("list_courses", ()))
        return [
            Course(id="111", name="DSC 190 - Capstone Project", code="DSC 190", term="Fall 2026"),
            Course(id="222", name="CSE 151A", code="CSE 151A", term="Spring 2026"),
        ]

    def list_assignments(self, course_id: str) -> list[Assignment]:
        self.calls.append(("list_assignments", (course_id,)))
        return [
            Assignment(
                id="777",
                course_id=course_id,
                title="Homework 1",
                due_date=datetime(2026, 11, 25, 23, 59),
                status="graded",
                score=8.5,
                max_score=10.0,
            ),
            Assignment(id="888", course_id=course_id, title="Homework 2", status="open"),
        ]

    def submit(self, course_id: str, assignment_id: str, files: Sequence[str | Path]) -> Submission:
        self.calls.append(("submit", (course_id, assignment_id, tuple(files))))
        return Submission(
            id="999",
            course_id=course_id,
            assignment_id=assignment_id,
            url=f"/courses/{course_id}/assignments/{assignment_id}/submissions/999",
        )

    def list_submissions(self, course_id: str, assignment_id: str) -> list[Submission]:
        self.calls.append(("list_submissions", (course_id, assignment_id)))
        return [
            Submission(
                id="999",
                course_id=course_id,
                assignment_id=assignment_id,
                submitted_at=datetime(2026, 11, 24, 10, 0),
                score=8.5,
                status="graded",
            ),
            Submission(
                id="998",
                course_id=course_id,
                assignment_id=assignment_id,
                submitted_at=datetime(2026, 11, 23, 9, 0),
                status="submitted",
            ),
        ]

    def get_autograder_result(
        self, course_id: str, assignment_id: str, submission_id: str
    ) -> AutograderResult:
        self.calls.append(("get_autograder_result", (course_id, assignment_id, submission_id)))
        return AutograderResult(
            submission_id=submission_id,
            status="graded",
            score=8.5,
            max_score=10.0,
            test_cases=[
                TestCaseResult(name="test_basic", score=5.0, max_score=5.0, status="passed")
            ],
        )

    def wait_for_autograder(
        self,
        course_id: str,
        assignment_id: str,
        submission_id: str,
        *,
        poll_interval: float = 5.0,
        timeout: float = 600.0,
        sleep: Callable[[float], None] = lambda _: None,
    ) -> AutograderResult:
        self.calls.append(("wait_for_autograder", (course_id, assignment_id, submission_id)))
        return self.get_autograder_result(course_id, assignment_id, submission_id)

    def get_leaderboard(self, course_id: str, assignment_id: str) -> list[LeaderboardEntry]:
        self.calls.append(("get_leaderboard", (course_id, assignment_id)))
        return [
            LeaderboardEntry(rank=1, name="Alice", score=99.5, scores={"task 1": 99.5}),
            LeaderboardEntry(rank=2, name="Bob", score=87.0, scores={"task 1": 87.0}),
        ]
