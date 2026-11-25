"""Screens and modals for the gradescope-cli TUI.

Navigation: courses -> assignments -> assignment detail (submit files,
watch the autograder, leaderboard). All network calls run in thread
workers so the UI never blocks; results are applied via call_from_thread.
"""

from __future__ import annotations

import os
import time
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.css.query import NoMatches
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    Checkbox,
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
from gradescope_cli.exceptions import ConfigError, GradescopeError
from gradescope_cli.render import (
    due_compact,
    due_style,
    due_text,
    score_bar,
    score_style,
    score_text,
    status_label,
    status_style,
)
from gradescope_cli.tui.widgets import RowClickTable

if TYPE_CHECKING:
    from gradescope_cli.tui.app import GradescopeApp

POLL_INTERVAL = 3.0
POLL_TIMEOUT = 600.0


def due_cell(due: datetime | None) -> Text:
    """Styled compact due-date cell ("10-13 05:00 · overdue 39d")."""
    now = datetime.now()
    return Text(due_compact(due, now=now), style=due_style(due, now=now))


def score_cell(score: float | None, max_score: float | None, bar_width: int = 8) -> Text:
    """Styled score cell: colored bar + "8.5/10 (85%)"."""
    if score is None or max_score is None:
        return Text("-", style="dim")
    bar = Text(f"{score_bar(score, max_score, width=bar_width)} {score_text(score, max_score)}")
    bar.stylize(score_style(score, max_score))
    return bar


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
            yield Checkbox("Remember me (save to ~/.config, 0600)", id="save")
            yield Button("Log In", id="login", variant="primary")
            yield Static(id="login-error")
        yield Footer()

    def __init__(self) -> None:
        super().__init__()
        self.error_text = ""
        self._attempt: tuple[str, str] | None = None

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
        self._attempt = (email, password)
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
        # "Remember me": cache credentials (0600) unless env vars already provide them.
        if self.query_one("#save", Checkbox).value and self._attempt is not None:
            from gradescope_cli.config import (
                Credentials,
                credentials_from_env,
                save_credentials,
            )

            try:
                credentials_from_env(dict(os.environ))
            except ConfigError:
                email, password = self._attempt
                save_credentials(Credentials(email=email, password=password))
        self.app.switch_screen(CoursesScreen())


class CoursesScreen(GradescopeScreen):
    """Lists all courses; enter opens one."""

    BINDINGS = [
        Binding("r", "reload", "Refresh"),
        Binding("q", "app.quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._courses: dict[str, Course] = {}
        self._default_hint = ""

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Courses  (enter: open · r: refresh · q: quit)", classes="hint")
        yield RowClickTable(cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        self._default_hint = str(self.query_one(".hint", Static).content)
        table = self.query_one(DataTable)
        table.add_column("ID", key="id", width=10)
        table.add_column("Term", key="term", width=12)
        table.add_column("Course", key="name")
        table.add_column("Code", key="code", width=12)
        table.add_column("Asg", key="count", width=5)
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
                Text(course.id),
                Text(course.term or "-", style="dim"),
                Text(course.name, style="bold"),
                Text(course.code or "", style="dim"),
                Text(
                    str(course.num_assignments) if course.num_assignments is not None else "-",
                    style="dim",
                ),
                key=course.id,
            )
            self._courses[course.id] = course
        if not courses:
            self.set_hint("No courses found — are you enrolled? (r: retry · q: quit)")
        else:
            self.set_hint(self._default_hint)

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
        Binding("s", "submit", "Submit files"),
        Binding("l", "leaderboard", "Leaderboard"),
        Binding("r", "reload", "Refresh"),
        Binding("escape", "back", "Back"),
    ]

    def __init__(self, course: Course) -> None:
        super().__init__()
        self.course = course
        self._assignments: dict[str, Assignment] = {}
        self._default_hint = ""

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            f"{self.course.name} (course {self.course.id}) — "
            "enter: open · s: submit · l: leaderboard · r: refresh · esc: back",
            classes="hint",
        )
        yield RowClickTable(cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        self._default_hint = str(self.query_one(".hint", Static).content)
        table = self.query_one(DataTable)
        table.add_column("ID", key="id", width=9)
        table.add_column("Assignment", key="title")
        table.add_column("Due", key="due", width=24)
        table.add_column("Status", key="status", width=9)
        table.add_column("Score", key="score", width=23)
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
            table.add_row(
                Text(assignment.id),
                Text(assignment.title),
                due_cell(assignment.due_date),
                Text(status_label(assignment.status), style=status_style(assignment.status)),
                score_cell(assignment.score, assignment.max_score),
                key=assignment.id,
            )
            self._assignments[assignment.id] = assignment
        if not assignments:
            self.set_hint("No assignments found. (r: retry · esc: back)")
        else:
            self.set_hint(self._default_hint)

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
        yield RowClickTable(id="submissions", cursor_type="row")
        yield RowClickTable(id="cases", cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#info", Static).update(
            f"{self.assignment.title} (assignment {self.assignment.id}) — "
            f"due {due_text(self.assignment.due_date)} · "
            "enter: track submission · s: submit · g: autograder · l: leaderboard · esc: back"
        )
        submissions = self.query_one("#submissions", DataTable)
        submissions.add_column("Submission", key="id", width=12)
        submissions.add_column("Submitted", key="when")
        submissions.add_column("Score", key="score", width=23)
        cases = self.query_one("#cases", DataTable)
        cases.display = False
        cases.add_column("Test case", key="name")
        cases.add_column("Result", key="result", width=9)
        cases.add_column("Score", key="score", width=23)
        self.load_submissions_worker()
        submissions.focus()
        if self._submit_paths is not None:
            paths, self._submit_paths = self._submit_paths, None
            self._do_submit(paths)

    @work(thread=True)
    def load_submissions_worker(self) -> None:
        try:
            submissions = self.client.list_submissions(self.course.id, self.assignment.id)
        except GradescopeError as exc:
            self.app.call_from_thread(self.show_error, str(exc))
            return
        self.app.call_from_thread(self.populate_submissions, submissions)

    def populate_submissions(self, submissions: list[Submission]) -> None:
        table = self.query_one("#submissions", DataTable)
        table.clear()
        for s in submissions:
            table.add_row(
                Text(f"#{s.id}"),
                due_cell(s.submitted_at),
                score_cell(s.score, self.assignment.max_score),
                key=s.id,
            )

    @on(DataTable.RowSelected, "#submissions")
    def track_submission(self, event: DataTable.RowSelected) -> None:
        self.submission_id = str(event.row_key.value)
        self._set_status(f"tracking submission #{self.submission_id}...")
        self.poll_worker(watch=True)

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
        self.load_submissions_worker()  # refresh the submissions list

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
        header = Text(
            f"status: {status_label(result.status)}", style=status_style(result.status) or "bold"
        )
        if result.score is not None and result.max_score is not None:
            header.append(f"  score: {score_text(result.score, result.max_score)}")
            header.stylize(score_style(result.score, result.max_score), 7)
        self._set_status(header)
        bar = self.query_one("#progress", ProgressBar)
        if result.status == "graded" and result.max_score:
            bar.update(total=result.max_score, progress=result.score or 0.0)
        else:
            bar.update(total=None)  # indeterminate while pending
        cases = self.query_one("#cases", DataTable)
        cases.clear()
        for case in result.test_cases:
            result_style = (
                "green" if case.status == "passed" else "red" if case.status == "failed" else ""
            )
            cases.add_row(
                Text(case.name),
                Text(case.status, style=result_style),
                score_cell(case.score, case.max_score),
            )
        cases.display = bool(result.test_cases)

    def _set_status(self, text: str | Text) -> None:
        self.status_text = str(text)
        self.query_one("#status", Static).update(text)
        if isinstance(text, str) and (
            text in {"submitting...", "checking autograder..."} or "watching" in text
        ):
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
        self._default_hint = ""

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            f"Leaderboard — {self.assignment.title} (r: refresh · esc: back)",
            classes="hint",
        )
        yield RowClickTable(cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        self._default_hint = str(self.query_one(".hint", Static).content)
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
            rank_style = "bold yellow" if entry.rank == 1 else "dim" if entry.rank > 3 else ""
            table.add_row(
                Text(str(entry.rank), style=rank_style),
                Text(entry.name, style="bold" if entry.rank == 1 else ""),
                Text(f"{entry.score:g}", style=rank_style),
                key=str(entry.rank),
            )
        if not entries:
            self.set_hint("No leaderboard entries. (r: retry · esc: back)")
        else:
            self.set_hint(self._default_hint)

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
