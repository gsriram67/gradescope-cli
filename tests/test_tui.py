"""Headless tests for the textual TUI, using textual's Pilot (run_test)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

import pytest
from textual.css.query import NoMatches
from textual.pilot import Pilot
from textual.widgets import DataTable, Input, Static, Tree

from gradescope_cli.api.models import Course
from gradescope_cli.exceptions import AuthError
from gradescope_cli.tui.app import GradescopeApp
from gradescope_cli.tui.screens import (
    AssignmentScreen,
    AssignmentsScreen,
    CoursesScreen,
    LeaderboardScreen,
    LoginScreen,
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


def make_app(*, authenticated: bool = True) -> tuple[GradescopeApp, FakeClient]:
    client = FakeClient()
    if authenticated:
        client.login("student@ucsd.edu", "pw")
    return GradescopeApp(client), client


def table_rows(app: GradescopeApp) -> int:
    return app.screen.query_one(DataTable).row_count


def rows_loaded(app: GradescopeApp, n: int = 2) -> bool:
    """True when the current screen's list has n entries (Tree terms or table rows)."""
    if isinstance(app.screen, CoursesScreen):
        try:
            tree = app.screen.query_one("#courses-tree", Tree)
        except NoMatches:
            return False
        return len(tree.root.children) == n
    try:
        return app.screen.query_one(DataTable).row_count == n
    except NoMatches:
        return False


class FailingLoginClient(FakeClient):
    def login(self, email: str, password: str) -> None:
        raise AuthError("Gradescope login failed ... SSO ... not supported")


def login_screen(app: GradescopeApp) -> LoginScreen:
    screen = app.screen
    assert isinstance(screen, LoginScreen)
    return screen


def test_login_screen_shown_when_unauthenticated() -> None:
    app, _ = make_app(authenticated=False)

    async def go() -> None:
        async with app.run_test() as pilot:
            await wait_for(pilot, lambda: isinstance(app.screen, LoginScreen))
            # email hint is prefilled when provided
            assert login_screen(app).query_one("#email", Input).value == ""

    run(go())


def test_login_screen_prefills_email_hint() -> None:
    client = FakeClient()
    app = GradescopeApp(client, email_hint="hint@ucsd.edu")

    async def go() -> None:
        async with app.run_test() as pilot:
            await wait_for(pilot, lambda: isinstance(app.screen, LoginScreen))
            assert login_screen(app).query_one("#email", Input).value == "hint@ucsd.edu"

    run(go())


def test_login_flow_then_courses() -> None:
    app, client = make_app(authenticated=False)

    async def go() -> None:
        async with app.run_test() as pilot:
            await wait_for(pilot, lambda: isinstance(app.screen, LoginScreen))
            screen = login_screen(app)
            screen.query_one("#email", Input).value = "student@ucsd.edu"
            screen.query_one("#password", Input).value = "hunter2"
            await pilot.press("enter")
            await wait_for(pilot, lambda: isinstance(app.screen, CoursesScreen))
            await wait_for(pilot, lambda: rows_loaded(app))
            assert ("login", ("student@ucsd.edu", "hunter2")) in client.calls
            assert client.is_authenticated

    run(go())


def test_login_remember_me_saves_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from textual.widgets import Checkbox

    from gradescope_cli.config import credentials_path, load_cached_credentials

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("GRADESCOPE_EMAIL", raising=False)
    monkeypatch.delenv("GRADESCOPE_PASSWORD", raising=False)
    app, _ = make_app(authenticated=False)

    async def go() -> None:
        async with app.run_test() as pilot:
            await wait_for(pilot, lambda: isinstance(app.screen, LoginScreen))
            screen = login_screen(app)
            screen.query_one("#email", Input).value = "student@ucsd.edu"
            screen.query_one("#password", Input).value = "hunter2"
            screen.query_one("#save", Checkbox).value = True
            await pilot.press("enter")
            await wait_for(pilot, lambda: isinstance(app.screen, CoursesScreen))

    run(go())
    saved = load_cached_credentials(credentials_path())
    assert saved is not None
    assert saved.email == "student@ucsd.edu"
    assert saved.password == "hunter2"


def test_login_failure_shows_error() -> None:
    app = GradescopeApp(FailingLoginClient())

    async def go() -> None:
        async with app.run_test() as pilot:
            await wait_for(pilot, lambda: isinstance(app.screen, LoginScreen))
            screen = login_screen(app)
            screen.query_one("#email", Input).value = "student@ucsd.edu"
            screen.query_one("#password", Input).value = "wrong"
            await pilot.press("enter")
            await wait_for(pilot, lambda: "SSO" in screen.error_text)
            # still on the login screen
            assert isinstance(app.screen, LoginScreen)

    run(go())


def test_authenticated_client_skips_login_screen() -> None:
    client = FakeClient()
    client.is_authenticated = True
    app = GradescopeApp(client)

    async def go() -> None:
        async with app.run_test() as pilot:
            await wait_for(pilot, lambda: isinstance(app.screen, CoursesScreen))
            await wait_for(pilot, lambda: rows_loaded(app))

    run(go())


class EmptyCoursesClient(FakeClient):
    def list_courses(self) -> list[Course]:
        self.calls.append(("list_courses", ()))
        return []


def test_empty_courses_shows_visible_hint() -> None:
    """Regression test: an empty course list must be visible, not a blank table."""
    client = EmptyCoursesClient()
    client.login("student@ucsd.edu", "pw")
    app = GradescopeApp(client)

    async def go() -> None:
        async with app.run_test() as pilot:
            await wait_for(
                pilot,
                lambda: (
                    isinstance(app.screen, CoursesScreen)
                    and "No courses found" in str(app.screen.query_one(".hint", Static).content)
                ),
            )
            tree = app.screen.query_one("#courses-tree", Tree)
            assert len(tree.root.children) == 0

    run(go())


def test_courses_screen_lists_courses() -> None:
    app, _ = make_app()

    async def go() -> None:
        async with app.run_test() as pilot:
            await wait_for(pilot, lambda: rows_loaded(app))
            assert isinstance(app.screen, CoursesScreen)

    run(go())


def test_term_sections_fold_and_unfold() -> None:
    app, _ = make_app()

    async def go() -> None:
        async with app.run_test() as pilot:
            await wait_for(pilot, lambda: rows_loaded(app))
            tree = app.screen.query_one("#courses-tree", Tree)
            term_node = tree.root.children[0]
            assert term_node.is_expanded
            await pilot.press("down")  # cursor -> first term node (line 0)
            await pilot.press("enter")  # fold
            await wait_for(pilot, lambda: not term_node.is_expanded)
            await pilot.press("enter")  # unfold again
            await wait_for(pilot, lambda: term_node.is_expanded)

    run(go())


def test_click_course_in_tree_opens_it() -> None:
    app, _ = make_app()

    async def go() -> None:
        async with app.run_test(size=(100, 30)) as pilot:
            await wait_for(pilot, lambda: rows_loaded(app))
            # second line of the tree = first course under the first term
            await pilot.click("#courses-tree", offset=(10, 1))
            await wait_for(pilot, lambda: isinstance(app.screen, AssignmentsScreen))

    run(go())


def test_navigate_to_assignments() -> None:
    app, _ = make_app()

    async def go() -> None:
        async with app.run_test() as pilot:
            await wait_for(pilot, lambda: rows_loaded(app))
            await pilot.press("down", "down")  # -> first course node (line 1)
            await pilot.press("enter")  # open first course
            await wait_for(
                pilot,
                lambda: isinstance(app.screen, AssignmentsScreen) and table_rows(app) == 2,
            )
            screen = app.screen
            assert isinstance(screen, AssignmentsScreen)
            assert screen.course.id == "111"
            # score column renders a graphical bar for the graded assignment
            row = app.screen.query_one(DataTable).get_row_at(0)
            assert "█" in str(row[4]) and "8.5/10" in str(row[4])
            assert str(row[3]) == "graded"
            # due column has a relative hint ("in 1 day" / "overdue ...")
            assert "·" in str(row[2])
            # 8.5/10 = 85% -> green bar (Rich span style)
            assert any(str(span.style) == "green" for span in row[4].spans)

    run(go())


def test_click_opens_assignment() -> None:
    """A single mouse click on a row should open it (RowClickTable)."""
    app, _ = make_app()

    async def go() -> None:
        async with app.run_test(size=(100, 30)) as pilot:
            await wait_for(pilot, lambda: rows_loaded(app))  # courses
            await pilot.press("down", "down")  # -> first course node
            await pilot.press("enter")
            await wait_for(pilot, lambda: isinstance(app.screen, AssignmentsScreen))
            await wait_for(pilot, lambda: table_rows(app) == 2)  # assignments
            await pilot.click(DataTable, offset=(8, 1))  # first data row
            await wait_for(pilot, lambda: isinstance(app.screen, AssignmentScreen))

    run(go())


def test_open_assignment_and_leaderboard() -> None:
    app, _ = make_app()

    async def go() -> None:
        async with app.run_test() as pilot:
            await wait_for(pilot, lambda: rows_loaded(app))
            await pilot.press("down", "down")  # -> first course node
            await pilot.press("enter")
            await wait_for(pilot, lambda: isinstance(app.screen, AssignmentsScreen))
            await wait_for(pilot, lambda: table_rows(app) == 2)  # assignments table
            await pilot.press("enter")  # open first assignment (cursor on row 0)
            await wait_for(pilot, lambda: isinstance(app.screen, AssignmentScreen))
            await pilot.press("l")  # leaderboard
            await wait_for(
                pilot,
                lambda: isinstance(app.screen, LeaderboardScreen) and table_rows(app) == 2,
            )
            # per-category columns: Rank, Name, task 1, Total
            lb = app.screen.query_one(DataTable)
            assert [c.label.plain for c in lb.ordered_columns] == [
                "Rank",
                "Name",
                "task 1",
                "Total",
            ]

    run(go())


def test_assignment_screen_lists_and_tracks_submissions() -> None:
    app, _ = make_app()

    async def go() -> None:
        async with app.run_test() as pilot:
            await wait_for(pilot, lambda: rows_loaded(app))  # courses
            await pilot.press("down", "down")  # -> first course node
            await pilot.press("enter")
            await wait_for(pilot, lambda: isinstance(app.screen, AssignmentsScreen))
            await wait_for(pilot, lambda: table_rows(app) == 2)  # assignments
            await pilot.press("enter")  # open assignment
            await wait_for(pilot, lambda: isinstance(app.screen, AssignmentScreen))
            screen = app.screen
            assert isinstance(screen, AssignmentScreen)
            # submissions table loads with the FakeClient history
            subs = screen.query_one("#submissions", DataTable)
            await wait_for(pilot, lambda: subs.row_count == 2)
            # press enter on the first submission -> autograder result shown
            subs.focus()
            await pilot.press("enter")
            await wait_for(pilot, lambda: "graded" in screen.status_text)
            assert screen.submission_id == "999"
            assert "8.5/10" in screen.status_text

    run(go())


def test_submit_flow_watches_autograder(tmp_path: Path) -> None:
    code = tmp_path / "solution.py"
    code.write_text("print('hi')\n")
    app, client = make_app()

    async def go() -> None:
        async with app.run_test() as pilot:
            await wait_for(pilot, lambda: rows_loaded(app))
            await pilot.press("down", "down")  # -> first course node
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
            assert "8.5/10" in screen.status_text
            assert screen.submission_id == "999"
            assert ("submit", ("111", "777", (code,))) in client.calls

    run(go())


def test_submit_modal_rejects_missing_files(tmp_path: Path) -> None:
    app, client = make_app()

    async def go() -> None:
        async with app.run_test() as pilot:
            await wait_for(pilot, lambda: rows_loaded(app))
            await pilot.press("down", "down")  # -> first course node
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
            await wait_for(pilot, lambda: rows_loaded(app))
            await pilot.press("down", "down")  # -> first course node
            await pilot.press("enter")
            await wait_for(pilot, lambda: isinstance(app.screen, AssignmentsScreen))
            await wait_for(pilot, lambda: rows_loaded(app))
            await pilot.press("down", "down")  # -> first course node
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
