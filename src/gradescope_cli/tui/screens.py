"""Screens and modals for the gradescope-cli TUI.

Navigation: courses -> assignments -> assignment detail (submit files,
watch the autograder, leaderboard). All network calls run in thread
workers so the UI never blocks; results are applied via call_from_thread.
"""

from __future__ import annotations

import time
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.css.query import NoMatches
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    ProgressBar,
    Static,
)

from gradescope_cli.api.client import GradescopeAPI
from gradescope_cli.api.models import (
    Assignment,
    AutograderResult,
    Course,
    LeaderboardEntry,
    Submission,
)
from gradescope_cli.exceptions import GradescopeError

if TYPE_CHECKING:
    from gradescope_cli.tui.app import GradescopeApp

POLL_INTERVAL = 3.0
POLL_TIMEOUT = 600.0


def fmt_due(due: datetime | None) -> str:
    return due.strftime("%Y-%m-%d %H:%M") if due is not None else "-"


def score_bar(score: float | None, max_score: float | None, width: int = 12) -> str:
    """Bubbletea-style text progress bar, e.g. ``██████░░░░░░``."""
    if score is None or max_score is None or max_score <= 0:
        return "░" * width
    filled = min(width, max(0, round(score / max_score * width)))
    return "█" * filled + "░" * (width - filled)


def fmt_score(score: float | None, max_score: float | None) -> str:
    if score is not None and max_score is not None:
        return f"{score:g}/{max_score:g}"
    return "-"


class GradescopeScreen(Screen[None]):
    """Base screen with access to the shared API client."""

    @property
    def client(self) -> GradescopeAPI:
        return cast("GradescopeApp", self.app).client

    def notify_error(self, exc: Exception) -> None:
        self.show_error(str(exc))

    def show_error(self, message: str) -> None:
        """Show an error as a toast AND persistently in the hint line."""
        self.app.notify(f"error: {message}", severity="error", title="Gradescope")
        with suppress(NoMatches):
            self.query_one(".hint", Static).update(f"error: {message}  (r: retry)")

    def set_hint(self, message: str) -> None:
        with suppress(NoMatches):
            self.query_one(".hint", Static).update(message)


class LoginScreen(GradescopeScreen):
    """Sign in with a regular Gradescope account (email + password, not SSO)."""

    BINDINGS = [Binding("q", "app.quit", "Quit")]

    CSS = """
    LoginScreen {
        align: center middle;
    }
    #login-box {
        width: 60;
        height: auto;
        padding: 1 2;
        border: solid $primary;
        background: $surface;
    }
    #login-title {
        text-style: bold;
        padding-bottom: 1;
    }
    #login-error {
        color: $error;
        height: auto;
        padding-top: 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="login-box"):
            yield Static("Sign in to Gradescope", id="login-title")
            yield Label("Email")
            yield Input(id="email", placeholder="you@ucsd.edu")
            yield Label("Password")
            yield Input(id="password", password=True)
            yield Button("Log In", id="login", variant="primary")
            yield Static(id="login-error")
        yield Footer()

    def __init__(self) -> None:
        super().__init__()
        self.error_text = ""

    def on_mount(self) -> None:
        hint = cast("GradescopeApp", self.app).email_hint
        if hint:
            self.query_one("#email", Input).value = hint

    @on(Button.Pressed, "#login")
    def _on_login_button(self) -> None:
        self._try_login()

    @on(Input.Submitted)
    def _on_input_submitted(self) -> None:
        self._try_login()

    def _try_login(self) -> None:
        email = self.query_one("#email", Input).value.strip()
        password = self.query_one("#password", Input).value
        if not email or not password:
            self._show_error("email and password are required")
            return
        self._show_error("signing in...")
        self.login_worker(email, password)

    @work(thread=True)
    def login_worker(self, email: str, password: str) -> None:
        try:
            self.client.login(email, password)
        except GradescopeError as exc:
            self.app.call_from_thread(self._show_error, str(exc))
            return
        self.app.call_from_thread(self._on_success)

    def _show_error(self, message: str) -> None:
        self.error_text = message
        self.query_one("#login-error", Static).update(message)

    def _on_success(self) -> None:
        self.app.switch_screen(CoursesScreen())


class CoursesScreen(GradescopeScreen):
    """Lists all courses; enter opens one."""

    BINDINGS = [
        Binding("enter", "open_course", "Open"),
        Binding("r", "reload", "Refresh"),
        Binding("q", "app.quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._courses: dict[str, Course] = {}

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Courses  (enter: open · r: refresh · q: quit)", classes="hint")
        yield DataTable(cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_column("ID", key="id", width=10)
        table.add_column("Term", key="term", width=12)
        table.add_column("Course", key="name")
        table.add_column("Code", key="code", width=12)
        self.set_hint("loading courses...")
        self.reload_courses()

    @work(thread=True)
    def reload_courses(self) -> None:
        try:
            courses = self.client.list_courses()
        except GradescopeError as exc:
            self.app.call_from_thread(self.show_error, str(exc))
            return
        self.app.call_from_thread(self.populate_courses, courses)

    def populate_courses(self, courses: list[Course]) -> None:
        table = self.query_one(DataTable)
        table.clear()
        self._courses = {}
        for course in courses:
            table.add_row(
                course.id, course.term or "-", course.name, course.code or "", key=course.id
            )
            self._courses[course.id] = course
        if not courses:
            self.set_hint("No courses found — are you enrolled? (r: retry · q: quit)")

    def action_reload(self) -> None:
        self.reload_courses()

    @on(DataTable.RowSelected)
    def open_course(self, event: DataTable.RowSelected) -> None:
        course = self._courses.get(str(event.row_key.value))
        if course is not None:
            self.app.push_screen(AssignmentsScreen(course))


class AssignmentsScreen(GradescopeScreen):
    """Lists assignments of a course with due dates."""

    BINDINGS = [
        Binding("enter", "open_assignment", "Open"),
        Binding("s", "submit", "Submit files"),
        Binding("l", "leaderboard", "Leaderboard"),
        Binding("r", "reload", "Refresh"),
        Binding("escape", "back", "Back"),
    ]

    def __init__(self, course: Course) -> None:
        super().__init__()
        self.course = course
        self._assignments: dict[str, Assignment] = {}

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            f"{self.course.name} (course {self.course.id}) — "
            "enter: open · s: submit · l: leaderboard · r: refresh · esc: back",
            classes="hint",
        )
        yield DataTable(cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_column("ID", key="id", width=10)
        table.add_column("Assignment", key="title")
        table.add_column("Due", key="due", width=18)
        table.add_column("Status", key="status", width=10)
        table.add_column("Score", key="score", width=22)
        self.set_hint(f"loading assignments for {self.course.name}...")
        self.reload_assignments()

    @work(thread=True)
    def reload_assignments(self) -> None:
        try:
            assignments = self.client.list_assignments(self.course.id)
        except GradescopeError as exc:
            self.app.call_from_thread(self.show_error, str(exc))
            return
        self.app.call_from_thread(self.populate_assignments, assignments)

    def populate_assignments(self, assignments: list[Assignment]) -> None:
        table = self.query_one(DataTable)
        table.clear()
        self._assignments = {}
        for assignment in assignments:
            score_cell = (
                f"{score_bar(assignment.score, assignment.max_score)} "
                f"{fmt_score(assignment.score, assignment.max_score)}"
                if assignment.score is not None
                else "-"
            )
            table.add_row(
                assignment.id,
                assignment.title,
                fmt_due(assignment.due_date),
                assignment.status or "-",
                score_cell,
                key=assignment.id,
            )
            self._assignments[assignment.id] = assignment
        if not assignments:
            self.set_hint("No assignments found. (r: retry · esc: back)")

    def action_reload(self) -> None:
        self.reload_assignments()

    def action_back(self) -> None:
        self.app.pop_screen()

    def current_assignment(self) -> Assignment | None:
        table = self.query_one(DataTable)
        cell_key = table.coordinate_to_cell_key(table.cursor_coordinate)
        return self._assignments.get(str(cell_key.row_key.value))

    @on(DataTable.RowSelected)
    def open_assignment(self, event: DataTable.RowSelected) -> None:
        assignment = self._assignments.get(str(event.row_key.value))
        if assignment is not None:
            self.app.push_screen(AssignmentScreen(self.course, assignment))

    def action_submit(self) -> None:
        assignment = self.current_assignment()
        if assignment is None:
            self.app.notify("select an assignment first", severity="warning")
            return

        def done(paths: list[Path] | None) -> None:
            if paths:
                self.app.push_screen(AssignmentScreen(self.course, assignment, submit_paths=paths))

        self.app.push_screen(SubmitModal(), callback=done)

    def action_leaderboard(self) -> None:
        assignment = self.current_assignment()
        if assignment is None:
            self.app.notify("select an assignment first", severity="warning")
            return
        self.app.push_screen(LeaderboardScreen(self.course, assignment))


class AssignmentScreen(GradescopeScreen):
    """Assignment detail: submit files, watch the autograder, leaderboard."""

    BINDINGS = [
        Binding("s", "submit", "Submit files"),
        Binding("g", "grade", "Autograder status"),
        Binding("l", "leaderboard", "Leaderboard"),
        Binding("escape", "back", "Back"),
    ]

    def __init__(
        self,
        course: Course,
        assignment: Assignment,
        submit_paths: list[Path] | None = None,
    ) -> None:
        super().__init__()
        self.course = course
        self.assignment = assignment
        self.submission_id: str | None = None
        self.status_text = ""
        self._submit_paths = submit_paths

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(id="info", classes="hint")
        yield ProgressBar(id="progress", total=None)  # indeterminate until graded
        yield Static(id="status")
        yield DataTable(id="cases", cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        due = fmt_due(self.assignment.due_date)
        self.query_one("#info", Static).update(
            f"{self.assignment.title} (assignment {self.assignment.id}) — due {due} · "
            "s: submit · g: autograder · l: leaderboard · esc: back"
        )
        cases = self.query_one("#cases", DataTable)
        cases.display = False
        cases.add_column("Test case", key="name")
        cases.add_column("Result", key="result", width=9)
        cases.add_column("Score", key="score", width=22)
        if self._submit_paths is not None:
            paths, self._submit_paths = self._submit_paths, None
            self._do_submit(paths)

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_leaderboard(self) -> None:
        self.app.push_screen(LeaderboardScreen(self.course, self.assignment))

    def action_submit(self) -> None:
        self.app.push_screen(SubmitModal(), callback=self._on_modal_paths)

    def _on_modal_paths(self, paths: list[Path] | None) -> None:
        if paths:
            self._do_submit(paths)

    def _do_submit(self, paths: list[Path]) -> None:
        self._set_status("submitting...")
        self.submit_worker(paths)

    @work(thread=True)
    def submit_worker(self, paths: list[Path]) -> None:
        try:
            submission = self.client.submit(self.course.id, self.assignment.id, paths)
        except (GradescopeError, OSError, ValueError) as exc:
            self.app.call_from_thread(self.show_error, str(exc))
            self.app.call_from_thread(self._set_status, f"submit failed: {exc}")
            return
        self.app.call_from_thread(self._after_submit, submission)

    def _after_submit(self, submission: Submission) -> None:
        self.submission_id = submission.id
        self._set_status(f"submitted #{submission.id} — watching autograder...")
        self.poll_worker(watch=True)

    def action_grade(self) -> None:
        if self.submission_id is None:
            self.app.push_screen(SubmissionIdModal(), callback=self._on_submission_id)
        else:
            self._set_status("checking autograder...")
            self.poll_worker(watch=False)

    def _on_submission_id(self, value: str | None) -> None:
        if value:
            self.submission_id = value.strip()
            self.action_grade()

    @work(thread=True)
    def poll_worker(self, watch: bool) -> None:
        submission_id = self.submission_id
        if submission_id is None:
            return
        deadline = time.monotonic() + POLL_TIMEOUT
        while True:
            try:
                result = self.client.get_autograder_result(
                    self.course.id, self.assignment.id, submission_id
                )
            except GradescopeError as exc:
                self.app.call_from_thread(self.show_error, str(exc))
                return
            if result.status != "pending":
                self.app.call_from_thread(self._show_result, result)
                return
            if not watch or time.monotonic() >= deadline:
                self.app.call_from_thread(self._show_result, result)
                return
            time.sleep(POLL_INTERVAL)

    def _show_result(self, result: AutograderResult) -> None:
        header = f"status: {result.status}"
        if result.score is not None and result.max_score is not None:
            header += f"  score: {result.score:g} / {result.max_score:g}"
        self._set_status(header)
        bar = self.query_one("#progress", ProgressBar)
        if result.status == "graded" and result.max_score:
            bar.update(total=result.max_score, progress=result.score or 0.0)
        else:
            bar.update(total=None)  # indeterminate while pending
        cases = self.query_one("#cases", DataTable)
        cases.clear()
        for case in result.test_cases:
            cases.add_row(
                case.name,
                case.status,
                f"{score_bar(case.score, case.max_score)} {fmt_score(case.score, case.max_score)}",
            )
        cases.display = bool(result.test_cases)

    def _set_status(self, text: str) -> None:
        self.status_text = text
        self.query_one("#status", Static).update(text)
        if text in {"submitting...", "checking autograder..."} or "watching" in text:
            self.query_one("#progress", ProgressBar).update(total=None)


class LeaderboardScreen(GradescopeScreen):
    """Leaderboard for an assignment."""

    BINDINGS = [
        Binding("r", "reload", "Refresh"),
        Binding("escape", "back", "Back"),
    ]

    def __init__(self, course: Course, assignment: Assignment) -> None:
        super().__init__()
        self.course = course
        self.assignment = assignment

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            f"Leaderboard — {self.assignment.title} (r: refresh · esc: back)",
            classes="hint",
        )
        yield DataTable(cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_column("Rank", key="rank", width=6)
        table.add_column("Name", key="name")
        table.add_column("Score", key="score", width=10)
        self.set_hint("loading leaderboard...")
        self.reload()

    @work(thread=True)
    def reload(self) -> None:
        try:
            entries = self.client.get_leaderboard(self.course.id, self.assignment.id)
        except GradescopeError as exc:
            self.app.call_from_thread(self.show_error, str(exc))
            return
        self.app.call_from_thread(self.populate, entries)

    def populate(self, entries: list[LeaderboardEntry]) -> None:
        table = self.query_one(DataTable)
        table.clear()
        for entry in entries:
            table.add_row(str(entry.rank), entry.name, f"{entry.score:g}", key=str(entry.rank))
        if not entries:
            self.set_hint("No leaderboard entries. (r: retry · esc: back)")

    def action_reload(self) -> None:
        self.reload()

    def action_back(self) -> None:
        self.app.pop_screen()


class SubmitModal(ModalScreen[list[Path] | None]):
    """Asks for the file paths to submit."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    CSS = """
    SubmitModal {
        align: center middle;
    }
    SubmitModal > Vertical {
        width: 70;
        height: auto;
        padding: 1 2;
        border: solid $primary;
        background: $surface;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Files to submit (comma or space separated):")
            yield Input(id="paths", placeholder="solution.py, utils/helpers.py")
            yield Button("Submit", id="submit", variant="primary")

    @on(Button.Pressed, "#submit")
    def _on_submit_button(self) -> None:
        self._dismiss_with_paths()

    @on(Input.Submitted, "#paths")
    def _on_paths_submitted(self) -> None:
        self._dismiss_with_paths()

    def _dismiss_with_paths(self) -> None:
        raw = self.query_one("#paths", Input).value
        paths = [Path(p) for p in raw.replace(",", " ").split()]
        if not paths:
            self.dismiss(None)
            return
        missing = [p for p in paths if not p.is_file()]
        if missing:
            self.app.notify(
                "file not found: " + ", ".join(str(p) for p in missing),
                severity="error",
                title="Submit",
            )
            return
        self.dismiss(paths)

    def action_cancel(self) -> None:
        self.dismiss(None)


class SubmissionIdModal(ModalScreen[str | None]):
    """Asks for a submission id to check autograder status for."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    CSS = """
    SubmissionIdModal {
        align: center middle;
    }
    SubmissionIdModal > Vertical {
        width: 60;
        height: auto;
        padding: 1 2;
        border: solid $primary;
        background: $surface;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Submission id:")
            yield Input(id="submission-id", placeholder="e.g. 123456")
            yield Button("Check", id="check", variant="primary")

    @on(Button.Pressed, "#check")
    def _on_check_button(self) -> None:
        self._dismiss_with_id()

    @on(Input.Submitted, "#submission-id")
    def _on_id_submitted(self) -> None:
        self._dismiss_with_id()

    def _dismiss_with_id(self) -> None:
        value = self.query_one("#submission-id", Input).value.strip()
        self.dismiss(value or None)

    def action_cancel(self) -> None:
        self.dismiss(None)
