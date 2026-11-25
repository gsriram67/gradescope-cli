"""The gradescope-cli TUI application shell."""

from __future__ import annotations

from textual.app import App
from textual.binding import Binding

from gradescope_cli.api.client import GradescopeAPI
from gradescope_cli.tui.screens import CoursesScreen, LoginScreen


class GradescopeApp(App[None]):
    """Interactive browser for courses, assignments, submissions and leaderboards.

    The API backend is injected, so tests can run the app headless with a
    fake client via ``GradescopeApp(client).run_test()``. If the client is
    not authenticated yet, a login screen is shown first.
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
    #progress {
        height: 1;
        padding: 0 2;
    }
    #progress .bar--bar {
        background: $success;
    }
    #cases {
        height: auto;
        max-height: 30%;
    }
    #submissions {
        height: auto;
        max-height: 30%;
    }
    DataTable {
        height: 1fr;
    }
    Tree {
        height: 1fr;
        padding: 0 1;
    }
    Tree .tree--guides {
        color: $surface-lighten-2;
    }
    Tree .tree--label {
        padding: 0 1;
    }
    """

    def __init__(self, client: GradescopeAPI, *, email_hint: str | None = None) -> None:
        super().__init__()
        self.client = client
        self.email_hint = email_hint

    def on_mount(self) -> None:
        if self.client.is_authenticated:
            self.push_screen(CoursesScreen())
        else:
            self.push_screen(LoginScreen())
