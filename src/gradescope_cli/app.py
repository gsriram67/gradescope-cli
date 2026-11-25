"""Entry point for gradescope-cli: resolve credentials and launch the TUI.

Credentials come from GRADESCOPE_EMAIL / GRADESCOPE_PASSWORD env vars or the
saved cache (~/.config/gradescope-cli/credentials.json); if neither exists,
the TUI opens with its own login screen (with a "Remember me" checkbox).
"""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence

from gradescope_cli import __version__
from gradescope_cli.api.client import GradescopeClient
from gradescope_cli.config import ENV_EMAIL, resolve_credentials
from gradescope_cli.exceptions import ConfigError, GradescopeError

HELP = f"""usage: gradescope [-h] [--version]

gradescope-cli {__version__} — a terminal UI (TUI) for Gradescope.

With no arguments, launches the interactive TUI (sign in, browse courses and
assignments, submit files, track the autograder, view leaderboards).

options:
  -h, --help     show this help message and exit
  --version      show the version and exit
"""


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. Returns a process exit code."""
    args = list(sys.argv[1:] if argv is None else argv)
    if "-h" in args or "--help" in args:
        print(HELP)
        return 0
    if "--version" in args:
        print(f"gradescope-cli {__version__}")
        return 0
    if not sys.stdin.isatty():
        # No terminal (e.g. piped/CI): don't crash the TUI launcher.
        print(
            "gradescope-cli is a terminal UI — run `gradescope` in a terminal "
            "(or `gradescope --help`).",
            file=sys.stderr,
        )
        return 0
    try:
        creds, _source = resolve_credentials(interactive=False)
    except ConfigError:
        creds = None  # TUI login screen handles it
    client = GradescopeClient()
    if creds is not None:
        try:
            client.login(creds.email, creds.password)
        except GradescopeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    from gradescope_cli.tui import GradescopeApp

    email_hint = creds.email if creds is not None else os.environ.get(ENV_EMAIL)
    GradescopeApp(client, email_hint=email_hint).run()
    return 0
