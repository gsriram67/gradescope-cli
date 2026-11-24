"""The gradescope-cli TUI application shell."""

from __future__ import annotations

from textual.app import App
from textual.binding import Binding

from gradescope_cli.api.client import GradescopeAPI
from gradescope_cli.tui.screens import CoursesScreen


class GradescopeApp(App[None]):
    """Interactive browser for courses, assignments, submissions and leaderboards.

    The API backend is injected, so tests can run the app headless with a
    fake client via ``GradescopeApp(client).run_test()``.
    """

    TITLE = "gradescope-cli"
    BINDINGS = [Binding("q", "quit", "Quit")]

    CSS = """
    .hint {
        padding: 1 2 0 2;
        color: $text-muted;
    }
    #status {
        padding: 1 2;
        height: auto;
    }
    DataTable {
        height: 1fr;
    }
    """

    def __init__(self, client: GradescopeAPI) -> None:
        super().__init__()
        self.client = client

    def on_mount(self) -> None:
        self.push_screen(CoursesScreen())
