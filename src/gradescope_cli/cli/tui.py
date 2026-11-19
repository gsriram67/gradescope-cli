"""Interactive TUI for browsing assignments (work in progress).

The TUI will be built on ``textual`` and share the same
:class:`~gradescope_cli.api.client.GradescopeAPI` backend as the CLI.
For now this is a stub so the ``gradescope tui`` command exists.
"""

from __future__ import annotations

from gradescope_cli.api.client import GradescopeAPI


def launch_tui(client: GradescopeAPI) -> int:
    """Launch the interactive TUI. Not implemented yet."""
    print(
        "The TUI is not implemented yet.\n"
        "Use the CLI subcommands instead, e.g.:\n"
        "  gradescope courses\n"
        "  gradescope assignments <course_id>\n"
        "  gradescope submit <course_id> <assignment_id> <files...>\n"
        "  gradescope status <course_id> <assignment_id> <submission_id>\n"
        "  gradescope leaderboard <course_id> <assignment_id>"
    )
    return 0
