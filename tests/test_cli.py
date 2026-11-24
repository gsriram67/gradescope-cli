from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

import pytest

from gradescope_cli.api.models import (
    Assignment,
    AutograderResult,
    Course,
    LeaderboardEntry,
    Submission,
    TestCaseResult,
)
from gradescope_cli.cli import app
from gradescope_cli.exceptions import APIError
from gradescope_cli.tui.app import GradescopeApp


class FakeClient:
    """Implements GradescopeAPI with canned data and call recording."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def login(self, email: str, password: str) -> None:
        self.calls.append(("login", (email, password)))

    def list_courses(self) -> list[Course]:
        self.calls.append(("list_courses", ()))
        return [
            Course(id="111", name="DSC 190 - Capstone Project", code="DSC 190"),
            Course(id="222", name="CSE 151A", code="CSE 151A"),
        ]

    def list_assignments(self, course_id: str) -> list[Assignment]:
        self.calls.append(("list_assignments", (course_id,)))
        return [
            Assignment(
                id="777",
                course_id=course_id,
                title="Homework 1",
                due_date=datetime(2026, 11, 25, 23, 59),
            ),
            Assignment(id="888", course_id=course_id, title="Homework 2"),
        ]

    def submit(self, course_id: str, assignment_id: str, files: Sequence[str | Path]) -> Submission:
        self.calls.append(("submit", (course_id, assignment_id, tuple(files))))
        return Submission(
            id="999",
            course_id=course_id,
            assignment_id=assignment_id,
            url=f"/courses/{course_id}/assignments/{assignment_id}/submissions/999",
        )

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
            LeaderboardEntry(rank=1, name="Alice", score=99.5),
            LeaderboardEntry(rank=2, name="Bob", score=87.0),
        ]


@pytest.fixture
def fake_client() -> FakeClient:
    return FakeClient()


class TestParser:
    def test_submit_args(self) -> None:
        args = app.build_parser().parse_args(["submit", "111", "777", "a.py", "b.py"])
        assert args.course_id == "111"
        assert args.assignment_id == "777"
        assert args.files == [Path("a.py"), Path("b.py")]
        assert args.watch is False
        assert args.func is app.cmd_submit

    def test_status_watch_flag(self) -> None:
        args = app.build_parser().parse_args(["status", "1", "2", "3", "--watch"])
        assert args.watch is True
        assert args.func is app.cmd_status

    def test_requires_subcommand(self) -> None:
        with pytest.raises(SystemExit):
            app.build_parser().parse_args([])


class TestCommands:
    def test_courses(self, fake_client: FakeClient, capsys: pytest.CaptureFixture[str]) -> None:
        assert app.main(["courses"], client=fake_client) == 0
        out = capsys.readouterr().out
        assert "DSC 190 - Capstone Project" in out
        assert "111" in out
        assert fake_client.calls == [("list_courses", ())]

    def test_assignments(self, fake_client: FakeClient, capsys: pytest.CaptureFixture[str]) -> None:
        assert app.main(["assignments", "111"], client=fake_client) == 0
        out = capsys.readouterr().out
        assert "Homework 1" in out
        assert "2026-11-25 23:59" in out
        assert "-" in out  # Homework 2 has no due date

    def test_submit(self, fake_client: FakeClient, capsys: pytest.CaptureFixture[str]) -> None:
        rc = app.main(["submit", "111", "777", "solution.py"], client=fake_client)
        assert rc == 0
        out = capsys.readouterr().out
        assert "submission id: 999" in out
        name, call_args = fake_client.calls[0]
        assert name == "submit"
        assert call_args[:2] == ("111", "777")
        assert call_args[2] == (Path("solution.py"),)

    def test_submit_watch(
        self, fake_client: FakeClient, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = app.main(["submit", "111", "777", "a.py", "--watch"], client=fake_client)
        assert rc == 0
        out = capsys.readouterr().out
        assert "graded" in out
        assert "8.5 / 10" in out
        assert "test_basic" in out
        assert ("wait_for_autograder", ("111", "777", "999")) in fake_client.calls

    def test_status(self, fake_client: FakeClient, capsys: pytest.CaptureFixture[str]) -> None:
        assert app.main(["status", "111", "777", "999"], client=fake_client) == 0
        out = capsys.readouterr().out
        assert "status: graded" in out
        assert "8.5 / 10" in out

    def test_leaderboard(self, fake_client: FakeClient, capsys: pytest.CaptureFixture[str]) -> None:
        assert app.main(["leaderboard", "111", "777"], client=fake_client) == 0
        out = capsys.readouterr().out
        assert "Alice" in out and "99.5" in out
        assert "Bob" in out

    def test_tui_launches_app(
        self, fake_client: FakeClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        launched: list[GradescopeApp] = []
        monkeypatch.setattr(
            "gradescope_cli.tui.app.GradescopeApp.run",
            lambda self: launched.append(self),
        )
        rc = app.main(["tui"], client=fake_client)
        assert rc == 0
        assert len(launched) == 1
        assert launched[0].client is fake_client

    def test_error_handling(
        self, fake_client: FakeClient, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def boom() -> list[Course]:
            raise APIError("HTTP 500", status_code=500)

        fake_client.list_courses = boom  # type: ignore[method-assign]
        rc = app.main(["courses"], client=fake_client)
        assert rc == 1
        assert "error: HTTP 500" in capsys.readouterr().err
