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
from typing import TYPE_CHECKING, Any, cast

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
    Tree,
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
    fmt_number,
    score_style,
    score_text,
    status_label,
    status_style,
)
from gradescope_cli.tui.widgets import NavTree, RowClickTable

if TYPE_CHECKING:
    from gradescope_cli.tui.app import GradescopeApp

POLL_INTERVAL = 3.0
POLL_TIMEOUT = 600.0


def due_cell(due: datetime | None) -> Text:
    """Styled compact due-date cell ("10-13 05:00 · overdue 39d")."""
    now = datetime.now()
    return Text(due_compact(due, now=now), style=due_style(due, now=now))


def score_cell(score: float | None, max_score: float | None) -> Text:
    """Colored score text, e.g. green "8.5/10 (85%)" (no bar)."""
    if score is None or max_score is None:
        return Text("-", style="dim")
    return Text(score_text(score, max_score), style=score_style(score, max_score))


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
    """Courses grouped under foldable term sections (a Tree).

    Click a term's ▸ (or press enter on it) to fold/unfold; enter/click a
    course to open it.
    """

    BINDINGS = [
        Binding("r", "reload", "Refresh"),
        Binding("q", "app.quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._default_hint = ""

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            "Courses — j/k: move · ▸/enter on term: fold · enter/click course: open · r · q",
            classes="hint",
        )
        yield NavTree("Courses", id="courses-tree")
        yield Footer()

    def on_mount(self) -> None:
        self._default_hint = str(self.query_one(".hint", Static).content)
        tree = self.query_one("#courses-tree", NavTree)
        tree.show_root = False
        tree.auto_expand = False  # we toggle term nodes ourselves in on_node_selected
        tree.focus()
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
        tree = self.query_one("#courses-tree", NavTree)
        tree.clear()
        # group by term, preserving the client's term-descending order
        by_term: dict[str, list[Course]] = {}
        for course in courses:
            by_term.setdefault(course.term or "Other", []).append(course)
        # pad names so the [id] / asg columns line up (tabular feel), capped
        name_width = min(55, max((len(c.name) for c in courses), default=0))
        for term_index, (term, term_courses) in enumerate(by_term.items()):
            # most recent term gets a highlight color; older terms stay bold
            term_label = Text(term, style="bold green" if term_index == 0 else "bold")
            term_label.append(f"  ({len(term_courses)})", style="dim")
            term_node = tree.root.add(term_label, data=("term", term))
            for course in term_courses:
                label = Text(f"{course.name:<{name_width}}")
                label.append(f"  [{course.id}]", style="cyan")
                if course.num_assignments is not None:
                    label.append(f" · {course.num_assignments} asg", style="dim")
                term_node.add(label, data=course)
            if term_index == 0:
                term_node.expand()  # only the most recent term starts unfolded
        if not courses:
            self.set_hint("No courses found — are you enrolled? (r: retry · q: quit)")
        else:
            self.set_hint(self._default_hint)

    def action_reload(self) -> None:
        self.reload_courses()

    @on(Tree.NodeSelected)
    def on_node_selected(self, event: Tree.NodeSelected[Any]) -> None:
        data = event.node.data
        if isinstance(data, Course):
            self.app.push_screen(AssignmentsScreen(data))
        elif isinstance(data, tuple) and data[0] == "term":
            event.node.toggle()  # fold/unfold a term section via keyboard too


class AssignmentsScreen(GradescopeScreen):
    """Lists assignments of a course with due dates."""

    BINDINGS = [
        Binding("s", "submit", "Submit files"),
        Binding("l", "leaderboard", "Leaderboard"),
        Binding("r", "reload", "Refresh"),
        Binding("escape", "back", "Back"),
        Binding("h", "back", "Back", show=False),
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
            "j/k: move · enter: open · s: submit · l: leaderboard · r: refresh · h/esc: back",
            classes="hint",
        )
        yield RowClickTable(cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        self._default_hint = str(self.query_one(".hint", Static).content)
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
        table.clear(columns=True)
        # Size the Due/Score columns to their content, widening when the
        # terminal has room and shrinking (table scrolls/clips) when narrow.
        avail = self.app.size.width
        due_texts = [due_compact(a.due_date) for a in assignments]
        score_texts = [
            score_text(a.score, a.max_score) if a.score is not None else "-" for a in assignments
        ]
        due_w = min(max([len(t) for t in due_texts] + [3]), 26)
        score_w = min(max([len(t) for t in score_texts] + [5]), 22)
        fixed = 9 + 9 + 15  # ID + Status + min Assignment column
        if avail < fixed + due_w + score_w:
            overflow = fixed + due_w + score_w - avail
            score_w = max(10, score_w - overflow)
            overflow = fixed + due_w + score_w - avail
            due_w = max(16, due_w - max(0, overflow))
        table.add_column("ID", key="id", width=9)
        table.add_column("Assignment", key="title")
        table.add_column("Due", key="due", width=due_w)
        table.add_column("Status", key="status", width=9)
        table.add_column("Score", key="score", width=score_w)
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
        Binding("h", "back", "Back", show=False),
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
        yield ProgressBar(id="progress", total=None, show_percentage=False, show_eta=False)
        yield Static(id="status")
        yield RowClickTable(id="submissions", cursor_type="row")
        yield RowClickTable(id="cases", cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#info", Static).update(
            f"{self.assignment.title} (assignment {self.assignment.id}) — "
            f"due {due_text(self.assignment.due_date)} · "
            "j/k: move · enter: track · s: submit · g: autograder · l: leaderboard · h/esc: back"
        )
        submissions = self.query_one("#submissions", DataTable)
        submissions.add_column("Submission", key="id", width=12)
        submissions.add_column("Submitted", key="when")
        submissions.add_column("Score", key="score", width=18)
        cases = self.query_one("#cases", DataTable)
        cases.display = False
        cases.add_column("Test case", key="name")
        cases.add_column("Result", key="result", width=9)
        cases.add_column("Score", key="score", width=18)
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
        if not submissions and not self.status_text:
            self._set_status("no submissions yet — press s to submit files")

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
        Binding("h", "back", "Back", show=False),
    ]

    def __init__(self, course: Course, assignment: Assignment) -> None:
        super().__init__()
        self.course = course
        self.assignment = assignment
        self._default_hint = ""

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            f"Leaderboard — {self.assignment.title} (j/k: move · r: refresh · h/esc: back)",
            classes="hint",
        )
        yield RowClickTable(cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        self._default_hint = str(self.query_one(".hint", Static).content)
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
        table.clear(columns=True)
        table.add_column("Rank", key="rank", width=6)
        table.add_column("Name", key="name")
        # one column per leaderboard category (e.g. "task 1", "task 2"), in order
        categories: list[str] = []
        for entry in entries:
            for col in entry.scores:
                if col not in categories:
                    categories.append(col)
        for col in categories:
            table.add_column(col, key=f"cat:{col}", width=12)
        table.add_column("Total", key="total", width=12)
        for entry in entries:
            rank_style = "bold yellow" if entry.rank == 1 else "dim" if entry.rank > 3 else ""
            row: list[Text] = [
                Text(str(entry.rank), style=rank_style),
                Text(entry.name, style="bold" if entry.rank == 1 else ""),
            ]
            for col in categories:
                if col in entry.scores:
                    row.append(Text(fmt_number(entry.scores[col])))
                else:
                    row.append(Text("-", style="dim"))
            row.append(Text(fmt_number(entry.score), style=rank_style))
            table.add_row(*row, key=str(entry.rank))
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
