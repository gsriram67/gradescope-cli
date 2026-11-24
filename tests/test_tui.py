"""Headless tests for the textual TUI, using textual's Pilot (run_test)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

from textual.pilot import Pilot
from textual.widgets import DataTable, Input

from gradescope_cli.tui.app import GradescopeApp
from gradescope_cli.tui.screens import (
    AssignmentScreen,
    AssignmentsScreen,
    CoursesScreen,
    LeaderboardScreen,
    SubmitModal,
)
from tests.test_cli import FakeClient


def run(coro: Coroutine[Any, Any, Any]) -> Any:
    return asyncio.run(coro)


async def wait_for(pilot: Pilot[Any], predicate: Callable[[], bool], timeout: float = 5.0) -> None:
    """Wait until predicate() is true (workers run in threads, so poll)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await pilot.pause(0.05)
    raise AssertionError("condition not met within timeout")


def make_app() -> tuple[GradescopeApp, FakeClient]:
    client = FakeClient()
    return GradescopeApp(client), client


def table_rows(app: GradescopeApp) -> int:
    return app.screen.query_one(DataTable).row_count


def test_courses_screen_lists_courses() -> None:
    app, _ = make_app()

    async def go() -> None:
        async with app.run_test() as pilot:
            await wait_for(pilot, lambda: table_rows(app) == 2)
            assert isinstance(app.screen, CoursesScreen)

    run(go())


def test_navigate_to_assignments() -> None:
    app, _ = make_app()

    async def go() -> None:
        async with app.run_test() as pilot:
            await wait_for(pilot, lambda: table_rows(app) == 2)
            await pilot.press("enter")  # open first course
            await wait_for(
                pilot,
                lambda: isinstance(app.screen, AssignmentsScreen) and table_rows(app) == 2,
            )
            screen = app.screen
            assert isinstance(screen, AssignmentsScreen)
            assert screen.course.id == "111"

    run(go())


def test_open_assignment_and_leaderboard() -> None:
    app, _ = make_app()

    async def go() -> None:
        async with app.run_test() as pilot:
            await wait_for(pilot, lambda: table_rows(app) == 2)
            await pilot.press("enter")
            await wait_for(pilot, lambda: isinstance(app.screen, AssignmentsScreen))
            await wait_for(pilot, lambda: table_rows(app) == 2)
            await pilot.press("enter")  # open first assignment
            await wait_for(pilot, lambda: isinstance(app.screen, AssignmentScreen))
            await pilot.press("l")  # leaderboard
            await wait_for(
                pilot,
                lambda: isinstance(app.screen, LeaderboardScreen) and table_rows(app) == 2,
            )

    run(go())


def test_submit_flow_watches_autograder(tmp_path: Path) -> None:
    code = tmp_path / "solution.py"
    code.write_text("print('hi')\n")
    app, client = make_app()

    async def go() -> None:
        async with app.run_test() as pilot:
            await wait_for(pilot, lambda: table_rows(app) == 2)
            await pilot.press("enter")  # course 111
            await wait_for(pilot, lambda: isinstance(app.screen, AssignmentsScreen))
            await wait_for(pilot, lambda: table_rows(app) == 2)
            await pilot.press("s")  # submit modal for highlighted assignment
            await wait_for(pilot, lambda: isinstance(app.screen, SubmitModal))
            app.screen.query_one("#paths", Input).value = str(code)
            await pilot.press("enter")  # submit the modal
            # assignment screen opens and auto-submits, then watches autograder
            await wait_for(pilot, lambda: isinstance(app.screen, AssignmentScreen))
            screen = app.screen
            assert isinstance(screen, AssignmentScreen)
            await wait_for(
                pilot,
                lambda: "graded" in screen.status_text,
            )
            assert "8.5 / 10" in screen.status_text
            assert screen.submission_id == "999"
            assert ("submit", ("111", "777", (code,))) in client.calls

    run(go())


def test_submit_modal_rejects_missing_files(tmp_path: Path) -> None:
    app, client = make_app()

    async def go() -> None:
        async with app.run_test() as pilot:
            await wait_for(pilot, lambda: table_rows(app) == 2)
            await pilot.press("enter")
            await wait_for(pilot, lambda: isinstance(app.screen, AssignmentsScreen))
            await wait_for(pilot, lambda: table_rows(app) == 2)
            await pilot.press("s")
            await wait_for(pilot, lambda: isinstance(app.screen, SubmitModal))
            app.screen.query_one("#paths", Input).value = str(tmp_path / "nope.py")
            await pilot.press("enter")
            await pilot.pause(0.2)
            # modal stays open, nothing submitted
            assert isinstance(app.screen, SubmitModal)
            assert not any(name == "submit" for name, _ in client.calls)

    run(go())


def test_autograder_status_via_submission_id_modal() -> None:
    app, _ = make_app()

    async def go() -> None:
        async with app.run_test() as pilot:
            await wait_for(pilot, lambda: table_rows(app) == 2)
            await pilot.press("enter")
            await wait_for(pilot, lambda: isinstance(app.screen, AssignmentsScreen))
            await wait_for(pilot, lambda: table_rows(app) == 2)
            await pilot.press("enter")
            await wait_for(pilot, lambda: isinstance(app.screen, AssignmentScreen))
            screen = app.screen
            assert isinstance(screen, AssignmentScreen)
            await pilot.press("g")  # no submission yet -> asks for id
            await wait_for(pilot, lambda: app.screen.__class__.__name__ == "SubmissionIdModal")
            app.screen.query_one("#submission-id", Input).value = "999"
            await pilot.press("enter")
            await wait_for(pilot, lambda: isinstance(app.screen, AssignmentScreen))
            await wait_for(
                pilot,
                lambda: "graded" in screen.status_text,
            )
            assert screen.submission_id == "999"

    run(go())
