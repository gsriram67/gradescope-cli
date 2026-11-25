"""Entry point for gradescope-cli: resolve credentials and launch the TUI.

Credentials come from GRADESCOPE_EMAIL / GRADESCOPE_PASSWORD env vars or the
saved cache (~/.config/gradescope-cli/credentials.json); if neither exists,
the TUI opens with its own login screen (with a "Remember me" checkbox).
"""

from __future__ import annotations

import os
import sys

from gradescope_cli.api.client import GradescopeClient
from gradescope_cli.config import ENV_EMAIL, resolve_credentials
from gradescope_cli.exceptions import ConfigError, GradescopeError


def main() -> int:
    """Launch the TUI. Returns a process exit code."""
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
